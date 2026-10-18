"""Execute the native controller route, including cancellation and host isolation."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDX,
    UC_X86_REG_ESP,
)

from gk3hd.patch.binary.x86 import X86Emitter
from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_input import VRInputCompiler
from gk3hd.patch.definitions.vr_native_scene import NATIVE_SCENE_TYPES
from gk3hd.patch.definitions.vr_navigation import VRNavigationCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.definitions.vr_world import VRWorldCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_vr_panel import _linked_panel
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_navigation import VRNavigationABI


class InputHarness:
    """A native UI observer, not a second implementation of the router."""

    def __init__(
        self,
        profile: BuildProfile = GOG_BUILD,
        *,
        paired: bool = False,
        world: bool = False,
        navigation: bool = False,
    ) -> None:
        image, self.panel, previous = _linked_panel(paired=paired or world)
        self.scene = VRSceneCompiler(profile=profile, units_per_meter=40).abi(image)
        self.world = None
        self.navigation = None
        if world:
            world_compiler = VRWorldCompiler(profile=profile, scene=self.scene)
            world_compiler.apply(image)
            world_compiler.postcheck(image)
            self.world = world_compiler.abi(image)
        if navigation:
            self.navigation = self.install_navigation(image, profile)
        for event in VRInputCompiler._events:
            image.write_u32_va(
                profile.address(f"input.{event}_slot"), profile.address(f"input.{event}")
            )
        self.compiler = VRInputCompiler(
            profile=profile,
            panel=self.panel,
            expected_presenter_va=previous,
            world=self.world,
            navigation=self.navigation,
        )
        self.compiler.apply(image)
        self.compiler.postcheck(image)
        self.abi = self.compiler.abi(image)
        self.machine = _machine(image)
        self.initialize_exception_chain()
        self.entry = image.read_u32_va(
            TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
        )
        self.image = image
        self.owner = _HEAP + 0x6000
        self.events: list[tuple[str, tuple[int, int]]] = []
        self.keys: list[tuple[str, int, int]] = []
        self.characters: list[tuple[int, int]] = []
        self.world_routes: list[tuple[str, int]] = []
        self.change_on = ""
        self.presented = 0
        self.composed = 0
        self.profile = profile
        self.previous = previous
        self.word(self.abi.enabled_va, 1)
        self.word(self.panel.enabled_va, 1)
        if self.world is not None:
            self.word(self.world.enabled_va, 1)
            self.word(self.scene.enabled_va, 1)
            self.word(self.owner, profile.address("vr.room_layer_vtable"))
            self.room = _HEAP + 0xB000
            self.word(profile.address("vr.room_global"), self.room)
            self.word(self.room, profile.address("vr.user_scene_vtable"))
            self.machine.mem_write(profile.site("vr.world_hover").va, bytes.fromhex("c2 04 00"))
        self.word(profile.address("mouse_move.mouse_manager"), _HEAP + 0x5000)
        self.engine = _HEAP + 0x8000
        self.word(profile.address("engine.loop"), self.engine)
        self.machine.mem_write(previous, b"\xc3")
        self.machine.mem_write(self.panel.composition_presenter_va, b"\xc3")
        self.machine.mem_write(profile.address("ui.current_layer"), b"\xc3")
        for event in VRInputCompiler._events:
            self.machine.mem_write(profile.address(f"input.{event}"), bytes.fromhex("c2 04 00"))
        for name in ("vr.key_down", "vr.key_up", "vr.character_event"):
            self.machine.mem_write(profile.site(name).va, bytes.fromhex("c2 08 00"))

        self.machine.hook_add(UC_HOOK_CODE, self.observe)
        self.snapshot()

    def initialize_exception_chain(self) -> None:
        """Model the real x86 thread's pre-existing exception registration."""
        self.machine.mem_map(0, 0x1000)  # x86 FS/TEB exception-chain fixture.
        self.word(0, 0x12345678)
        self.word(self.abi.enabled_va - self.compiler._enabled + self.compiler._host_focus, 1)
        self.unwind_handler = 0

    def install_navigation(self, image: PEFile, profile: BuildProfile) -> VRNavigationABI:
        nav = VRNavigationCompiler(profile=profile, panel=self.panel, scene=self.scene)
        nav.apply(image)
        nav.postcheck(image)
        return nav.abi(image)

    def observe(self, current: Uc, address: int, _size: int, _context: object) -> None:
        if address == self.previous:
            self.presented += 1
            registration = self.read(0)
            assert self.read(registration) == 0x12345678
            self.unwind_handler = self.read(registration + 4)
        if address == self.panel.composition_presenter_va:
            self.composed += 1
        if address == self.profile.address("ui.current_layer"):
            current.reg_write(UC_X86_REG_EAX, self.owner)
        self.observe_character(current, address)
        if self.world is not None and address == self.profile.site("vr.world_hover").va:
            assert current.reg_read(UC_X86_REG_ECX) == self.room
            point = self.read(current.reg_read(UC_X86_REG_ESP) + 4)
            self.events.append(("world_hover", struct.unpack("<2i", current.mem_read(point, 8))))
            self.world_routes.append(("world_hover", self.read(self.world.dispatch_va)))
            self.clobber(current, "world_hover")
        for event in ("down", "up"):
            if address == self.profile.site(f"vr.key_{event}").va:
                self.observe_key(current, event)
        for event in VRInputCompiler._events:
            if address != self.profile.address(f"input.{event}"):
                continue
            assert current.reg_read(UC_X86_REG_ECX) == self.engine
            point = self.read(current.reg_read(UC_X86_REG_ESP) + 4)
            self.events.append((event, struct.unpack("<2i", current.mem_read(point, 8))))
            if self.world is not None:
                self.world_routes.append((event, self.read(self.world.dispatch_va)))
            self.clobber(current, event)

    def observe_character(self, current: Uc, address: int) -> None:
        if address == self.profile.site("vr.character_event").va:
            assert current.reg_read(UC_X86_REG_ECX) == self.engine
            self.characters.append(
                struct.unpack("<2I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 8))
            )
            self.clobber(current, "character")

    def observe_key(self, current: Uc, event: str) -> None:
        assert current.reg_read(UC_X86_REG_ECX) == self.engine
        key, flags = struct.unpack("<2I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 8))
        self.keys.append((event, key, flags))
        self.clobber(current, f"key_{event}")

    def clobber(self, current: Uc, event: str) -> None:
        if event == self.change_on:
            self.owner += 0x100
        current.reg_write(UC_X86_REG_EAX, 0xDEAD)
        current.reg_write(UC_X86_REG_ECX, 0xBEEF)
        current.reg_write(UC_X86_REG_EDX, 0xCAFE)

    def word(self, address: int, value: int) -> None:
        self.machine.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.machine.mem_read(address, 4))[0]

    def snapshot(
        self,
        *,
        point: tuple[float, float] = (200.5, 300.5),
        held: int = 0,
        loss: str = "",
        hand: int = 1,
    ) -> None:
        frame = self.panel.frame_va
        self.word(frame + 8, 1280)
        self.word(frame + 12, 800)
        self.word(frame + 64, loss != "focus")
        for index in range(2):
            self.word(frame + 68 + 48 * index, loss != "tracking")
        self.word(frame + 164, loss != "outside")
        self.word(frame + 168, hand)
        self.machine.mem_write(frame + 172, struct.pack("<2f", *point))
        self.word(frame + 180, held)
        if self.world is not None:
            self.word(self.scene.world_input_va + 4, 3 if loss != "tracking" else 0)
            self.word(self.scene.world_input_va + 8, loss != "focus")

    def invoke(self, entry: int | None = None, *, argument: int = 123, cleanup: int = 0) -> None:
        self.machine.mem_write(_STACK, struct.pack("<2I", _RETURN, argument))
        self.machine.reg_write(UC_X86_REG_ESP, _STACK)
        self.machine.reg_write(UC_X86_REG_EBX, 37)
        self.machine.reg_write(UC_X86_REG_ECX, self.engine)
        self.machine.emu_start(self.entry if entry is None else entry, _RETURN, count=3000)
        assert self.machine.reg_read(UC_X86_REG_ESP) == _STACK + 4 + cleanup
        assert self.machine.reg_read(UC_X86_REG_EBX) == 37
        assert self.read(0) == 0x12345678

    def physical_key(self, event: str, value: int, flags: int) -> None:
        self.machine.mem_write(_STACK + 8, struct.pack("<I", flags))
        slot = self.profile.site(f"vr.host_{event}_slot").va
        self.invoke(self.image.read_u32_va(slot), argument=value, cleanup=8)


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_input_installation_is_dormant_and_verifies(profile: BuildProfile) -> None:
    harness = InputHarness(profile)
    assert harness.image.read_u32_va(harness.abi.enabled_va) == 0
    with pytest.raises(PatchError, match="already installed"):
        harness.compiler.apply(harness.image)


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
@pytest.mark.parametrize("delay", [50, 70])
@pytest.mark.parametrize("presentation", ["active", "dormant", "no_frames", "hidden", "failed"])
def test_native_button_waits_do_not_block_successful_vr_presentation(
    profile: BuildProfile, delay: int, presentation: str
) -> None:
    harness = InputHarness(profile)
    harness.word(harness.panel.enabled_va, presentation != "dormant")
    harness.word(harness.panel.submitted_frames_va, 0 if presentation == "no_frames" else 9)
    harness.word(
        harness.panel.completion_result_va,
        {"hidden": 1, "failed": 0x80004005}.get(presentation, 0),
    )
    original_sleep = _HEAP + 0xC000
    harness.word(profile.address("win32.Sleep"), original_sleep)
    harness.machine.mem_write(original_sleep, bytes.fromhex("c2 04 00"))
    waits = []

    def observe_sleep(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == original_sleep:
            waits.append(harness.read(current.reg_read(UC_X86_REG_ESP) + 4))

    harness.machine.hook_add(UC_HOOK_CODE, observe_sleep)
    entry = harness.image.read_u32_va(profile.site("vr.button_wait").va + 1)
    harness.invoke(entry, argument=delay, cleanup=4)
    assert waits == ([] if presentation == "active" else [delay])
    assert harness.presented == harness.composed == 0, "waiting must not advance the game or XR"


@pytest.mark.parametrize("delay", [0, 1, 49, 51, 69, 71, 200])
def test_unrelated_button_wait_durations_keep_native_sleep(delay: int) -> None:
    harness = InputHarness()
    harness.word(harness.panel.submitted_frames_va, 9)
    original_sleep = _HEAP + 0xC000
    harness.word(GOG_BUILD.address("win32.Sleep"), original_sleep)
    harness.machine.mem_write(original_sleep, bytes.fromhex("c2 04 00"))
    waits = []

    def observe_sleep(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == original_sleep:
            waits.append(harness.read(current.reg_read(UC_X86_REG_ESP) + 4))

    harness.machine.hook_add(UC_HOOK_CODE, observe_sleep)
    entry = harness.image.read_u32_va(GOG_BUILD.site("vr.button_wait").va + 1)
    harness.invoke(entry, argument=delay, cleanup=4)
    assert waits == [delay]


def test_changed_button_delay_call_invalidates_installed_router() -> None:
    harness = InputHarness()
    site = GOG_BUILD.site("vr.button_wait")
    harness.image.write_bytes(harness.image.va_to_offset(site.va + len(site.original)), b"\xcc")
    with pytest.raises(PatchError, match="button delay calls changed"):
        harness.compiler.postcheck(harness.image)


@pytest.mark.parametrize(
    "anchor",
    [
        "vr.key_down",
        "vr.key_up",
        "vr.menu_down",
        "vr.menu_up",
        "vr.character_event",
        "vr.movie_character",
        "vr.button_wait",
    ],
)
def test_changed_native_shortcut_is_rejected_without_modifying_executable(anchor: str) -> None:
    image, panel, previous = _linked_panel()
    for event in VRInputCompiler._events:
        image.write_u32_va(
            GOG_BUILD.address(f"input.{event}_slot"), GOG_BUILD.address(f"input.{event}")
        )
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(anchor).va), b"\xcc")
    before = image.to_bytes()
    compiler = VRInputCompiler(profile=GOG_BUILD, panel=panel, expected_presenter_va=previous)
    with pytest.raises(PatchError, match="anchor changed"):
        compiler.apply(image)
    assert image.to_bytes() == before


def test_select_and_menu_use_native_canvas_events_once() -> None:
    harness = InputHarness()
    harness.invoke()
    harness.events.clear()
    for buttons in (1, 1, 0, 4, 4, 0):
        harness.snapshot(held=buttons)
        harness.invoke()
    names = [name for name, _point in harness.events]
    assert names.count("left_down") == names.count("left_up") == 1
    assert names.count("right_down") == names.count("right_up") == 1
    assert all(
        point == (200, 300) or (name == "pointer_move" and point == (-10000, -10000))
        for name, point in harness.events
    )
    assert harness.read(harness.abi.held_va) == 0
    assert harness.presented == 7


def test_stationary_controller_does_not_restart_native_hover_animation() -> None:
    harness = InputHarness()
    for _ in range(5):
        harness.snapshot(point=(200, 300))
        harness.invoke()
    assert [point for name, point in harness.events if name == "pointer_move"] == [(200, 300)]
    harness.snapshot(point=(201, 300))
    harness.invoke()
    harness.snapshot(point=(201, 301))
    harness.invoke()
    assert [point for name, point in harness.events if name == "pointer_move"] == [
        (200, 300),
        (201, 300),
        (201, 301),
    ]


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_focused_physical_keyboard_preserves_native_typing_and_autorepeat(
    profile: BuildProfile,
) -> None:
    harness = InputHarness(profile)
    flags = 0x001E0001
    repeat = flags | 0x40000000
    harness.physical_key("key_down", ord("A"), flags)
    harness.physical_key("character", ord("a"), flags)
    harness.physical_key("key_down", ord("A"), repeat)
    harness.physical_key("character", ord("a"), repeat)
    harness.physical_key("key_up", ord("A"), flags | 0xC0000000)
    assert harness.keys == [
        ("down", ord("A"), flags),
        ("down", ord("A"), repeat),
        ("up", ord("A"), flags | 0xC0000000),
    ]
    assert harness.characters == [(ord("a"), flags), (ord("a"), repeat)]


@pytest.mark.parametrize("lost_through", ["frame", "key_down", "character"])
def test_physical_keys_require_a_fresh_press_after_dashboard_focus_loss(lost_through: str) -> None:
    harness = InputHarness()
    flags = 0x001E0001
    harness.physical_key("key_down", ord("A"), flags)
    harness.snapshot(loss="focus")
    harness.invoke()  # Publish the completed runtime focus loss.
    if lost_through == "frame":
        pass
    else:
        harness.physical_key(lost_through, ord("A"), flags | 0x40000000)
    harness.snapshot()
    harness.invoke()
    harness.keys.clear()
    harness.physical_key("key_down", ord("A"), flags | 0x40000000)
    harness.physical_key("character", ord("a"), flags | 0x40000000)
    assert harness.keys == harness.characters == []
    harness.physical_key("key_up", ord("A"), flags | 0xC0000000)
    harness.physical_key("key_down", ord("A"), flags)
    harness.physical_key("character", ord("a"), flags)
    assert harness.keys == [("up", ord("A"), flags | 0xC0000000), ("down", ord("A"), flags)]
    assert harness.characters == [(ord("a"), flags)]


def test_physical_key_release_reaches_native_cleanup_while_dashboard_has_focus() -> None:
    harness = InputHarness()
    flags = 0x002A0001
    harness.physical_key("key_down", 0x10, flags)
    harness.snapshot(loss="focus")
    harness.physical_key("key_up", 0x10, flags | 0xC0000000)
    assert harness.keys == [("down", 0x10, flags), ("up", 0x10, flags | 0xC0000000)]


@pytest.mark.parametrize("held", [1, 8 | 1, 16 | 1, 32 | 1, 0x38 | 1])
def test_dashboard_focus_loss_releases_native_modifiers_without_a_physical_key_up(
    held: int,
) -> None:
    harness = InputHarness()
    harness.word(harness.engine + 0x518, held)
    harness.snapshot(loss="focus")
    harness.invoke()
    assert harness.keys == [
        ("up", key, 0xC0000001) for key, mask in ((0x10, 8), (0x11, 16), (0x12, 32)) if held & mask
    ]
    assert harness.characters == []


def test_dormant_vr_does_not_release_a_flat_players_keyboard_modifiers() -> None:
    harness = InputHarness()
    harness.word(harness.engine + 0x518, 0x38)
    harness.word(harness.abi.enabled_va, 0)
    harness.snapshot(loss="focus")
    harness.invoke()
    assert harness.keys == []


def test_incomplete_producer_output_cannot_revoke_physical_typing_mid_frame() -> None:
    harness = InputHarness()
    flags = 0x001E0001
    emitter = X86Emitter(base_va=harness.previous)
    emitter.raw(b"\xc7\x05" + struct.pack("<I", harness.panel.frame_va + 64) + bytes(4))
    for event, value in (("key_down", ord("A")), ("key_up", ord("A")), ("character", ord("a"))):
        emitter.push_imm32(flags)
        emitter.push_imm32(value)
        emitter.raw(b"\xb9" + struct.pack("<I", harness.engine))
        emitter.call_absolute(harness.image.read_u32_va(GOG_BUILD.site(f"vr.host_{event}_slot").va))
    emitter.raw(b"\xc7\x05" + struct.pack("<I", harness.panel.frame_va + 64) + struct.pack("<I", 1))
    emitter.raw(b"\xc3")
    harness.machine.mem_write(harness.previous, emitter.build())
    harness.invoke()
    assert harness.characters == [(ord("a"), flags)]
    assert [event for event, _value, _flags in harness.keys] == ["down", "up"]


@pytest.mark.parametrize("loss", ["outside", "tracking"])
def test_controller_ray_loss_does_not_revoke_focused_physical_typing(loss: str) -> None:
    harness = InputHarness()
    flags = 0x001E0001
    harness.physical_key("key_down", ord("A"), flags)
    harness.snapshot(loss=loss)
    harness.invoke()
    harness.physical_key("character", ord("a"), flags)
    assert harness.characters == [(ord("a"), flags)]


def test_physical_extended_scan_codes_are_independent_of_ordinary_keys() -> None:
    harness = InputHarness()
    flags = 0x001E0001
    extended = flags | 0x01000000
    harness.physical_key("key_down", ord("A"), extended)
    harness.physical_key("character", ord("a"), flags)
    harness.physical_key("character", ord("a"), extended)
    assert harness.characters == [(ord("a"), extended)]


def test_fast_physical_typing_accepts_a_character_queued_after_native_key_release() -> None:
    harness = InputHarness()
    flags = 0x001E0001
    harness.physical_key("key_down", ord("A"), flags)
    harness.physical_key("key_up", ord("A"), flags | 0xC0000000)
    harness.physical_key("character", ord("a"), flags)
    assert harness.characters == [(ord("a"), flags)]


@pytest.mark.parametrize("inactive", ["input", "panel"])
def test_dormant_vr_does_not_change_physical_keyboard_behavior(inactive: str) -> None:
    harness = InputHarness()
    harness.word(harness.abi.enabled_va if inactive == "input" else harness.panel.enabled_va, 0)
    harness.snapshot(loss="focus")
    harness.physical_key("character", ord("a"), 0x401E0001)
    assert harness.characters == [(ord("a"), 0x401E0001)]


@pytest.mark.parametrize("event", VRInputCompiler._keyboard_events)
def test_foreign_physical_keyboard_owner_is_rejected_before_installing(event: str) -> None:
    image, panel, previous = _linked_panel()
    for mouse in VRInputCompiler._events:
        image.write_u32_va(
            GOG_BUILD.address(f"input.{mouse}_slot"), GOG_BUILD.address(f"input.{mouse}")
        )
    image.write_u32_va(GOG_BUILD.site(f"vr.host_{event}_slot").va, 0)
    original = image.to_bytes()
    with pytest.raises(PatchError, match="physical keyboard event owner changed"):
        VRInputCompiler(profile=GOG_BUILD, panel=panel, expected_presenter_va=previous).apply(image)
    assert image.to_bytes() == original


@pytest.mark.parametrize("change", ["owner", "hand", "tracking"])
def test_new_pointer_owner_receives_move_at_unchanged_point(change: str) -> None:
    harness = InputHarness()
    harness.invoke()
    if change == "owner":
        harness.owner += 0x100
    elif change == "hand":
        harness.snapshot(hand=0)
    else:
        harness.snapshot(loss="tracking")
        harness.invoke()
        harness.snapshot()
    harness.events.clear()
    harness.invoke()
    assert ("pointer_move", (200, 300)) in harness.events


def test_stationary_world_anchor_keeps_refreshing_native_noun_picker() -> None:
    harness = InputHarness(world=True)
    harness.snapshot(loss="outside")
    for _ in range(5):
        harness.invoke()
    assert [name for name, _ in harness.events].count("world_hover") == 5


@pytest.mark.parametrize("scene_type", NATIVE_SCENE_TYPES)
def test_room_trigger_routes_native_picking_without_a_panel_hit(scene_type: str) -> None:
    harness = InputHarness(world=True)
    harness.word(harness.room, GOG_BUILD.address(scene_type))
    assert harness.world is not None
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.events.clear()
    harness.world_routes.clear()
    for held in (1, 1, 0):
        harness.snapshot(held=held, loss="outside")
        harness.invoke()
    assert [name for name, _point in harness.events].count("left_down") == 1
    assert [name for name, _point in harness.events].count("left_up") == 1
    assert all(point == (640, 400) for _name, point in harness.events)
    assert all(route == 1 for _event, route in harness.world_routes)
    assert harness.read(harness.world.dispatch_va) == 0
    assert harness.read(harness.scene.enabled_va) == 1


@pytest.mark.parametrize("menu", ["vr.action_menu_vtable", "vr.toolbar_vtable"])
@pytest.mark.parametrize("hand", [0, 1])
def test_wall_fade_navigation_yields_to_visible_native_menus(menu: str, hand: int) -> None:
    harness = InputHarness(world=True, navigation=True)
    assert harness.navigation is not None
    assert harness.world is not None
    harness.snapshot(hand=hand, loss="outside")
    harness.word(harness.scene.world_input_va + 4, 0)
    harness.word(harness.scene.world_input_va + 12 + hand * 48, 1)
    children, child = _HEAP + 0x9000, _HEAP + 0xA000
    harness.word(harness.owner + 0x4C, children)
    harness.word(harness.owner + 0x50, 1)
    harness.word(children, child)
    harness.word(child, GOG_BUILD.address(menu))
    harness.word(child + 0x18, 1)
    observed = _navigation_arguments(harness)
    harness.invoke()
    assert observed == [0]


@pytest.mark.parametrize("hand", [0, 1])
@pytest.mark.parametrize("loss", [None, "focus", "tracking", "failed", "scene", "overlay"])
def test_obscured_room_can_retreat_without_selecting_and_rejects_unsafe_owners(
    hand: int, loss: str | None
) -> None:
    harness = InputHarness(world=True, navigation=True)
    assert harness.navigation is not None
    assert harness.world is not None
    harness.snapshot(hand=hand, held=1, loss="outside")
    harness.word(harness.scene.world_input_va + 4, 0)
    harness.word(harness.scene.world_input_va + 12 + hand * 48, 1)
    if loss == "focus":
        harness.word(harness.panel.frame_va + 64, 0)
    elif loss == "tracking":
        harness.word(harness.panel.frame_va + 68 + hand * 48, 0)
    elif loss == "failed":
        harness.word(harness.panel.completion_result_va, 0x80004005)
    elif loss == "scene":
        harness.word(harness.scene.result_va, 0x80004005)
    elif loss == "overlay":
        harness.word(harness.panel.frame_va + 164, 1)
    observed = _navigation_arguments(harness)
    harness.invoke()
    assert observed == [int(loss is None)]
    assert not any(name in {"left_down", "world_hover"} for name, _point in harness.events)
    assert harness.read(harness.world.dispatch_va) == 0
    if loss is None:
        # Visibility recovery cannot turn the obscured held trigger into a
        # click. Original selection works again only after release/repress.
        harness.snapshot(hand=hand, held=1, loss="outside")
        harness.invoke()
        assert not any(name == "left_down" for name, _point in harness.events)
        harness.snapshot(hand=hand, loss="outside")
        harness.invoke()
        harness.snapshot(hand=hand, held=1, loss="outside")
        harness.invoke()
        assert any(name == "left_down" for name, _point in harness.events)


def _navigation_arguments(harness: InputHarness) -> list[int]:
    """Observe the real router's navigation boundary without emulating a camera."""
    assert harness.navigation is not None
    entry = harness.navigation.tick_va
    harness.machine.mem_write(entry, bytes.fromhex("c2 04 00"))
    observed = []

    def callback(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == entry:
            observed.append(harness.read(current.reg_read(UC_X86_REG_ESP) + 4))

    harness.machine.hook_add(UC_HOOK_CODE, callback)
    return observed


def test_entering_wall_fade_cancels_held_selection_without_activating_an_object() -> None:
    harness = InputHarness(world=True, navigation=True)
    assert harness.world is not None
    harness.snapshot(loss="outside")
    observed = _navigation_arguments(harness)
    harness.invoke()
    harness.snapshot(held=1, loss="outside")
    harness.invoke()
    assert any(name == "left_down" for name, _point in harness.events)
    harness.events.clear()
    harness.world_routes.clear()
    harness.word(harness.scene.world_input_va + 4, 0)
    harness.word(harness.scene.world_input_va + 12 + 48, 1)
    harness.invoke()
    assert ("left_up", (-10000, -10000)) in harness.events
    assert not any(name in {"left_down", "world_hover"} for name, _point in harness.events)
    assert all(route == 0 for _event, route in harness.world_routes)
    assert observed[-1] == 1
    harness.events.clear()
    harness.snapshot(held=1, loss="outside")
    harness.invoke()
    assert not any(name == "left_down" for name, _point in harness.events)


@pytest.mark.parametrize("menu", ["vr.action_menu_vtable", "vr.toolbar_vtable"])
def test_visible_room_menu_owns_panel_and_retires_held_world_selection(menu: str) -> None:
    harness = InputHarness(world=True)
    assert harness.world is not None
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.snapshot(held=1, loss="outside")
    harness.invoke()
    children, child = _HEAP + 0x9000, _HEAP + 0xA000
    harness.word(harness.owner + 0x4C, children)
    harness.word(harness.owner + 0x50, 1)
    harness.word(children, child)
    harness.word(child, GOG_BUILD.address(menu))
    harness.word(child + 0x18, 1)
    harness.events.clear()
    harness.world_routes.clear()
    harness.snapshot(held=1)
    harness.invoke()
    assert harness.events[0] == ("left_up", (-10000, -10000))
    assert all(route == 0 for _event, route in harness.world_routes)
    # A held trigger must not activate a menu that just took ownership.
    assert not any(name == "left_down" for name, _point in harness.events)
    harness.snapshot()
    harness.invoke()
    harness.events.clear()
    harness.snapshot(held=1)
    harness.invoke()
    assert ("left_down", (200, 300)) in harness.events
    assert harness.read(harness.world.dispatch_va) == 0


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_interactive_puzzle_overlay_takes_pointer_from_world_without_trigger_replay(
    profile: BuildProfile,
) -> None:
    harness = InputHarness(profile, world=True)
    assert harness.world is not None
    harness.word(harness.room, profile.address("vr.coordinate_device_scene_vtable"))
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.snapshot(held=1, loss="outside")
    harness.invoke()
    harness.events.clear()
    harness.world_routes.clear()
    # No toolbar/action-menu child is involved. The current XR source supplies
    # the qualified hit, and a held world trigger must not press the new control.
    harness.snapshot(held=1, point=(207.3, 320.3))
    harness.invoke()
    assert harness.events[0] == ("left_up", (-10000, -10000))
    assert not any(name == "left_down" for name, _point in harness.events)
    assert all(route == 0 for _event, route in harness.world_routes)
    harness.snapshot(point=(207.3, 320.3))
    harness.invoke()
    harness.events.clear()
    harness.snapshot(held=1, point=(207.3, 320.3))
    harness.invoke()
    assert ("left_down", (207, 320)) in harness.events
    assert harness.read(harness.world.dispatch_va) == 0


@pytest.mark.parametrize("failure", ["scene", "completion", "disabled"])
def test_failed_world_frame_does_not_select_using_desktop_fallback(failure: str) -> None:
    harness = InputHarness(world=True)
    assert harness.world is not None
    harness.invoke()
    if failure == "scene":
        harness.word(harness.scene.result_va, 0x80004005)
    elif failure == "completion":
        harness.word(harness.panel.completion_result_va, 0x80004005)
    else:
        harness.word(harness.world.enabled_va, 0)
    harness.events.clear()
    harness.snapshot(held=1)
    harness.invoke()
    assert not any(name == "left_down" for name, _point in harness.events)
    assert harness.read(harness.world.dispatch_va) == 0


@pytest.mark.parametrize("invalid", ["count", "list"])
def test_invalid_room_child_list_does_not_choose_a_desktop_object(invalid: str) -> None:
    harness = InputHarness(world=True)
    assert harness.world is not None
    harness.invoke()
    harness.word(harness.owner + 0x50, 257 if invalid == "count" else 1)
    harness.word(harness.owner + 0x4C, 0)
    harness.events.clear()
    harness.snapshot(held=1)
    harness.invoke()
    assert not any(name == "left_down" for name, _point in harness.events)
    assert harness.read(harness.world.dispatch_va) == 0


def test_failed_shared_frame_cancels_a_held_panel_press_outside_controls() -> None:
    harness = InputHarness(paired=True)
    harness.invoke()
    harness.snapshot(held=1)
    harness.invoke()
    harness.events.clear()
    harness.word(harness.panel.completion_result_va, 0x80004005)
    harness.invoke()
    assert harness.events == [
        ("left_up", (-10000, -10000)),
        ("pointer_move", (-10000, -10000)),
    ]
    assert harness.read(harness.abi.held_va) == 0


def test_hidden_room_menus_do_not_block_controller_hover() -> None:
    harness = InputHarness(world=True)
    children, child = _HEAP + 0x9000, _HEAP + 0xA000
    harness.word(harness.owner + 0x4C, children)
    harness.word(harness.owner + 0x50, 1)
    harness.word(children, child)
    harness.word(child, GOG_BUILD.address("vr.action_menu_vtable"))
    harness.word(child + 0x18, 0)
    harness.snapshot(loss="outside")
    harness.invoke()
    assert ("world_hover", (640, 400)) in harness.events


@pytest.mark.parametrize(
    "loss", ["focus", "tracking", "outside", "hidden", "closed", "disabled", "layer", "hand"]
)
def test_lost_ownership_cancels_outside_and_requires_release(loss: str) -> None:
    harness = InputHarness()
    harness.invoke()
    harness.snapshot(held=1)
    harness.invoke()
    harness.events.clear()
    harness.snapshot(
        held=1,
        loss=loss,
        hand=0 if loss == "hand" else 1,
    )
    if loss == "hidden":
        harness.word(harness.panel.result_va, 1)
    if loss == "closed":
        harness.word(harness.panel.enabled_va, 0)
    if loss == "disabled":
        harness.word(harness.abi.enabled_va, 0)
    if loss == "layer":
        harness.owner += 0x100
    harness.invoke()
    assert ("left_up", (-10000, -10000)) in harness.events
    assert harness.read(harness.abi.held_va) & 1 == 0
    harness.events.clear()
    harness.word(harness.panel.result_va, 0)
    harness.word(harness.panel.enabled_va, 1)
    harness.word(harness.abi.enabled_va, 1)
    harness.snapshot(held=1)
    harness.invoke()
    harness.invoke()
    assert not any(name == "left_down" for name, _point in harness.events)
    harness.snapshot()
    harness.invoke()
    harness.snapshot(held=1)
    harness.invoke()
    assert [name for name, _point in harness.events].count("left_down") == 1


@pytest.mark.parametrize(
    "point",
    [(-0.5, 100), (100, -0.5), (1280, 100), (100, 800), (float("nan"), 100), (100, float("inf"))],
)
def test_invalid_coordinates_do_not_become_edge_clicks(point: tuple[float, float]) -> None:
    harness = InputHarness()
    harness.invoke()
    harness.events.clear()
    harness.snapshot(point=point, held=1)
    harness.invoke()
    assert not any(name == "left_down" for name, _point in harness.events)
    assert struct.unpack("<2i", harness.machine.mem_read(harness.abi.pointer_va, 8)) == (
        -10000,
        -10000,
    )


@pytest.mark.parametrize("event", ["left_down", "left_up", "pointer_move", "right_up"])
def test_an_event_cannot_reuse_its_snapshot_on_a_new_modal_layer(event: str) -> None:
    harness = InputHarness()
    harness.invoke()
    if event == "left_up":
        harness.snapshot(held=1)
        harness.invoke()
    harness.events.clear()
    harness.change_on = event
    harness.snapshot(held={"left_down": 1, "left_up": 4, "pointer_move": 5, "right_up": 4}[event])
    harness.invoke()
    assert harness.read(harness.abi.held_va) == 0
    if event in {"left_up", "pointer_move"}:
        assert not any(name in {"left_down", "right_down"} for name, _point in harness.events)


def test_dormant_bridge_does_not_touch_native_cursor_or_dispatch() -> None:
    harness = InputHarness()
    harness.word(harness.abi.enabled_va, 0)
    harness.word(GOG_BUILD.address("input.cursor_position"), 999)
    harness.invoke()
    assert harness.events == []
    assert harness.read(GOG_BUILD.address("input.cursor_position")) == 999


@pytest.mark.parametrize("event", VRInputCompiler._events)
def test_host_mouse_events_are_suppressed_only_when_vr_owns_input(event: str) -> None:
    harness = InputHarness()
    slot = GOG_BUILD.address(f"input.{event}_slot")
    harness.machine.mem_write(_HEAP + 0x7000, struct.pack("<2i", 17, 23))
    harness.invoke(harness.read(slot), argument=_HEAP + 0x7000, cleanup=4)
    assert harness.events == []
    harness.word(harness.abi.enabled_va, 0)
    harness.invoke(harness.read(slot), argument=_HEAP + 0x7000, cleanup=4)
    assert harness.events == [(event, (17, 23))]


def test_virtual_point_queries_and_warps_leave_desktop_input_alone() -> None:
    harness = InputHarness()
    harness.invoke()
    point = _HEAP + 0x7000
    harness.invoke(GOG_BUILD.site("vr.client_point").va, argument=point)
    assert struct.unpack("<2i", harness.machine.mem_read(point, 8)) == (200, 300)
    assert harness.machine.reg_read(UC_X86_REG_EAX) == point
    harness.invoke(GOG_BUILD.site("vr.set_client_point").va, argument=point)
    assert harness.machine.reg_read(UC_X86_REG_EAX) == 1


@pytest.mark.parametrize("closing", ["panel", "input"])
def test_cancel_callbacks_keep_the_outside_point_even_after_disable(closing: str) -> None:
    harness = InputHarness()
    harness.invoke()
    harness.snapshot(held=1)
    harness.invoke()
    point = _HEAP + 0x7000
    emitter = X86Emitter(base_va=GOG_BUILD.address("input.left_up"))
    emitter.push_imm32(point)
    emitter.call_absolute(GOG_BUILD.site("vr.client_point").va)
    emitter.raw(bytes.fromhex("83 c4 04 c2 04 00"))
    harness.machine.mem_write(GOG_BUILD.address("input.left_up"), emitter.build())
    harness.word(harness.panel.enabled_va if closing == "panel" else harness.abi.enabled_va, 0)
    harness.invoke()
    assert struct.unpack("<2i", harness.machine.mem_read(point, 8)) == (-10000, -10000)


def test_native_point_and_warp_continue_normally_when_vr_is_dormant() -> None:
    harness = InputHarness()
    harness.word(harness.abi.enabled_va, 0)
    point = _HEAP + 0x7000
    site = GOG_BUILD.site("vr.client_point")
    # Emulate the native OS result at the untouched prologue continuation.
    harness.machine.mem_write(
        site.va + len(site.original),
        bytes.fromhex("8b 45 08 c7 00 1e 00 00 00 c7 40 04 28 00 00 00 c9 c3"),
    )
    harness.invoke(site.va, argument=point)
    assert struct.unpack("<2i", harness.machine.mem_read(point, 8)) == (30, 40)
    site = GOG_BUILD.site("vr.set_client_point")
    harness.machine.mem_write(site.va + len(site.original), bytes.fromhex("b8 7b 00 00 00 c9 c3"))
    harness.invoke(site.va, argument=point)
    assert harness.machine.reg_read(UC_X86_REG_EAX) == 123


def test_missing_native_engine_owner_does_not_dispatch() -> None:
    harness = InputHarness()
    harness.word(GOG_BUILD.address("engine.loop"), 0)
    harness.snapshot(held=1)
    harness.invoke()
    assert harness.events == []


@pytest.mark.parametrize(("button", "key", "scan"), [(2, 0x1B, 1), (8, 0x49, 0x17)])
def test_back_and_inventory_use_native_key_pulses_without_pointing(
    button: int, key: int, scan: int
) -> None:
    harness = InputHarness()
    harness.snapshot(loss="outside")
    harness.invoke()
    for buttons in (button, button, 0, button):
        harness.snapshot(loss="outside", held=buttons)
        harness.invoke()
    assert harness.keys == [
        (edge, key, flags)
        for _ in range(2)
        for edge, flags in (("down", (scan << 16) | 1), ("up", 0xC0000001 | (scan << 16)))
    ]
    assert not any(name in {"left_down", "right_down"} for name, _point in harness.events)


@pytest.mark.parametrize("context", ["world", "pause", "toolbar", "action_menu", "modal"])
def test_back_pauses_or_resumes_world_but_cancels_interfaces(context: str) -> None:
    harness = InputHarness(world=True)
    if context in {"pause", "modal"}:
        harness.word(
            harness.owner,
            GOG_BUILD.address("pause.vtable" if context == "pause" else "driving_map.vtable"),
        )
    elif context in {"toolbar", "action_menu"}:
        children, child = _HEAP + 0x9000, _HEAP + 0xA000
        harness.word(harness.owner + 0x4C, children)
        harness.word(harness.owner + 0x50, 1)
        harness.word(children, child)
        harness.word(child, GOG_BUILD.address(f"vr.{context}_vtable"))
        harness.word(child + 0x18, 1)
    harness.snapshot(loss="outside")
    harness.invoke()
    for _ in range(2):
        harness.snapshot(loss="outside", held=2)
        harness.invoke()
    key, scan = (0x50, 0x19) if context in {"world", "pause"} else (0x1B, 1)
    assert harness.keys == [
        ("down", key, (scan << 16) | 1),
        ("up", key, 0xC0000001 | (scan << 16)),
    ]
    assert not any(name in {"left_down", "right_down"} for name, _point in harness.events)


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
@pytest.mark.parametrize("binding", [0x1B, 0x20, 0x73, 0])
def test_back_skips_owned_native_action_using_configured_binding_once(
    profile: BuildProfile, binding: int
) -> None:
    harness = InputHarness(profile, world=True)
    children, skipper = _HEAP + 0x9000, _HEAP + 0xA000
    subsystem, manager, bindings = _HEAP + 0x1000, _HEAP + 0x2000, _HEAP + 0x3000
    for address, value in (
        (harness.owner + 0x4C, children),
        (harness.owner + 0x50, 1),
        (children, skipper),
        (skipper, profile.address("vr.action_skip_vtable")),
        (skipper + 0x18, 0x101),
        (harness.engine + 0x444, subsystem),
        (subsystem + 0x44, manager),
        (manager + 0x6C, bindings),
        (bindings + 0xF8, binding),
    ):
        harness.word(address, value)
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.snapshot(loss="outside", held=2)
    harness.invoke()
    harness.invoke()
    assert harness.keys == ([("down", binding, 1), ("up", binding, 0xC0000001)] if binding else [])
    assert harness.characters == [], "native action skipping is a key-down route, not text"
    assert harness.read(harness.abi.pending_release_va) == 0
    assert not any(name in {"left_down", "right_down"} for name, _point in harness.events)
    # Action retirement must not replay held Back as Pause in the returned room.
    harness.word(harness.owner + 0x50, 0)
    harness.invoke()
    assert len(harness.keys) == (2 if binding else 0)
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.snapshot(loss="outside", held=2)
    harness.invoke()
    assert harness.keys[-2:] == [("down", 0x50, 0x190001), ("up", 0x50, 0xC0190001)]


@pytest.mark.parametrize("state", ["hidden", "disabled", "ordinary", "toolbar", "action_menu"])
def test_back_does_not_skip_unowned_actions_or_bypass_open_menus(state: str) -> None:
    harness = InputHarness(world=True)
    children, skipper, menu = _HEAP + 0x9000, _HEAP + 0xA000, _HEAP + 0xB100
    for address, value in (
        (harness.owner + 0x4C, children),
        (harness.owner + 0x50, 1),
        (children, skipper),
        (skipper, GOG_BUILD.address("vr.action_skip_vtable")),
        (skipper + 0x18, {"hidden": 0x100, "disabled": 1}.get(state, 0x101)),
    ):
        harness.word(address, value)
    if state == "ordinary":
        harness.word(skipper, GOG_BUILD.address("title.vtable"))
    elif state in {"toolbar", "action_menu"}:
        harness.word(harness.owner + 0x50, 2)
        harness.word(children + 4, menu)
        harness.word(menu, GOG_BUILD.address(f"vr.{state}_vtable"))
        harness.word(menu + 0x18, 0x101)
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.snapshot(loss="outside", held=2)
    harness.invoke()
    key = 0x1B if state in {"toolbar", "action_menu"} else 0x50
    assert [value for _edge, value, _flags in harness.keys] == [key, key]
    assert harness.characters == []


@pytest.mark.parametrize("missing", ["subsystem", "manager", "bindings"])
def test_action_back_with_missing_binding_owner_does_not_invent_skip_or_pause(missing: str) -> None:
    harness = InputHarness(world=True)
    children, skipper = _HEAP + 0x9000, _HEAP + 0xA000
    subsystem, manager, bindings = _HEAP + 0x1000, _HEAP + 0x2000, _HEAP + 0x3000
    for address, value in (
        (harness.owner + 0x4C, children),
        (harness.owner + 0x50, 1),
        (children, skipper),
        (skipper, GOG_BUILD.address("vr.action_skip_vtable")),
        (skipper + 0x18, 0x101),
        (harness.engine + 0x444, 0 if missing == "subsystem" else subsystem),
        (subsystem + 0x44, 0 if missing == "manager" else manager),
        (manager + 0x6C, 0 if missing == "bindings" else bindings),
    ):
        harness.word(address, value)
    harness.invoke()
    harness.snapshot(held=2)
    harness.invoke()
    assert harness.keys == harness.characters == []


@pytest.mark.parametrize("anchor", ["vr.action_skip_key", "vr.action_skip_key_slot"])
def test_changed_native_action_skip_route_invalidates_player_verification(anchor: str) -> None:
    harness = InputHarness(world=True)
    harness.image.write_bytes(harness.image.va_to_offset(GOG_BUILD.site(anchor).va), b"\xcc")
    with pytest.raises(PatchError, match="shortcut entry failed verification"):
        harness.compiler.postcheck(harness.image)


def test_aborted_pause_key_defers_native_release_without_repeating_toggle() -> None:
    harness = InputHarness(world=True)
    harness.word(harness.owner, GOG_BUILD.address("pause.vtable"))
    harness.invoke()
    harness.snapshot(held=2)
    _unwind_at_callback(harness, GOG_BUILD.site("vr.key_down").va, 2)
    harness.keys.clear()
    harness.invoke()
    assert harness.keys == [("up", 0x50, 0xC0190001)]
    assert harness.read(harness.abi.pending_release_va) == 0


def test_nonpointing_menu_uses_center_not_stale_cursor() -> None:
    harness = InputHarness()
    harness.invoke()
    harness.snapshot(loss="outside", held=4)
    harness.invoke()
    harness.invoke()
    assert [(name, point) for name, point in harness.events if name.startswith("right_")] == [
        ("right_down", (640, 400)),
        ("right_up", (640, 400)),
    ]


@pytest.mark.parametrize("binding", [0x1B, 0x20, 0])
@pytest.mark.parametrize("change_layer", [False, True])
def test_movie_back_uses_current_native_skip_character_once(
    binding: int, *, change_layer: bool
) -> None:
    harness = InputHarness(world=True)
    harness.word(harness.owner, GOG_BUILD.address("movies.layer_vtable"))
    subsystem, manager, bindings = _HEAP + 0x1000, _HEAP + 0x2000, _HEAP + 0x3000
    for address, value in (
        (harness.engine + 0x444, subsystem),
        (subsystem + 0x44, manager),
        (manager + 0x6C, bindings),
        (bindings + 0x108, binding),
    ):
        harness.word(address, value)
    harness.snapshot(loss="outside")
    harness.invoke()
    if change_layer:
        harness.change_on = "character"
    harness.snapshot(loss="outside", held=2)
    harness.invoke()
    harness.invoke()
    assert harness.characters == ([(binding, 1)] if binding else [])
    assert harness.keys == [], "movie skip is not a key-down or key-up callback"
    assert harness.read(harness.abi.pending_release_va) == 0
    assert not any(name in {"left_down", "right_down"} for name, _point in harness.events)


@pytest.mark.parametrize("missing", ["subsystem", "manager", "bindings"])
def test_movie_back_with_unavailable_binding_owner_does_not_invent_a_skip(missing: str) -> None:
    harness = InputHarness()
    harness.word(harness.owner, GOG_BUILD.address("movies.layer_vtable"))
    subsystem, manager, bindings = _HEAP + 0x1000, _HEAP + 0x2000, _HEAP + 0x3000
    harness.word(harness.engine + 0x444, 0 if missing == "subsystem" else subsystem)
    harness.word(subsystem + 0x44, 0 if missing == "manager" else manager)
    harness.word(manager + 0x6C, 0 if missing == "bindings" else bindings)
    harness.word(bindings + 0x108, 0x1B)
    harness.invoke()
    harness.snapshot(held=2)
    harness.invoke()
    assert harness.keys == harness.characters == []


def test_back_does_not_force_pop_interfaces_without_native_escape_support() -> None:
    harness = InputHarness()
    original = harness.owner
    harness.word(original, GOG_BUILD.address("driving_map.vtable"))
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.snapshot(loss="outside", held=2)
    harness.invoke()
    harness.invoke()
    assert harness.owner == original
    assert [(edge, key) for edge, key, _flags in harness.keys] == [("down", 0x1B), ("up", 0x1B)]
    assert harness.read(harness.abi.held_va) == 0


@pytest.mark.parametrize("loss", ["focus", "tracking", "hand", "layer"])
def test_back_cannot_dispatch_on_map_after_input_ownership_changes(loss: str) -> None:
    harness = InputHarness()
    harness.word(harness.owner, GOG_BUILD.address("driving_map.vtable"))
    harness.snapshot(loss="outside")
    harness.invoke()
    if loss == "layer":
        harness.owner += 0x100
    harness.snapshot(loss=loss, held=2, hand=0 if loss == "hand" else 1)
    harness.invoke()
    harness.snapshot(loss="outside", held=2)
    harness.invoke()
    assert harness.keys == []


@pytest.mark.parametrize(
    "loss", ["focus", "tracking", "hand", "layer", "disabled", "closed", "hidden"]
)
@pytest.mark.parametrize("button", [2, 4, 8])
def test_shortcuts_require_release_after_lost_ownership(loss: str, button: int) -> None:
    harness = InputHarness()
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.snapshot(held=button, loss=loss, hand=0 if loss == "hand" else 1)
    if loss == "layer":
        harness.owner += 0x100
    if loss == "disabled":
        harness.word(harness.abi.enabled_va, 0)
    if loss == "closed":
        harness.word(harness.panel.enabled_va, 0)
    if loss == "hidden":
        harness.word(harness.panel.result_va, 1)
    harness.invoke()
    assert harness.keys == []
    assert not any(name == "right_down" for name, _point in harness.events)
    harness.word(harness.abi.enabled_va, 1)
    harness.word(harness.panel.enabled_va, 1)
    harness.word(harness.panel.result_va, 0)
    harness.snapshot(loss="outside", held=button)
    harness.invoke()
    harness.invoke()
    assert harness.keys == []
    assert not any(name == "right_down" for name, _point in harness.events)
    harness.snapshot(loss="outside")
    harness.invoke()
    harness.snapshot(loss="outside", held=button)
    harness.invoke()
    assert bool(harness.keys) == (button != 4)
    assert sum(name == "right_down" for name, _point in harness.events) == (button == 4)


def test_simultaneous_shortcuts_act_once_on_original_layer_with_back_priority() -> None:
    harness = InputHarness()
    harness.invoke()
    harness.change_on = "key_down"
    harness.snapshot(held=14)
    harness.invoke()
    harness.invoke()
    assert [key for edge, key, _flags in harness.keys if edge == "down"] == [0x1B]
    assert not any(name == "right_down" for name, _point in harness.events)


def test_shortcut_retires_drag_before_native_key_dispatch() -> None:
    harness = InputHarness()
    harness.invoke()
    harness.snapshot(held=1)
    harness.invoke()
    harness.events.clear()
    harness.snapshot(held=9)
    harness.invoke()
    assert ("left_up", (-10000, -10000)) in harness.events
    assert harness.read(harness.abi.held_va) == 0
    assert [key for edge, key, _flags in harness.keys if edge == "down"] == [0x49]


def test_native_key_redraw_cannot_reenter_xr_or_repeat_shortcuts() -> None:
    harness = InputHarness()
    harness.invoke()
    emitter = X86Emitter(base_va=GOG_BUILD.site("vr.key_down").va)
    emitter.call_absolute(harness.entry)
    emitter.raw(bytes.fromhex("c2 08 00"))
    harness.machine.mem_write(GOG_BUILD.site("vr.key_down").va, emitter.build())
    harness.snapshot(held=8)
    harness.invoke()
    assert harness.presented == 2
    assert harness.composed == 1
    assert len(harness.keys) == 2
    assert harness.read(harness.abi.held_va) == 0


def _unwind_at_callback(harness: InputHarness, address: int, exception_flags: int) -> None:
    """Stop in a native callback and execute its installed SEH registration."""
    stopped = False

    def stop(current: Uc, current_address: int, _size: int, _context: object) -> None:
        nonlocal stopped
        if current_address == address:
            stopped = True
            current.emu_stop()

    hook = harness.machine.hook_add(UC_HOOK_CODE, stop)
    harness.machine.mem_write(_STACK, struct.pack("<I", _RETURN))
    harness.machine.reg_write(UC_X86_REG_ESP, _STACK)
    harness.machine.emu_start(harness.entry, _RETURN, count=3000)
    harness.machine.hook_del(hook)
    assert stopped
    registration = harness.read(0)
    assert harness.read(registration) == 0x12345678
    handler = harness.read(registration + 4)
    assert handler == harness.unwind_handler
    exception, stack = _HEAP + 0xD000, _STACK - 0x800
    harness.word(exception, 0xE06D7363)
    harness.word(exception + 4, exception_flags)
    harness.machine.mem_write(stack, struct.pack("<5I", _RETURN, exception, registration, 0, 0))
    harness.machine.reg_write(UC_X86_REG_ESP, stack)
    harness.machine.emu_start(handler, _RETURN, count=500)
    assert harness.machine.reg_read(UC_X86_REG_EAX) == 1  # ExceptionContinueSearch.
    assert harness.machine.reg_read(UC_X86_REG_ESP) == stack + 4  # cdecl.
    assert harness.read(0) == registration  # The OS owns removal during unwind.
    harness.word(0, 0x12345678)


@pytest.mark.parametrize("exception_flags", [0, 1, 2, 4, 6, 8])
@pytest.mark.parametrize("mode", ["panel", "paired", "world", "navigation"])
def test_native_exception_search_does_not_steal_recovery_and_unwind_retires_vr(
    mode: str, exception_flags: int
) -> None:
    harness = InputHarness(
        paired=mode == "paired",
        world=mode in {"world", "navigation"},
        navigation=mode == "navigation",
    )
    harness.word(harness.scene.enabled_va, 1)
    if harness.navigation is not None:
        harness.word(harness.navigation.enabled_va, 1)
    _unwind_at_callback(harness, harness.previous, exception_flags)
    unwinding = bool(exception_flags & 6)
    assert harness.read(harness.abi.unwind_count_va) == unwinding
    assert harness.read(harness.abi.enabled_va) == (not unwinding)
    assert harness.read(harness.panel.enabled_va) == (not unwinding)
    if harness.panel.world_enabled_va:
        assert harness.read(harness.scene.enabled_va) == (not unwinding)
    if harness.world is not None:
        assert harness.read(harness.world.enabled_va) == (not unwinding)
        assert harness.read(harness.world.dispatch_va) == 0
        assert harness.read(harness.world.ready_va) == 0
    if harness.navigation is not None:
        assert harness.read(harness.navigation.enabled_va) == (not unwinding)
    assert harness.read(harness.abi.pending_release_va) == unwinding
    # Exception-search notifications must leave the enclosing transaction alive
    # so a native inner handler can recover. Only unwind retires its scope.
    base = harness.abi.enabled_va - harness.compiler._enabled
    assert harness.read(base + harness.compiler._routing) == (not unwinding)
    if unwinding:
        harness.invoke()
        assert harness.read(harness.abi.pending_release_va) == 0
        assert harness.read(harness.scene.enabled_va) == (not harness.panel.world_enabled_va)


@pytest.mark.parametrize("callback", ["left_down", "right_down", "right_up", "key_down", "left_up"])
def test_faulted_native_input_defers_safe_release_and_cannot_activate_on_recovery(
    callback: str,
) -> None:
    harness = InputHarness(world=True)
    assert harness.world is not None
    harness.invoke()
    if callback == "left_up":
        harness.snapshot(held=1)
        harness.invoke()
    held = {"left_down": 1, "right_down": 4, "right_up": 4, "key_down": 8, "left_up": 0}[callback]
    harness.snapshot(held=held)
    address = (
        GOG_BUILD.site("vr.key_down").va
        if callback == "key_down"
        else GOG_BUILD.address(f"input.{callback}")
    )
    _unwind_at_callback(harness, address, 2)
    assert harness.read(harness.abi.pending_release_va) == 1
    assert harness.read(harness.world.dispatch_va) == harness.read(harness.world.active_va) == 0
    assert harness.read(harness.scene.enabled_va) == 0
    assert struct.unpack("<2i", harness.machine.mem_read(harness.abi.pointer_va, 8)) == (
        -10000,
        -10000,
    )
    # A physical mouse cannot turn the pending VR drag into a real-world click.
    harness.events.clear()
    harness.keys.clear()
    harness.invoke(harness.image.read_u32_va(GOG_BUILD.address("input.left_down_slot")), cleanup=4)
    assert harness.events == []
    harness.invoke()
    assert all(point == (-10000, -10000) for _event, point in harness.events)
    assert not any(event.endswith("down") for event, _point in harness.events)
    if callback in {"left_down", "left_up"}:
        assert ("left_up", (-10000, -10000)) in harness.events
    if callback in {"right_down", "right_up"}:
        assert ("right_up", (-10000, -10000)) in harness.events
    if callback == "key_down":
        assert [(edge, key) for edge, key, _flags in harness.keys] == [("up", 0x49)]
    assert harness.read(harness.abi.held_va) == 0
    assert harness.read(harness.abi.pending_release_va) == 0
    # Explicit re-enabling still requires neutral before another held action.
    for enabled in (
        harness.abi.enabled_va,
        harness.panel.enabled_va,
        harness.scene.enabled_va,
        harness.world.enabled_va,
    ):
        harness.word(enabled, 1)
    harness.events.clear()
    harness.keys.clear()
    harness.snapshot(held=held)
    harness.invoke()
    harness.invoke()
    assert not any(event.endswith("down") for event, _point in harness.events)
    assert harness.keys == []
    harness.snapshot()
    harness.invoke()
    harness.snapshot(held=1)
    harness.invoke()
    assert sum(event == "left_down" for event, _point in harness.events) == 1


@pytest.mark.parametrize("button", [1, 8])
def test_pending_release_survives_another_fault_and_waits_for_native_engine(button: int) -> None:
    harness = InputHarness()
    harness.invoke()
    harness.snapshot(held=button)
    down = GOG_BUILD.address("input.left_down") if button == 1 else GOG_BUILD.site("vr.key_down").va
    up = GOG_BUILD.address("input.left_up") if button == 1 else GOG_BUILD.site("vr.key_up").va
    _unwind_at_callback(harness, down, 2)
    _unwind_at_callback(harness, up, 2)
    assert harness.read(harness.abi.unwind_count_va) == 2
    assert harness.read(harness.abi.pending_release_va) == 1
    harness.word(GOG_BUILD.address("engine.loop"), 0)
    harness.invoke()
    assert harness.read(harness.abi.pending_release_va) == 1
    harness.word(GOG_BUILD.address("engine.loop"), harness.engine)
    harness.events.clear()
    harness.keys.clear()
    harness.invoke()
    assert harness.read(harness.abi.pending_release_va) == 0
    if button == 1:
        assert ("left_up", (-10000, -10000)) in harness.events
    else:
        assert [(edge, key) for edge, key, _flags in harness.keys] == [("up", 0x49)]


@pytest.mark.parametrize("shortcut", ["inventory", "menu", "back"])
def test_native_shortcut_redraw_preserves_stereo_and_does_not_resample(shortcut: str) -> None:
    harness = InputHarness(paired=True)
    world = harness.panel.world_enabled_va
    harness.word(world, 1)
    if shortcut == "back":
        harness.word(harness.owner, GOG_BUILD.address("driving_map.vtable"))
    harness.invoke()
    address, cleanup, button = {
        "inventory": (GOG_BUILD.site("vr.key_down").va, bytes.fromhex("c2 08 00"), 8),
        "menu": (GOG_BUILD.address("input.right_up"), bytes.fromhex("c2 04 00"), 4),
        "back": (GOG_BUILD.site("vr.key_down").va, bytes.fromhex("c2 08 00"), 2),
    }[shortcut]
    emitter = X86Emitter(base_va=address)
    emitter.call_absolute(harness.entry)
    emitter.raw(cleanup)
    harness.machine.mem_write(address, emitter.build())
    composed_world: list[int] = []

    def observe_redraw(_current: Uc, current_address: int, _size: int, _context: object) -> None:
        if current_address == harness.panel.composition_presenter_va:
            composed_world.append(harness.read(world))

    harness.machine.hook_add(UC_HOOK_CODE, observe_redraw)
    harness.snapshot(held=button)
    harness.invoke()
    assert harness.presented == 2
    assert composed_world == [0]
    assert harness.read(world) == 1
    if shortcut == "menu":
        assert sum(name == "right_up" for name, _point in harness.events) == 1
    else:
        assert len(harness.keys) == 2


@pytest.mark.parametrize(
    "changed",
    [
        "payload",
        "event",
        "presenter",
        "point",
        "point-continuation",
        "warp-continuation",
        "menu-down",
        "menu-up",
    ],
)
def test_changed_input_installation_is_detected(changed: str) -> None:
    harness = InputHarness()
    address = {
        "payload": harness.abi.pointer_va,
        "event": GOG_BUILD.address("input.left_down_slot"),
        "presenter": TransitionFrameCompiler.runtime_abi(harness.image).pre_flip_presenter_slot_va,
        "point": GOG_BUILD.site("vr.client_point").va,
        "point-continuation": GOG_BUILD.site("vr.client_point").va
        + len(GOG_BUILD.site("vr.client_point").original),
        "warp-continuation": GOG_BUILD.site("vr.set_client_point").va
        + len(GOG_BUILD.site("vr.set_client_point").original),
        "menu-down": GOG_BUILD.site("vr.menu_down").va,
        "menu-up": GOG_BUILD.site("vr.menu_up").va,
    }[changed]
    harness.image.write_bytes(harness.image.va_to_offset(address), b"\xcc")
    with pytest.raises(PatchError):
        harness.compiler.postcheck(harness.image)
