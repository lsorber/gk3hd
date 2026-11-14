#define NOMINMAX
#include <windows.h>
#include "ddraw_util.h"
#include <array>
#include <cstdlib>
#include <iostream>

int main() {
  const std::array<DWORD, 9> positions = {0, D3DFVF_XYZ, D3DFVF_XYZRHW,
    D3DFVF_XYZB1, D3DFVF_XYZB2, D3DFVF_XYZB3, D3DFVF_XYZB4, D3DFVF_XYZB5, D3DFVF_RESERVED0};
  unsigned checked = 0;
  for (DWORD position : positions) {
    for (DWORD textures = 0; textures <= 8; ++textures) {
      for (DWORD attributes : {DWORD(0), DWORD(D3DFVF_DIFFUSE), DWORD(D3DFVF_SPECULAR),
                               DWORD(D3DFVF_NORMAL | D3DFVF_DIFFUSE | D3DFVF_SPECULAR)}) {
        const DWORD fvf = position | (textures << D3DFVF_TEXCOUNT_SHIFT) | attributes;
        if (dxvk::IsPretransformedFVF(fvf) != (position == D3DFVF_XYZRHW)) {
          std::cerr << "Pretransformed FVF classification failed\n";
          return 1;
        }
        ++checked;
      }
    }
  }
  if (!dxvk::IsPretransformedFVF(D3DFVF_TLVERTEX)
      || dxvk::IsPretransformedFVF(D3DFVF_VERTEX)
      || dxvk::IsPretransformedFVF(D3DFVF_LVERTEX)) return 1;
  std::cout << checked << " position/texture/attribute combinations and legacy vertex formats pass\n";
}
