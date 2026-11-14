#include "game_menu.h"
#include "camera.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>

using namespace gk3hd::vr;
namespace {
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
PanelGeometry parent() { return {{0,0,0,1}, {0,1.5f,-1.6f}, {1.6f,1.f}}; }
InputSnapshot controllers() {
  InputSnapshot result{}; result.flags = InputFocused;
  for (auto& hand : result.hands) { hand.flags = AimValid; hand.orientation[3] = 1; hand.position[1] = 1.5f; }
  return result;
}
void neutral(InputSnapshot& input) { for (auto& hand : input.hands) hand.held = hand.pressed = 0; }
void aim(InputSnapshot& input, const GameMenuFrame& frame, const OverlayRegion& r) {
  auto& hand = input.hands[frame.hand];
  hand.orientation[3] = 1;
  hand.position[0] = frame.geometry.position[0]+((float(r.left+r.right)*.5f)/GameMenuState::Width-.5f)*frame.geometry.size[0];
  hand.position[1] = frame.geometry.position[1]+(.5f-(float(r.top+r.bottom)*.5f)/GameMenuState::Height)*frame.geometry.size[1];
  hand.position[2] = frame.geometry.position[2]+1;
}
const GameMenuButton& button(const GameMenuState& state, GameMenuCommand command) {
  for (const auto& b : state.buttons()) if (b.command == command) return b;
  throw std::runtime_error("menu command absent");
}
GameMenuFrame click(GameMenuState& state, InputSnapshot& input, GameMenuCommand command,
                    unsigned hand = 1, uint32_t allowed = GameMenuAllowed) {
  neutral(input);
  auto frame = state.prepare(7,allowed,parent(),input,hand,true);
  aim(input,frame,button(state,command).bounds);
  frame = state.prepare(7,allowed,parent(),input,hand,true);
  input.hands[hand].held = input.hands[hand].pressed = Select;
  return state.prepare(7,allowed,parent(),input,hand,true);
}
void selection() {
  for (unsigned hand : {0u,1u}) {
    GameMenuState state; auto input = controllers();
    input.hands[hand].held = input.hands[hand].pressed = Select;
    auto frame = state.prepare(7,GameMenuAllowed,parent(),input,hand,true);
    aim(input,frame,button(state,GameMenuCommand::Resume).bounds);
    frame = state.prepare(7,GameMenuAllowed,parent(),input,hand,true);
    require(!frame.action.command,"opening Select activated Resume");
    frame = click(state,input,GameMenuCommand::Resume,hand);
    require(frame.action.command == uint32_t(GameMenuCommand::Resume),"fresh Select did not Resume");
    require(frame.pointer.flags == PointerHit && frame.hovered == 0,"menu cursor and button disagree");
    require(!state.prepare(7,GameMenuAllowed,parent(),input,hand,true).action.command,"held Select replayed");
  }
}
void quitAndControls() {
  GameMenuState state; auto input = controllers();
  auto frame = click(state,input,GameMenuCommand::Quit);
  require(frame.page == GameMenuPage::ConfirmQuit && !frame.action.command,"Quit was not separately confirmed");
  require(!state.prepare(7,GameMenuAllowed,parent(),input,1,true).action.command,"opening Quit press confirmed");
  frame = click(state,input,GameMenuCommand::None);
  require(frame.page == GameMenuPage::Main && !frame.action.command,"Keep playing did not cancel Quit");
  frame = click(state,input,GameMenuCommand::Controls);
  require(frame.page == GameMenuPage::Controls && !frame.action.command,"Controls leaked a native action");
  neutral(input); state.prepare(7,GameMenuAllowed,parent(),input,1,true);
  input.hands[0].pressed = input.hands[0].held = Cancel;
  frame = state.prepare(7,GameMenuAllowed,parent(),input,1,true);
  require(frame.page == GameMenuPage::Main && !frame.action.command,"Back did not return to main menu");
  frame = click(state,input,GameMenuCommand::Quit);
  frame = click(state,input,GameMenuCommand::Quit);
  require(frame.action.command == uint32_t(GameMenuCommand::Quit),"confirmed Quit missing");
}
void lossAndMisses() {
  GameMenuState state; auto input = controllers();
  auto frame = click(state,input,GameMenuCommand::Save);
  require(frame.action.command == uint32_t(GameMenuCommand::Save),"Save action missing");
  input.hands[1].flags = 0;
  frame = state.prepare(7,GameMenuAllowed,parent(),input,1,true);
  require(frame.visible && !frame.pointer.flags && !frame.action.command,"lost hand hid menu or selected");
  input.hands[1].flags = AimValid;
  frame = state.prepare(7,GameMenuAllowed,parent(),input,1,true);
  require(!frame.action.command,"held reacquisition replayed Select");
  input.flags = 0;
  require(!state.prepare(7,GameMenuAllowed,parent(),input,1,true).action.command,"unfocused menu acted");
  input.flags = InputFocused;
  input.hands[1].position[0] = 50;
  neutral(input); frame = state.prepare(7,0,parent(),input,1,true);
  require(!frame.pointer.flags && frame.hovered == -1,"off-panel miss was clamped");
  aim(input,frame,button(state,GameMenuCommand::Save).bounds);
  input.hands[1].held = input.hands[1].pressed = Select;
  frame = state.prepare(7,0,parent(),input,1,true);
  require(frame.hovered == -1 && !frame.action.command,"unavailable action was selectable");
}
void modalAndMailbox() {
  GameMenu menu; GameMenuRequest request{}; request.epoch = 12; request.allowed = GameMenuAllowed;
  menu.configure(request);
  PanelFrame panel{}; panel.geometry = parent(); panel.input = controllers();
  panel.pointer = {PointerHit,1,50,50,Select|Inventory|Menu,Select|Inventory|Menu};
  panel.input.hands[0].held = Select|Cancel|Inventory;
  panel.input.hands[0].stick[0] = 1;
  auto frame = menu.prepare(panel);
  require(frame.visible && !panel.pointer.flags && !panel.pointer.held,"menu did not block underlying pointer");
  for (const auto& hand : panel.input.hands)
    require(!hand.held && !hand.pressed && !hand.stick[0] && !hand.stick[1],"menu leaked buttons or movement");
  panel.input = controllers(); panel.geometry = parent(); menu.prepare(panel);
  panel.input = controllers(); panel.input.hands[0].held = panel.input.hands[0].pressed = Menu;
  panel.geometry = parent(); frame = menu.prepare(panel);
  require(frame.action.command == uint32_t(GameMenuCommand::Resume),"off-hand Menu did not Resume");
  menu.configure(request);
  require(request.action.epoch == 12 && request.action.command == uint32_t(GameMenuCommand::Resume),"completed action was not delivered");
  menu.configure(request); require(!request.action.command,"action delivered twice");
  panel.input = controllers(); panel.geometry = parent(); menu.prepare(panel);
  panel.input.hands[0].held = panel.input.hands[0].pressed = Menu; menu.prepare(panel);
  request.epoch = 13; menu.configure(request);
  require(!request.action.command,"stale action crossed menu epoch");
  request.epoch = 0; menu.configure(request); require(!menu.active(),"menu failed to retire");
}
void labels() {
  GameMenuState state; auto input = controllers();
  auto frame = state.prepare(7,GameMenuAllowed,parent(),input,1,true);
  const auto& image = state.image(frame);
  require(image.width == GameMenuState::Width && image.height == GameMenuState::Height,"invalid menu image extent");
  require(std::all_of(image.pixels.begin(),image.pixels.end(),[](uint32_t p) {return (p>>24) == 255;}),"GDI label alpha was not opaque");
  const auto original = image.pixels;
  frame = click(state,input,GameMenuCommand::Controls);
  require(state.image(frame).pixels != original,"Controls labels did not change");
  state.close(); require(state.image({}).pixels.empty(),"retired menu retained pixels");
}
void heldHandoff() {
  for (unsigned pointing : {0u,1u}) for (unsigned source : {0u,1u})
    for (uint32_t key : {uint32_t(Select),uint32_t(Cancel),uint32_t(Menu),uint32_t(Inventory)}) {
      GameMenu menu; GameMenuRequest request{}; request.epoch = 21;
      menu.configure(request);
      PanelFrame panel{}; panel.hand = pointing; panel.geometry = parent(); panel.input = controllers();
      menu.prepare(panel);
      panel.input = controllers(); panel.input.hands[source].held = panel.input.hands[source].pressed = key;
      menu.prepare(panel);
      request.epoch = 0; menu.configure(request);
      require(!menu.active(),"menu did not retire its visual owner");
      for (unsigned frame = 0; frame < 3; ++frame) {
        panel.input = controllers(); panel.input.hands[source].held = panel.input.hands[source].pressed = key;
        panel.pointer = {PointerHit,pointing,12,34,key,key};
        if (frame == 1) { menu.close(); menu.filterInput(panel); } // world/isolated presentation
        else menu.prepare(panel); // ordinary resumed inventory/page
        require(!panel.input.hands[source].held && !panel.input.hands[source].pressed,
                "dismissed gesture became underlying input before release");
        require(!panel.pointer.held && !panel.pointer.pressed,"pointer retained a consumed shortcut");
        require(panel.pointer.flags == PointerHit && panel.pointer.x == 12 && panel.pointer.y == 34,
                "button retirement changed pointer geometry");
      }
      // A shortcut on the other controller is independent, even if its bit
      // equals the still-consumed button. Never retire shortcuts globally.
      if (key != Select) {
        panel.input = controllers();
        panel.input.hands[source].held = key;
        panel.input.hands[source^1].held = panel.input.hands[source^1].pressed = key;
        menu.filterInput(panel);
        require(panel.pointer.held == key && panel.pointer.pressed == key,
                "retirement swallowed a fresh shortcut from the other hand");
      }
      panel.input = controllers(); menu.filterInput(panel); // actual release
      panel.input = controllers(); panel.input.hands[source].held = panel.input.hands[source].pressed = key;
      menu.filterInput(panel);
      require(panel.input.hands[source].held == key && panel.input.hands[source].pressed == key,
              "fresh press stayed retired after release");
    }
}
void lostHandoff() {
  for (unsigned lost = 0; lost < 2; ++lost) {
    GameMenu menu; GameMenuRequest request{}; request.epoch = 22; menu.configure(request);
    PanelFrame panel{}; panel.geometry = parent(); panel.input = controllers();
    panel.input.hands[1].held = Cancel; menu.prepare(panel);
    request.epoch = 0; menu.configure(request);
    panel.input = controllers();
    if (lost) panel.input.hands[1].flags = 0; else panel.input.flags = 0;
    menu.filterInput(panel);
    panel.input = controllers(); panel.input.hands[1].held = panel.input.hands[1].pressed = Cancel;
    menu.filterInput(panel);
    require(!panel.pointer.held && !panel.pointer.pressed,
            "tracking/focus loss manufactured a release for a menu gesture");
  }
}
}
int main() {
  try { selection(); quitAndControls(); lossAndMisses(); modalAndMailbox(); labels(); heldHandoff(); lostHandoff();
    std::cout << "Shared game menu selection, confirmation, ownership and labels passed\n"; return 0;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
