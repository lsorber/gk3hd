"""Seated controller navigation through the original float camera methods."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_panel import VRPanelABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@dataclass(frozen=True, slots=True)
class VRNavigationABI:
    """Dormant switch, completed-input callback and native camera counters."""

    enabled_va: int
    tick_va: int
    movement_count_va: int
    turn_count_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRNavigationCompiler:
    """Move the authored camera, never the character or tracked eye pose.

    The input owner calls ``tick(world_owned)`` once after completed controller
    dispatch. Left stick translates at at most 1.4 metres/second with a radial
    dead zone. Right stick turns 30 degrees once, requiring neutral to repeat.
    Focus, tracking, ownership, camera locks and scripted controllers retire input without
    accumulating time. Recovery requires neutral, independently for each hand.
    Native float movement/commit retains collision and bypasses keyboard ramps.
    """

    profile: BuildProfile
    panel: VRPanelABI
    scene: VRSceneABI

    section_name: ClassVar[str] = ".gk3vn"
    section_size: ClassVar[int] = 0x1000
    _magic: ClassVar[bytes] = b"GK3XRN01"
    _enabled: ClassVar[int] = 0x0C
    _valid: ClassVar[int] = 0x10
    _last: ClassVar[int] = 0x14
    _move_armed: ClassVar[int] = 0x18
    _turn_armed: ClassVar[int] = 0x1C
    _manager: ClassVar[int] = 0x20
    _delta: ClassVar[int] = 0x24
    _side: ClassVar[int] = 0x28
    _forward: ClassVar[int] = 0x2C
    _angle: ClassVar[int] = 0x30
    _moves: ClassVar[int] = 0x34
    _turns: ClassVar[int] = 0x38
    _constants: ClassVar[int] = 0x40
    _code: ClassVar[int] = 0x100
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.camera_translate",
        "vr.camera_rotate",
        "vr.camera_commit",
        "vr.camera_input_lock",
        "vr.camera_controller_top",
        "vr.camera_controller_stack",
        "vr.user_camera_controller",
        "vr.user_scene_controller",
    )

    def abi(self, image: PEFile) -> VRNavigationABI:
        """Return the verified private navigation entry."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR navigation section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRNavigationABI(
            base + self._enabled, base + self._code, base + self._moves, base + self._turns
        )

    def _check(self, image: PEFile) -> None:
        if (
            VRPanelCompiler(profile=self.profile).abi(image) != self.panel
            or VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene
            or self.panel.world_enabled_va != self.scene.enabled_va
        ):
            msg = "VR navigation composition boundary changed"
            raise PatchError(msg)
        for name in self._anchors:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR navigation native camera anchor changed: {name}"
                raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Install a dormant callback without redirecting ordinary controls."""
        if image.get_section(self.section_name) is not None:
            msg = "VR navigation is already installed"
            raise PatchError(msg)
        self._check(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        image.write_bytes(
            section.pointer_to_raw_data, self._payload(image.rva_to_va(section.virtual_address))
        )

    def postcheck(self, image: PEFile) -> None:
        """Verify native targets, dependencies and the complete callback."""
        self._check(image)
        base = self.abi(image).enabled_va - self._enabled
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(base):
            msg = "VR navigation payload failed verification"
            raise PatchError(msg)

    def _payload(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._code)
        p = self.profile
        frame = self.panel.frame_va

        def absolute(op: bytes, address: int) -> None:
            e.raw(op + struct.pack("<I", address))

        def state(op: bytes, offset: int) -> None:
            absolute(op, base + offset)

        def store(offset: int, value: int = 0) -> None:
            state(b"\xc7\x05", offset)
            e.raw(struct.pack("<I", value))

        def constant(op: bytes, index: int) -> None:
            state(op, self._constants + 4 * index)

        def camera_call(name: str, value: int, flags: int) -> None:
            e.raw(b"\x6a\x00")
            state(b"\xff\x35", value)
            e.raw(b"\x6a" + bytes((flags,)))
            state(b"\x8b\x0d", self._manager)
            e.call_absolute(p.site(name).va)

        e.raw(bytes.fromhex("9c 60"))
        store(self._side)
        store(self._forward)
        store(self._angle)
        state(b"\x83\x3d", self._enabled)
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "reset")
        e.raw(bytes.fromhex("83 7c 24 28 01"))  # world_owned argument after pushfd/pushad
        e.jump_if(Condition.NOT_EQUAL, "reset")
        absolute(b"\xf7\x05", frame + 64)
        e.raw(struct.pack("<I", 1))
        e.jump_if(Condition.EQUAL, "reset")
        absolute(b"\xa1", p.address("engine.loop"))
        for instruction in (b"", bytes.fromhex("8b 80 44 04 00 00"), b"\x8b\x40\x28"):
            e.raw(instruction + bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "reset")
        e.raw(bytes.fromhex("81 38") + struct.pack("<I", p.address("vr.camera_manager_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "reset")
        # The original keyboard camera producer checks this same lock.
        e.raw(bytes.fromhex("80 b8 c5 01 00 00 00"))
        e.jump_if(Condition.NOT_EQUAL, "reset")
        state(b"\xa3", self._manager)
        e.raw(bytes.fromhex("83 b8 b0 00 00 00 01"))
        e.jump_if(Condition.NOT_EQUAL, "reset")
        e.raw(bytes.fromhex("89 c1"))
        e.call_absolute(p.site("vr.camera_controller_top").va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "reset")
        for name in ("vr.user_camera_controller_vtable", "vr.user_scene_controller_vtable"):
            e.raw(b"\x81\x38" + struct.pack("<I", p.address(name)))
            e.jump_if(Condition.EQUAL, "user_camera")
        e.jump("reset")
        e.label("user_camera")
        absolute(b"\xff\x15", p.address("win32.timeGetTime"))
        state(b"\x8b\x15", self._last)
        state(b"\xa3", self._last)
        e.raw(bytes.fromhex("29 d0"))
        state(b"\x83\x3d", self._valid)
        e.raw(b"\x01")
        e.jump_if(Condition.EQUAL, "elapsed")
        store(self._valid, 1)
        e.raw(bytes.fromhex("31 c0"))
        e.label("elapsed")
        e.raw(bytes.fromhex("3d fa 00 00 00"))
        e.jump_if(Condition.ABOVE, "reset")
        e.raw(bytes.fromhex("83 f8 32"))
        e.jump_if(Condition.BELOW_OR_EQUAL, "bounded")
        e.raw(bytes.fromhex("b8 32 00 00 00"))
        e.label("bounded")
        e.raw(bytes.fromhex("f3 0f 2a c0"))
        state(bytes.fromhex("f3 0f 11 05"), self._delta)

        # Validate each stick before floating-point arithmetic. Absolute IEEE
        # bits above 1.0 include infinities and every NaN, including negative NaN.
        for hand, armed, following in (
            (0, self._move_armed, "turn"),
            (1, self._turn_armed, "apply"),
        ):
            e.label("move" if hand == 0 else "turn")
            absolute(b"\x83\x3d", frame + 68 + 48 * hand)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, f"invalid_{hand}")
            for axis in range(2):
                absolute(b"\xa1", frame + 108 + 48 * hand + 4 * axis)
                e.raw(bytes.fromhex("25 ff ff ff 7f 3d 00 00 80 3f"))
                e.jump_if(Condition.ABOVE, f"invalid_{hand}")
            if hand == 0:
                absolute(bytes.fromhex("f3 0f 10 05"), frame + 108)
                absolute(bytes.fromhex("f3 0f 10 0d"), frame + 112)
                e.raw(bytes.fromhex("f3 0f 59 c0 f3 0f 59 c9 f3 0f 58 c1 f3 0f 51 c0"))
                constant(bytes.fromhex("0f 2e 05"), 0)  # radius <= .2
                e.jump_if(Condition.BELOW_OR_EQUAL, "move_neutral")
                state(b"\x83\x3d", armed)
                e.raw(b"\x01")
                e.jump_if(Condition.NOT_EQUAL, following)
                e.raw(bytes.fromhex("0f 28 c8"))  # xmm1 = radius
                constant(bytes.fromhex("f3 0f 5d 05"), 1)  # clamp diagonal magnitude
                constant(bytes.fromhex("f3 0f 5c 05"), 0)
                e.raw(bytes.fromhex("f3 0f 5e c1"))
                state(bytes.fromhex("f3 0f 59 05"), self._delta)
                absolute(bytes.fromhex("f3 0f 59 05"), self.scene.recenter_va + 4)  # units/metre
                constant(bytes.fromhex("f3 0f 59 05"), 2)  # 1.4m/s / .8 dead-zone span / 1000
                for coordinate, destination in ((108, self._side), (112, self._forward)):
                    absolute(bytes.fromhex("f3 0f 10 0d"), frame + coordinate)
                    e.raw(bytes.fromhex("f3 0f 59 c8"))
                    state(bytes.fromhex("f3 0f 11 0d"), destination)
                e.jump(following)
                e.label("move_neutral")
                store(armed, 1)
                e.jump(following)
            else:
                absolute(b"\xa1", frame + 156)
                e.raw(bytes.fromhex("89 c2 25 ff ff ff 7f"))
                e.raw(b"\x3d" + struct.pack("<f", 0.2))
                e.jump_if(Condition.ABOVE, "turn_threshold")
                absolute(b"\xa1", frame + 160)
                e.raw(bytes.fromhex("25 ff ff ff 7f"))
                e.raw(b"\x3d" + struct.pack("<f", 0.2))
                e.jump_if(Condition.BELOW_OR_EQUAL, "turn_neutral")
                e.jump(following)
                e.label("turn_threshold")
                state(b"\x83\x3d", armed)
                e.raw(b"\x01")
                e.jump_if(Condition.NOT_EQUAL, following)
                e.raw(b"\x3d" + struct.pack("<f", 0.7))
                e.jump_if(Condition.BELOW, following)
                store(armed)
                constant(b"\xa1", 3)
                e.raw(bytes.fromhex("81 e2 00 00 00 80 09 d0"))
                state(b"\xa3", self._angle)
                e.jump(following)
                e.label("turn_neutral")
                store(armed, 1)
                e.jump(following)
            e.label(f"invalid_{hand}")
            store(armed)
            e.jump(following)

        e.label("apply")
        state(b"\x83\x3d", self._angle)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "translation")
        camera_call("vr.camera_rotate", self._angle, 4)
        state(b"\xff\x05", self._turns)
        e.label("translation")
        state(b"\xa1", self._side)
        state(b"\x0b\x05", self._forward)
        e.raw(bytes.fromhex("25 ff ff ff 7f"))
        e.jump_if(Condition.EQUAL, "commit")
        camera_call("vr.camera_translate", self._side, 4)
        camera_call("vr.camera_translate", self._forward, 3)
        state(b"\xff\x05", self._moves)
        e.label("commit")
        state(b"\xa1", self._side)
        state(b"\x0b\x05", self._forward)
        state(b"\x0b\x05", self._angle)
        e.raw(bytes.fromhex("25 ff ff ff 7f"))
        e.jump_if(Condition.EQUAL, "done")
        e.raw(bytes.fromhex("6a 00 6a 00"))
        state(b"\x8b\x0d", self._manager)
        e.call_absolute(p.site("vr.camera_commit").va)
        e.jump("done")
        e.label("reset")
        for offset in (self._valid, self._move_armed, self._turn_armed):
            store(offset)
        e.label("done")
        e.raw(bytes.fromhex("61 9d c2 04 00"))

        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into("<4f", header, self._constants, 0.2, 1, 1.4 / 0.8 / 1000, math.pi / 6)
        payload = SegmentPayloadBuilder(
            owner="vr_navigation", segment=self.section_name, size=self.section_size
        )
        payload.place(label="navigation state", offset=0, payload=bytes(header))
        payload.place(
            label="native camera callback",
            offset=self._code,
            payload=e.build(maximum_size=self.section_size - self._code),
        )
        return payload.build()
