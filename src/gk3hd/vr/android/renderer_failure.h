#pragma once
#include <windows.h>
#include <stdio.h>

/* One manual-reset event per random host session. Only the launcher creates
 * it; the renderer can signal only that existing session. No file polling or
 * changes to unrelated Wine processes, prefixes or desktop/PC-VR launches. */
static int standalone_renderer_session_token(char token[33]) {
    DWORD length=GetEnvironmentVariableA("GK3HD_FRAME_SESSION",token,33);
    if(!length) {SetLastError(ERROR_SUCCESS);return 0;}
    if(length!=32) {SetLastError(ERROR_INVALID_PARAMETER);return 0;}
    for(unsigned i=0;i<32;i++) if(!((token[i]>='0'&&token[i]<='9')||(token[i]>='a'&&token[i]<='f'))) {
        SetLastError(ERROR_INVALID_PARAMETER);return 0;
    }
    return 1;
}

static int standalone_renderer_failure_name(char name[96]) {
    char token[33];
    if(!standalone_renderer_session_token(token))return 0;
    snprintf(name,96,"Local\\GK3HD.RendererFault.%s",token);
    return 1;
}

static HANDLE standalone_renderer_failure(void) {
    char name[96];
    if(!standalone_renderer_failure_name(name))return NULL;
    HANDLE event=CreateEventA(NULL,TRUE,FALSE,name);
    if(event&&GetLastError()==ERROR_ALREADY_EXISTS) {
        CloseHandle(event);SetLastError(ERROR_ALREADY_EXISTS);return NULL;
    }
    return event;
}

/* An exceptional runtime path may signal only the launcher's existing event.
 * Never create/reset a session here, or obscure the caller's original error. */
static void standalone_report_renderer_failure(void) {
    DWORD previous=GetLastError();
    char name[96];
    if(standalone_renderer_failure_name(name)) {
        HANDLE event=OpenEventA(EVENT_MODIFY_STATE,FALSE,name);
        if(event) {SetEvent(event);CloseHandle(event);}
    }
    SetLastError(previous);
}

static inline int standalone_renderer_setup_requested(void) {
    char setting[2];
    return GetEnvironmentVariableA("GK3HD_WXR_DIRECT_TARGET",setting,sizeof(setting))==1&&setting[0]=='1';
}

static inline int standalone_renderer_setup_name(char name[96]) {
    char token[33];
    if(!standalone_renderer_session_token(token))return 0;
    snprintf(name,96,"Local\\GK3HD.RendererSetup.%s",token);
    return 1;
}

/* Only the launcher owns this deadline. The guest can arm its existing timer
 * while setting up the compressed swapchain. It cannot create a timer for a
 * stale or unrelated session. */
static inline HANDLE standalone_renderer_setup_timer(void) {
    char name[96];
    if(!standalone_renderer_setup_name(name))return NULL;
    HANDLE timer=CreateWaitableTimerA(NULL,TRUE,name);
    if(timer&&GetLastError()==ERROR_ALREADY_EXISTS) {
        CloseHandle(timer);SetLastError(ERROR_ALREADY_EXISTS);return NULL;
    }
    return timer;
}

static inline HANDLE standalone_renderer_begin_setup(DWORD milliseconds) {
    char name[96];
    if(!milliseconds||!standalone_renderer_setup_name(name))return NULL;
    HANDLE timer=OpenWaitableTimerA(TIMER_MODIFY_STATE,FALSE,name);
    if(timer) {
        LARGE_INTEGER due;
        due.QuadPart=-(LONGLONG)milliseconds*10000;
        if(!SetWaitableTimer(timer,&due,0,NULL,NULL,FALSE)) {
            DWORD error=GetLastError();
            CloseHandle(timer);SetLastError(error);return NULL;
        }
    }
    return timer;
}

static inline void standalone_renderer_end_setup(HANDLE timer) {
    CancelWaitableTimer(timer);
    CloseHandle(timer);
}

#ifdef __cplusplus
class StandaloneRendererSetup {
    HANDLE timer;
public:
    explicit StandaloneRendererSetup(DWORD milliseconds) : timer(standalone_renderer_begin_setup(milliseconds)) {}
    ~StandaloneRendererSetup() {if(timer)standalone_renderer_end_setup(timer);}
    StandaloneRendererSetup(const StandaloneRendererSetup&)=delete;
    StandaloneRendererSetup& operator=(const StandaloneRendererSetup&)=delete;
    explicit operator bool() const {return timer!=NULL;}
};
#endif

/* Failure or expiry wins if the child exits in the same observation. An
 * unarmed setup timer has no effect on normal play or the ordinary fallback. */
static inline DWORD standalone_wait_child(HANDLE child,HANDLE failure,HANDLE setup,DWORD timeout) {
    HANDLE handles[3];
    DWORD results[3],count=0;
    if(failure){handles[count]=failure;results[count++]=WAIT_OBJECT_0+1;}
    if(setup){handles[count]=setup;results[count++]=WAIT_OBJECT_0+2;}
    handles[count]=child;results[count++]=WAIT_OBJECT_0;
    DWORD result=WaitForMultipleObjects(count,handles,FALSE,timeout);
    return result<count?results[result]:result;
}
