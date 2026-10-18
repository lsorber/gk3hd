"""Observe native float camera calls from completed controller snapshots."""

from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_navigation import VRNavigationCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_vr_input import InputHarness
from tests.unit.patch.test_vr_panel import _linked_panel
from tests.unit.patch.test_vr_scene import _HEAP

if TYPE_CHECKING:
    from unicorn import Uc


class NavigationHarness(InputHarness):
    """Stub only native camera methods and the clock, not navigation math."""

    def snapshot(
        self,
        *,
        point: tuple[float, float] = (200.5, 300.5),
        held: int = 0,
        loss: str = "",
        hand: int = 1,
    ) -> None:
        # Ordinary navigation has a world ray, not a rendered interface hit.
        super().snapshot(point=point, held=held, loss=loss or "outside", hand=hand)

    def __init__(self) -> None:
        super().__init__(world=True, navigation=True)
        assert self.navigation is not None
        self.now = 1000
        self.manager = _HEAP + 0xC000
        self.services = _HEAP + 0xA000
        self.timer = _HEAP + 0xD000
        self.word(self.engine + 0x444, self.services)
        self.word(self.services + 0x28, self.manager)
        self.word(self.manager, self.profile.address("vr.camera_manager_vtable"))
        self.controller = self.manager + 0x400
        self.controller_slot = self.manager + 0x408
        self.word(self.manager + 0xB0, 1)
        self.word(self.controller_slot, self.controller)
        self.word(self.controller, self.profile.address("vr.user_scene_controller_vtable"))
        self.machine.mem_write(
            self.profile.site("vr.camera_controller_top").va,
            b"\xa1" + struct.pack("<I", self.controller_slot) + b"\xc3",
        )
        self.word(self.profile.address("win32.timeGetTime"), self.timer)
        self.machine.mem_write(self.timer, b"\xc3")
        self.word(self.navigation.enabled_va, 1)
        self.camera_calls: list[tuple[str, int, float]] = []
        for name in ("vr.camera_translate", "vr.camera_rotate", "vr.camera_commit"):
            self.machine.mem_write(
                self.profile.site(name).va,
                bytes.fromhex("c2 08 00" if name.endswith("commit") else "c2 0c 00"),
            )
        self.machine.hook_add(UC_HOOK_CODE, self.observe_camera)

    def observe_camera(self, current: Uc, address: int, _size: int, _context: object) -> None:
        if address == self.timer:
            current.reg_write(UC_X86_REG_EAX, self.now)
        for name in ("vr.camera_translate", "vr.camera_rotate", "vr.camera_commit"):
            if address != self.profile.site(name).va:
                continue
            assert current.reg_read(UC_X86_REG_ECX) == self.manager
            stack = current.reg_read(UC_X86_REG_ESP)
            flags, value = struct.unpack("<If", current.mem_read(stack + 4, 8))
            assert self.world is not None
            assert self.read(self.world.dispatch_va) == 0
            assert self.read(self.scene.enabled_va) == 0
            self.camera_calls.append((name, flags, value))
            # Camera calls can freely clobber caller-saved registers.
            self.clobber(current, name)

    def sticks(
        self, left: tuple[float, float] = (0, 0), right: tuple[float, float] = (0, 0)
    ) -> None:
        self.machine.mem_write(self.panel.frame_va + 108, struct.pack("<2f", *left))
        self.machine.mem_write(self.panel.frame_va + 156, struct.pack("<2f", *right))

    def step(self, milliseconds: int = 10) -> None:
        self.now = (self.now + milliseconds) & 0xFFFFFFFF
        self.invoke()


def test_dormant_callback_and_changed_native_anchor_rejection() -> None:
    harness = InputHarness(world=True, navigation=True)
    assert harness.navigation is not None
    assert harness.image.read_u32_va(harness.navigation.enabled_va) == 0
    compiler = VRNavigationCompiler(
        profile=harness.profile, panel=harness.panel, scene=harness.scene
    )
    harness.image.write_bytes(
        harness.image.va_to_offset(harness.profile.site("vr.camera_translate").va), b"\xcc"
    )
    with pytest.raises(PatchError, match="camera anchor changed"):
        compiler.postcheck(harness.image)


