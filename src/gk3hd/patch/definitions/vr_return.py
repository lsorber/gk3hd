"""Single-use observer Return, owned by the native game menu transaction."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.vr_ownership import VROwnershipCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_protagonist import VRProtagonistCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_ownership import VROwnershipABI
    from gk3hd.patch.definitions.vr_panel import VRPanelABI
    from gk3hd.patch.definitions.vr_protagonist import VRProtagonistABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@dataclass(frozen=True, slots=True)
class VRReturnABI:
    """Game-thread calls, never launch switches or permission from a saved pointer.

    available(room_layer*) and request(room_layer*) return one on success.
    tick() and cancel() are called inside the menu's guarded presenter. Cancel
    touches only owned scratch state and is also safe during native unwinding.
    """

    available_va: int
    request_va: int
    tick_va: int
    cancel_va: int
    pending_va: int
    result_va: int
    commits_va: int
    destination_va: int  # Native observer eye XYZ from the last successful search.


@dataclass(frozen=True, slots=True, kw_only=True)
class VRReturnCompiler:
    """Stage one Return and consume only its completed, focused black frame.

    The native owner retains scene/ego/model/UI/camera identities, while the
    shared renderer finds a nearby standing point. Original CameraAngle and
    CameraManager methods move the observer without a scripted camera cut.
    This installs inert calls, not hooks. The game menu owns dispatch, faults
    and activation. After commit/cancellation, real neutral controls are needed
    before published input is allowed through again.
    """

    profile: BuildProfile
    panel: VRPanelABI
    scene: VRSceneABI
    ownership: VROwnershipABI
    protagonist: VRProtagonistABI

    section_name: ClassVar[str] = ".gk3rt"
    section_size: ClassVar[int] = 0x3000
    _magic: ClassVar[bytes] = b"GK3XRR01"
    _pending: ClassVar[int] = 0x10  # 1 waiting for blackout, 2 waiting for neutral.
    _result: ClassVar[int] = 0x14  # 0 idle/staged, 1 committed, 2 cancelled/rejected.
    _commits: ClassVar[int] = 0x18
    _rejected: ClassVar[int] = 0x1C
    _bridge: ClassVar[int] = 0x20
    _layer: ClassVar[int] = 0x24
    _started: ClassVar[int] = 0x28
    _frame: ClassVar[int] = 0x2C
    _scratch: ClassVar[int] = 0x80  # 32-byte native protagonist snapshot.
    _manager: ClassVar[int] = 0xA0
    _controller: ClassVar[int] = 0xA4
    _saved: ClassVar[int] = 0xB0  # scene/ego/model/manager/controller.
    _destination: ClassVar[int] = 0xD0  # floor XYZ, then observer eye XYZ.
    _angle: ClassVar[int] = 0x100  # native 32-byte CameraAngle, not EngineCamera.
    _available: ClassVar[int] = 0x1000
    _request: ClassVar[int] = 0x1100
    _tick: ClassVar[int] = 0x1500
    _cancel: ClassVar[int] = 0x1900
    _helpers: ClassVar[int] = 0x1A00
    _dll: ClassVar[int] = 0x2800
    _export: ClassVar[int] = 0x2820

    @classmethod
    def abi(cls, image: PEFile) -> VRReturnABI:
        """Read the checked calls after verifying this private section identity."""
        section = image.get_section(cls.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != cls._magic:
            msg = "VR Return section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRReturnABI(
            *(
                base + offset
                for offset in (
                    cls._available,
                    cls._request,
                    cls._tick,
                    cls._cancel,
                    cls._pending,
                    cls._result,
                    cls._commits,
                    cls._destination + 12,
                )
            )
        )

    def _check(self, image: PEFile) -> None:
        if (
            VRPanelCompiler(profile=self.profile).abi(image) != self.panel
            or VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene
            or VRProtagonistCompiler(profile=self.profile).abi(image) != self.protagonist
            or VROwnershipCompiler(profile=self.profile, panel=self.panel, scene=self.scene).abi(
                image
            )
            != self.ownership
        ):
            msg = "VR Return composition boundary changed"
            raise PatchError(msg)
        for name in (
            "vr.camera_angle_position",
            "vr.camera_angle_commit",
            "vr.camera_controller_top",
        ):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR Return native anchor changed: {name}"
                raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Add dormant callable entries without changing existing presenter links."""
        if image.get_section(self.section_name) is not None:
            msg = "VR Return is already installed"
            raise PatchError(msg)
        self._check(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        image.write_bytes(
            section.pointer_to_raw_data, self._payload(image.rva_to_va(section.virtual_address))
        )

    def postcheck(self, image: PEFile) -> None:
        """Recheck the native transaction, dependencies and every callable byte."""
        self._check(image)
        base = self.abi(image).pending_va - self._pending
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(base):
            msg = "VR Return payload failed verification"
            raise PatchError(msg)

    def _payload(self, base: int) -> bytes:
        payload = SegmentPayloadBuilder(
            owner="vr_return", segment=self.section_name, size=self.section_size
        )
        payload.place(label="Return identity", offset=0, payload=self._magic)
        for offset, following, build in (
            (self._available, self._request, self._emit_available),
            (self._request, self._tick, self._emit_request),
            (self._tick, self._cancel, self._emit_tick),
            (self._cancel, self._helpers, self._emit_cancel),
            (self._helpers, self._helpers + 0x400, self._emit_snapshot),
            (self._helpers + 0x400, self._helpers + 0x500, self._emit_focus),
            (self._helpers + 0x500, self._dll, self._emit_solver),
        ):
            c = _ReturnCode(X86Emitter(base_va=base + offset), base)
            build(c)
            payload.place(
                label=f"Return entry {offset:x}",
                offset=offset,
                payload=c.e.build(maximum_size=following - offset),
            )
        payload.place(
            label="observer eye height",
            offset=self._destination + 24,
            payload=struct.pack("<f", 69.5),
        )
        payload.place(label="Return renderer", offset=self._dll, payload=b"ddraw.dll\0")
        payload.place(label="Return solver", offset=self._export, payload=b"Gk3hdXrReturnFloorV1\0")
        return payload.build()

    def _emit_available(self, c: _ReturnCode) -> None:
        e = c.e
        e.raw(bytes.fromhex("9c 60 8b 44 24 28"))
        e.call_absolute(c.base + self._helpers)
        e.jump("done")
        e.label("done")
        e.raw(bytes.fromhex("89 44 24 1c 61 9d c2 04 00"))

    def _emit_request(self, c: _ReturnCode) -> None:
        e = c.e
        e.raw(bytes.fromhex("9c 60"))
        c.check(self._pending, 0, "failed")
        e.raw(bytes.fromhex("8b 44 24 28"))
        c.state(b"\xa3", self._layer)
        e.call_absolute(c.base + self._helpers)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        e.call_absolute(c.base + self._helpers + 0x400)  # Focus/completed frame.
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        e.call_absolute(c.base + self._helpers + 0x500)  # Read-only standing-space solver.
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        for index, offset in enumerate(
            (
                self._scratch + 4,
                self._scratch + 8,
                self._scratch + 12,
                self._manager,
                self._controller,
            )
        ):
            c.state(b"\xa1", offset)
            c.state(b"\xa3", self._saved + 4 * index)
        c.absolute(b"\xff\x15", self.profile.address("win32.timeGetTime"))
        c.state(b"\xa3", self._started)
        c.absolute(b"\xa1", self.panel.submitted_frames_va)
        c.state(b"\xa3", self._frame)
        c.store(self._result, 0)
        c.store(self._pending, 1)
        c.absolute(b"\x83\x0d", self.scene.recenter_va)
        e.raw(b"\x08")
        e.raw(bytes.fromhex("b8 01 00 00 00"))
        e.jump("done")
        e.label("failed")
        c.state(b"\xff\x05", self._rejected)
        c.store(self._result, 2)
        e.raw(bytes.fromhex("31 c0"))
        e.label("done")
        e.raw(bytes.fromhex("89 44 24 1c 61 9d c2 04 00"))

    def _emit_tick(self, c: _ReturnCode) -> None:
        e = c.e
        e.raw(bytes.fromhex("9c 60"))
        c.check(self._pending, 0, "done", equal=True)
        c.check(self._pending, 2, "neutral", equal=True)
        e.call_absolute(c.base + self._helpers + 0x400)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "cancel")
        c.state(b"\xa1", self._layer)
        e.call_absolute(c.base + self._helpers)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "cancel")
        for index, offset in enumerate(
            (
                self._scratch + 4,
                self._scratch + 8,
                self._scratch + 12,
                self._manager,
                self._controller,
            )
        ):
            c.state(b"\xa1", offset)
            c.state(b"\x3b\x05", self._saved + 4 * index)
            e.jump_if(Condition.NOT_EQUAL, "cancel")
        c.absolute(b"\xff\x15", self.profile.address("win32.timeGetTime"))
        c.state(b"\x2b\x05", self._started)
        e.raw(bytes.fromhex("3d e8 03 00 00"))
        e.jump_if(Condition.ABOVE, "cancel")
        c.absolute(b"\xa1", self.panel.submitted_frames_va)
        c.state(b"\x3b\x05", self._frame)
        e.jump_if(Condition.EQUAL, "mask")
        c.absolute(b"\x83\x3d", self.scene.teleport_va + 4)
        e.raw(b"\x02")
        e.jump_if(Condition.NOT_EQUAL, "cancel")
        e.call_absolute(c.base + self._helpers + 0x500)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "cancel")
        # Copy the native angle (including yaw/pitch), replace only position,
        # and call the qualified original camera transaction. No actor setter.
        c.state(b"\x8b\x35", self._manager)
        e.raw(bytes.fromhex("81 c6 3c 01 00 00 fc"))
        e.raw(b"\xbf" + struct.pack("<I", c.base + self._angle))
        e.raw(bytes.fromhex("b9 08 00 00 00 f3 a5"))
        e.push_imm32(c.base + self._destination + 12)
        e.raw(b"\xb9" + struct.pack("<I", c.base + self._angle))
        e.call_absolute(self.profile.site("vr.camera_angle_position").va)
        e.raw(bytes.fromhex("6a 00 6a 01"))
        e.push_imm32(c.base + self._angle)
        c.state(b"\x8b\x0d", self._manager)
        e.call_absolute(self.profile.site("vr.camera_angle_commit").va)
        c.state(b"\xff\x05", self._commits)
        c.store(self._result, 1)
        e.call_absolute(c.base + self._cancel)
        e.jump("mask")
        e.label("cancel")
        c.state(b"\xff\x05", self._rejected)
        c.store(self._result, 2)
        e.call_absolute(c.base + self._cancel)
        e.jump("mask")
        e.label("neutral")
        c.absolute(b"\xa1", self.panel.submitted_frames_va)
        c.state(b"\x3b\x05", self._frame)
        e.jump_if(Condition.EQUAL, "mask")
        c.state(b"\xa3", self._frame)
        e.call_absolute(c.base + self._helpers + 0x400)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "mask")
        for offset in (72, 76, 120, 124, 180, 184):
            c.absolute(b"\x83\x3d", self.panel.frame_va + offset)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "mask")
        for offset in (108, 112, 156, 160):
            c.absolute(b"\xa1", self.panel.frame_va + offset)
            e.raw(bytes.fromhex("25 ff ff ff 7f") + b"\x3d" + struct.pack("<f", 0.2))
            e.jump_if(Condition.ABOVE, "mask")
        c.store(self._pending, 0)
        e.jump("done")
        e.label("mask")
        for offset in (72, 76, 108, 112, 120, 124, 156, 160, 164, 180, 184):
            c.absolute(b"\xc7\x05", self.panel.frame_va + offset)
            e.raw(bytes(4))
        # World routing uses a separate completed snapshot; mask that too.
        c.absolute(b"\xc7\x05", self.scene.world_input_va + 4)
        e.raw(bytes(4))
        for offset in (16, 20, 52, 56, 64, 68, 100, 104):
            c.absolute(b"\xc7\x05", self.scene.world_input_va + offset)
            e.raw(bytes(4))
        e.label("done")
        e.raw(bytes.fromhex("61 9d c3"))

    def _emit_cancel(self, c: _ReturnCode) -> None:
        e = c.e
        e.raw(bytes.fromhex("9c 60"))
        c.check(self._pending, 1, "done")
        c.check(self._result, 1, "preserve_commit", equal=True)
        c.store(self._result, 2)
        e.label("preserve_commit")
        c.store(self._pending, 2)
        c.absolute(b"\xa1", self.panel.submitted_frames_va)
        c.state(b"\xa3", self._frame)
        c.absolute(b"\x83\x25", self.scene.recenter_va)
        e.raw(b"\xf7")
        c.absolute(b"\x83\x3d", self.scene.teleport_va + 4)
        e.raw(b"\x02")
        e.jump_if(Condition.NOT_EQUAL, "done")
        c.absolute(b"\xc7\x05", self.scene.teleport_va + 4)
        e.raw(bytes(4))
        e.label("done")
        e.raw(bytes.fromhex("61 9d c3"))

    def _emit_snapshot(self, c: _ReturnCode) -> None:
        e = c.e
        # EAX is the expected room UI owner, not a cached scene/actor pointer.
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        e.raw(bytes.fromhex("89 c3"))
        e.call_absolute(self.profile.address("ui.current_layer"))
        e.raw(bytes.fromhex("3b c3"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("vr.room_layer_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.call_absolute(self.ownership.query_va)
        e.raw(bytes.fromhex("83 f8 01"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        c.store(self._scratch, 32)
        e.push_imm32(c.base + self._scratch)
        e.call_absolute(self.protagonist.query_va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        c.absolute(b"\xa1", self.profile.address("engine.loop"))
        e.raw(bytes.fromhex("8b 80 44 04 00 00 8b 48 28"))
        c.state(b"\x89\x0d", self._manager)
        e.call_absolute(self.profile.site("vr.camera_controller_top").va)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        c.state(b"\xa3", self._controller)
        c.check(self._bridge, 0, "ready")
        e.push_imm32(c.base + self._dll)
        c.absolute(b"\xff\x15", self.profile.address("win32.GetModuleHandleA"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        e.push_imm32(c.base + self._export)
        e.raw(b"\x50")
        c.absolute(b"\xff\x15", self.profile.address("win32.GetProcAddress"))
        c.state(b"\xa3", self._bridge)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        e.label("ready")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        e.label("failed")
        e.raw(bytes.fromhex("31 c0 c3"))

    def _emit_focus(self, c: _ReturnCode) -> None:
        e = c.e
        # Shared focus gate. Panel snapshots retain actual focus metadata.
        for address in (self.panel.result_va, self.panel.completion_result_va):
            c.absolute(b"\x83\x3d", address)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "unfocused")
        c.absolute(b"\xf7\x05", self.panel.frame_va + 64)
        e.raw(struct.pack("<I", 1))
        e.jump_if(Condition.EQUAL, "unfocused")
        c.absolute(b"\xa1", self.panel.pointing_hand_va)
        e.raw(bytes.fromhex("83 f8 01"))
        e.jump_if(Condition.ABOVE, "unfocused")
        e.raw(bytes.fromhex("6b c0 30"))
        c.absolute(b"\x8d\x80", self.panel.frame_va + 68)
        e.raw(bytes.fromhex("f7 00 01 00 00 00"))
        e.jump_if(Condition.EQUAL, "unfocused")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        e.label("unfocused")
        e.raw(bytes.fromhex("31 c0 c3"))

    def _emit_solver(self, c: _ReturnCode) -> None:
        e = c.e
        e.push_imm32(c.base + self._destination)
        e.push_imm32(c.base + self._scratch + 16)
        e.push_imm32(self.scene.recenter_va - 4)
        c.state(b"\xff\x15", self._bridge)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "no_destination")
        # S_OK means a floor was found; S_FALSE/unavailable must never move.
        for axis in range(3):
            c.state(b"\xa1", self._destination + 4 * axis)
            e.raw(bytes.fromhex("25 ff ff ff 7f 3d 00 00 80 7f"))
            e.jump_if(Condition.ABOVE_OR_EQUAL, "no_destination")
            c.state(b"\xa1", self._destination + 4 * axis)
            c.state(b"\xa3", self._destination + 12 + 4 * axis)
        c.state(b"\xd9\x05", self._destination + 16)
        c.state(b"\xd8\x05", self._destination + 24)
        c.state(b"\xd9\x1d", self._destination + 16)
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        e.label("no_destination")
        e.raw(bytes.fromhex("31 c0 c3"))


@dataclass(frozen=True, slots=True)
class _ReturnCode:
    e: X86Emitter
    base: int

    def absolute(self, op: bytes, address: int) -> None:
        self.e.raw(op + struct.pack("<I", address))

    def state(self, op: bytes, offset: int) -> None:
        self.absolute(op, self.base + offset)

    def store(self, offset: int, value: int) -> None:
        self.state(b"\xc7\x05", offset)
        self.e.raw(struct.pack("<I", value))

    def check(self, offset: int, value: int, label: str, *, equal: bool = False) -> None:
        self.state(b"\x83\x3d", offset)
        self.e.raw(bytes((value,)))
        self.e.jump_if(Condition.EQUAL if equal else Condition.NOT_EQUAL, label)
