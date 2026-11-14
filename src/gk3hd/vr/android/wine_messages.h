#ifndef GK3HD_WINE_MESSAGES_H
#define GK3HD_WINE_MESSAGES_H

#include <windows.h>

/* The runtime owns its transport window, not the game's message queue.
 * A nested pump must preserve any quit request for the application's outer
 * loop. A missing transport window is not permission to drain every window.
 */
static inline BOOL Gk3hdPumpPreviewMessages(HWND preview) {
    if(!preview) return TRUE;
    MSG message;
    while(PeekMessageW(&message,preview,0,0,PM_REMOVE)) {
        if(message.message==WM_QUIT) {
            PostQuitMessage((int)message.wParam);
            return FALSE;
        }
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return TRUE;
}

#endif