def test_pointing_at_interactive_overlay_stops_navigation_until_sticks_are_neutral() -> None:
    harness = NavigationHarness()
    harness.step()
    harness.sticks((0, 1), (1, 0))
    harness.step()
    initial = len(harness.camera_calls)
    harness.word(harness.panel.frame_va + 164, 1)
    harness.step()
    assert len(harness.camera_calls) == initial
    harness.snapshot()
    harness.sticks((0, 1), (1, 0))
    harness.step()
    assert len(harness.camera_calls) == initial
    harness.sticks()
    harness.step()
    harness.sticks((0, 1), (1, 0))
    harness.step()
    assert len(harness.camera_calls) > initial


@pytest.mark.parametrize("left", [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1)])
def test_translation_uses_physical_scale_native_flags_and_one_commit(left: tuple[int, int]) -> None:
    harness = NavigationHarness()
    harness.step()  # neutral enables movement without a first-frame displacement
    assert not harness.camera_calls
    harness.sticks(left)
    harness.step(50)
    calls = harness.camera_calls
    assert [item[0] for item in calls] == [
        "vr.camera_translate",
        "vr.camera_translate",
        "vr.camera_commit",
    ]
    assert [item[1] for item in calls] == [4, 3, 0]
    expected = 40 * 1.4 * 0.05
    assert math.hypot(calls[0][2], calls[1][2]) == pytest.approx(expected)
    for axis in range(2):
        assert math.copysign(1, calls[axis][2]) == math.copysign(1, left[axis])
    assert harness.navigation is not None
    assert harness.read(harness.navigation.movement_count_va) == 1


@pytest.mark.parametrize("direction", [-1, 1])
def test_snap_turn_requires_neutral_before_first_and_each_repeat(direction: int) -> None:
    harness = NavigationHarness()
    harness.sticks(right=(direction, 0))
    harness.step()
    harness.step()
    assert not harness.camera_calls
    harness.sticks()
    harness.step()
    harness.sticks(right=(direction, 0))
    harness.step()
    harness.step()
    assert len(harness.camera_calls) == 2
    assert harness.camera_calls[0][0:2] == ("vr.camera_rotate", 4)
    assert harness.camera_calls[0][2] == pytest.approx(direction * math.pi / 6)
    harness.sticks(right=(-direction, 0))
    harness.step()
    assert len(harness.camera_calls) == 2  # reversal without neutral is not another turn
    harness.sticks()
    harness.step()
    harness.sticks(right=(-direction, 0))
    harness.step()
    assert harness.navigation is not None
    assert harness.read(harness.navigation.turn_count_va) == 2


@pytest.mark.parametrize("loss", ["focus", "tracking", "menu", "lock", "completion", "gap"])
def test_interruption_stops_motion_and_requires_neutral_without_time_backlog(loss: str) -> None:
    harness = NavigationHarness()
    harness.step()
    harness.sticks((0, 1), (1, 0))
    harness.step()
    initial = len(harness.camera_calls)
    if loss == "menu":
        harness.word(harness.owner, harness.profile.address("vr.toolbar_vtable"))
    elif loss == "lock":
        harness.machine.mem_write(harness.manager + 0x1C5, b"\x01")
    elif loss == "completion":
        harness.word(harness.panel.completion_result_va, 1)
    elif loss in {"focus", "tracking"}:
        harness.snapshot(loss=loss)
    harness.step(1000 if loss == "gap" else 10)
    assert len(harness.camera_calls) == initial
    harness.word(harness.owner, harness.profile.address("vr.room_layer_vtable"))
    harness.machine.mem_write(harness.manager + 0x1C5, b"\x00")
    harness.word(harness.panel.completion_result_va, 0)
    harness.snapshot()
    harness.sticks((0, 1), (1, 0))
    harness.step()
    assert len(harness.camera_calls) == initial
    harness.sticks()
    harness.step()
    harness.sticks((0, 1), (1, 0))
    harness.step()
    assert len(harness.camera_calls) > initial


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 1.1, -1.1])
def test_invalid_sticks_never_reach_native_camera_methods(value: float) -> None:
    harness = NavigationHarness()
    harness.step()
    harness.sticks((value, value), (value, value))
    harness.step()
    assert not harness.camera_calls
    harness.sticks((0, 1), (1, 0))
    harness.step()
    assert not harness.camera_calls


