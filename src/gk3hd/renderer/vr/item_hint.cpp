#include "item_hint.h"
#include "camera.h"
#include "label_canvas.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <stdexcept>

namespace gk3hd::vr {
namespace {
constexpr uint32_t Width = 512, Height = 128;
bool canonical(char c) {
  return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
         (c >= '0' && c <= '9') || c == '_';
}
template<typename T> T word(const uint8_t* p) {
  T value{}; std::memcpy(&value,p,sizeof(value)); return value;
}
}
void ItemHint::load(const void* data, uint32_t bytes) {
  if (!data || bytes < 12 || bytes > 2*1024*1024)
    throw std::invalid_argument("invalid item visual catalog size");
  const auto* begin = static_cast<const uint8_t*>(data);
  if (std::memcmp(begin,"GK3ITM01",8) || word<uint32_t>(begin+8) > 256)
    throw std::invalid_argument("invalid item visual catalog header");
  const auto count = word<uint32_t>(begin+8);
  const auto* p = begin+12; const auto* end = begin+bytes;
  std::vector<Visual> visuals;
  for (uint32_t i = 0; i < count; ++i) {
    if (end-p < 8) throw std::invalid_argument("truncated item visual record");
    const auto names = word<uint16_t>(p), labels = word<uint16_t>(p+2);
    const auto width = word<uint16_t>(p+4), height = word<uint16_t>(p+6);
    p += 8;
    if (!names || names >= 96 || !labels || labels > 192 ||
        !width || width > 128 || !height || height > 128 ||
        size_t(end-p) < size_t(names)+labels+size_t(width)*height*4)
      throw std::invalid_argument("invalid item visual record bounds");
    Visual visual{};
    visual.name.assign(reinterpret_cast<const char*>(p),names); p += names;
    if (!std::all_of(visual.name.begin(),visual.name.end(),canonical) ||
        (!visuals.empty() && visuals.back().name >= visual.name))
      throw std::invalid_argument("invalid or unordered item visual name");
    if (std::memchr(p,0,labels)) throw std::invalid_argument("embedded item label terminator");
    const int length = MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,
      reinterpret_cast<const char*>(p),labels,nullptr,0);
    if (length <= 0) throw std::invalid_argument("invalid UTF-8 item label");
    visual.label.resize(size_t(length));
    if (MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,
          reinterpret_cast<const char*>(p),labels,visual.label.data(),length) != length)
      throw std::runtime_error("cannot decode item label");
    p += labels;
    visual.width = width; visual.height = height;
    visual.pixels.resize(size_t(width)*height);
    std::memcpy(visual.pixels.data(),p,visual.pixels.size()*4);
    p += visual.pixels.size()*4;
    visuals.push_back(std::move(visual));
  }
  if (p != end) throw std::invalid_argument("trailing item visual data");
  visuals_ = std::move(visuals); source_ = data; bytes_ = bytes;
  selected_ = painted_ = -1;
  image_ = {};
}
void ItemHint::configure(const ItemHintRequest& request, const void* catalog, uint32_t bytes) {
  close();
  if (request.size != sizeof(request) || request.item > 141)
    throw std::invalid_argument("invalid selected item request");
  if (catalog != source_ || bytes != bytes_) load(catalog,bytes);
  if (!request.item) return;
  const auto* end = static_cast<const char*>(std::memchr(request.name,0,sizeof(request.name)));
  if (!end || end == request.name || !std::all_of(request.name,end,canonical))
    throw std::invalid_argument("invalid selected item name");
  const std::string name(request.name,end);
  const auto it = std::lower_bound(visuals_.begin(),visuals_.end(),name,
    [](const Visual& visual, const std::string& key) { return visual.name < key; });
  if (it != visuals_.end() && it->name == name) selected_ = int(it-visuals_.begin());
  // Inspection pages/aliases without an explicit Inventory verb have no guessed icon.
}
std::optional<PanelGeometry> ItemHint::prepare(const FrameViews& views, unsigned hand,
                                              const PanelFrame* panel) {
  if (selected_ < 0) return std::nullopt;
  if (hand > 1 || !(views.input.flags & InputFocused) ||
      !(views.input.hands[hand].flags & AimValid)) { close(); return std::nullopt; }
  const auto& controller = views.input.hands[hand];
  for (float value : controller.position)
    if (!std::isfinite(value)) { close(); return std::nullopt; }
  PanelGeometry result{};
  XrVector3f local{};
  if (panel && (panel->pointer.flags & PointerHit)) {
    if (panel->hand != hand || !panel->canvasWidth || !panel->canvasHeight)
      throw std::invalid_argument("item hint received another pointer owner");
    result = panel->geometry;
    local = {(panel->pointer.x/float(panel->canvasWidth)-.5f)*result.size[0],
             (.5f-panel->pointer.y/float(panel->canvasHeight))*result.size[1], .02f};
  } else {
    const auto& eye = views.eyes[0];
    const auto q = normalized({eye.orientation[0],eye.orientation[1],
                               eye.orientation[2],eye.orientation[3]});
    result.orientation[0]=q.x; result.orientation[1]=q.y;
    result.orientation[2]=q.z; result.orientation[3]=q.w;
    const auto direction = rotate(normalized({controller.orientation[0],controller.orientation[1],
                                             controller.orientation[2],controller.orientation[3]}),{0,0,-1});
    for (unsigned i = 0; i < 3; ++i) result.position[i] = controller.position[i];
    result.position[0] += direction.x*.8f;
    result.position[1] += direction.y*.8f;
    result.position[2] += direction.z*.8f;
  }
  // Offset beside the exact pointer, not into its hitbox. Never move or clamp picking.
  local.x += hand ? .24f : -.24f; local.y -= .09f;
  const auto offset = rotate(normalized({result.orientation[0],result.orientation[1],
                                         result.orientation[2],result.orientation[3]}),local);
  result.position[0] += offset.x; result.position[1] += offset.y; result.position[2] += offset.z;
  result.size[0] = .4f; result.size[1] = .1f;
  return result;
}
const OverlayImage& ItemHint::image() {
  if (selected_ < 0) throw std::logic_error("item hint is not visible");
  if (painted_ == selected_) return image_;
  const auto& visual = visuals_.at(size_t(selected_));
  LabelCanvas canvas(Width,Height,30);
  if (!canvas.valid()) throw std::runtime_error("cannot create item feedback canvas");
  std::fill_n(canvas.pixels,size_t(Width)*Height,0xff161b22u);
  if (!SetBkMode(canvas.dc,TRANSPARENT) || SetTextColor(canvas.dc,RGB(245,247,250)) == CLR_INVALID)
    throw std::runtime_error("cannot configure item feedback text");
  RECT name{96,10,LONG(Width)-12,78}, hint{96,82,LONG(Width)-12,LONG(Height)-6};
  if (!DrawTextW(canvas.dc,visual.label.c_str(),int(visual.label.size()),&name,DT_WORDBREAK|DT_NOPREFIX) ||
      !DrawTextW(canvas.dc,L"Use on...   Back: cancel",-1,&hint,DT_SINGLELINE|DT_NOPREFIX))
    throw std::runtime_error("cannot draw item feedback text");
  if (!GdiFlush()) throw std::runtime_error("cannot finish item feedback text");
  image_.width = Width; image_.height = Height;
  image_.pixels.assign(canvas.pixels,canvas.pixels+size_t(Width)*Height);
  for (auto& pixel : image_.pixels) pixel |= 0xff000000u;
  for (uint32_t y = 0; y < 64; ++y) for (uint32_t x = 0; x < 64; ++x) {
    const auto pixel = visual.pixels[size_t(y*visual.height/64)*visual.width+x*visual.width/64];
    const unsigned alpha = pixel >> 24, inverse = 255-alpha;
    auto& out = image_.pixels[size_t(y+32)*Width+x+16];
    uint32_t blended = 0xff000000u;
    for (unsigned shift : {0u,8u,16u}) {
      const auto channel = std::min(255u,((pixel >> shift)&255) + (((out >> shift)&255)*inverse+127)/255);
      blended |= channel << shift;
    }
    out = blended;
  }
  image_.bounds = {0,0,Width,Height}; image_.coverage.clear();
  image_.interactiveBounds = {}; painted_ = selected_;
  return image_;
}

} // namespace gk3hd::vr
