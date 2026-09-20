"""Normalize manual keyboard camera motion at its native input boundary."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile, PatchSite


@dataclass(frozen=True, slots=True)
class KeyboardCameraMotionCompiler:
    """Make configured camera keys independent of cadence and resolution.

    Outcome:
        Pan, rotate, walk, fly, strafe, pitch, and level keys move the camera at
        one stable, controllable rate at 1024, HD, UHD, and different refresh
        rates. Brief taps remain precise instead of advancing a large fraction
        of the room.

    Before:
        ``UserSceneController`` synthesizes a fixed 12-pixel two-axis delta on
        every update and feeds it to the same function as physical mouse
        motion. No elapsed-time factor is applied, while rotation divides that
        delta by the live framebuffer dimensions. Keyboard speed therefore
        grows with frame cadence and changes with resolution.

    After:
        Keyboard deltas are scaled by elapsed milliseconds relative to a
        configurable reference update rate. Rotation uses the authored
        1024x768 dimensions; translational modes use only elapsed time. Long
        scheduling gaps are capped, so resuming or pressing a key after idle
        cannot cause a camera jump.

    Strategy:
        Redirect only the keyboard call into a small timing wrapper and mark
        that native call as keyboard-owned. A second bridge surrounds the
        existing integer-to-float conversion, applies the scoped factors, and
        immediately rejoins GK3's original camera-mode implementation. The
        bridge uses GK3's existing ``timeGetTime`` import and live display-size
        globals, adding no runtime library or presentation-backend dependency.

    Boundaries:
        Physical mouse deltas, key bindings, acceleration/smoothing history,
        collision, scripted/glide cameras, cutscenes, and camera-mode logic
        remain native. ``reference_updates_per_second`` is the patch's single
        speed parameter; 30 is a conservative period-appropriate default.
    """

    profile: BuildProfile
    reference_updates_per_second: float = 30.0

    id: ClassVar[str] = "fix_keyboard_camera_speed"
    section_name: ClassVar[str] = ".gkcam"
    _section_size: ClassVar[int] = 0x200
    _section_characteristics: ClassVar[int] = 0xE0000020
    _magic: ClassVar[bytes] = b"GK3CAM01"
    _layout_version: ClassVar[int] = 1

    _off_layout_version: ClassVar[int] = 0x08
    _off_last_tick: ClassVar[int] = 0x0C
    _off_delta_ms: ClassVar[int] = 0x10
    _off_keyboard_active: ClassVar[int] = 0x14
    _off_frame_factor: ClassVar[int] = 0x18
    _off_updates_per_ms: ClassVar[int] = 0x1C
    _off_inverse_reference_width: ClassVar[int] = 0x20
    _off_inverse_reference_height: ClassVar[int] = 0x24
    _off_first_delta_ms: ClassVar[int] = 0x28
    _off_max_delta_ms: ClassVar[int] = 0x2C
    _off_keyboard_wrapper: ClassVar[int] = 0x40
    _off_conversion_bridge: ClassVar[int] = 0x100

    _reference_width: ClassVar[float] = 1024.0
    _reference_height: ClassVar[float] = 768.0
    _maximum_reference_updates_per_second: ClassVar[float] = 240.0
    # A first tap receives one 60 Hz sample. Later gaps are capped at one 30 Hz
    # reference sample, preventing focus changes or stalls from accumulating.
    _first_delta_ms: ClassVar[int] = 17
    _max_delta_ms: ClassVar[int] = 34

    def __post_init__(self) -> None:
        """Reject speed parameters that cannot produce finite motion."""
        if not math.isfinite(self.reference_updates_per_second):
            msg = "keyboard camera reference rate must be finite"
            raise ValueError(msg)
        if not (
            1.0 <= self.reference_updates_per_second <= self._maximum_reference_updates_per_second
        ):
            msg = "keyboard camera reference rate must be between 1 and 240 updates/second"
            raise ValueError(msg)

    @property
    def _dispatch_site(self) -> PatchSite:
        return self.profile.site("camera.keyboard_motion_dispatch")

    @property
    def _conversion_site(self) -> PatchSite:
        return self.profile.site("camera.motion_float_conversion")

    def _build_keyboard_wrapper(self, *, section_va: int) -> bytes:
        """Timestamp one nonzero keyboard sample and call the native consumer."""
        last_tick_va = section_va + self._off_last_tick
        delta_ms_va = section_va + self._off_delta_ms
        active_va = section_va + self._off_keyboard_active
        first_delta_va = section_va + self._off_first_delta_ms
        max_delta_va = section_va + self._off_max_delta_ms

        code = X86Emitter(base_va=section_va + self._off_keyboard_wrapper)
        # WINMM calls may clobber EAX/ECX/EDX. EAX is dead at this native call
        # site, while ECX is UserSceneController's this pointer and EDX may be
        # live to its caller, so preserve the latter pair explicitly.
        code += b"\x51\x52"  # push ecx; push edx
        code += b"\xff\x15" + struct.pack("<I", self.profile.address("win32.timeGetTime"))
        code += b"\x8b\x15" + struct.pack("<I", last_tick_va)  # mov edx,[last_tick]
        code += b"\xa3" + struct.pack("<I", last_tick_va)  # mov [last_tick],eax
        code += b"\x85\xd2"  # test edx,edx
        code.jump_if(Condition.EQUAL, "first_sample")
        code += b"\x2b\xc2"  # sub eax,edx (wrap-safe unsigned milliseconds)
        code += b"\x3b\x05" + struct.pack("<I", max_delta_va)
        code.jump_if(Condition.BELOW_OR_EQUAL, "have_delta")
        code += b"\xa1" + struct.pack("<I", max_delta_va)
        code.jump("have_delta")
        code.label("first_sample")
        code += b"\xa1" + struct.pack("<I", first_delta_va)
        code.label("have_delta")
        code += b"\xa3" + struct.pack("<I", delta_ms_va)
        code += b"\x5a\x59"  # pop edx; pop ecx

        # Copy the three thiscall arguments. The native RET 0Ch consumes these
        # copies; this wrapper then consumes the originals from its caller.
        code += b"\xc7\x05" + struct.pack("<I", active_va) + struct.pack("<I", 1)
        code += b"\xff\x74\x24\x0c" * 3
        code.call_absolute(self.profile.address("camera.apply_motion"))
        code += b"\xc7\x05" + struct.pack("<I", active_va) + bytes(4)
        code += b"\xc2\x0c\x00"  # ret 0Ch
        return code.build(maximum_size=self._off_conversion_bridge - self._off_keyboard_wrapper)

    def _build_conversion_bridge(self, *, section_va: int) -> bytes:
        """Scale only the keyboard-owned visit to the shared motion function."""
        active_va = section_va + self._off_keyboard_active
        delta_ms_va = section_va + self._off_delta_ms
        factor_va = section_va + self._off_frame_factor
        updates_per_ms_va = section_va + self._off_updates_per_ms
        inverse_width_va = section_va + self._off_inverse_reference_width
        inverse_height_va = section_va + self._off_inverse_reference_height

        code = X86Emitter(base_va=section_va + self._off_conversion_bridge)
        # Reproduce the displaced native conversion and configured mode-key
        # lookup exactly before considering the scoped keyboard marker.
        code += bytes.fromhex("db 45 0c ff b0 44 01 00 00 d9 5d 10")
        code += b"\x83\x3d" + struct.pack("<I", active_va) + b"\x00"
        code.jump_if(Condition.EQUAL, "native_continue")

        code += b"\x52"  # preserve edx around live-dimension pointer reads
        code += b"\xdb\x05" + struct.pack("<I", delta_ms_va)  # fild dword [delta_ms]
        code += b"\xd8\x0d" + struct.pack("<I", updates_per_ms_va)  # fmul rate/1000
        code += b"\xd9\x1d" + struct.pack("<I", factor_va)  # fstp [frame_factor]

        # Horizontal rotation modes (0, 1, and 2) are normalized by GK3's live
        # width later in the native function. Compensate back to 1024 here;
        # mode 3 is strafe and mode 4 is retained defensively as translation.
        code += bytes.fromhex("d9 45 08")  # fld dword [ebp+08h]
        code += b"\xd8\x0d" + struct.pack("<I", factor_va)
        code += bytes.fromhex("83 ff 03")  # cmp edi,3
        code.jump_if(Condition.EQUAL, "horizontal_done")
        code += bytes.fromhex("83 ff 04")  # cmp edi,4
        code.jump_if(Condition.EQUAL, "horizontal_done")
        code += b"\x8b\x15" + struct.pack(
            "<I", self.profile.address("high_resolution_3d.display_width_ptr")
        )
        code += bytes.fromhex("da 0a")  # fimul dword [edx]
        code += b"\xd8\x0d" + struct.pack("<I", inverse_width_va)
        code.label("horizontal_done")
        code += bytes.fromhex("d9 5d 08")  # fstp dword [ebp+08h]

        # Only fly/pitch mode 2 takes the native live-height division. Walking,
        # levelling, and other direct translations must not acquire a display
        # scale merely because the framebuffer is larger.
        code += bytes.fromhex("d9 45 10")  # fld dword [ebp+10h]
        code += b"\xd8\x0d" + struct.pack("<I", factor_va)
        code += bytes.fromhex("83 ff 02")  # cmp edi,2
        code.jump_if(Condition.NOT_EQUAL, "vertical_done")
        code += b"\x8b\x15" + struct.pack(
            "<I", self.profile.address("high_resolution_3d.display_height_ptr")
        )
        code += bytes.fromhex("da 0a")  # fimul dword [edx]
        code += b"\xd8\x0d" + struct.pack("<I", inverse_height_va)
        code.label("vertical_done")
        code += bytes.fromhex("d9 5d 10 5a")  # fstp [ebp+10h]; pop edx

        code.label("native_continue")
        code.jump_absolute(self.profile.address("camera.motion_float_conversion_continue"))
        return code.build(maximum_size=self._section_size - self._off_conversion_bridge)

    def _immutable_regions(self, *, section_va: int) -> tuple[tuple[str, int, bytes], ...]:
        """Return constants and code that runtime timing state may not change."""
        return (
            ("magic", 0, self._magic),
            ("layout version", self._off_layout_version, struct.pack("<I", self._layout_version)),
            (
                "updates per millisecond",
                self._off_updates_per_ms,
                struct.pack("<f", self.reference_updates_per_second / 1000.0),
            ),
            (
                "inverse reference width",
                self._off_inverse_reference_width,
                struct.pack("<f", 1.0 / self._reference_width),
            ),
            (
                "inverse reference height",
                self._off_inverse_reference_height,
                struct.pack("<f", 1.0 / self._reference_height),
            ),
            ("first delta", self._off_first_delta_ms, struct.pack("<I", self._first_delta_ms)),
            ("maximum delta", self._off_max_delta_ms, struct.pack("<I", self._max_delta_ms)),
            (
                "keyboard wrapper",
                self._off_keyboard_wrapper,
                self._build_keyboard_wrapper(section_va=section_va),
            ),
            (
                "conversion bridge",
                self._off_conversion_bridge,
                self._build_conversion_bridge(section_va=section_va),
            ),
        )

    def _build_payload(self, *, section_va: int) -> bytes:
        section = SegmentPayloadBuilder(
            owner=self.id,
            segment=self.section_name,
            size=self._section_size,
        )
        for label, offset, payload in self._immutable_regions(section_va=section_va):
            section.place(label=label, offset=offset, payload=payload)
        # These cells are intentionally mutable and begin at zero. Reserving
        # the complete interval proves that no immutable payload overlaps it.
        section.reserve(label="runtime timing state", offset=self._off_last_tick, size=0x10)
        return section.build()

    def _mutation_plan(self, *, section_va: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner=self.id)
        plan.branch(
            label="keyboard camera dispatch",
            opcode=BranchOpcode.CALL,
            site_va=self._dispatch_site.va,
            expected=self._dispatch_site.original,
            target_va=section_va + self._off_keyboard_wrapper,
            size=len(self._dispatch_site.original),
        )
        plan.branch(
            label="camera float conversion",
            opcode=BranchOpcode.JUMP,
            site_va=self._conversion_site.va,
            expected=self._conversion_site.original,
            target_va=section_va + self._off_conversion_bridge,
            size=len(self._conversion_site.original),
        )
        return plan

    def _check_site(self, pe: PEFile, site: PatchSite, *, installed: bool) -> None:
        """Validate a hook's immutable context and selected source state."""
        before_va = site.va - len(site.context_before)
        after_va = site.va + len(site.original)
        if (
            pe.read_bytes(pe.va_to_offset(before_va), len(site.context_before))
            != site.context_before
        ):
            msg = f"{self.id} unexpected context before {site.symbol}"
            raise PatchError(msg)
        if pe.read_bytes(pe.va_to_offset(after_va), len(site.context_after)) != site.context_after:
            msg = f"{self.id} unexpected context after {site.symbol}"
            raise PatchError(msg)
        if not installed:
            actual = pe.read_bytes(pe.va_to_offset(site.va), len(site.original))
            if actual != site.original:
                msg = f"{self.id} unexpected source bytes at {site.symbol}"
                raise PatchError(msg)

    def precheck(self, pe: PEFile) -> None:
        """Require pristine hook sites and their full semantic contexts."""
        if pe.get_section(self.section_name) is not None:
            msg = f"{self.id} requires a pristine executable"
            raise PatchError(msg)
        self._check_site(pe, self._dispatch_site, installed=False)
        self._check_site(pe, self._conversion_site, installed=False)

    def apply(self, pe: PEFile) -> None:
        """Install the timing section and both keyboard-scoped redirects."""
        if pe.get_section(self.section_name) is not None:
            msg = f"{self.id} section already exists"
            raise PatchError(msg)
        section = pe.add_section(
            self.section_name,
            bytes(self._section_size),
            self._section_characteristics,
        )
        if section.size_of_raw_data < self._section_size:
            msg = f"{self.id} apply failed: section too small"
            raise PatchError(msg)
        pe.set_section_characteristics(self.section_name, self._section_characteristics)
        section_va = pe.rva_to_va(section.virtual_address)
        pe.write_bytes(section.pointer_to_raw_data, self._build_payload(section_va=section_va))
        self._mutation_plan(section_va=section_va).apply(pe)

    def postcheck(self, pe: PEFile) -> None:
        """Verify immutable payload, semantic anchors, and both redirects."""
        self._check_site(pe, self._dispatch_site, installed=True)
        self._check_site(pe, self._conversion_site, installed=True)
        section = pe.get_section(self.section_name)
        if section is None or section.size_of_raw_data < self._section_size:
            msg = f"{self.id} postcheck failed: section missing or too small"
            raise PatchError(msg)
        if section.characteristics != self._section_characteristics:
            msg = f"{self.id} postcheck failed: section is not executable and writable"
            raise PatchError(msg)
        section_va = pe.rva_to_va(section.virtual_address)
        for label, offset, payload in self._immutable_regions(section_va=section_va):
            if pe.read_bytes(section.pointer_to_raw_data + offset, len(payload)) != payload:
                msg = f"{self.id} postcheck failed: {label} mismatch"
                raise PatchError(msg)
        self._mutation_plan(section_va=section_va).verify(pe)
