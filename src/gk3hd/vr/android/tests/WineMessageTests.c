/* Hidden message-only windows, no GPU/headset or external process access. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include "wine_messages.h"

#define REQUIRE(test) do {if(!(test)){fprintf(stderr,"Failed: %s\n",#test);return 1;}} while(0)
static unsigned dispatched;
static LRESULT CALLBACK receive(HWND window,UINT message,WPARAM w,LPARAM l) {
    if(message==WM_APP+1) {dispatched+=(unsigned)w;return 0;}
    return DefWindowProcW(window,message,w,l);
}
int main(void) {
    HINSTANCE instance=GetModuleHandleW(NULL);
    WNDCLASSW type={0};type.lpfnWndProc=receive;type.hInstance=instance;
    type.lpszClassName=L"GK3HD private message regression";
    REQUIRE(RegisterClassW(&type));
    HWND preview=CreateWindowW(type.lpszClassName,L"",0,0,0,0,0,HWND_MESSAGE,NULL,instance,NULL);
    HWND game=CreateWindowW(type.lpszClassName,L"",0,0,0,0,0,HWND_MESSAGE,NULL,instance,NULL);
    REQUIRE(preview&&game);
    REQUIRE(PostMessageW(game,WM_APP+1,100,0));
    REQUIRE(PostMessageW(preview,WM_APP+1,7,0));
    REQUIRE(PostThreadMessageW(GetCurrentThreadId(),WM_APP+2,123,0));
    REQUIRE(Gk3hdPumpPreviewMessages(NULL));
    REQUIRE(dispatched==0);
    REQUIRE(Gk3hdPumpPreviewMessages(preview));
    REQUIRE(dispatched==7);
    MSG message;
    REQUIRE(PeekMessageW(&message,game,WM_APP+1,WM_APP+1,PM_REMOVE));
    REQUIRE(message.hwnd==game&&message.wParam==100);
    REQUIRE(PeekMessageW(&message,(HWND)-1,WM_APP+2,WM_APP+2,PM_REMOVE));
    REQUIRE(message.hwnd==NULL&&message.wParam==123);
    PostQuitMessage(37);
    Gk3hdPumpPreviewMessages(preview);
    Gk3hdPumpPreviewMessages(preview);
    REQUIRE(PeekMessageW(&message,NULL,0,0,PM_REMOVE));
    REQUIRE(message.message==WM_QUIT&&message.wParam==37);
    DestroyWindow(preview);DestroyWindow(game);UnregisterClassW(type.lpszClassName,instance);
    puts("Preview pump: private messages dispatched; game/thread messages and quit code preserved");
    return 0;
}
