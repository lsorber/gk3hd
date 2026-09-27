#define NOMINMAX
#include <windows.h>
#include "../util/log/log.h"
#include <iostream>

static unsigned calls = 0;

// Same ABI as Wine's actual ntdll export. Resolve through the declared pointer
// just as GetProcAddress does; do not let the compiler replace the indirect call.
static int __cdecl write_log(const char* text) {
  ++calls;
  return text[0];
}

int main() {
  volatile dxvk::PFN_wineLogOutput output =
    reinterpret_cast<dxvk::PFN_wineLogOutput>(&write_log);
  unsigned wrong = 0;
  for (unsigned i = 0; i < 256; ++i) {
    DWORD before, after;
    __asm mov before, esp
    int result = output("message");
    __asm mov after, esp
    // Restore before inspecting a failure, so even the broken ABI fails safely.
    __asm mov esp, before
    if (before != after || result != 'm') ++wrong;
  }
  if (wrong || calls != 256) {
    std::cerr << "Wine logging callback changed the caller's stack: " << wrong << '\n';
    return 1;
  }
  std::cout << "256 Wine-ABI logging calls preserve stack and results\n";
}
