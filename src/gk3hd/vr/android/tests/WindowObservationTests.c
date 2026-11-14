#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include "window_observation.h"

static unsigned int customReads;
static LRESULT CALLBACK custom(HWND window,UINT message,WPARAM w,LPARAM l) {
    if(message==WM_GETTEXT) customReads++;
    return DefWindowProcW(window,message,w,l);
}
static void check(int value,const char* message) {if(!value) {puts(message);exit(1);}}
int main(void) {
    HINSTANCE instance=GetModuleHandleW(NULL);
    WNDCLASSW kind={0};kind.hInstance=instance;kind.lpfnWndProc=custom;
    kind.lpszClassName=L"GK3HDObservationFixture";
    check(RegisterClassW(&kind)!=0,"Cannot register isolated custom-window fixture");
    HWND engine=CreateWindowExW(0,kind.lpszClassName,L"Not a dialog",0,0,0,1,1,NULL,NULL,instance,NULL);
    HWND dialog=CreateWindowExW(0,L"#32770",L"Native error",0,0,0,1,1,NULL,NULL,instance,NULL);
    check(engine!=NULL&&dialog!=NULL,"Cannot create hidden observer fixtures");
    HWND other=CreateWindowExW(0,kind.lpszClassName,L"Custom child",WS_CHILD,0,0,1,1,dialog,NULL,instance,NULL);
    HWND text=CreateWindowExW(0,L"Static",L"Read error",WS_CHILD,0,0,1,1,dialog,NULL,instance,NULL);
    check(other!=NULL&&text!=NULL,"Cannot create hidden dialog controls");
    customReads=0;
    WindowObservation own={GetCurrentProcessId(),2};
    describe_owned_top_window(engine,(LPARAM)&own);
    check(own.remaining==2&&customReads==0,"Custom engine received a synchronous text query");
    WindowObservation foreign={GetCurrentProcessId()+1,2};
    describe_owned_top_window(dialog,(LPARAM)&foreign);
    check(foreign.remaining==2,"Unowned dialog was inspected");
    describe_owned_top_window(dialog,(LPARAM)&own);
    check(own.remaining==0&&customReads==0,"Native dialog budget/filtering failed");
    DestroyWindow(dialog);DestroyWindow(engine);
    check(UnregisterClassW(kind.lpszClassName,instance)!=0,"Custom observer fixture leaked");
    puts("Owned native-dialog observations passed without querying custom windows");
    return 0;
}