@pytest.mark.parametrize("cadence", [10, 20, 40])
def test_distance_is_independent_of_cadence_and_resolution(cadence: int) -> None:
    harness = NavigationHarness()
    harness.step()
    harness.sticks((0, 1))
    harness.word(harness.panel.frame_va + 8, 3840)
    harness.word(harness.panel.frame_va + 12, 2160)
    for _ in range(1000 // cadence):
        harness.step(cadence)
    total = sum(
        value
        for name, flags, value in harness.camera_calls
        if name == "vr.camera_translate" and flags == 3
    )
    assert total == pytest.approx(40 * 1.4)


def test_clock_wrap_cap_dead_zone_and_independent_hands() -> None:
    harness = NavigationHarness()
    harness.now = 0xFFFFFFF0
    harness.step(0)
    harness.sticks((0.1, 0.1))
    harness.step(10)
    assert not harness.camera_calls
    harness.sticks((0, 1))
    harness.word(harness.panel.frame_va + 116, 0)  # right hand unavailable
    # Pointer ownership uses left, but left navigation does not require right.
    harness.word(harness.panel.frame_va + 168, 0)
    harness.step(100)
    assert harness.camera_calls[1][2] == pytest.approx(40 * 1.4 * 0.05)


def test_vertical_turn_stick_is_not_neutral_and_does_not_rearm() -> None:
    harness = NavigationHarness()
    harness.step()
    harness.sticks(right=(1, 0))
    harness.step()
    assert len(harness.camera_calls) == 2
    harness.sticks(right=(0, 1))
    harness.step()
    harness.sticks(right=(1, 0))
    harness.step()
    assert len(harness.camera_calls) == 2


@pytest.mark.parametrize("state", ["empty", "stacked", "damaged", "scripted", "missing"])
def test_scripted_camera_ownership_blocks_movement_and_requires_neutral_to_recover(
    state: str,
) -> None:
    harness = NavigationHarness()
    harness.step()
    harness.word(
        harness.manager + 0xB0, {"empty": 0, "stacked": 2, "damaged": 0xFFFFFFFF}.get(state, 1)
    )
    if state == "scripted":
        harness.word(harness.controller, 123)
    elif state == "missing":
        harness.word(harness.controller_slot, 0)
    harness.sticks((0, 1), (1, 0))
    harness.step()
    assert not harness.camera_calls
    harness.word(harness.manager + 0xB0, 1)
    harness.word(harness.controller, harness.profile.address("vr.user_scene_controller_vtable"))
    harness.word(harness.controller_slot, harness.controller)
    harness.step()
    assert not harness.camera_calls, "held input replayed after a native camera sequence"
    harness.sticks()
    harness.step()
    harness.sticks((0, 1), (1, 0))
    harness.step()
    assert harness.navigation is not None
    assert harness.read(harness.navigation.movement_count_va) == 1
    assert harness.read(harness.navigation.turn_count_va) == 1


def test_camera_only_user_controller_retains_seated_navigation() -> None:
    harness = NavigationHarness()
    harness.word(harness.controller, harness.profile.address("vr.user_camera_controller_vtable"))
    harness.step()
    harness.sticks((0, 1))
    harness.step()
    assert len(harness.camera_calls) == 3


@pytest.mark.parametrize("scale", [20, 80])
def test_translation_follows_scene_world_scale(scale: int) -> None:
    harness = NavigationHarness()
    harness.machine.mem_write(harness.scene.recenter_va + 4, struct.pack("<f", scale))
    harness.step()
    harness.sticks((0, 1))
    harness.step(50)
    assert harness.camera_calls[1][2] == pytest.approx(scale * 1.4 * 0.05)


def test_opening_world_action_menu_cannot_move_camera_on_the_same_dispatch() -> None:
    harness = NavigationHarness()
    harness.step()
    harness.sticks((0, 1))
    harness.snapshot(held=1)
    menu = _HEAP + 0xB500
    children = _HEAP + 0xB800

    def open_menu(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == harness.profile.address("input.left_down"):
            harness.word(harness.owner + 0x4C, children)
            harness.word(harness.owner + 0x50, 1)
            harness.word(children, menu)
            harness.word(menu, harness.profile.address("vr.action_menu_vtable"))
            current.mem_write(menu + 0x18, b"\x01")

    harness.machine.hook_add(UC_HOOK_CODE, open_menu)
    harness.step()
    assert not harness.camera_calls


@pytest.mark.parametrize(
    "anchor",
    list(VRNavigationCompiler._anchors),
)
def test_changed_native_camera_contract_is_rejected_before_installation(anchor: str) -> None:
    image, panel, _ = _linked_panel(paired=True)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).abi(image)
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(anchor).va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError, match="camera anchor changed"):
        VRNavigationCompiler(profile=GOG_BUILD, panel=panel, scene=scene).apply(image)
    assert image.to_bytes() == before
