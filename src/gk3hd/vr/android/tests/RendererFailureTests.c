#define WIN32_LEAN_AND_MEAN
#include "../renderer_failure.h"
#include <string.h>

static void require(int value,const char* message) {
    if(!value){fprintf(stderr,"Renderer failure wait: %s (%lu)\n",message,GetLastError());ExitProcess(1);}
}
int main(void) {
    char previous[256]={0},token[33],name[96];
    DWORD length=GetEnvironmentVariableA("GK3HD_FRAME_SESSION",previous,sizeof(previous));require(length<sizeof(previous),"bounded prior environment");
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",NULL),"unset optional session");
    require(standalone_renderer_failure()==NULL&&GetLastError()==ERROR_SUCCESS,"unhosted launch stays optional");
    SetLastError(1234);standalone_report_renderer_failure();require(GetLastError()==1234,"unhosted report preserves original error");
    for(unsigned i=0;i<2;i++) {
        require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",i?"0000000000000000000000000000000g":"short"),"invalid session input");
        require(standalone_renderer_failure()==NULL&&GetLastError()==ERROR_INVALID_PARAMETER,"reject malformed namespace");
    }
    snprintf(token,sizeof(token),"%016llx%016llx",(unsigned long long)GetCurrentProcessId(),(unsigned long long)GetTickCount64());
    char other[33];memcpy(other,token,sizeof(other));other[0]=other[0]=='0'?'1':'0';
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",token),"select owned namespace");
    HANDLE failure=standalone_renderer_failure();require(failure!=NULL,"create owned non-inherited event");
    DWORD flags=0;require(GetHandleInformation(failure,&flags)&&!(flags&HANDLE_FLAG_INHERIT),"event cannot leak inherited ownership");
    require(standalone_renderer_failure()==NULL&&GetLastError()==ERROR_ALREADY_EXISTS,"reject occupied namespace without adopting it");
    HANDLE child=CreateEventA(NULL,TRUE,FALSE,NULL);require(child!=NULL,"controlled child-completion source");
    require(standalone_wait_child(child,failure,NULL,0)==WAIT_TIMEOUT,"healthy pending child");
    HANDLE setup=standalone_renderer_setup_timer();require(setup!=NULL,"create owned setup timer");
    require(GetHandleInformation(setup,&flags)&&!(flags&HANDLE_FLAG_INHERIT),"timer cannot leak inherited ownership");
    require(standalone_renderer_setup_timer()==NULL&&GetLastError()==ERROR_ALREADY_EXISTS,"reject occupied setup timer");
    require(standalone_wait_child(child,failure,setup,0)==WAIT_TIMEOUT,"unarmed setup timer does not shorten startup");
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",other),"select a foreign setup namespace");
    require(!standalone_renderer_begin_setup(20),"foreign session cannot arm an existing launcher timer");
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",token),"restore the setup namespace");
    HANDLE attempt=standalone_renderer_begin_setup(100);
    require(attempt!=NULL,"arm owned setup timer");
    standalone_renderer_end_setup(attempt);
    require(standalone_wait_child(child,failure,setup,150)==WAIT_TIMEOUT,"completed setup cancels its deadline");
    attempt=standalone_renderer_begin_setup(20);
    require(attempt!=NULL,"arm a subsequent setup attempt");
    require(standalone_wait_child(child,failure,setup,2000)==WAIT_OBJECT_0+2,"expired setup wakes the launcher");
    require(SetEvent(child)&&standalone_wait_child(child,failure,setup,0)==WAIT_OBJECT_0+2,"setup expiry wins simultaneous completion");
    standalone_renderer_end_setup(attempt);CloseHandle(setup);
    require(!standalone_renderer_begin_setup(20),"retired setup namespace cannot be armed");
    require(standalone_wait_child(child,failure,NULL,0)==WAIT_OBJECT_0,"normal completion preserved");
    require(standalone_wait_child(child,NULL,NULL,0)==WAIT_OBJECT_0,"unhosted completion preserved");
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",other),"select another namespace");
    standalone_report_renderer_failure();require(standalone_wait_child(child,failure,NULL,0)==WAIT_OBJECT_0,"foreign report cannot signal owned session");
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",token),"restore owned namespace");
    SetLastError(1234);standalone_report_renderer_failure();require(GetLastError()==1234,"runtime report preserves original error");
    require(standalone_wait_child(child,failure,NULL,0)==WAIT_OBJECT_0+1,"terminal failure wins simultaneous completion");
    require(ResetEvent(child)&&standalone_wait_child(child,failure,NULL,0)==WAIT_OBJECT_0+1,"terminal failure wakes pending child wait");
    standalone_report_renderer_failure();require(standalone_wait_child(child,failure,NULL,0)==WAIT_OBJECT_0+1,"repeated runtime report remains terminal");
    CloseHandle(child);CloseHandle(failure);
    snprintf(name,sizeof(name),"Local\\GK3HD.RendererFault.%s",token);
    standalone_report_renderer_failure();
    require(!OpenEventA(SYNCHRONIZE,FALSE,name),"last owned handle retires namespace");
    require(SetEnvironmentVariableA("GK3HD_FRAME_SESSION",length?previous:NULL),"restore caller environment");
    puts("Renderer failure wait: normal exit, terminal priority, ownership and namespace isolation passed");return 0;
}
