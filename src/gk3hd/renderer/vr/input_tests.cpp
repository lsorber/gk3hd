#include "input.h"
#include "input_test_runtime.h"

#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <set>
#include <stdexcept>

using namespace gk3hd::vr;
namespace {
namespace test = gk3hd::vr::testinput;
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
void rejects(const std::function<void()>& call) {
  try { call(); } catch (const std::exception&) { return; }
  throw std::runtime_error("invalid input operation accepted");
}
const auto instance = test::handle<XrInstance>(1);
const auto session = test::handle<XrSession>(2);
const auto base = test::handle<XrSpace>(3);
void empty() {
  require(test::model.sets.empty() && test::model.actions.empty() && test::model.spaces.empty(),
          "input resources leaked");
}
void prepare(Actions& input) {
  input.initialize(instance); input.attach(session);
  for (auto& hand : test::model.hands) hand.active = true;
}
void lifecycle() {
  test::model = {};
  {
    Actions input(test::resolve);
    rejects([&] { input.sample(base, 10, true); });
    prepare(input);
    rejects([&] { input.initialize(instance); });
    rejects([&] { input.attach(session); });
    rejects([&] { input.sample(base, 0, true); });
    const auto first = input.sample(base, 100, true);
    require(first.flags == InputFocused && first.hands[0].flags == AimValid &&
            first.hands[1].flags == AimValid && test::model.locatedTime == 100,
            "aim was not located at predicted display time");
    test::model.hands[0].pose.position.x = -.25f;
    test::model.hands[1].pose.position.x = .45f;
    test::model.hands[1].pose.orientation.w = -2.f;
    test::model.hands[0].buttons = Select | Inventory;
    test::model.hands[1].buttons = Cancel | Menu | Recenter;
    auto state = input.sample(base, 110, true);
    require(state.hands[0].pressed == (Select | Inventory) &&
            state.hands[1].pressed == (Cancel | Menu | Recenter) &&
            state.hands[0].position[0] == -.25f && state.hands[1].position[0] == .45f &&
            state.hands[1].orientation[3] == -1.f, "hands, pose or button edges confused");
    state = input.sample(base, 120, true);
    require(!state.hands[0].pressed && state.hands[0].held == (Select | Inventory),
            "held button repeatedly clicked");
    test::model.hands[0].activeButtons &= ~Select;
    state = input.sample(base, 121, true);
    require(state.hands[0].held == Inventory, "inactive action still held");
    test::model.hands[0].activeButtons |= Select;
    state = input.sample(base, 122, true);
    require(state.hands[0].held == Inventory && !state.hands[0].pressed,
            "reconnected action activated a held control");
    test::model.hands[0].stick = {2.f, -.7f};
    state = input.sample(base, 130, true);
    require(state.hands[0].stick[0] == 1.f && state.hands[0].stick[1] == -.7f,
            "stick state not preserved/clamped");
    input.closeSession();
    require(test::model.spaces.empty() && test::model.sets.size() == 1,
            "session close did not retain action set");
    input.attach(test::handle<XrSession>(4));
    state = input.sample(base, 140, true);
    require(!state.hands[0].held && !state.hands[1].held && !state.hands[0].stick[0],
            "session recreation activated held controls");
  }
  empty();
}
void recovery() {
  test::model = {};
  {
    Actions input(test::resolve); prepare(input);
    test::model.hands[0].buttons = Select;
    test::model.hands[0].stick = {.8f, .5f};
    auto state = input.sample(base, 10, true);
    require(!state.hands[0].pressed && !state.hands[0].stick[0], "initial held controls activated");
    test::model.hands[0].buttons = 0; test::model.hands[0].stick = {};
    input.sample(base, 20, true);
    test::model.hands[0].buttons = Select; test::model.hands[0].stick = {.8f, .5f};
    state = input.sample(base, 30, true);
    require(state.hands[0].pressed == Select && state.hands[0].stick[0] == .8f,
            "released controls did not rearm");
    const auto syncs = test::model.syncs;
    state = input.sample(base, 40, false);
    require(!state.flags && !state.hands[0].flags && test::model.syncs == syncs,
            "dashboard focus did not suppress input");
    state = input.sample(base, 50, true);
    require(!state.hands[0].held && !state.hands[0].stick[0], "focus recovery activated controls");
    for (auto result : {XR_SESSION_NOT_FOCUSED, XR_SESSION_LOSS_PENDING}) {
      test::model.syncResult = result;
      state = input.sample(base, 60, true);
      require(!state.flags && !state.hands[0].flags, "positive runtime result accepted stale input");
    }
    test::model.syncResult = XR_SUCCESS;
    test::model.hands[0].valid = false;
    state = input.sample(base, 70, true);
    require(!state.hands[0].flags && state.hands[1].flags == AimValid,
            "one lost pointer disabled the wrong hand");
    test::model.hands[0].valid = true;
    state = input.sample(base, 80, true);
    require(!state.hands[0].held && !state.hands[0].stick[0], "tracking recovery activated controls");
    test::model.hands[0].pose.orientation = {};
    state = input.sample(base, 90, true);
    require(!state.hands[0].flags, "zero quaternion exposed as a usable pointer");
    test::model.hands[0].pose.orientation.w = 1;
    test::model.hands[0].pose.position.x = std::numeric_limits<float>::infinity();
    state = input.sample(base, 100, true);
    require(!state.hands[0].flags, "nonfinite position exposed as usable pointer");
    test::model.hands[0].pose.position.x = 0; test::model.hands[0].buttons = 0;
    test::model.hands[0].stick = {};
    input.sample(base, 110, true);
    test::model.hands[0].stick.x = std::numeric_limits<float>::quiet_NaN();
    state = input.sample(base, 120, true);
    require(state.hands[0].flags == AimValid && !state.hands[0].stick[0], "invalid stick polluted pose");
    test::model.hands[0].stick = {.5f, 0};
    require(!input.sample(base, 130, true).hands[0].stick[0], "invalid-stick recovery skipped neutral latch");
    test::model.fail = "boolean";
    rejects([&] { input.sample(base, 140, true); });
    test::model.fail.clear(); test::model.hands[0].buttons = Select;
    require(!input.sample(base, 150, true).hands[0].held, "query failure retained stale latch");
  }
  empty();
}
void failures() {
  for (const char* failure : {"createSet", "createAction", "suggest"}) {
    test::model = {}; test::model.fail = failure;
    Actions input(test::resolve);
    rejects([&] { input.initialize(instance); }); empty();
    test::model.fail.clear(); input.initialize(instance); input.shutdown(); empty();
  }
  for (unsigned failedSpace : {1u, 2u}) {
    test::model = {}; test::model.failSpaceAt = failedSpace;
    Actions input(test::resolve); input.initialize(instance);
    rejects([&] { input.attach(session); });
    require(test::model.spaces.empty(), "partial pointing spaces leaked");
    input.attach(test::handle<XrSession>(4));
    input.shutdown(); empty();
  }
  test::model = {};
  Actions input(test::resolve); input.initialize(instance);
  test::model.fail = "attach";
  rejects([&] { input.attach(session); });
  test::model.fail.clear(); input.attach(session);
  for (auto& hand : test::model.hands) hand.active = true;
  for (const char* failure : {"sync", "locate"}) {
    test::model.fail = failure;
    rejects([&] { input.sample(base, 10, true); });
    test::model.fail.clear();
    require(input.sample(base, 20, true).hands[0].flags == AimValid, "sampling cannot recover");
  }
  input.shutdown(); empty();
}
void bindings() {
  test::model = {};
  Actions input(test::resolve); input.initialize(instance);
  std::set<std::string> profiles;
  std::set<std::pair<std::string, std::string>> components;
  for (const auto& binding : test::model.bindings) {
    profiles.insert(binding.profile);
    require(components.insert({binding.profile, binding.path}).second,
            "one controller control triggers multiple actions");
    require(binding.path.find("/input/system/") == std::string::npos, "dashboard button bound");
    if (binding.action == "aim") require(binding.type == XR_ACTION_TYPE_POSE_INPUT, "wrong aim type");
    if (binding.action == "stick") require(binding.type == XR_ACTION_TYPE_VECTOR2F_INPUT, "wrong stick type");
    if (binding.profile.find("oculus/") != std::string::npos) {
      const bool left = binding.path.find("/left/") != std::string::npos;
      require(binding.path.find(left ? "/a/click" : "/x/click") == std::string::npos &&
              binding.path.find(left ? "/b/click" : "/y/click") == std::string::npos,
              "Touch binding uses opposite-hand buttons");
    }
  }
  require(profiles.size() == 5, "core controller profiles missing");
  input.shutdown(); empty();
  test::model = {};
  test::model.unsupportedProfile = "/interaction_profiles/htc/vive_controller";
  rejects([&] { input.initialize(instance); }); empty();
  test::model.unsupportedProfile.clear();
  input.initialize(instance); input.attach(session);
  input.shutdown(); empty();
}
} // namespace
int main() {
  try {
    lifecycle(); recovery(); failures(); bindings();
    std::cout << "Input passed: predicted poses, independent hands, focus/tracking guards, release-to-rearm, profile bindings, cleanup and recreation\n";
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
