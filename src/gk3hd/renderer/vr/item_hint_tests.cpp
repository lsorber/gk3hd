#include "item_hint.h"
#include <cstring>
#include <iostream>
#include <stdexcept>

using namespace gk3hd::vr;
namespace {
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
template<typename F> void rejects(F f) {
  bool rejected = false; try { f(); } catch (const std::invalid_argument&) { rejected = true; }
  require(rejected,"malformed item feedback accepted");
}
std::vector<uint8_t> catalog() {
  // One magenta-keyed, black/red original-style icon and a UTF-8 label.
  std::vector<uint8_t> data{'G','K','3','I','T','M','0','1',1,0,0,0,
    4,0,9,0,3,0,1,0,'N','O','T','E','N','o','t','e','b','o','o','k','!',
    0,0,0,0, 0,0,0,255, 0,0,255,255};
  return data;
}
FrameViews tracking() {
  FrameViews v{}; v.input.flags = InputFocused;
  for (auto& eye : v.eyes) eye.orientation[3] = 1;
  for (auto& hand : v.input.hands) { hand.flags = AimValid; hand.orientation[3] = 1; }
  return v;
}
void testFeedback() {
  auto data = catalog(); ItemHint hint; ItemHintRequest request{};
  request.item = 104; std::memcpy(request.name,"NOTE",5);
  hint.configure(request,data.data(),uint32_t(data.size()));
  auto v = tracking();
  const auto right = hint.prepare(v,1), left = hint.prepare(v,0);
  require(right && left && right->position[0] > 0 && left->position[0] < 0,
          "selected item does not follow the configured hand");
  const auto& image = hint.image();
  require(image.width==512 && image.height==128 && image.interactiveBounds.empty(),
          "item feedback acquired a picking footprint");
  require(image.pixels[32*512+16]==0xff161b22u,"transparent icon erased its background");
  require(image.pixels[32*512+40]==0xff000000u,"black artwork became transparent");
  require(image.pixels[32*512+70]==0xffff0000u,"original icon color changed");
  size_t glyphs=0;
  for (const auto pixel : image.pixels) {
    require((pixel>>24)==255,"label canvas lost opacity");
    glyphs += (pixel&255)>200 && ((pixel>>8)&255)>200 && ((pixel>>16)&255)>200;
  }
  require(glyphs>500,"selected item name or Use-on hint is absent");
  PanelFrame panel{}; panel.hand=1; panel.canvasWidth=1280; panel.canvasHeight=800;
  panel.geometry.orientation[3]=1; panel.geometry.position[2]=-1.6f;
  panel.geometry.size[0]=2.4f; panel.geometry.size[1]=1.5f;
  panel.pointer={PointerHit,1,640,400,Select,Select};
  const auto original = panel;
  require(hint.prepare(v,1,&panel).has_value() &&
          !std::memcmp(&panel,&original,sizeof(panel)),"item hint changed picking or input");
  v.input.flags=0;
  require(!hint.prepare(v,1),"unfocused item feedback remained visible");
  v.input.flags=InputFocused;
  require(!hint.prepare(v,1),"focus recovery resurrected a stale selection");
  hint.configure(request,data.data(),uint32_t(data.size()));
  v.input.hands[1].flags=0;
  require(!hint.prepare(v,1),"lost interaction hand kept item feedback");
  hint.configure(request,data.data(),uint32_t(data.size()));
  request.item=0; hint.configure(request,data.data(),uint32_t(data.size()));
  require(!hint.prepare(tracking(),1),"cancelled item remained visible");
  request.item=104; std::memcpy(request.name,"NONE",5);
  hint.configure(request,data.data(),uint32_t(data.size()));
  require(!hint.prepare(tracking(),1),"unknown item guessed an icon");
}
void testMalformed() {
  auto data=catalog(); ItemHint hint; ItemHintRequest request{};
  request.item=104; std::memcpy(request.name,"NOTE",5);
  rejects([&]{ hint.configure(request,data.data(),uint32_t(data.size()-1)); });
  data.push_back(0);
  rejects([&]{ hint.configure(request,data.data(),uint32_t(data.size())); });
  data=catalog(); data[16]=129;
  rejects([&]{ hint.configure(request,data.data(),uint32_t(data.size())); });
  data=catalog(); data[8]=255; data[9]=255;
  rejects([&]{ hint.configure(request,data.data(),uint32_t(data.size())); });
  data=catalog(); data[24]=0xff;
  rejects([&]{ hint.configure(request,data.data(),uint32_t(data.size())); });
  data=catalog(); std::memset(request.name,'A',sizeof(request.name));
  rejects([&]{ hint.configure(request,data.data(),uint32_t(data.size())); });
}
}
int main() {
  try { testFeedback(); testMalformed();
    std::cout << "Selected-item feedback passed: labels, original icon/keying, both hands, no picking changes, cancellation, focus/tracking loss and malformed assets\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
