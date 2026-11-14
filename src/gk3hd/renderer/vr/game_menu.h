#pragma once

#include "panel_bridge.h"
#include "overlay.h"
#include <array>
#include <string>
#include <vector>

namespace gk3hd::vr {

enum class GameMenuCommand : uint32_t {
  None, Resume, Save, Load, Settings, Controls, ReturnToProtagonist, Quit
};
constexpr uint32_t gameMenuBit(GameMenuCommand command) { return 1u << uint32_t(command); }
constexpr uint32_t GameMenuAllowed = gameMenuBit(GameMenuCommand::Save) |
  gameMenuBit(GameMenuCommand::Load) | gameMenuBit(GameMenuCommand::Settings) |
  gameMenuBit(GameMenuCommand::ReturnToProtagonist);
struct GameMenuAction { uint32_t epoch = 0, command = 0; };
// Native code supplies current Pause ownership, never a native pointer. An
// action belongs to that epoch and is consumed at most once on the game thread.
struct GameMenuRequest {
  uint32_t size = sizeof(GameMenuRequest), epoch = 0, allowed = 0;
  GameMenuAction action{};
};
static_assert(sizeof(GameMenuRequest) == 20);
enum class GameMenuPage { Main, Controls, ConfirmQuit };
struct GameMenuButton {
  GameMenuCommand command;
  std::string label;
  OverlayRegion bounds;
  bool enabled = true;
};
struct GameMenuFrame {
  bool visible = false;
  uint32_t epoch = 0, hand = 0;
  int hovered = -1;
  GameMenuPage page = GameMenuPage::Main;
  PanelGeometry geometry{};
  PanelPointer pointer{};
  GameMenuAction action{};
};

class GameMenuState {
public:
  static constexpr uint32_t Width = 960, Height = 1000;
  GameMenuFrame prepare(uint32_t epoch, uint32_t allowed, const PanelGeometry& parent,
                        const InputSnapshot& input, unsigned hand, bool available);
  const OverlayImage& image(const GameMenuFrame& frame);
  const std::vector<GameMenuButton>& buttons() const { return buttons_; }
  void close() noexcept;
private:
  void layout(uint32_t allowed);
  void changePage(GameMenuPage page, uint32_t allowed);
  uint32_t epoch_ = 0, hand_ = 0, allowed_ = 0;
  bool blocked_ = true, down_ = false, dirty_ = true;
  uint32_t shortcutHeld_ = 0, shortcutBlocked_ = Cancel | Menu;
  GameMenuPage page_ = GameMenuPage::Main;
  int paintedHover_ = -2;
  std::vector<GameMenuButton> buttons_;
  OverlayImage image_{};
};

class GameMenu {
public:
  void configure(GameMenuRequest& request);
  bool active() const { return epoch_ != 0; }
  GameMenuFrame prepare(PanelFrame& panel);
  // A dismissed menu's held gestures cannot become presses on its parent.
  // Apply on ordinary panels, isolated menus and world-only presentation.
  void filterInput(PanelFrame& panel);
  const OverlayImage& image(const GameMenuFrame& frame) { return state_.image(frame); }
  void close() noexcept;
private:
  GameMenuState state_;
  uint32_t epoch_ = 0, allowed_ = 0;
  GameMenuAction pending_{};
  std::array<uint32_t, 2> consumed_{};
};

} // namespace gk3hd::vr
