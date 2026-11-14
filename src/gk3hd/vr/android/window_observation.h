#ifndef GK3HD_WINDOW_OBSERVATION_H
#define GK3HD_WINDOW_OBSERVATION_H

#include <windows.h>
#include <stdio.h>
#include <wchar.h>

typedef struct {DWORD pid;unsigned int remaining;} WindowObservation;
static BOOL CALLBACK describe_owned_window(HWND window,LPARAM argument) {
    WindowObservation *observation=(WindowObservation*)argument;
    DWORD pid=0;GetWindowThreadProcessId(window,&pid);
    if(pid!=observation->pid) return TRUE;
    wchar_t text[256]={0},kind[64]={0};DWORD_PTR length=0;
    GetClassNameW(window,kind,64);
    /* Never dispatch WM_GETTEXT to an engine/XR/custom procedure. The Wine
     * path can block there despite the requested timeout. Only inspect the
     * standard controls belonging to a native dialog already awaiting input. */
    if(wcscmp(kind,L"#32770")&&wcscmp(kind,L"Static")&&
       wcscmp(kind,L"Button")&&wcscmp(kind,L"Edit")) return TRUE;
    if(!observation->remaining) return FALSE;
    observation->remaining--;
    if(SendMessageTimeoutW(window,WM_GETTEXT,256,(LPARAM)text,
                          SMTO_ABORTIFHUNG|SMTO_BLOCK,100,&length)) {
        char utf8[1024]={0},className[256]={0};
        text[255]=0;kind[63]=0;
        WideCharToMultiByte(CP_UTF8,0,text,-1,utf8,sizeof(utf8),NULL,NULL);
        WideCharToMultiByte(CP_UTF8,0,kind,-1,className,sizeof(className),NULL,NULL);
        printf("Owned window class=%s visible=%d text=%s\n",className,IsWindowVisible(window)!=0,utf8);
    }
    return observation->remaining!=0;
}
static BOOL CALLBACK describe_owned_top_window(HWND window,LPARAM argument) {
    WindowObservation *observation=(WindowObservation*)argument;
    DWORD pid=0;GetWindowThreadProcessId(window,&pid);
    if(pid!=observation->pid) return TRUE;
    wchar_t kind[64]={0};GetClassNameW(window,kind,64);
    if(wcscmp(kind,L"#32770")) return TRUE;
    if(!describe_owned_window(window,argument)) return FALSE;
    EnumChildWindows(window,describe_owned_window,argument);
    return observation->remaining!=0;
}
#endif
