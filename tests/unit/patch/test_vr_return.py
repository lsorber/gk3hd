"""Execute the observer transaction with native recipients and completed XR frames."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.vr_ownership import VROwnershipCompiler
from gk3hd.patch.definitions.vr_protagonist import VRProtagonistCompiler
from gk3hd.patch.definitions.vr_return import VRReturnCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from tests.unit.patch.test_vr_panel import _linked_panel
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc


class ReturnHarness:
    """Model engine ownership and recipients, not the generated transaction."""

    def __init__(self) -> None:
        image, self.panel, _previous = _linked_panel(paired=True)
        self.scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).abi(image)
        owner = VROwnershipCompiler(profile=GOG_BUILD, panel=self.panel, scene=self.scene)
        owner.apply(image)
        protagonist = VRProtagonistCompiler(profile=GOG_BUILD)
        protagonist.apply(image)
        self.compiler = VRReturnCompiler(
            profile=GOG_BUILD,
            panel=self.panel,
            scene=self.scene,
            ownership=owner.abi(image),
            protagonist=protagonist.abi(image),
        )
        self.compiler.apply(image)
        self.compiler.postcheck(image)
        self.abi = self.compiler.abi(image)
        self.machine = _machine(image)
        self.layer, self.engine, self.services, self.manager, self.controller = (
            _HEAP + offset for offset in (0x1000, 0x2000, 0x3000, 0x4000, 0x5000)
        )
        self.room, self.actor, self.model = _HEAP + 0x6000, _HEAP + 0x7000, _HEAP + 0x8000
        self.ui = self.layer
        self.user_owned = self.bridge_available = True
        self.solver_result = 0
        self.floor = (266.0, 0.0, 52.0)
        self.clock = 50
        self.position = (100.0, 69.5, 100.0)
        self.moves: list[tuple[float, float, float]] = []
        self.angle_before = struct.pack("<8f", 1, 2, 3, 4, 5, 6, 7, 8)
        self.module, self.resolve, self.solver, self.timer = (
            _HEAP + x for x in (0x9000, 0x9100, 0x9200, 0x9300)
        )
        self.owner_query = owner.abi(image).query_va
        self.actor_query = protagonist.abi(image).query_va
        self.machine.mem_write(self.manager + 0x13C, self.angle_before)
        for address, value in (
            (self.layer, GOG_BUILD.address("vr.room_layer_vtable")),
            (GOG_BUILD.address("engine.loop"), self.engine),
            (self.engine + 0x444, self.services),
            (self.services + 0x28, self.manager),
            (GOG_BUILD.address("win32.GetModuleHandleA"), self.module),
            (GOG_BUILD.address("win32.GetProcAddress"), self.resolve),
            (GOG_BUILD.address("win32.timeGetTime"), self.timer),
        ):
            self.word(address, value)
        for address, cleanup in (
            (self.module, 4),
            (self.resolve, 8),
            (self.solver, 12),
            (self.timer, 0),
            (self.owner_query, 0),
            (self.actor_query, 4),
            (GOG_BUILD.address("ui.current_layer"), 0),
            (GOG_BUILD.site("vr.camera_controller_top").va, 0),
            (GOG_BUILD.site("vr.camera_angle_position").va, 4),
            (GOG_BUILD.site("vr.camera_angle_commit").va, 12),
        ):
            self.machine.mem_write(
                address, b"\xc3" if not cleanup else b"\xc2" + struct.pack("<H", cleanup)
            )
        self.machine.hook_add(UC_HOOK_CODE, self.observe)
        self.frame()

    def word(self, address: int, value: int) -> None:
        self.machine.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.machine.mem_read(address, 4))[0]

    def frame(
        self,
        *,
        held: int = 0,
        stick: float = 0,
        focused: bool = True,
        tracked: bool = True,
        hand: int = 1,
    ) -> None:
        self.word(self.panel.submitted_frames_va, self.read(self.panel.submitted_frames_va) + 1)
        for offset, value in (
            (16, hand),
            (64, int(focused)),
            (68, int(tracked)),
            (116, int(tracked)),
            (72, held),
            (76, 0),
            (120, held),
            (124, 0),
            (180, held),
            (184, 0),
        ):
            self.word(self.panel.frame_va + offset, value)
        for offset in (108, 112, 156, 160):
            self.machine.mem_write(self.panel.frame_va + offset, struct.pack("<f", stick))
        self.word(self.scene.world_input_va + 4, 3)
        self.word(self.scene.teleport_va + 4, 0)

    def invoke(self, entry: int, *args: int) -> int:
        self.machine.mem_write(_STACK, struct.pack("<" + "I" * (1 + len(args)), _RETURN, *args))
        self.machine.reg_write(UC_X86_REG_ESP, _STACK)
        self.machine.emu_start(entry, _RETURN, count=10000)
        assert self.machine.reg_read(UC_X86_REG_ESP) == _STACK + 4 * (1 + len(args))
        return self.machine.reg_read(UC_X86_REG_EAX)

    def request(self) -> int:
        return self.invoke(self.abi.request_va, self.layer)

    def complete(
        self,
        *,
        held: int = 0,
        stick: float = 0,
        focused: bool = True,
        tracked: bool = True,
        hand: int = 1,
    ) -> None:
        self.frame(held=held, stick=stick, focused=focused, tracked=tracked, hand=hand)
        self.word(self.scene.teleport_va + 4, 2)
        self.invoke(self.abi.tick_va)

    def observe(self, current: Uc, address: int, _size: int, _context: object) -> None:
        stack = current.reg_read(UC_X86_REG_ESP)
        if address == GOG_BUILD.address("ui.current_layer"):
            current.reg_write(UC_X86_REG_EAX, self.ui)
        elif address == self.owner_query:
            current.reg_write(UC_X86_REG_EAX, int(self.user_owned))
        elif address == self.actor_query:
            record = self.read(stack + 4)
            current.mem_write(
                record, struct.pack("<4I4f", 32, self.room, self.actor, self.model, 235, 34, 58, 1)
            )
            current.reg_write(UC_X86_REG_EAX, 1)
        elif address == GOG_BUILD.site("vr.camera_controller_top").va:
            current.reg_write(UC_X86_REG_EAX, self.controller)
        elif address == self.module:
            current.reg_write(UC_X86_REG_EAX, 1)
        elif address == self.resolve:
            current.reg_write(UC_X86_REG_EAX, self.solver if self.bridge_available else 0)
        elif address == self.timer:
            current.reg_write(UC_X86_REG_EAX, self.clock)
        elif address == self.solver:
            scene, anchor, output = struct.unpack("<3I", current.mem_read(stack + 4, 12))
            assert scene == self.scene.recenter_va - 4
            assert struct.unpack("<3f", current.mem_read(anchor, 12)) == (235, 34, 58)
            current.mem_write(output, struct.pack("<3f", *self.floor))
            current.reg_write(UC_X86_REG_EAX, self.solver_result)
        else:
            self.observe_camera(current, address, stack)

    def observe_camera(self, current: Uc, address: int, stack: int) -> None:
        if address == GOG_BUILD.site("vr.camera_angle_position").va:
            angle = current.reg_read(UC_X86_REG_ECX)
            assert bytes(current.mem_read(angle, 32)) == self.angle_before
            position = self.read(stack + 4)
            self.position = struct.unpack("<3f", current.mem_read(position, 12))
        elif address == GOG_BUILD.site("vr.camera_angle_commit").va:
            assert current.reg_read(UC_X86_REG_ECX) == self.manager
            assert struct.unpack("<2I", current.mem_read(stack + 8, 8)) == (1, 0)
            self.moves.append(self.position)


@pytest.mark.parametrize("hand", [0, 1])
def test_return_requires_completed_black_frame_and_runs_once(hand: int) -> None:
    h = ReturnHarness()
    h.frame(hand=hand)
    assert h.invoke(h.abi.available_va, h.layer) == 1
    assert h.request() == 1
    h.invoke(h.abi.tick_va)
    assert h.moves == []
    h.complete(hand=hand)
    assert h.moves == [(266, 69.5, 52)]
    h.complete(hand=hand)
    h.complete(hand=hand)
    assert h.moves == [(266, 69.5, 52)]
    assert bytes(h.machine.mem_read(h.manager + 0x13C, 32)) == h.angle_before


@pytest.mark.parametrize(
    "changed",
    [
        "room",
        "actor",
        "model",
        "manager",
        "controller",
        "ui",
        "scripted",
        "focus",
        "tracking",
        "failed_frame",
        "timeout",
    ],
)
def test_ownership_or_presentation_changes_cancel_the_pending_return(changed: str) -> None:
    h = ReturnHarness()
    assert h.request() == 1
    if changed in {"room", "actor", "model", "controller"}:
        setattr(h, changed, getattr(h, changed) + 4)
    elif changed == "manager":
        h.word(h.services + 0x28, h.manager + 4)
    elif changed == "ui":
        h.ui += 4
    elif changed == "scripted":
        h.user_owned = False
    elif changed == "failed_frame":
        h.word(h.panel.completion_result_va, 0x80004005)
    elif changed == "timeout":
        h.clock += 5000
    h.complete(focused=changed != "focus", tracked=changed != "tracking")
    assert h.moves == []
    h.complete()
    assert h.moves == [], "late blackout replayed a cancelled request"


@pytest.mark.parametrize(
    "fault", ["no_solver", "no_ground", "solver_error", "nan_floor", "not_room", "no_user_camera"]
)
def test_unavailable_return_never_arms_relocation(fault: str) -> None:
    h = ReturnHarness()
    if fault == "no_solver":
        h.bridge_available = False
    elif fault == "no_ground":
        h.solver_result = 1
    elif fault == "solver_error":
        h.solver_result = 0x80004005
    elif fault == "nan_floor":
        h.floor = (float("nan"), 0, 1)
    elif fault == "not_room":
        h.ui += 4
    elif fault == "no_user_camera":
        h.user_owned = False
    assert h.request() == 0
    assert h.read(h.scene.recenter_va) & 8 == 0
    h.complete()
    assert h.moves == []


@pytest.mark.parametrize(("held", "stick"), [(1, 0.0), (4, 0.0), (0, 0.8)])
def test_held_input_stays_consumed_until_a_fresh_neutral_frame(held: int, stick: float) -> None:
    h = ReturnHarness()
    assert h.request() == 1
    h.complete(held=held, stick=stick)
    for _ in range(3):
        h.frame(held=held, stick=stick)
        h.invoke(h.abi.tick_va)
        assert h.read(h.panel.frame_va + 180) == 0
        assert h.read(h.panel.frame_va + 108) == 0
        assert h.read(h.scene.world_input_va + 4) == 0
        # Reentrant/repeated consumption of the already-masked frame cannot
        # stand in for an actual release from a subsequent runtime sample.
        h.invoke(h.abi.tick_va)
    h.frame()
    h.invoke(h.abi.tick_va)
    h.frame(held=held, stick=stick)
    h.invoke(h.abi.tick_va)
    assert h.read(h.panel.frame_va + 180) == held
    assert struct.unpack("<f", h.machine.mem_read(h.panel.frame_va + 108, 4))[0] == pytest.approx(
        stick
    )
    assert len(h.moves) == 1


def test_explicit_cancel_does_not_change_ordinary_teleport_completion() -> None:
    h = ReturnHarness()
    h.word(h.scene.teleport_va + 4, 1)
    h.invoke(h.abi.cancel_va)
    assert h.read(h.scene.teleport_va + 4) == 1
    assert h.request() == 1
    h.invoke(h.abi.cancel_va)
    h.complete()
    assert h.moves == []


def test_clock_wrap_does_not_drop_a_timely_return() -> None:
    h = ReturnHarness()
    h.clock = 0xFFFFFFF0
    assert h.request() == 1
    h.clock = 0x20
    h.complete()
    assert len(h.moves) == 1
