"""Verified original-engine stereo hooks, not yet exposed as a public patch plan."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, decode_rel32_branch
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_floor import VRFloorABI, VRFloorCompiler
from gk3hd.patch.definitions.vr_native_scene import (
    check_native_scene_types,
    emit_native_scene_guard,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


@dataclass(frozen=True, slots=True)
class VRSceneABI:
    """Render-thread controls and diagnostics for the private native scene bridge."""

    enabled_va: int
    recenter_va: int
    result_va: int
    submitted_frames_va: int
    eye_draws_va: int
    world_input_va: int
    query_slot_va: int
    target_va: int
    unwind_count_va: int
    ownership_query_slot_va: int
    frame_pending_va: int
    geometry_query_slot_va: int
    prewarm_owner_va: int | None
    prewarm_count_va: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class VRSceneCompiler:
    """Draw both tracked engine eyes while preserving native page ownership.

    Uses the renderer's versioned scene callback, not CPU image captures or
    synthesized eye poses. Each callback scopes camera/projection state, clears
    color/depth after BeginScene, and redraws world geometry without ticking.
    Optional eye mirroring retains verified page preparation but replaces the
    redundant center geometry on success. Hidden/failed scenes retain ordinary
    drawing, and all native camera/projection state is restored for picking.
    Installation/launch and interfaces are incomplete, so no public plan enables
    this compiler yet. World scale must be calibrated explicitly by its caller.
    """

    profile: BuildProfile
    units_per_meter: float
    enabled: bool = False
    deferred_frame: bool = False
    mirror_world: bool = False
    prewarm_scene: bool = False
    floor: VRFloorABI | None = None

    section_name: ClassVar[str] = ".gk3vr"
    section_size: ClassVar[int] = 0x2000
    world_input_size: ClassVar[int] = 180
    scene_size: ClassVar[int] = 256
    _magic: ClassVar[bytes] = b"GK3XR001"
    _code_offset: ClassVar[int] = 0x100
    _scene: ClassVar[int] = 0x1100
    _eye: ClassVar[int] = 0x1200
    _camera_saved: ClassVar[int] = 0x1300
    _projection_saved: ClassVar[int] = 0x1400
    _viewport: ClassVar[int] = 0x1520
    _rectangle: ClassVar[int] = 0x1530
    _renderer_name: ClassVar[int] = 0x1540
    _scene_export: ClassVar[int] = 0x1550
    _world_input: ClassVar[int] = 0x1580
    _target: ClassVar[int] = 0x16C0
    _enabled: ClassVar[int] = 0x0C
    _result: ClassVar[int] = 0x10
    _frames: ClassVar[int] = 0x14
    _eye_active: ClassVar[int] = 0x18
    _camera: ClassVar[int] = 0x1C
    _projection_active: ClassVar[int] = 0x20
    _cached: ClassVar[int] = 0x24
    _this: ClassVar[int] = 0x28
    _argument1: ClassVar[int] = 0x2C
    _argument2: ClassVar[int] = 0x30
    _bridge: ClassVar[int] = 0x34
    _resolved: ClassVar[int] = 0x38
    _clear_result: ClassVar[int] = 0x3C
    _eye_draws: ClassVar[int] = 0x40
    _flat_target: ClassVar[int] = 0x44
    _drawing: ClassVar[int] = 0x48
    _unwinds: ClassVar[int] = 0x4C
    _aborted: ClassVar[int] = 0x50
    _ownership_query: ClassVar[int] = 0x54
    _frame_pending: ClassVar[int] = 0x58
    _prewarm_owner: ClassVar[int] = 0x60
    _prewarm_count: ClassVar[int] = 0x64
    _prewarm_enabled: ClassVar[int] = 0x68
    _prewarm_active: ClassVar[int] = 0x6C
    _prewarm_projection: ClassVar[int] = 0x1800
    _geometry_anchors: ClassVar[tuple[str, ...]] = (
        "vr.geometry_segment",
        "vr.geometry_bsp",
        "vr.geometry_actor_enumerate",
        "vr.geometry_actor_segment",
        "vr.geometry_model_color_key",
        "vr.geometry_bsp_color_key",
        "vr.geometry_texture_color_key",
    )
    _anchors: ClassVar[tuple[str, ...]] = (
        "vr.camera_setup",
        "vr.camera_end",
        "vr.room_clear",
        "transition.scene_setup_anchor",
        "vr.presentation_mode",
        *_geometry_anchors,
    )

    def abi(self, image: PEFile) -> VRSceneABI:
        """Return controls after verifying the installed section's ABI identity."""
        section = image.get_section(self.section_name)
        if (
            section is None
            or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic
            or image.read_u32_va(image.rva_to_va(section.virtual_address) + self._scene)
            != self.scene_size
        ):
            msg = "VR scene section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        prewarm = image.read_u32_va(base + self._prewarm_enabled)
        if prewarm not in (0, 1):
            msg = "VR scene prewarm mode is invalid"
            raise PatchError(msg)
        return VRSceneABI(
            base + self._enabled,
            base + self._scene + 4,
            base + self._result,
            base + self._frames,
            base + self._eye_draws,
            base + self._world_input,
            base + self._scene + 240,
            base + self._target,
            base + self._unwinds,
            base + self._ownership_query,
            base + self._frame_pending,
            base + self._scene + 248,
            base + self._prewarm_owner if prewarm else None,
            base + self._prewarm_count if prewarm else None,
        )

    def _original_target(self, image: PEFile) -> int:
        site = self.profile.site("transition.seed_hook")
        actual = image.read_bytes(image.va_to_offset(site.va), len(site.original))
        if actual == site.original:
            return 0
        target = decode_rel32_branch(opcode=BranchOpcode.CALL, site_va=site.va, instruction=actual)
        if target == TransitionFrameCompiler(profile=self.profile).room_draw_entry(image):
            return target
        msg = "VR cannot compose an unknown room-draw hook"
        raise PatchError(msg)

    def precheck(self, image: PEFile) -> None:
        """Reject altered engine anchors before adding any code or redirects."""
        check_native_scene_types(image, self.profile)
        if not math.isfinite(self.units_per_meter) or self.units_per_meter <= 0:
            msg = "VR world scale must be finite and positive"
            raise PatchError(msg)
        try:
            native_scale = struct.unpack("<f", struct.pack("<f", self.units_per_meter))[0]
        except OverflowError as error:
            msg = "VR world scale is outside the native float range"
            raise PatchError(msg) from error
        if not native_scale:
            msg = "VR world scale underflows the native float range"
            raise PatchError(msg)
        if image.get_section(self.section_name) is not None:
            msg = "VR scene hooks are already installed"
            raise PatchError(msg)
        for name in self._anchors:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR precheck failed: unexpected {name} bytes"
                raise PatchError(msg)
        flat = self._original_target(image)
        if self.floor is not None:
            floor = VRFloorCompiler(profile=self.profile)
            floor.postcheck(image)
            if floor.abi(image) != self.floor:
                msg = "VR observer floor dependency changed"
                raise PatchError(msg)
        if self.mirror_world and not flat:
            msg = "VR eye mirroring requires verified native page preparation"
            raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Compose verified redirects and a bounded native-engine bridge."""
        self.precheck(image)
        flat = self._original_target(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        payload, labels = self._payload(base, flat)
        image.write_bytes(section.pointer_to_raw_data, payload)
        plan = ExecutableMutationPlan(owner="vr_scene")
        for name, label in (
            ("transition.seed_hook", "draw"),
            ("vr.camera_setup", "setup"),
            ("vr.camera_end", "end"),
            ("vr.room_clear", "clear"),
        ):
            site = self.profile.site(name)
            plan.branch(
                label=name,
                site_va=site.va,
                expected=image.read_bytes(image.va_to_offset(site.va), len(site.original)),
                target_va=labels[label],
                opcode=BranchOpcode.JUMP,
                size=len(site.original),
            )
        plan.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify code, redirects and untouched continuation anchors."""
        check_native_scene_types(image, self.profile)
        if self.floor is not None:
            floor = VRFloorCompiler(profile=self.profile)
            floor.postcheck(image)
            if floor.abi(image) != self.floor:
                msg = "VR observer floor dependency changed"
                raise PatchError(msg)
        self.abi(image)
        section = image.get_section(self.section_name)
        if section is None:
            msg = "VR section disappeared during verification"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        flat = image.read_u32_va(base + self._flat_target)
        if flat and flat != TransitionFrameCompiler(profile=self.profile).room_draw_entry(image):
            msg = "VR flat-frame dependency failed verification"
            raise PatchError(msg)
        expected, labels = self._payload(base, flat)
        if image.read_bytes(section.pointer_to_raw_data, self.section_size) != expected:
            msg = "VR scene payload failed verification"
            raise PatchError(msg)
        continuation = self.profile.site("transition.scene_setup_anchor")
        if (
            image.read_bytes(image.va_to_offset(continuation.va), len(continuation.original))
            != continuation.original
        ):
            msg = "VR room-draw continuation failed verification"
            raise PatchError(msg)
        for name, label in (
            ("transition.seed_hook", "draw"),
            ("vr.camera_setup", "setup"),
            ("vr.camera_end", "end"),
            ("vr.room_clear", "clear"),
        ):
            site = self.profile.site(name)
            actual = image.read_bytes(image.va_to_offset(site.va), len(site.original))
            target = decode_rel32_branch(
                opcode=BranchOpcode.JUMP, site_va=site.va, instruction=actual[:5]
            )
            if target != labels[label]:
                msg = f"VR redirect failed verification: {name}"
                raise PatchError(msg)
        for name in self._geometry_anchors:
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR geometry query changed: {name}"
                raise PatchError(msg)

    def _payload(self, base: int, flat: int) -> tuple[bytes, dict[str, int]]:
        e = X86Emitter(base_va=base + self._code_offset)
        p = self.profile
        renderer = p.address("vr.renderer_global")
        device = p.address("high_resolution_3d.render_wrapper_ptr")
        globals_va = p.address("vr.projection_globals")
        nesting = p.address("vr.projection_nesting")
        draw = p.site("transition.seed_hook")
        setup = p.site("vr.camera_setup")
        end = p.site("vr.camera_end")
        clear = p.site("vr.room_clear")

        def absolute(opcode: bytes, address: int) -> None:
            e.raw(opcode + struct.pack("<I", address))

        def state(opcode: bytes, offset: int) -> None:
            absolute(opcode, base + offset)

        def store(offset: int, value: int) -> None:
            state(b"\xc7\x05", offset)
            e.raw(struct.pack("<I", value))

        def copy(source: int, destination: int, words: int) -> None:
            absolute(b"\xbe", source)
            absolute(b"\xbf", destination)
            absolute(b"\xb9", words)
            e.raw(bytes.fromhex("fc f3 a5"))

        def original(label: str) -> None:
            state(b"\xff\x35", self._argument2)
            state(b"\xff\x35", self._argument1)
            state(b"\x8b\x0d", self._this)
            e.call(label)

        def register_unwind() -> None:
            e.raw(b"\x68")
            e.absolute_label("unwind")
            e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))

        def unregister_unwind() -> None:
            e.raw(bytes.fromhex("8b 14 24 64 89 15 00 00 00 00 83 c4 08"))

        e.label("draw")
        e.raw(bytes.fromhex("9c 60"))
        # A native redraw inside the renderer's callback belongs to this same
        # transaction. It must not replace the saved room/camera or start XR
        # again; retain the ordinary draw path for that nested call.
        state(b"\x83\x3d", self._drawing)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "flat")
        if self.deferred_frame:
            # Native page repair can redraw the room several times before the
            # completed-page presenter. Those maintenance draws retain the
            # ordinary page, not another XR transaction or a new input sample.
            # Keep the first world's picking snapshot until finalization.
            state(b"\x83\x3d", self._frame_pending)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "flat")
        # Never leave the previous world's ray valid in an unloaded room,
        # dormant flat mode, a hidden frame, or after a failed scene bridge.
        store(self._world_input + 4, 0)
        store(self._target + 4, 0xFFFFFFFF)
        store(self._target + 8, 0)
        state(b"\x83\x3d", self._enabled)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "flat")
        state(b"\x83\x3d", self._ownership_query)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "owned_world")
        e.raw(b"\x51")
        state(b"\xff\x15", self._ownership_query)
        e.raw(bytes.fromhex("59 a8 01"))
        e.jump_if(Condition.EQUAL, "flat")
        e.label("owned_world")
        absolute(b"\xa1", p.address("vr.room_global"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "flat")
        e.raw(bytes.fromhex("3b 48 50"))
        e.jump_if(Condition.NOT_EQUAL, "flat")
        e.raw(bytes.fromhex("61 9d 55 8b ec 53 56 57"))
        state(b"\x89\x0d", self._this)
        e.raw(bytes.fromhex("8b 45 08"))
        state(b"\xa3", self._argument1)
        e.raw(bytes.fromhex("8b 45 0c"))
        state(b"\xa3", self._argument2)
        e.raw(bytes.fromhex("8b 41 34"))
        state(b"\xa3", self._cached)
        store(self._drawing, 1)
        store(self._aborted, 0)
        store(self._result, 0x80004001)
        register_unwind()
        state(b"\x83\x3d", self._resolved)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "resolved")
        store(self._resolved, 1)
        state(b"\x68", self._renderer_name)
        absolute(b"\xff\x15", p.address("win32.GetModuleHandleA"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "disabled")
        state(b"\x68", self._scene_export)
        e.raw(b"\x50")
        absolute(b"\xff\x15", p.address("win32.GetProcAddress"))
        state(b"\xa3", self._bridge)
        e.label("resolved")
        state(b"\x83\x3d", self._bridge)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "disabled")
        absolute(b"\xa1", renderer)
        e.raw(bytes.fromhex("8b b0 c8 01 00 00"))
        state(b"\xbf", self._scene + 12)
        absolute(b"\xb9", 52)
        e.raw(bytes.fromhex("fc f3 a5"))
        for pointer, destination in (
            ("high_resolution_3d.display_width_ptr", self._scene + 220),
            ("high_resolution_3d.display_height_ptr", self._scene + 224),
        ):
            absolute(b"\xa1", p.address(pointer))
            e.raw(bytes.fromhex("8b 00"))
            state(b"\xa3", destination)
        if self.deferred_frame:
            state(b"\x83\x0d", self._scene + 4)
            e.raw(b"\x02")
            store(self._frame_pending, 1)
        if self.mirror_world:
            # Seed/own the native page before copying a completed eye over it.
            # Doing this after the mirror would replace new pixels with the
            # previous page. No camera tick or geometry draw occurs here.
            e.call("prepare_page")
            state(b"\x83\x0d", self._scene + 4)
            e.raw(b"\x04")
        if self.prewarm_scene:
            # Experimental draw-only resource preparation while the loading
            # helper still owns XR. No tick, XR pose sample or presentation.
            # Loading retirement invalidates this owner even if allocation
            # reuse gives the next room the same native scene address.
            state(b"\xa1", self._this)
            state(b"\x3b\x05", self._prewarm_owner)
            e.jump_if(Condition.EQUAL, "resources_ready")
            copy(globals_va, base + self._prewarm_projection, 71)
            store(self._prewarm_active, 1)
            original("draw_only")
            e.call("restore_prewarm")
            state(b"\x8b\x0d", self._this)
            state(b"\xa1", self._cached)
            e.raw(bytes.fromhex("89 41 34"))
            state(b"\x89\x0d", self._prewarm_owner)
            state(b"\xff\x05", self._prewarm_count)
            e.label("resources_ready")
        state(b"\x68", self._scene)
        absolute(b"\xa1", device)
        e.raw(bytes.fromhex("ff b0 e8 04 00 00"))
        absolute(b"\xff\x15", base + self._bridge)
        state(b"\xa3", self._result)
        store(self._scene + 4, self._scene_flags)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.SIGN, "disabled")
        e.jump_if(Condition.NOT_EQUAL, "restore")
        state(b"\xff\x05", self._frames)
        e.jump("restore")
        e.label("disabled")
        store(self._enabled, 0)
        e.label("restore")
        store(self._eye_active, 0)
        e.call("restore_projection")
        state(b"\x8b\x0d", self._this)
        state(b"\xa1", self._cached)
        e.raw(bytes.fromhex("89 41 34"))
        if self.mirror_world:
            state(b"\x83\x3d", self._result)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "draw_center")
            # The native cached center bitmap is no longer the visible page.
            # Force fresh geometry if a later frame needs ordinary fallback.
            e.raw(bytes.fromhex("c7 41 34 00 00 00 00 31 c0"))
            e.jump("center_done")
            e.label("draw_center")
        original("flat_draw")
        e.label("center_done")
        store(self._drawing, 0)
        unregister_unwind()
        e.raw(bytes.fromhex("5f 5e 5b c9 c2 08 00"))
        e.label("flat")
        e.raw(bytes.fromhex("61 9d"))
        e.jump("flat_draw")
        e.label("flat_draw")
        if flat:
            e.push_imm32(draw.va + len(draw.original))
            e.jump_absolute(flat)
        else:
            e.raw(draw.original)
            e.jump_absolute(draw.va + len(draw.original))
        e.label("draw_only")
        e.raw(draw.original)
        e.jump_absolute(draw.va + len(draw.original))

        e.label("eye_callback")
        e.raw(bytes.fromhex("55 8b ec 53 56 57 8b 75 10"))
        register_unwind()
        state(b"\xbf", self._eye)
        absolute(b"\xb9", 58)
        e.raw(bytes.fromhex("fc f3 a5"))
        store(self._eye_active, 1)
        store(self._clear_result, 0x80004005)
        state(b"\xff\x05", self._eye_draws)
        state(b"\x8b\x0d", self._this)
        e.raw(bytes.fromhex("c7 41 34 00 00 00 00"))
        original("draw_only")
        # An inner handler can recover yet bypass native EndScene. Reject the
        # incomplete eye instead of publishing it, and restore its CPU scope.
        state(b"\x83\x3d", self._projection_active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "eye_balanced")
        store(self._clear_result, 0x80004005)
        e.call("restore_projection")
        e.label("eye_balanced")
        store(self._eye_active, 0)
        state(b"\xa1", self._clear_result)
        unregister_unwind()
        e.raw(bytes.fromhex("5f 5e 5b c9 c2 0c 00"))

        e.label("setup")
        e.raw(bytes.fromhex("9c 60"))
        state(b"\x83\x3d", self._eye_active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "setup_original")
        absolute(b"\x83\x3d", nesting)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "setup_original")
        state(b"\x83\x3d", self._projection_active)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "setup_original")
        e.raw(bytes.fromhex("8b 81 c8 01 00 00"))
        state(b"\xa3", self._camera)
        e.raw(bytes.fromhex("89 c6"))
        state(b"\xbf", self._camera_saved)
        absolute(b"\xb9", 52)
        e.raw(bytes.fromhex("fc f3 a5"))
        copy(globals_va, base + self._projection_saved, 71)
        # Both snapshots are complete. Mark ownership before the first authored
        # write so even an interrupted camera copy can restore the original.
        store(self._projection_active, 1)
        state(b"\xa1", self._camera)
        e.raw(bytes.fromhex("8d 78 1c"))
        state(b"\xbe", self._eye + 0x1C)
        absolute(b"\xb9", 45)
        e.raw(bytes.fromhex("f3 a5"))
        e.label("setup_original")
        e.raw(bytes.fromhex("61 9d"))
        e.call("setup_original_entry")
        e.raw(bytes.fromhex("9c 60"))
        state(b"\x83\x3d", self._projection_active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "setup_done")
        copy(base + self._eye + 208, globals_va + 0xD8, 6)
        # Native setup also publishes the desktop framebuffer's clipping box.
        # Eye geometry has its own zero-origin target and must not be clipped
        # to that desktop box. These globals belong to the saved eye scope.
        for offset in (0x90, 0x94):
            absolute(b"\xc7\x05", globals_va + offset)
            e.raw(struct.pack("<I", 0))
        for source, destinations in (
            (self._eye + 0x58, (0x20, 0x98)),
            (self._eye + 0x5C, (0x24, 0x9C)),
        ):
            state(b"\xa1", source)
            for offset in destinations:
                absolute(b"\xa3", globals_va + offset)
        e.label("setup_done")
        e.raw(bytes.fromhex("61 9d c3"))
        e.label("setup_original_entry")
        e.raw(setup.original)
        e.jump_absolute(setup.va + len(setup.original))

        e.label("end")
        e.call("end_original_entry")
        e.raw(bytes.fromhex("9c 60"))
        absolute(b"\x83\x3d", nesting)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "end_done")
        e.call("restore_projection")
        e.label("end_done")
        e.raw(bytes.fromhex("61 9d c3"))
        e.label("end_original_entry")
        e.raw(end.original)
        e.jump_absolute(end.va + len(end.original))

        e.label("restore_projection")
        state(b"\x83\x3d", self._projection_active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "projection_restored")
        state(b"\xa1", self._camera)
        e.raw(bytes.fromhex("8d 78 1c"))
        state(b"\xbe", self._camera_saved + 0x1C)
        absolute(b"\xb9", 45)
        e.raw(bytes.fromhex("fc f3 a5"))
        copy(base + self._projection_saved, globals_va, 71)
        store(self._projection_active, 0)
        e.label("projection_restored")
        e.raw(b"\xc3")

        if self.prewarm_scene:
            e.label("restore_prewarm")
            state(b"\x83\x3d", self._prewarm_active)
            e.raw(b"\x00")
            e.jump_if(Condition.EQUAL, "prewarm_restored")
            copy(base + self._prewarm_projection, globals_va, 71)
            store(self._prewarm_active, 0)
            e.label("prewarm_restored")
            e.ret()

        # cdecl Windows exception handler. Search must remain side-effect free
        # so a handler inside the game/renderer may recover. On unwind, restore
        # only owned memory, call no engine/COM methods, and do not swallow the
        # fault or edit the OS-owned registration chain. Both scopes use this
        # handler, with idempotent cleanup and one count per aborted transaction.
        e.label("unwind")
        e.raw(bytes.fromhex("55 8b ec 53 56 57 8b 45 08 f7 40 04 06 00 00 00"))
        e.jump_if(Condition.EQUAL, "unwind_done")
        e.call("restore_projection")
        if self.prewarm_scene:
            e.call("restore_prewarm")
        state(b"\x8b\x0d", self._this)
        state(b"\xa1", self._cached)
        e.raw(bytes.fromhex("89 41 34"))
        for offset in (
            self._enabled,
            self._eye_active,
            self._drawing,
            self._frame_pending,
            self._world_input + 4,
        ):
            store(offset, 0)
        store(self._result, 0x80004005)
        store(self._clear_result, 0x80004005)
        store(self._target + 4, 0xFFFFFFFF)
        store(self._target + 8, 0)
        state(b"\x83\x3d", self._aborted)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "unwind_done")
        store(self._aborted, 1)
        state(b"\xff\x05", self._unwinds)
        e.label("unwind_done")
        e.raw(bytes.fromhex("5f 5e 5b c9 b8 01 00 00 00 c3"))

        e.label("clear")
        e.raw(bytes.fromhex("9c 60"))
        state(b"\x83\x3d", self._eye_active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "clear_done")
        for destination, source in (
            (self._rectangle + 8, self._eye + 0x58),
            (self._rectangle + 12, self._eye + 0x5C),
        ):
            state(b"\xa1", source)
            state(b"\xa3", destination)
        absolute(b"\xa1", device)
        e.raw(bytes.fromhex("8b 80 e8 04 00 00"))
        state(b"\x68", self._viewport)
        e.raw(bytes.fromhex("50 8b 10 ff 52 34"))
        state(b"\xa3", self._clear_result)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "clear_done")
        state(b"\xa1", self._viewport)
        e.raw(bytes.fromhex("6a 00 68 00 00 80 3f 6a 00 6a 03"))
        state(b"\x68", self._rectangle)
        e.raw(bytes.fromhex("6a 01 50 8b 10 ff 52 50"))
        state(b"\xa3", self._clear_result)
        state(b"\xa1", self._viewport)
        e.raw(bytes.fromhex("50 8b 10 ff 52 08"))
        e.label("clear_done")
        e.raw(bytes.fromhex("61 9d"))
        e.raw(clear.original)
        e.jump_absolute(clear.va + len(clear.original))

        # stdcall(context, from*, to*, hit*). Always query outwards from the
        # authored interior: native BSP intersections reject back faces. This
        # is a geometry query, not a screen pick or an action/noun filter.
        # No authored camera, walker mask or controller ownership is changed.
        e.label("geometry")
        # Stack-local enumeration context: renderer, from*, bounded endpoint,
        # hit*, result. Never temporarily alter visibility or object hit tests.
        e.raw(bytes.fromhex("55 8b ec 53 56 57 83 ec 1c"))
        for offset in (0x0C, 0x10, 0x14):
            e.raw(bytes((0x83, 0x7D, offset, 0)))
            e.jump_if(Condition.EQUAL, "geometry_unavailable")
        absolute(b"\xa1", p.address("vr.room_global"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "geometry_unavailable")
        emit_native_scene_guard(e, p, register="eax", rejected="geometry_unavailable")
        e.raw(bytes.fromhex("8b 40 50 85 c0"))
        e.jump_if(Condition.EQUAL, "geometry_unavailable")
        e.raw(bytes.fromhex("8b 58 2c 85 db"))
        e.jump_if(Condition.EQUAL, "geometry_unavailable")
        absolute(b"\x8b\x0d", renderer)
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "geometry_unavailable")
        e.raw(bytes.fromhex("89 4d d8 8b 45 0c 89 45 dc 8b 45 14 89 45 ec"))
        # Native renderer thiscall(handle, from*, to*, noun*, flags, hit*,
        # filter*, color*, auxiliary*, auxiliary*) preserves keyed holes.
        for _ in range(4):
            e.push_imm32(0)
        e.raw(bytes.fromhex("ff 75 14"))
        e.push_imm32(0)
        e.push_imm32(0)
        e.raw(bytes.fromhex("ff 75 10 ff 75 0c 53"))
        e.call_absolute(p.site("vr.geometry_segment").va)
        e.raw(bytes.fromhex("89 45 f0 8b 55 10 85 c0"))
        e.jump_if(Condition.EQUAL, "geometry_endpoint")
        e.raw(bytes.fromhex("8b 55 14"))
        e.label("geometry_endpoint")
        # The nearest BSP hit bounds the actor search. Each closer model hit
        # shortens this private endpoint, so enumeration order cannot reveal a
        # model behind a wall or replace a near hit with a farther one.
        e.raw(bytes.fromhex("8b 02 89 45 e0 8b 42 04 89 45 e4 8b 42 08 89 45 e8"))
        e.raw(bytes.fromhex("8d 45 d8 50 68"))
        e.absolute_label("geometry_actor")
        e.raw(bytes.fromhex("8b 4d d8"))
        e.call_absolute(p.site("vr.geometry_actor_enumerate").va)
        e.raw(bytes.fromhex("8b 45 f0"))
        e.jump("geometry_done")
        e.label("geometry_unavailable")
        e.raw(bytes.fromhex("b8 ff ff ff ff"))
        e.label("geometry_done")
        e.raw(bytes.fromhex("83 c4 1c 5f 5e 5b c9 c2 10 00"))

        # Native cdecl callback(handle, context). The engine enumerates current
        # renderer models with their complete generation-tagged handles. Its
        # actor segment entry checks visible meshes and their actual transformed
        # triangles, not the screen rectangle or selectable-object property.
        e.label("geometry_actor")
        e.raw(bytes.fromhex("55 8b ec 53 56 57 83 ec 08 8b 75 0c"))
        e.raw(bytes.fromhex("8b 7e 04 ff 76 14 ff 76 10 ff 76 0c ff 76 08"))
        e.raw(bytes.fromhex("ff 77 08 ff 77 04 ff 37 6a 01 8d 45 08 50 8d 45 f0 50"))
        e.raw(bytes.fromhex("8b 0e"))
        e.call_absolute(p.site("vr.geometry_actor_segment").va)
        e.raw(bytes.fromhex("83 7d f0 00"))
        e.jump_if(Condition.EQUAL, "geometry_actor_done")
        e.raw(bytes.fromhex("c7 46 18 01 00 00 00 8b 56 14"))
        e.raw(bytes.fromhex("8b 02 89 46 08 8b 42 04 89 46 0c 8b 42 08 89 46 10"))
        e.label("geometry_actor_done")
        e.raw(bytes.fromhex("b8 01 00 00 00 83 c4 08 5f 5e 5b c9 c3"))

        if self.mirror_world:
            e.label("prepare_page")
            transition = TransitionFrameCompiler(profile=self.profile)
            # Windowed primary dimensions describe the desktop, not the
            # retained game back image. Its complete GPU replacement needs
            # room ownership, but no fullscreen primary-to-back page seed.
            absolute(b"\xa1", p.address("vr.fullscreen_flag_ptr"))
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "prepare_flip_pages")
            e.raw(bytes.fromhex("80 38 00"))
            e.jump_if(Condition.NOT_EQUAL, "prepare_flip_pages")
            e.raw(
                transition.room_preparation_code(
                    wrapper_va=base + self._code_offset + e.offset,
                    draw_entry=flat,
                    seed_flip_pages=False,
                )
            )
            e.label("prepare_flip_pages")
            e.raw(
                transition.room_preparation_code(
                    wrapper_va=base + self._code_offset + e.offset,
                    draw_entry=flat,
                )
            )

        code = e.build(maximum_size=0x1000)
        labels = {name: address for name, _offset, address in e.listing()}
        payload = SegmentPayloadBuilder(
            owner="vr_scene", segment=self.section_name, size=self.section_size
        )
        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into("<I", header, self._enabled, self.enabled)
        struct.pack_into("<I", header, self._flat_target, flat)
        struct.pack_into("<I", header, self._prewarm_enabled, self.prewarm_scene)
        payload.place(label="state", offset=0, payload=bytes(header))
        payload.place(label="code", offset=self._code_offset, payload=code)
        scene = struct.pack("<2If", self.scene_size, self._scene_flags, self.units_per_meter)
        scene += bytes(208)
        scene += struct.pack("<5I", 0, 0, labels["eye_callback"], base, base + self._world_input)
        scene += struct.pack("<2I", 0, base + self._target)
        scene += struct.pack("<I", labels["geometry"])
        scene += struct.pack("<I", self.floor.observer_query_va if self.floor is not None else 0)
        payload.place(label="scene", offset=self._scene, payload=scene)
        payload.place(label="renderer name", offset=self._renderer_name, payload=b"ddraw.dll\0")
        payload.place(label="scene export", offset=self._scene_export, payload=b"Gk3hdXrSceneV1\0")
        payload.place(
            label="world input",
            offset=self._world_input,
            payload=struct.pack("<I", self.world_input_size),
        )
        payload.place(
            label="world target",
            offset=self._target,
            payload=struct.pack("<3I3f", 24, 0xFFFFFFFF, 0, 0, 0, 0),
        )
        return payload.build(), labels

    @property
    def _scene_flags(self) -> int:
        return (2 if self.deferred_frame else 0) | (4 if self.mirror_world else 0)
