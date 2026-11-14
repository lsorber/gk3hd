"""Game-thread ownership for the shared VR game menu and native dialogs."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_native_scene import (
    check_native_scene_types,
    emit_native_scene_guard,
)
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_return import VRReturnCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_panel import VRPanelABI
    from gk3hd.patch.definitions.vr_return import VRReturnABI


@dataclass(frozen=True, slots=True)
class VRGameMenuABI:
    """Dormant activation and current game-thread menu diagnostics."""

    enabled_va: int
    epoch_va: int
    owner_va: int
    accepted_va: int
    rejected_va: int
    bridge_result_va: int
    request_va: int
    presenter_va: int
    shortcut_filter_slot_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRGameMenuCompiler:
    """Consume Menu before ordinary input and delegate original layer changes.

    Install after the completed panel producer, before input/text consumers.
    Native Pause keeps the previous layer on its original stack. Resume hides
    only that verified current Pause instance. Save/Load leave Pause before
    opening the original dialog. Renderer-owned Controls and Quit confirmation
    emit only epoch-tagged intent; no native pointers cross the bridge.

    All callbacks run on the game's rendering thread. Reentrant painting only
    runs the existing flat composition, never another XR input transaction.
    Focus/tracking loss retires pending intent and rearms shortcuts after release.
    Real focus/tracking metadata is preserved: modal ownership masks buttons,
    pointing and movement rather than pretending the runtime lost focus.
    """

    profile: BuildProfile
    panel: VRPanelABI
    expected_presenter_va: int
    observer_return: VRReturnABI | None = None

    section_name: ClassVar[str] = ".gk3gu"
    section_size: ClassVar[int] = 0x3000
    _magic: ClassVar[bytes] = b"GK3XRG01"
    _enabled: ClassVar[int] = 0x0C
    _owner: ClassVar[int] = 0x10
    _epoch: ClassVar[int] = 0x14
    _busy: ClassVar[int] = 0x18
    _held: ClassVar[int] = 0x1C
    _blocked: ClassVar[int] = 0x20
    _bridge: ClassVar[int] = 0x24
    _bridge_result: ClassVar[int] = 0x28
    _current: ClassVar[int] = 0x2C
    _prior: ClassVar[int] = 0x30
    _hand: ClassVar[int] = 0x34
    _allowed: ClassVar[int] = 0x38
    _command: ClassVar[int] = 0x3C
    _shortcut_filter: ClassVar[int] = 0x48  # Optional EDX filter before native Menu.
    _accepted: ClassVar[int] = 0x40
    _rejected: ClassVar[int] = 0x44
    _request: ClassVar[int] = 0x50  # 20-byte GameMenuRequest, no native pointers.
    _code: ClassVar[int] = 0x1000
    _unwind: ClassVar[int] = 0x2800
    _renderer_name: ClassVar[int] = 0x2900
    _export_name: ClassVar[int] = 0x2920
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.layer_show",
        "vr.layer_hide",
        "vr.pause_factory",
    )

    def abi(self, image: PEFile) -> VRGameMenuABI:
        """Read the versioned menu section without trusting runtime state."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR game menu section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRGameMenuABI(
            *(
                base + offset
                for offset in (
                    self._enabled,
                    self._epoch,
                    self._owner,
                    self._accepted,
                    self._rejected,
                    self._bridge_result,
                    self._request,
                    self._code,
                    self._shortcut_filter,
                )
            )
        )

    def _check(self, image: PEFile) -> None:
        if VRPanelCompiler(profile=self.profile).abi(image) != self.panel:
            msg = "VR game menu panel boundary changed"
            raise PatchError(msg)
        check_native_scene_types(image, self.profile)
        if self.observer_return is not None and VRReturnCompiler.abi(image) != self.observer_return:
            msg = "VR game menu Return dependency changed"
            raise PatchError(msg)
        for name in self._anchors:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR game menu native anchor changed: {name}"
                raise PatchError(msg)

    def _link(self, image: PEFile, target: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_game_menu")
        plan.pointer(
            label="game menu presenter",
            slot_va=TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va,
            expected=self.expected_presenter_va,
            target_va=target,
        )
        return plan

    def apply(self, image: PEFile) -> None:
        """Install a dormant menu consumer before ordinary controller input."""
        if image.get_section(self.section_name) is not None:
            msg = "VR game menu is already installed"
            raise PatchError(msg)
        self._check(image)
        slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
        if not self.expected_presenter_va or image.read_u32_va(slot) != self.expected_presenter_va:
            msg = "VR game menu presenter changed"
            raise PatchError(msg)
        image.va_to_offset(self.expected_presenter_va)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._payload(base))
        self._link(image, base + self._code).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Recheck all native dependencies, bytes and the input-chain link."""
        self._check(image)
        base = self.abi(image).enabled_va - self._enabled
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(base):
            msg = "VR game menu payload failed verification"
            raise PatchError(msg)
        self._link(image, base + self._code).verify(image)

    def _payload(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._code)
        c = _MenuCode(e, base, self.profile, self.panel)
        self._presenter(c)
        self._probe(c)
        self._shortcuts(c)
        self._capabilities(c)
        self._configuration(c)
        self._dispatch(c)
        self._mask(c)
        payload = SegmentPayloadBuilder(
            owner="vr_game_menu", segment=self.section_name, size=self.section_size
        )
        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into("<I", header, self._blocked, 4)
        struct.pack_into("<I", header, self._bridge_result, 0x80004001)
        struct.pack_into("<I", header, self._request, 20)
        payload.place(label="menu state", offset=0, payload=bytes(header))
        payload.place(
            label="menu consumer",
            offset=self._code,
            payload=e.build(maximum_size=self._unwind - self._code),
        )
        payload.place(label="menu unwind", offset=self._unwind, payload=self._build_unwind(base))
        payload.place(label="menu renderer", offset=self._renderer_name, payload=b"ddraw.dll\0")
        payload.place(label="menu bridge", offset=self._export_name, payload=b"Gk3hdXrGameMenuV1\0")
        return payload.build()

    def _presenter(self, c: _MenuCode) -> None:
        e = c.e
        e.raw(bytes.fromhex("9c 60"))
        c.check(self._busy, 0, "nested")
        e.push_imm32(c.base + self._unwind)
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
        c.store(self._busy, 1)
        e.call_absolute(self.expected_presenter_va)
        c.check(self._enabled, 1, "disabled")
        if self.observer_return is not None:
            e.call_absolute(self.observer_return.tick_va)
        e.call("ready")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "withdraw")
        e.call("resolve")
        c.check(self._bridge, 0, "resolved")
        e.jump("withdraw")
        e.label("resolved")
        c.current()
        c.state(b"\xa3", self._current)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "withdraw")
        c.check(self._owner, 0, "bridge_checked")
        e.call("configure")  # Confirm that the renderer accepts retirement before opening Pause.
        c.check(self._bridge_result, 0, "withdraw")
        e.label("bridge_checked")
        e.call("shortcuts")
        e.call("configure")
        e.call("dispatch")
        e.call("mask_owned")
        e.jump("done")
        e.label("disabled")
        c.store(self._owner, 0)
        e.label("withdraw")
        if self.observer_return is not None:
            e.call_absolute(self.observer_return.cancel_va)
        c.store(self._held, 0)
        c.store(self._blocked, 4)
        c.store(self._request + 4, 0)
        e.call("bridge_call")
        e.label("done")
        c.store(self._busy, 0)
        e.raw(bytes.fromhex("8b 04 24 64 a3 00 00 00 00 83 c4 08"))
        e.jump("return")
        e.label("nested")
        e.call_absolute(self.panel.composition_presenter_va)
        e.label("return")
        e.raw(bytes.fromhex("61 9d c3"))

    def _probe(self, c: _MenuCode) -> None:
        e = c.e
        e.label("ready")
        for address, value in (
            (self.panel.enabled_va, 1),
            (self.panel.result_va, 0),
            (self.panel.completion_result_va, 0),
        ):
            c.absolute(b"\x83\x3d", address)
            e.raw(bytes((value,)))
            e.jump_if(Condition.NOT_EQUAL, "not_ready")
        c.absolute(b"\x83\x3d", self.panel.submitted_frames_va)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "not_ready")
        c.absolute(b"\xf7\x05", self.panel.frame_va + 64)
        e.raw(struct.pack("<I", 1))
        e.jump_if(Condition.EQUAL, "not_ready")
        c.absolute(b"\xa1", self.panel.frame_va + 68)
        c.absolute(b"\x0b\x05", self.panel.frame_va + 116)
        e.raw(bytes.fromhex("a8 01"))
        e.jump_if(Condition.EQUAL, "not_ready")
        c.absolute(b"\xa1", self.profile.address("engine.loop"))
        for instruction in (bytes.fromhex("8b 80 44 04 00 00"), bytes.fromhex("8b 40 48")):
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "not_ready")
            e.raw(instruction)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "not_ready")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        e.label("not_ready")
        e.raw(bytes.fromhex("31 c0 c3"))

    def _shortcuts(self, c: _MenuCode) -> None:
        e = c.e
        e.label("shortcuts")
        c.absolute(b"\xa1", self.panel.frame_va + 180)
        e.raw(bytes.fromhex("83 e0 04"))
        c.state(b"\x21\x05", self._blocked)
        e.raw(bytes.fromhex("8b d0"))
        c.state(b"\x8b\x0d", self._held)
        e.raw(bytes.fromhex("f7 d1 21 ca"))
        c.absolute(b"\x0b\x15", self.panel.frame_va + 184)
        c.state(b"\xa3", self._held)
        c.state(b"\x8b\x0d", self._blocked)
        e.raw(bytes.fromhex("f7 d1 21 ca 83 e2 04"))
        c.check(self._shortcut_filter, 0, "shortcut_filtered", equal=True)
        c.state(b"\xff\x15", self._shortcut_filter)
        e.label("shortcut_filtered")
        # Consume Menu before the ordinary right-click shortcut route.
        for offset in (180, 184):
            c.absolute(b"\x83\x25", self.panel.frame_va + offset)
            e.raw(b"\xfb")
        c.state(b"\xa1", self._current)
        e.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("pause.vtable")))
        e.jump_if(Condition.EQUAL, "adopt_pause")
        c.store(self._owner, 0)
        e.raw(bytes.fromhex("85 d2"))
        e.jump_if(Condition.EQUAL, "shortcut_return")
        c.absolute(b"\xa1", self.profile.address("vr.room_global"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "shortcut_return")
        emit_native_scene_guard(e, self.profile, register="eax", rejected="shortcut_return")
        c.state(b"\xa1", self._current)
        e.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("movies.layer_vtable")))
        e.jump_if(Condition.EQUAL, "shortcut_return")
        c.state(b"\xa3", self._prior)
        e.call("capabilities")
        c.layer(13, show=True)
        c.current()
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "shortcut_return")
        e.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("pause.vtable")))
        e.jump_if(Condition.NOT_EQUAL, "shortcut_return")
        e.label("adopt_pause")
        c.state(b"\x3b\x05", self._owner)
        e.jump_if(Condition.EQUAL, "same_menu_owner")
        c.state(b"\xa3", self._owner)
        c.bump_epoch(self._epoch)
        e.label("same_menu_owner")
        c.absolute(b"\xa1", self.panel.pointing_hand_va)
        c.state(b"\x3b\x05", self._hand)
        e.jump_if(Condition.EQUAL, "shortcut_return")
        c.state(b"\xa3", self._hand)
        c.bump_epoch(self._epoch)
        e.label("shortcut_return")
        e.raw(b"\xc3")

    def _capabilities(self, c: _MenuCode) -> None:
        e = c.e
        e.label("capabilities")
        c.store(self._allowed, 8)  # Load may abandon the scene; Save must not capture an action.
        c.state(b"\xa1", self._current)
        e.raw(bytes.fromhex("8b 50 4c 8b 48 50 81 f9 00 01 00 00"))
        e.jump_if(Condition.ABOVE, "capability_return")
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "save_allowed")
        e.raw(bytes.fromhex("85 d2"))
        e.jump_if(Condition.EQUAL, "capability_return")
        e.label("capability_child")
        e.raw(bytes.fromhex("8b 02 85 c0"))
        e.jump_if(Condition.EQUAL, "capability_next")
        for offset in (0x18, 0x19):
            e.raw(bytes((0x80, 0x78, offset, 0)))
            e.jump_if(Condition.EQUAL, "capability_next")
        e.raw(b"\x81\x38" + struct.pack("<I", self.profile.address("vr.action_skip_vtable")))
        e.jump_if(Condition.EQUAL, "capability_return")
        e.label("capability_next")
        e.raw(bytes.fromhex("83 c2 04 49"))
        e.jump_if(Condition.NOT_EQUAL, "capability_child")
        e.label("save_allowed")
        c.store(self._allowed, 12)
        e.label("capability_return")
        if self.observer_return is not None:
            c.state(b"\xff\x35", self._current)
            e.call_absolute(self.observer_return.available_va)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "return_capability_done")
            c.state(b"\x83\x0d", self._allowed)
            e.raw(b"\x40")
            e.label("return_capability_done")
        e.raw(b"\xc3")

    def _configuration(self, c: _MenuCode) -> None:
        e = c.e
        e.label("resolve")
        c.check(self._bridge, 0, "resolve_return")
        e.push_imm32(c.base + self._renderer_name)
        c.absolute(b"\xff\x15", self.profile.address("win32.GetModuleHandleA"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "resolve_return")
        e.push_imm32(c.base + self._export_name)
        e.raw(b"\x50")
        c.absolute(b"\xff\x15", self.profile.address("win32.GetProcAddress"))
        c.state(b"\xa3", self._bridge)
        e.label("resolve_return")
        e.raw(b"\xc3")
        e.label("configure")
        c.store(self._request + 4, 0)
        c.store(self._request + 8, 0)
        c.check(self._owner, 0, "bridge_call", equal=True)
        c.state(b"\xa1", self._epoch)
        c.state(b"\xa3", self._request + 4)
        c.state(b"\xa1", self._allowed)
        c.state(b"\xa3", self._request + 8)
        e.label("bridge_call")
        c.store(self._bridge_result, 0x80004001)
        for offset in (12, 16):
            c.store(self._request + offset, 0)
        c.check(self._bridge, 0, "bridge_return", equal=True)
        c.absolute(b"\xa1", self.profile.address("high_resolution_3d.render_wrapper_ptr"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "bridge_return")
        e.raw(bytes.fromhex("8b 80 e8 04 00 00 85 c0"))
        e.jump_if(Condition.EQUAL, "bridge_return")
        e.push_imm32(c.base + self._request)
        e.raw(b"\x50")
        c.state(b"\xff\x15", self._bridge)
        c.state(b"\xa3", self._bridge_result)
        e.label("bridge_return")
        e.raw(b"\xc3")

    def _dispatch(self, c: _MenuCode) -> None:
        e = c.e
        e.label("dispatch")
        c.check(self._bridge_result, 0, "action_return")
        c.state(b"\xa1", self._request + 16)
        c.store(self._request + 16, 0)  # Retire before any callback can redraw or unwind.
        c.state(b"\xa3", self._command)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "action_return")
        c.check(self._owner, 0, "reject", equal=True)
        c.state(b"\xa1", self._request + 12)
        c.state(b"\x3b\x05", self._epoch)
        e.jump_if(Condition.NOT_EQUAL, "reject")
        c.current()
        c.state(b"\x3b\x05", self._owner)
        e.jump_if(Condition.NOT_EQUAL, "reject")
        for command in (1, 7):
            c.check(self._command, command, "accepted", equal=True)
        commands = (2, 3, 6) if self.observer_return is not None else (2, 3)
        for command in commands:
            c.check(self._command, command, f"action_{command}", equal=True)
        e.jump("reject")
        for command in commands:
            e.label(f"action_{command}")
            c.state(b"\xf7\x05", self._allowed)
            e.raw(struct.pack("<I", 1 << command))
            e.jump_if(Condition.EQUAL, "reject")
            e.jump("accepted")
        e.label("accepted")
        c.state(b"\xff\x05", self._accepted)
        c.store(self._owner, 0)
        c.check(self._command, 7, "quit", equal=True)
        c.layer(13, show=False)
        for command, layer in ((2, 14), (3, 9)):
            c.check(self._command, command, f"next_{command}")
            c.layer(layer, show=True)
            e.label(f"next_{command}")
        if self.observer_return is not None:
            c.check(self._command, 6, "return_requested")
            c.state(b"\xff\x35", self._prior)
            e.call_absolute(self.observer_return.request_va)
            e.label("return_requested")
        e.jump("action_retire")
        e.label("quit")
        e.push_imm32(0)
        c.absolute(b"\xff\x15", self.profile.address("win32.PostQuitMessage"))
        e.label("action_retire")
        e.call("mask_input")
        e.call("configure")
        e.jump("action_return")
        e.label("reject")
        c.state(b"\xff\x05", self._rejected)
        e.label("action_return")
        e.raw(b"\xc3")

    def _mask(self, c: _MenuCode) -> None:
        e = c.e
        e.label("mask_owned")
        c.check(self._bridge_result, 0, "mask_return")
        c.check(self._owner, 0, "mask_return", equal=True)
        e.label("mask_input")
        # Do not change real InputFocused/AimValid metadata. The menu owns
        # interaction; head tracking, physical-key cleanup and diagnostics stay real.
        for offset in (72, 76, 108, 112, 120, 124, 156, 160, 164, 180, 184):
            c.absolute(b"\xc7\x05", self.panel.frame_va + offset)
            e.raw(bytes(4))
        e.label("mask_return")
        e.raw(b"\xc3")

    def _build_unwind(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._unwind)
        e.raw(bytes.fromhex("8b 44 24 04 f7 40 04 66 00 00 00"))
        e.jump_if(Condition.EQUAL, "return")
        for offset, value in (
            (self._busy, 0),
            (self._held, 0),
            (self._blocked, 4),
            (self._owner, 0),
            (self._request + 4, 0),
            (self._request + 16, 0),
        ):
            e.raw(b"\xc7\x05" + struct.pack("<II", base + offset, value))
        if self.observer_return is not None:
            e.call_absolute(self.observer_return.cancel_va)
        e.raw(b"\xff\x05" + struct.pack("<I", base + self._epoch))
        e.label("return")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        return e.build()


@dataclass(frozen=True, slots=True)
class _MenuCode:
    e: X86Emitter
    base: int
    profile: BuildProfile
    panel: VRPanelABI

    def absolute(self, opcode: bytes, address: int) -> None:
        self.e.raw(opcode + struct.pack("<I", address))

    def state(self, opcode: bytes, offset: int) -> None:
        self.absolute(opcode, self.base + offset)

    def store(self, offset: int, value: int) -> None:
        self.state(b"\xc7\x05", offset)
        self.e.raw(struct.pack("<I", value))

    def check(self, offset: int, value: int, label: str, *, equal: bool = False) -> None:
        self.state(b"\x83\x3d", offset)
        self.e.raw(bytes((value,)))
        self.e.jump_if(Condition.EQUAL if equal else Condition.NOT_EQUAL, label)

    def current(self) -> None:
        self.e.call_absolute(self.profile.address("ui.current_layer"))

    def layer(self, index: int, *, show: bool) -> None:
        self.absolute(b"\xa1", self.profile.address("engine.loop"))
        self.e.raw(bytes.fromhex("8b 80 44 04 00 00 8b 48 48"))
        if show:
            self.e.push_imm32(1)
        self.e.push_imm32(index)
        self.e.call_absolute(self.profile.site("vr.layer_show" if show else "vr.layer_hide").va)

    def bump_epoch(self, offset: int) -> None:
        self.state(b"\xff\x05", offset)
        self.state(b"\x83\x3d", offset)
        self.e.raw(b"\x00\x75\x06")
        self.state(b"\xff\x05", offset)
