#include "keyboard.h"
#include "camera.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

namespace gk3hd::vr {
namespace {
constexpr uint32_t Margin = 12, Gap = 8, RowHeight = 80, Top = 12;
constexpr float Unit = float(KeyboardState::Width - 2*Margin)/12;

void key(std::vector<KeyboardKey>& keys, unsigned row, float x, float units,
         KeyboardCommand command, uint32_t character, std::string label) {
  const auto left = Margin + uint32_t(std::lround(x*Unit));
  const auto right = Margin + uint32_t(std::lround((x+units)*Unit));
  const auto top = Top + row*(RowHeight+Gap);
  keys.push_back({command, character, std::move(label), {left, top, right-Gap, top+RowHeight}});
}
// All owned handles are restored/released, including on a failed label draw.
struct Canvas {
  HDC dc = nullptr;
  HBITMAP bitmap = nullptr;
  HFONT font = nullptr;
  HGDIOBJ oldBitmap = nullptr, oldFont = nullptr;
  uint32_t* pixels = nullptr;
  Canvas() {
    BITMAPINFO info{};
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = KeyboardState::Width;
    info.bmiHeader.biHeight = -int32_t(KeyboardState::Height);
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    info.bmiHeader.biCompression = BI_RGB;
    dc = CreateCompatibleDC(nullptr);
    if (dc) bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS,
                                    reinterpret_cast<void**>(&pixels), nullptr, 0);
    if (bitmap) oldBitmap = SelectObject(dc, bitmap);
    if (oldBitmap && oldBitmap != HGDI_ERROR)
      font = CreateFontW(-36, 0, 0, 0, FW_MEDIUM, FALSE, FALSE, FALSE, ANSI_CHARSET,
                        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY,
                        DEFAULT_PITCH, L"Segoe UI");
    if (font) oldFont = SelectObject(dc, font);
  }
  ~Canvas() {
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
}

void KeyboardState::layout() {
  keys_.clear();
  const char* rows[]{symbols_ ? "!@#$%^&*()_+" : "1234567890-=",
                     symbols_ ? "[]{}\\|<>~`" : "qwertyuiop",
                     symbols_ ? ":;\"'?,./-=" : "asdfghjkl'",
                     symbols_ ? "1234567890" : "zxcvbnm,./"};
  for (unsigned row = 0; row < 4; ++row) {
    float x = row == 3 ? 2.f : 0.f;
    for (const char* p = rows[row]; *p; ++p, x += 1) {
      const char value = caps_ && *p >= 'a' && *p <= 'z' ? char(*p-'a'+'A') : *p;
      key(keys_, row, x, 1, KeyboardCommand::Character, uint32_t(value), std::string(1, value));
    }
  }
  key(keys_, 1, 10, 2, KeyboardCommand::Backspace, 0, "Backspace");
  key(keys_, 2, 10, 2, KeyboardCommand::Delete, 0, "Delete");
  key(keys_, 3, 0, 2, KeyboardCommand::Caps, 0, caps_ ? "CAPS ON" : "Caps");
  key(keys_, 4, 0, 1.5f, KeyboardCommand::Home, 0, "Home");
  key(keys_, 4, 1.5f, 1.5f, KeyboardCommand::Left, 0, "Left");
  key(keys_, 4, 3, 4, KeyboardCommand::Character, 32, "Space");
  key(keys_, 4, 7, 1.5f, KeyboardCommand::Right, 0, "Right");
  key(keys_, 4, 8.5f, 1.5f, KeyboardCommand::End, 0, "End");
  key(keys_, 4, 10, 1, KeyboardCommand::Symbols, 0, symbols_ ? "ABC" : "#+=");
  key(keys_, 4, 11, 1, KeyboardCommand::Enter, 0, "Enter");
  dirty_ = true;
}
void KeyboardState::close() noexcept {
  epoch_ = hand_ = 0;
  caps_ = symbols_ = down_ = false;
  blocked_ = dirty_ = true;
  paintedHover_ = -2;
  keys_.clear();
  // A withdrawn keyboard has no reusable visible content or hit coverage.
  image_.pixels.clear(); image_.coverage.clear(); image_.bounds = {};
}
int KeyboardState::keyAt(float x, float y) const {
  if (!std::isfinite(x) || !std::isfinite(y)) return -1;
  for (size_t i = 0; i < keys_.size(); ++i) {
    const auto& r = keys_[i].bounds;
    if (x >= float(r.left) && x < float(r.right) && y >= float(r.top) && y < float(r.bottom))
      return int(i);
  }
  return -1;
}
KeyboardFrame KeyboardState::prepare(uint32_t epoch, const PanelGeometry& parent,
                                    const InputSnapshot& input, uint32_t hand, bool mailboxAvailable) {
  KeyboardFrame frame{};
  if (!epoch || hand > 1 || !(input.flags & InputFocused) || !(input.hands[hand].flags & AimValid)) {
    close(); return frame;
  }
  for (float value : parent.position)
    if (!std::isfinite(value)) { close(); throw std::invalid_argument("invalid keyboard parent position"); }
  for (float value : parent.size)
    if (!std::isfinite(value) || value <= 0) { close(); throw std::invalid_argument("invalid keyboard parent size"); }
  XrQuaternionf q{};
  try { q = normalized({parent.orientation[0], parent.orientation[1],
                         parent.orientation[2], parent.orientation[3]}); }
  catch (...) { close(); throw; }
  if (epoch != epoch_ || hand != hand_) {
    close(); epoch_ = epoch; hand_ = hand; layout();
  }
  frame.visible = true; frame.epoch = epoch; frame.hand = hand;
  frame.geometry = parent;
  const float orientation[]{q.x, q.y, q.z, q.w};
  std::copy_n(orientation, 4, frame.geometry.orientation);
  frame.geometry.size[0] = std::min(parent.size[0], 1.2f);
  frame.geometry.size[1] = frame.geometry.size[0]*float(Height)/float(Width);
  const auto offset = rotate(q, {0, -(parent.size[1]+frame.geometry.size[1])*.5f-.06f, .02f});
  for (unsigned i = 0; i < 3; ++i) {
    const float delta[]{offset.x, offset.y, offset.z};
    frame.geometry.position[i] += delta[i];
    if (!std::isfinite(frame.geometry.position[i])) { close(); throw std::invalid_argument("invalid keyboard placement"); }
  }
  const auto& controller = input.hands[hand];
  const bool held = (controller.held & Select) != 0;
  if (!held) blocked_ = false;
  PanelPoint point{};
  const XrPosef aim{{controller.orientation[0], controller.orientation[1], controller.orientation[2], controller.orientation[3]},
                   {controller.position[0], controller.position[1], controller.position[2]}};
  const XrPosef pose{q, {frame.geometry.position[0], frame.geometry.position[1], frame.geometry.position[2]}};
  bool hit = false;
  try { hit = panelPoint(pose, frame.geometry.size[0], frame.geometry.size[1], aim, float(Width), float(Height), point); }
  catch (...) { close(); throw; }
  if (hit) {
    frame.consumesSelect = true;
    frame.hovered = keyAt(point.x, point.y);
    if (frame.hovered >= 0 && held && !down_ && !blocked_ && (controller.pressed & Select) && mailboxAvailable) {
      const auto selected = keys_[size_t(frame.hovered)];
      switch (selected.command) {
        case KeyboardCommand::Caps: caps_ = !caps_; layout(); break;
        case KeyboardCommand::Symbols: symbols_ = !symbols_; layout(); break;
        case KeyboardCommand::Character: frame.action = {epoch, 1, selected.character}; break;
        case KeyboardCommand::Backspace: frame.action = {epoch, 2, 8}; break;
        case KeyboardCommand::Delete: frame.action = {epoch, 2, 46}; break;
        case KeyboardCommand::Left: frame.action = {epoch, 2, 37}; break;
        case KeyboardCommand::Right: frame.action = {epoch, 2, 39}; break;
        case KeyboardCommand::Home: frame.action = {epoch, 2, 36}; break;
        case KeyboardCommand::End: frame.action = {epoch, 2, 35}; break;
        case KeyboardCommand::Enter: frame.action = {epoch, 3, 13}; break;
      }
    }
  }
  down_ = held;
  return frame;
}
const OverlayImage& KeyboardState::image(const KeyboardFrame& frame) {
  if (!frame.visible || !epoch_) { close(); return image_; }
  if (frame.epoch != epoch_ || frame.hand != hand_)
    throw std::invalid_argument("stale keyboard view");
  if (frame.hovered < -1 || frame.hovered >= int(keys_.size()))
    throw std::invalid_argument("invalid keyboard hover");
  if (!dirty_ && paintedHover_ == frame.hovered) return image_;
  Canvas canvas;
  if (!canvas.valid()) throw std::runtime_error("cannot create VR keyboard label canvas");
  std::fill_n(canvas.pixels, size_t(Width)*Height, 0xff161b22u);
  if (!SetBkMode(canvas.dc, TRANSPARENT) || SetTextColor(canvas.dc, RGB(245, 247, 250)) == CLR_INVALID)
    throw std::runtime_error("cannot configure VR keyboard labels");
  for (size_t i = 0; i < keys_.size(); ++i) {
    const auto& k = keys_[i]; const auto& r = k.bounds;
    const bool active = (k.command == KeyboardCommand::Caps && caps_) ||
                        (k.command == KeyboardCommand::Symbols && symbols_);
    const uint32_t color = int(i) == frame.hovered ? 0xff276fafu : active ? 0xff355678u : 0xff303944u;
    for (uint32_t y = r.top; y < r.bottom; ++y)
      std::fill(canvas.pixels + size_t(y)*Width+r.left, canvas.pixels + size_t(y)*Width+r.right, color);
    RECT rect{LONG(r.left), LONG(r.top), LONG(r.right), LONG(r.bottom)};
    if (!DrawTextA(canvas.dc, k.label.c_str(), int(k.label.size()), &rect,
                   DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX))
      throw std::runtime_error("cannot draw VR keyboard label");
  }
  if (!GdiFlush()) throw std::runtime_error("cannot finish VR keyboard labels");
  image_.width = Width; image_.height = Height;
  image_.pixels.resize(size_t(Width)*Height);
  // GDI does not maintain alpha. All keyboard pixels intentionally opaque,
  // including the background between keys. Labels never infer transparency.
  for (size_t i = 0; i < image_.pixels.size(); ++i) image_.pixels[i] = canvas.pixels[i] | 0xff000000u;
  image_.bounds = {0, 0, Width, Height}; image_.coverage.clear();
  dirty_ = false; paintedHover_ = frame.hovered;
  return image_;
}
} // namespace gk3hd::vr
