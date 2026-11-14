"""Dormant native room-status sources with exact lifetime and fade ownership."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, encode_rel32_branch
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.compiler import Runtime2DCompiler
from gk3hd.patch.definitions.runtime2d.system.menus import MenuFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.room_status import RoomStatusFeatureCompiler
from gk3hd.patch.definitions.vr_hud import (
    HUD_BACKGROUND_OPACITY,
    HUD_BUSY,
    HUD_CAPTURED_OWNER,
    HUD_GLYPH_OPACITY,
    HUD_OWNER,
    HUD_READY,
    HUD_STATE_SIZE,
    build_hud_glyph_fill,
    build_hud_text_scope,
    build_hud_text_unwind,
)
from gk3hd.patch.definitions.vr_hud_reuse import (
    REUSE_EXPORT,
    REUSE_STATE_SIZE,
    build_hud_reuse_probe,
)
from gk3hd.patch.definitions.vr_menu import (
    build_menu_cache_blt_result,
    build_menu_cache_prepare,
    build_menu_cache_release,
    build_menu_cache_unwind,
    build_menu_cache_validate,
    build_menu_destination_scope,
    menu_destination_state,
)
from gk3hd.patch.definitions.vr_menu_compiler import VRMenuCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.system.room_status import NativeRoomStatusABI

_I386_MACHINE = 0x14C
_NEAR_EDGE_COUNT = 2


@dataclass(frozen=True, slots=True)
class HudSourceABI:
    """Independent keyed destination and its scoped native text state."""

    cache_va: int
    state_va: int
    validate_va: int


@dataclass(frozen=True, slots=True)
class VRHudABI:
    """Private current-page HUD append callback, dormant until enabled."""

    enabled_va: int
    query_va: int
    world_enabled_va: int
    glyph: HudSourceABI
    backing: HudSourceABI
    destroyed_va: int
    stereo_only_va: int
    finish_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRHudCompiler:
    """Capture original opaque glyph/backing pixels, compose authored opacity.

    Install after Runtime2D/deferred world and optional menus, before panels.
    Ordinary native Draw runs exactly once by default. An explicit stereo-only
    contract may defer that page work until the finalizer decides it is needed.
    Two independent capture-only scopes
    cannot write to the desktop. The current RoomLayer child, native page,
    dimensions, successful transfers and unchanged text fields must all agree
    before publication. Destruction/modal/disabled paths withdraw ownership.
    No retained pointer alone authorizes reading or publishing an object.
    This compiler is not installed by the public patch catalog.
    """

    profile: BuildProfile
    world_enabled_va: int

    section_name: ClassVar[str] = ".gk3vh"
    section_size: ClassVar[int] = 0x8000
    _magic: ClassVar[bytes] = b"GK3XRH02"
    _enabled: ClassVar[int] = 0x0C
    _world: ClassVar[int] = 0x10
    _count_before: ClassVar[int] = 0x14
    _destroyed: ClassVar[int] = 0x18
    # Explicit output contract, off for desktop/PC-VR. This is not readiness.
    _stereo_only: ClassVar[int] = 0x1C
    _deferred_owner: ClassVar[int] = 0x20
    _deferred_bitmap: ClassVar[int] = 0x24
    _deferred_generation: ClassVar[int] = 0x28
    _deferred_resource: ClassVar[int] = 0x2C
    _deferred_wrapper: ClassVar[int] = 0x30
    _deferred_surface: ClassVar[int] = 0x34
    _deferred_count: ClassVar[int] = 0x38
    _repaired_count: ClassVar[int] = 0x3C
    _discarded_count: ClassVar[int] = 0x40
    _deferred_damage: ClassVar[int] = 0x100
    _deferred_rect: ClassVar[int] = 0x110
    _batch_renderer: ClassVar[int] = 0x120
    _batch_export: ClassVar[int] = 0x130
    _reuse_export: ClassVar[int] = 0x150
    _reuse_state: ClassVar[int] = 0x400
    # Query/probe update live state on every frame. Keep their instructions
    # off the header's mutable page to avoid translator invalidation.
    _query: ClassVar[int] = 0x7000
    _probe: ClassVar[int] = 0x7C00
    _caches: ClassVar[tuple[int, int]] = (0x1000, 0x1500)
    _states: ClassVar[tuple[int, int]] = (0x1A00, 0x1A80)
    _rect: ClassVar[int] = 0x1B00
    _draw: ClassVar[int] = 0x2000
    _destructor: ClassVar[int] = 0x2400
    _withdraw: ClassVar[int] = 0x2600
    _finish: ClassVar[int] = 0x2800
    _batch: ClassVar[int] = 0x2C00
    _glyph_fill: ClassVar[int] = 0x2E00
    _helpers: ClassVar[tuple[int, int]] = (0x3000, 0x5000)

    def abi(self, image: PEFile) -> VRHudABI:
        """Read the versioned private boundary, without runtime-memory inference."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR HUD section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        sources = tuple(
            HudSourceABI(base + cache, base + state, base + helper + 0x1A00)
            for cache, state, helper in zip(self._caches, self._states, self._helpers, strict=True)
        )
        return VRHudABI(
            base + self._enabled,
            base + self._query,
            image.read_u32_va(base + self._world),
            sources[0],
            sources[1],
            base + self._destroyed,
            base + self._stereo_only,
            base + self._finish,
        )

    def native_image(self, image: PEFile) -> PEFile:
        """Restore only verified HUD bindings in a clone for composed checks."""
        native = image.clone()
        hooks = RoomStatusFeatureCompiler.native_hooks_abi(image, self.profile)
        base = self.abi(image).enabled_va - self._enabled
        self._links(base, hooks).verify(image)
        native.write_u32_va(hooks.vtable_va + 0xA0, hooks.draw_va)
        native.write_u32_va(hooks.vtable_va, hooks.destructor_va)
        site = self.profile.site("room_text.fill_call")
        native.write_bytes(native.va_to_offset(site.va), self._native_fill_call(hooks))
        return native

    def _dependencies(self, image: PEFile) -> NativeRoomStatusABI:
        scene = VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image)
        characteristics = struct.unpack("<H", image.read_bytes(image.optional_offset + 70, 2))[0]
        load_config = image.read_bytes(image.optional_offset + 96 + 10 * 8, 8)
        if (
            scene.enabled_va != self.world_enabled_va
            or image.read_u32_va(scene.recenter_va) & 2 == 0
            or image.machine != _I386_MACHINE
            or characteristics & 0x400
            or any(load_config)
        ):
            msg = "VR HUD requires a verified deferred world and supported exception metadata"
            raise PatchError(msg)
        return RoomStatusFeatureCompiler.native_hooks_abi(image, self.profile)

    def _verify_native(self, image: PEFile) -> None:
        if image.get_section(VRMenuCompiler.section_name) is not None:
            VRMenuCompiler(profile=self.profile, world_enabled_va=self.world_enabled_va).postcheck(
                image
            )
        else:
            native = image.clone()
            menu = MenuFeatureCompiler.native_hooks_abi(native, self.profile)
            transition = TransitionFrameCompiler.runtime_abi(native)
            native.write_u32_va(transition.pre_flip_presenter_slot_va, menu.frame_presenter_va)
            Runtime2DCompiler(profile=self.profile).postcheck(native)

    def _native_fill_call(self, hooks: NativeRoomStatusABI) -> bytes:
        return encode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=self.profile.site("room_text.fill_call").va,
            target_va=hooks.fill_va,
        )

    def _links(self, base: int, hooks: NativeRoomStatusABI) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_hud")
        for label, slot, expected, target in (
            ("status draw", hooks.vtable_va + 0xA0, hooks.draw_va, base + VRHudCompiler._draw),
            (
                "text destructor",
                hooks.vtable_va,
                hooks.destructor_va,
                base + VRHudCompiler._destructor,
            ),
        ):
            plan.pointer(label=label, slot_va=slot, expected=expected, target_va=target)
        plan.branch(
            label="isolated glyph backing fill",
            opcode=BranchOpcode.CALL,
            site_va=self.profile.site("room_text.fill_call").va,
            expected=self._native_fill_call(hooks),
            target_va=base + self._glyph_fill,
            size=5,
        )
        return plan

    def apply(self, image: PEFile) -> None:
        """Install dormant capture/lifetime hooks only after full verification."""
        if image.get_section(self.section_name) is not None:
            msg = "VR HUD hooks are already installed"
            raise PatchError(msg)
        hooks = self._dependencies(image)
        if (
            image.read_u32_va(hooks.vtable_va + 0xA0) != hooks.draw_va
            or image.read_u32_va(hooks.vtable_va) != hooks.destructor_va
        ):
            msg = "VR HUD native binding changed"
            raise PatchError(msg)
        self._verify_native(image)
        preview = image.clone()
        section = preview.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = preview.rva_to_va(section.virtual_address)
        payload = self._payload(base, image, hooks)
        section = image.add_section(self.section_name, payload, 0xE0000060)
        if image.rva_to_va(section.virtual_address) != base:
            msg = "VR HUD section placement changed"
            raise PatchError(msg)
        self._links(base, hooks).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Rebuild all dormant bytes and verify composed native dependencies."""
        hooks = self._dependencies(image)
        base = self.abi(image).enabled_va - self._enabled
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(
            base, image, hooks
        ):
            msg = "VR HUD payload failed verification"
            raise PatchError(msg)
        self._verify_native(self.native_image(image))

    def _payload(self, base: int, image: PEFile, hooks: NativeRoomStatusABI) -> bytes:
        payload = SegmentPayloadBuilder(
            owner="vr_hud", segment=self.section_name, size=self.section_size
        )
        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into("<I", header, self._world, self.world_enabled_va)
        payload.place(label="state", offset=0, payload=bytes(header))
        payload.place(
            label="owned fallback damage",
            offset=self._deferred_damage,
            payload=struct.pack(
                "<4I", 0, base + self._deferred_rect, base + self._deferred_rect + 16, 0
            )
            + bytes(16),
        )
        payload.place(label="batch renderer", offset=self._batch_renderer, payload=b"ddraw.dll\0")
        payload.place(
            label="batch export", offset=self._batch_export, payload=b"Gk3hdXrGlyphBatchV1\0"
        )
        payload.place(label="reuse export", offset=self._reuse_export, payload=REUSE_EXPORT)
        payload.reserve(
            label="reuse key and result", offset=self._reuse_state, size=REUSE_STATE_SIZE
        )
        for label, start, end, data in (
            ("query", self._query, self._probe, self._build_query(base)),
            ("live status", self._probe, self.section_size, self._build_probe(base)),
            ("draw", self._draw, self._destructor, self._build_draw(base, hooks, image)),
            ("destructor", self._destructor, self._withdraw, self._build_destructor(base, hooks)),
            ("withdraw", self._withdraw, self._finish, self._build_withdraw(base)),
            ("finish", self._finish, self._batch, self._build_finish(base, hooks, image)),
            ("glyph batch", self._batch, self._glyph_fill, self._build_batch(base)),
            (
                "isolated glyph backing fill",
                self._glyph_fill,
                self._helpers[0],
                build_hud_glyph_fill(
                    wrapper_va=base + self._glyph_fill,
                    fill_va=hooks.fill_va,
                    stereo_only_va=base + self._stereo_only,
                    glyph_busy_va=base + self._states[0] + HUD_BUSY,
                ),
            ),
        ):
            payload.place(label=label, offset=start, payload=data, limit=end)
        payload.reserve(label="physical rectangle", offset=self._rect, size=16)
        generation = TransitionFrameCompiler.runtime_abi(image).successful_flip_count_va
        p = self.profile
        glyph_reuse = base + self._helpers[0] + 0x1C00
        payload.place(
            label="glyph reuse probe",
            offset=glyph_reuse - base,
            limit=self._helpers[1],
            payload=build_hud_reuse_probe(
                wrapper_va=glyph_reuse,
                state_va=base + self._reuse_state,
                cache_va=base + self._caches[0],
                stereo_only_va=base + self._stereo_only,
                class_vtable=hooks.vtable_va,
                display_va=p.address("display.dimensions"),
                manager_va=p.address("resource.manager"),
                readable_iat_va=p.address("win32.IsBadReadPtr"),
                module_iat_va=p.address("win32.GetModuleHandleA"),
                proc_iat_va=p.address("win32.GetProcAddress"),
                renderer_name_va=base + self._batch_renderer,
                export_name_va=base + self._reuse_export,
            ),
        )
        for index, (cache, state, helper) in enumerate(
            zip(self._caches, self._states, self._helpers, strict=True)
        ):
            c, s, h = base + cache, base + state, base + helper
            payload.place(label=f"cache {index}", offset=cache, payload=menu_destination_state(c))
            payload.reserve(label=f"text state {index}", offset=state, size=HUD_STATE_SIZE)
            regions = (
                (
                    0,
                    0x800,
                    build_menu_destination_scope(
                        wrapper_va=h,
                        state_va=c,
                        target_va=h + 0x1400,
                        class_vtable=hooks.vtable_va,
                        toolbar=False,
                        resolve_resource_va=p.address("bitmap.resolve_resource"),
                        resource_manager_va=p.address("resource.manager"),
                        back_surface_va=p.address("transition.back_surface_ptr"),
                        directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                        readable_iat_va=p.address("win32.IsBadReadPtr"),
                        prepare_va=h + 0x800,
                        blt_va=h + 0x1100,
                        blt_fast_va=h + 0x1200,
                        generation_va=generation,
                        unwind_va=h + 0x1300,
                        capture_only=True,
                        batch_va=base + self._batch if index == 0 else None,
                        capture_ready_va=s + HUD_READY if index == 0 else None,
                    ),
                ),
                (
                    0x800,
                    0x1000,
                    build_menu_cache_prepare(
                        wrapper_va=h + 0x800,
                        state_va=c,
                        release_va=h + 0x1000,
                        directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                        source_key=1,
                        reuse_va=glyph_reuse if index == 0 else None,
                    ),
                ),
                (0x1000, 0x1100, build_menu_cache_release(wrapper_va=h + 0x1000, state_va=c)),
                (
                    0x1100,
                    0x1200,
                    build_menu_cache_blt_result(wrapper_va=h + 0x1100, state_va=c, fast=False),
                ),
                (
                    0x1200,
                    0x1300,
                    build_menu_cache_blt_result(wrapper_va=h + 0x1200, state_va=c, fast=True),
                ),
                (
                    0x1300,
                    0x1400,
                    build_menu_cache_unwind(wrapper_va=h + 0x1300, state_va=c, qualified=True),
                ),
                (
                    0x1400,
                    0x1800,
                    build_hud_text_scope(
                        wrapper_va=h + 0x1400,
                        state_va=s,
                        target_va=hooks.draw_va,
                        class_vtable=hooks.vtable_va,
                        capture_active_va=c + 20,
                        unwind_va=h + 0x1800,
                        backing=index == 1,
                        font_scope_va=hooks.present_depth_va,
                        reuse_state_va=base + self._reuse_state if index == 0 else None,
                    ),
                ),
                (
                    0x1800,
                    0x1A00,
                    build_hud_text_unwind(
                        wrapper_va=h + 0x1800, state_va=s, font_scope_va=hooks.present_depth_va
                    ),
                ),
                (
                    0x1A00,
                    0x1C00,
                    build_menu_cache_validate(
                        wrapper_va=h + 0x1A00,
                        state_va=c,
                        release_va=h + 0x1000,
                        class_vtable=hooks.vtable_va,
                        directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                        dimensions_va=p.address("display.dimensions"),
                        generation_va=generation,
                        readable_iat_va=p.address("win32.IsBadReadPtr"),
                    ),
                ),
            )
            for start, end, data in regions:
                payload.place(
                    label=f"source {index} helper {start:x}",
                    offset=helper + start,
                    payload=data,
                    limit=helper + end,
                )
        return payload.build()

    def _build_batch(self, base: int) -> bytes:
        """Complete the glyph transfer before the existing readiness check."""
        e = X86Emitter(base_va=base + self._batch)
        e.raw(bytes.fromhex("9c 60"))
        e.raw(b"\x83\x3d" + struct.pack("<I", base + self._stereo_only) + b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "native")
        e.push_imm32(base + self._batch_renderer)
        e.raw(b"\xff\x15" + struct.pack("<I", self.profile.address("win32.GetModuleHandleA")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "native")
        e.push_imm32(base + self._batch_export)
        e.raw(b"\x50\xff\x15" + struct.pack("<I", self.profile.address("win32.GetProcAddress")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "native")
        e.push_imm32(base + self._caches[0] + 20)
        e.raw(bytes.fromhex("ff 74 24 20"))  # Original EAX is the operation.
        e.raw(b"\xff\x35" + struct.pack("<I", base + self._caches[0] + 4))
        e.raw(bytes.fromhex("ff d0 85 c0 0f 99 c0 0f b6 c0 89 44 24 1c 61 9d c3"))
        e.label("native")
        e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00 61 9d c3"))
        return e.build()

    def _build_probe(self, base: int) -> bytes:
        """Find the unique live room status, independent of sibling order.

        Native toolbars can be inserted before the status TextBox. Prove its
        membership in the complete bounded live vector, not a retained address
        or a fixed index. Ambiguous/unreadable children fail closed.
        """
        e = X86Emitter(base_va=base + self._probe)
        e.raw(bytes.fromhex("9c 60"))
        e.call_absolute(self.profile.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("8b f0 6a 54 56"))
        e.raw(b"\xff\x15" + struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("transition.room_layer_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "absent")
        e.raw(bytes.fromhex("8b 7e 50 85 ff"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("81 ff 00 01 00 00"))
        e.jump_if(Condition.ABOVE, "unknown")
        e.raw(bytes.fromhex("8b 5e 4c 85 db"))
        e.jump_if(Condition.EQUAL, "unknown")
        # Check the whole pointer span before reading any child. Count is at
        # most 256, so the byte-length multiplication cannot overflow.
        e.raw(bytes.fromhex("8d 04 bd 00 00 00 00 50 53"))
        e.raw(b"\xff\x15" + struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(bytes.fromhex("31 f6"))
        e.label("child")
        e.raw(bytes.fromhex("8b 2b 85 ed"))
        e.jump_if(Condition.EQUAL, "unknown")
        e.raw(bytes.fromhex("6a 04 55"))
        e.raw(b"\xff\x15" + struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(b"\x81\x7d\x00" + struct.pack("<I", self.profile.address("room_text.vtable")))
        e.jump_if(Condition.NOT_EQUAL, "next_child")
        e.raw(bytes.fromhex("85 f6"))
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(bytes.fromhex("68 8c 00 00 00 55"))
        e.raw(b"\xff\x15" + struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(bytes.fromhex("8b f5"))
        e.label("next_child")
        e.raw(bytes.fromhex("83 c3 04 4f"))
        e.jump_if(Condition.NOT_EQUAL, "child")
        e.raw(bytes.fromhex("85 f6"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("80 7e 18 00"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("89 74 24 1c"))
        e.jump("return")
        e.label("absent")
        e.raw(bytes.fromhex("c7 44 24 1c 00 00 00 00"))
        e.jump("return")
        e.label("unknown")
        e.raw(bytes.fromhex("c7 44 24 1c ff ff ff ff"))
        e.label("return")
        e.raw(bytes.fromhex("61 9d c3"))
        return e.build()

    def _build_draw(self, base: int, hooks: NativeRoomStatusABI, image: PEFile) -> bytes:
        e = X86Emitter(base_va=base + self._draw)
        scene = VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image)
        generation = TransitionFrameCompiler.runtime_abi(image).successful_flip_count_va
        # [PUSHAD, flags, result, this, native-done, return, bitmap, damage].
        # No caller-owned damage pointer survives this synchronous Draw.
        e.raw(bytes.fromhex("6a 00 51 50 9c 60"))

        def word(opcode: bytes, offset: int, suffix: bytes = b"") -> None:
            e.raw(opcode + struct.pack("<I", base + offset) + suffix)

        def result() -> None:
            e.raw(bytes.fromhex("89 44 24 1c 89 44 24 24 89 54 24 14 9c 58 89 44 24 20"))

        def ordinary() -> None:
            e.raw(bytes.fromhex("8b 4c 24 28 8b 44 24 1c 8b 54 24 14 ff 74 24 20 9d"))
            e.raw(bytes.fromhex("ff 74 24 38 ff 74 24 38"))
            e.call_absolute(hooks.draw_va)
            result()
            e.raw(bytes.fromhex("c7 44 24 2c 01 00 00 00 8b 4c 24 28"))

        # A second Draw cannot overwrite an earlier deferred call silently.
        word(b"\x83\x3d", self._deferred_owner, b"\x00")
        e.jump_if(Condition.EQUAL, "eligibility")
        e.raw(bytes.fromhex("6a 01"))
        e.call_absolute(base + self._finish)
        e.label("eligibility")
        for address, value in (
            (base + self._stereo_only, 1),
            (base + self._enabled, 1),
            (self.world_enabled_va, 1),
            (scene.frame_pending_va, 1),
            (scene.result_va, 0),
        ):
            e.raw(b"\x83\x3d" + struct.pack("<I", address) + bytes((value,)))
            e.jump_if(Condition.NOT_EQUAL, "ordinary_first")
        # Only an independently classified free world can defer its page.
        e.raw(b"\x83\x3d" + struct.pack("<I", scene.ownership_query_slot_va) + b"\x00")
        e.jump_if(Condition.EQUAL, "ordinary_first")
        e.raw(b"\xff\x15" + struct.pack("<I", scene.ownership_query_slot_va))
        e.raw(bytes.fromhex("83 f8 01"))
        e.jump_if(Condition.EQUAL, "capture_checks")
        e.label("ordinary_first")
        ordinary()
        e.label("capture_checks")
        for address in (base + self._enabled, self.world_enabled_va):
            e.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "done")
        e.call_absolute(base + self._probe)
        e.raw(bytes.fromhex("3b c1"))
        e.jump_if(Condition.NOT_EQUAL, "done")
        for cache, state in zip(self._caches, self._states, strict=True):
            for address in (base + cache + 20, base + state + HUD_BUSY):
                e.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x00")
                e.jump_if(Condition.NOT_EQUAL, "done")
        for cache, state in zip(self._caches, self._states, strict=True):
            for address, value in (
                (base + cache, 1),
                (base + state, 1),
                (base + state + HUD_READY, 0),
            ):
                e.raw(b"\xc7\x05" + struct.pack("<II", address, value))
            e.raw(b"\x89\x0d" + struct.pack("<I", base + state + HUD_OWNER))
        e.raw(bytes.fromhex("ff 74 24 38 ff 74 24 38"))
        e.call_absolute(base + self._helpers[0])
        # In the capture-first case retain the actual glyph Draw return state.
        e.raw(bytes.fromhex("9c 83 7c 24 30 00"))
        e.jump_if(Condition.NOT_EQUAL, "glyph_result_native")
        e.raw(b"\x9d")
        result()
        e.jump("glyph_result_saved")
        e.label("glyph_result_native")
        e.raw(b"\x9d")
        e.label("glyph_result_saved")
        # Zero backing requires neither an allocation nor a second traversal.
        e.raw(bytes.fromhex("83 b9 88 00 00 00 00"))
        e.jump_if(Condition.EQUAL, "captured")
        e.raw(bytes.fromhex("ff 74 24 38 ff 74 24 38"))
        e.call_absolute(base + self._helpers[1])
        e.label("captured")
        e.raw(bytes.fromhex("83 7c 24 2c 00"))
        e.jump_if(Condition.NOT_EQUAL, "return")
        # Current source validation, not yesterday's enabled/ready bit.
        for index, state in enumerate(self._states):
            if index:
                e.raw(bytes.fromhex("83 b9 88 00 00 00 00"))
                e.jump_if(Condition.EQUAL, "defer")
            word(b"\x83\x3d", state + HUD_READY, b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "native_fallback")
            word(b"\x3b\x0d", state + HUD_CAPTURED_OWNER)
            e.jump_if(Condition.NOT_EQUAL, "native_fallback")
            e.call_absolute(base + self._helpers[index] + 0x1A00)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "native_fallback")
        e.label("defer")
        word(b"\xa1", self._caches[0] + 28)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "native_fallback")
        e.raw(bytes.fromhex("6a 50 50"))
        e.raw(b"\xff\x15" + struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "native_fallback")
        e.raw(bytes.fromhex("8b 4c 24 28"))
        word(b"\x89\x0d", self._deferred_owner)
        e.raw(bytes.fromhex("8b 44 24 34"))
        word(b"\xa3", self._deferred_bitmap)
        e.raw(b"\xa1" + struct.pack("<I", generation))
        word(b"\xa3", self._deferred_generation)
        word(b"\xa1", self._caches[0] + 24)
        word(b"\xa3", self._deferred_resource)
        word(b"\xa1", self._caches[0] + 28)
        word(b"\xa3", self._deferred_wrapper)
        e.raw(bytes.fromhex("8b 40 2c"))
        word(b"\xa3", self._deferred_surface)
        for source, destination in ((8, 8), (12, 12)):
            word(b"\xa1", self._caches[0] + source)
            word(b"\xa3", self._deferred_rect + destination)
        word(b"\xff\x05", self._deferred_count)
        e.jump("return")
        e.label("done")
        e.raw(bytes.fromhex("83 7c 24 2c 00"))
        e.jump_if(Condition.NOT_EQUAL, "return")
        e.label("native_fallback")
        ordinary()
        e.label("return")
        e.raw(bytes.fromhex("61 9d 58 59 8d 64 24 04 c2 08 00"))
        return e.build()

    def _build_finish(self, base: int, hooks: NativeRoomStatusABI, image: PEFile) -> bytes:
        """Finish this page once: discard unused native output or repair it.

        stdcall(bool native_required). Full owned damage avoids retaining a
        caller's temporary region/vector after its Draw returns. Only the same
        live status and successful-Flip generation may be repaired. The panel
        must call this before consuming an opaque page, and on every exit.
        """
        e = X86Emitter(base_va=base + self._finish)
        generation = TransitionFrameCompiler.runtime_abi(image).successful_flip_count_va
        e.raw(bytes.fromhex("9c 60"))
        e.raw(b"\x8b\x1d" + struct.pack("<I", base + self._deferred_owner))
        # Retire before callbacks/native code so recursion cannot replay twice.
        e.raw(b"\xc7\x05" + struct.pack("<I", base + self._deferred_owner) + bytes(4))
        e.raw(bytes.fromhex("85 db"))
        e.jump_if(Condition.EQUAL, "done")
        e.raw(bytes.fromhex("83 7c 24 28 01"))
        e.jump_if(Condition.EQUAL, "repair")
        e.raw(b"\xff\x05" + struct.pack("<I", base + self._discarded_count))
        e.jump("done")
        e.label("repair")
        e.raw(b"\xa1" + struct.pack("<I", generation))
        e.raw(b"\x3b\x05" + struct.pack("<I", base + self._deferred_generation))
        e.jump_if(Condition.NOT_EQUAL, "done")
        e.call_absolute(base + self._probe)
        e.raw(bytes.fromhex("3b c3"))
        e.jump_if(Condition.NOT_EQUAL, "done")
        # Re-resolve the bitmap handle. Neither a retained resource pointer
        # nor an unchanged Flip count proves that its page still exists.
        p = self.profile
        e.raw(b"\x8b\x0d" + struct.pack("<I", p.address("resource.manager")))
        e.raw(bytes.fromhex("85 c9"))
        e.jump_if(Condition.EQUAL, "done")
        e.raw(bytes.fromhex("68 24 01 00 00 51"))
        e.raw(b"\xff\x15" + struct.pack("<I", p.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "done")
        e.raw(b"\x8b\x0d" + struct.pack("<I", p.address("resource.manager")))
        e.raw(bytes.fromhex("83 b9 20 01 00 00 00"))
        e.jump_if(Condition.EQUAL, "done")
        e.raw(b"\xff\x35" + struct.pack("<I", base + self._deferred_bitmap))
        e.call_absolute(p.address("bitmap.resolve_resource"))
        e.raw(b"\x3b\x05" + struct.pack("<I", base + self._deferred_resource))
        e.jump_if(Condition.NOT_EQUAL, "done")
        e.raw(bytes.fromhex("6a 34 50"))
        e.raw(b"\xff\x15" + struct.pack("<I", p.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "done")
        e.raw(b"\xa1" + struct.pack("<I", base + self._deferred_resource))
        e.raw(bytes.fromhex("8b 70 30"))
        e.raw(b"\x3b\x35" + struct.pack("<I", base + self._deferred_wrapper))
        e.jump_if(Condition.NOT_EQUAL, "done")
        e.raw(bytes.fromhex("6a 50 56"))
        e.raw(b"\xff\x15" + struct.pack("<I", p.address("win32.IsBadReadPtr")))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "done")
        e.raw(bytes.fromhex("8b 46 2c"))
        for address in (base + self._deferred_surface, p.address("transition.back_surface_ptr")):
            e.raw(b"\x3b\x05" + struct.pack("<I", address))
            e.jump_if(Condition.NOT_EQUAL, "done")
        for dimension, field in ((8, 0x38), (12, 0x3C)):
            e.raw(b"\x8b\x46" + bytes((field,)))
            e.raw(b"\x3b\x05" + struct.pack("<I", base + self._deferred_rect + dimension))
            e.jump_if(Condition.NOT_EQUAL, "done")
        e.raw(b"\x68" + struct.pack("<I", base + self._deferred_damage))
        e.raw(b"\xff\x35" + struct.pack("<I", base + self._deferred_bitmap))
        e.raw(bytes.fromhex("8b cb"))
        e.raw(b"\xff\x05" + struct.pack("<I", base + self._repaired_count))
        e.call_absolute(hooks.draw_va)
        e.label("done")
        e.raw(bytes.fromhex("61 9d c2 04 00"))
        return e.build()

    def _build_withdraw(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._withdraw)
        e.raw(bytes.fromhex("9c 60"))
        e.raw(b"\xc7\x05" + struct.pack("<I", base + self._deferred_owner) + bytes(4))
        for cache, state in zip(self._caches, self._states, strict=True):
            for address in (base + cache + 20, base + state + HUD_BUSY):
                e.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x00")
                e.jump_if(Condition.NOT_EQUAL, "done")
        for cache, state, helper in zip(self._caches, self._states, self._helpers, strict=True):
            for address in (
                base + cache + 32,
                *(base + state + off for off in (HUD_OWNER, HUD_READY, HUD_CAPTURED_OWNER)),
            ):
                e.raw(b"\xc7\x05" + struct.pack("<I", address) + bytes(4))
            e.call_absolute(base + helper + 0x1000)
        e.label("done")
        e.raw(bytes.fromhex("61 9d c3"))
        return e.build()

    def _build_destructor(self, base: int, hooks: NativeRoomStatusABI) -> bytes:
        e = X86Emitter(base_va=base + self._destructor)
        e.raw(bytes.fromhex("9c 60"))
        for state in self._states:
            e.raw(b"\x3b\x0d" + struct.pack("<I", base + state + HUD_OWNER))
            e.jump_if(Condition.EQUAL, "owned")
        e.jump("native")
        e.label("owned")
        e.call_absolute(base + self._withdraw)
        e.raw(b"\xff\x05" + struct.pack("<I", base + self._destroyed))
        e.label("native")
        e.raw(bytes.fromhex("61 9d"))
        e.jump_absolute(hooks.destructor_va)
        return e.build()

    def _build_query(self, base: int) -> bytes:
        e = X86Emitter(base_va=base + self._query)
        glyph, back = (base + state for state in self._states)
        cache = base + self._caches[0]

        def absolute(opcode: bytes, address: int, suffix: bytes = b"") -> None:
            e.raw(opcode + struct.pack("<I", address) + suffix)

        e.raw(bytes.fromhex("9c 60 8b 7c 24 28 8b 87 bc 00 00 00"))
        absolute(b"\xa3", base + self._count_before)
        # Reserve two HUD, three menu and two text parts atomically.
        e.raw(bytes.fromhex("83 f8 09"))
        e.jump_if(Condition.ABOVE, "failed")
        for address in (base + self._enabled, self.world_enabled_va):
            absolute(b"\x83\x3d", address, b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "absent")
        e.call_absolute(base + self._probe)
        e.raw(bytes.fromhex("83 f8 ff"))
        e.jump_if(Condition.EQUAL, "withdraw_failed")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("8b f0"))
        for state in (glyph, back):
            absolute(b"\x3b\x35", state + HUD_OWNER)
            e.jump_if(Condition.NOT_EQUAL, "withdraw_failed")
        absolute(b"\x83\x3d", glyph + HUD_READY, b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "failed")
        absolute(b"\x3b\x35", glyph + HUD_CAPTURED_OWNER)
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.call_absolute(base + self._helpers[0] + 0x1A00)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        absolute(b"\x3b\x35", cache + 32)
        e.jump_if(Condition.NOT_EQUAL, "failed")
        # Fade snapshots must still belong to the current native object.
        for source, native in ((HUD_BACKGROUND_OPACITY, 0x88),):
            e.raw(b"\x8b\x86" + struct.pack("<I", native))
            absolute(b"\x3b\x05", glyph + source)
            e.jump_if(Condition.NOT_EQUAL, "failed")
        for index in range(5):
            e.raw(b"\x8b\x46" + bytes((0x5C + index * 4,)))
            absolute(b"\x3b\x05", glyph + 24 + index * 4)
            e.jump_if(Condition.NOT_EQUAL, "failed")
        # Affine uses live height/768 for both axes, signed floor/ceil bounds.
        # Bounded coordinates prevent overflowing the integer product.
        for index in range(4):
            e.raw(b"\x8b\x46" + bytes((0x1C + index * 4,)))
            absolute(b"\x3b\x05", cache + 0x180 + index * 4)
            e.jump_if(Condition.NOT_EQUAL, "failed")
            e.raw(bytes.fromhex("3d 00 e0 ff ff"))
            e.jump_if(Condition.LESS, "failed")
            e.raw(bytes.fromhex("3d 00 20 00 00"))
            e.jump_if(Condition.GREATER, "failed")
            absolute(b"\x0f\xaf\x05", cache + 12)
            e.raw(bytes.fromhex("99 b9 00 03 00 00 f7 f9 85 d2"))
            e.jump_if(Condition.EQUAL, f"rounded_{index}")
            if index < _NEAR_EDGE_COUNT:
                e.jump_if(Condition.NOT_SIGN, f"rounded_{index}")
                e.raw(b"\x48")
            else:
                e.jump_if(Condition.SIGN, f"rounded_{index}")
                e.raw(b"\x40")
            e.label(f"rounded_{index}")
            e.raw(bytes.fromhex("31 d2 85 c0 0f 4c c2"))
            absolute(b"\x3b\x05", cache + (8 if index % 2 == 0 else 12))
            absolute(b"\x0f\x4f\x05", cache + (8 if index % 2 == 0 else 12))
            absolute(b"\xa3", base + self._rect + index * 4)
        for near, far in ((0, 8), (4, 12)):
            absolute(b"\xa1", base + self._rect + far)
            absolute(b"\x3b\x05", base + self._rect + near)
            e.jump_if(Condition.LESS_OR_EQUAL, "failed")
        absolute(b"\x83\x3d", glyph + HUD_BACKGROUND_OPACITY, b"\x00")
        e.jump_if(Condition.EQUAL, "glyph")
        absolute(b"\x83\x3d", back + HUD_READY, b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "failed")
        absolute(b"\x3b\x35", back + HUD_CAPTURED_OWNER)
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.call_absolute(base + self._helpers[1] + 0x1A00)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        absolute(b"\x3b\x35", base + self._caches[1] + 32)
        e.jump_if(Condition.NOT_EQUAL, "failed")
        for index in range(4):
            absolute(b"\xa1", base + self._caches[1] + 0x180 + index * 4)
            absolute(b"\x3b\x05", cache + 0x180 + index * 4)
            e.jump_if(Condition.NOT_EQUAL, "failed")
        self._append(e, base, base + self._caches[1], glyph + HUD_BACKGROUND_OPACITY)
        e.label("glyph")
        absolute(b"\x83\x3d", glyph + HUD_GLYPH_OPACITY, b"\x00")
        e.jump_if(Condition.EQUAL, "accepted")
        self._append(e, base, cache, glyph + HUD_GLYPH_OPACITY)
        e.jump("accepted")
        e.label("withdraw_failed")
        e.call_absolute(base + self._withdraw)
        e.jump("failed")
        e.label("absent")
        e.call_absolute(base + self._withdraw)
        e.label("accepted")
        e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00"))
        e.jump("return")
        e.label("failed")
        absolute(b"\xa1", base + self._count_before)
        e.raw(bytes.fromhex("89 87 bc 00 00 00 c7 44 24 1c 00 00 00 00"))
        e.label("return")
        e.raw(bytes.fromhex("61 9d c2 04 00"))
        return e.build()

    @staticmethod
    def _append(e: X86Emitter, base: int, cache: int, opacity: int) -> None:
        e.raw(bytes.fromhex("8b 8f bc 00 00 00 6b c9 28 8d 8c 0f c0 00 00 00"))
        e.raw(b"\xa1" + struct.pack("<I", cache + 4) + bytes.fromhex("89 01"))
        for offset, value in ((4, 17), (8, 1)):  # keyed, display-only room status
            e.raw(b"\xc7\x41" + bytes((offset,)) + struct.pack("<I", value))
        for index in range(4):
            e.raw(b"\xa1" + struct.pack("<I", base + VRHudCompiler._rect + index * 4))
            e.raw(b"\x89\x41" + bytes((12 + index * 4,)))
            if index < _NEAR_EDGE_COUNT:
                e.raw(b"\x89\x41" + bytes((28 + index * 4,)))
        e.raw(b"\xa1" + struct.pack("<I", opacity) + bytes.fromhex("89 41 24 ff 87 bc 00 00 00"))
