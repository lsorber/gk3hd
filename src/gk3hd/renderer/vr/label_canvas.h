#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <cstdint>

namespace gk3hd::vr {

// System-font labels shared by the keyboard and game menu. Restore selected
// objects before releasing owned GDI handles, including failed construction.
struct LabelCanvas {
  HDC dc = nullptr;
  HBITMAP bitmap = nullptr;
  HFONT font = nullptr;
  HGDIOBJ oldBitmap = nullptr, oldFont = nullptr;
  uint32_t* pixels = nullptr;
  LabelCanvas(uint32_t width, uint32_t height, int fontHeight = 36) {
    BITMAPINFO info{};
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = LONG(width);
    info.bmiHeader.biHeight = -LONG(height);
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    info.bmiHeader.biCompression = BI_RGB;
    dc = CreateCompatibleDC(nullptr);
    if (dc) bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS,
                                    reinterpret_cast<void**>(&pixels), nullptr, 0);
    if (bitmap) oldBitmap = SelectObject(dc, bitmap);
    if (oldBitmap && oldBitmap != HGDI_ERROR)
      font = CreateFontW(-fontHeight, 0, 0, 0, FW_MEDIUM, FALSE, FALSE, FALSE, ANSI_CHARSET,
                        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY,
                        DEFAULT_PITCH, L"Segoe UI");
    if (font) oldFont = SelectObject(dc, font);
  }
  LabelCanvas(const LabelCanvas&) = delete;
  LabelCanvas& operator=(const LabelCanvas&) = delete;
  ~LabelCanvas() {
    if (oldFont && oldFont != HGDI_ERROR) SelectObject(dc, oldFont);
    if (oldBitmap && oldBitmap != HGDI_ERROR) SelectObject(dc, oldBitmap);
    if (font) DeleteObject(font);
    if (bitmap) DeleteObject(bitmap);
    if (dc) DeleteDC(dc);
  }
  bool valid() const {
    return pixels && oldBitmap && oldBitmap != HGDI_ERROR && oldFont && oldFont != HGDI_ERROR;
  }
};

} // namespace gk3hd::vr
