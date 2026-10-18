"""Publish the native coordinate device without copying a room into VR."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, encode_rel32_branch
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.gps import (
    AUXILIARY_FIELD,
    DRAW_SITES,
    MEMBER_FIELDS,
    native_gps_hooks,
)
from gk3hd.patch.definitions.vr_hud_compiler import VRHudCompiler
from gk3hd.patch.definitions.vr_menu import (
    append_opaque_overlay,
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
    from gk3hd.patch.definitions.runtime2d.gps import NativeGPSHooksABI

_DRAW_SLOT = 0xA0
_ROOT_MEMBER = MEMBER_FIELDS[0]
_MAX_CHILDREN = 256
_MAX_EDGE = 8192


@dataclass(frozen=True, slots=True)
class VRGPSABI:
    """Dormant capture and current-page append entries shared with the panel."""

    enabled_va: int
    query_va: int
    probe_va: int
    world_enabled_va: int
    cache_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRGPSCompiler:
    """Capture only the current GPS siblings in their native drawing order.

    The existing Runtime2D adapters retain source density, corner placement and
    native input calibration. A capture-only traversal uses the same native
    Draw calls on an independent destination. It never reads a desktop target.
    Publication requires the live owner/room, unchanged footprint, successful
    transfers and the current page generation. Destruction, modal replacement
    and disabled rendering withdraw the source and its interactive footprint.
    """

    profile: BuildProfile
    world_enabled_va: int

    section_name: ClassVar[str] = ".gk3vg"
    section_size: ClassVar[int] = 0x6000
    _magic: ClassVar[bytes] = b"GK3XRG01"
    _enabled: ClassVar[int] = 0x0C
    _world: ClassVar[int] = 0x10
    _count_before: ClassVar[int] = 0x14
    _live_scene: ClassVar[int] = 0x40
    _live_room: ClassVar[int] = 0x44
    _live_children: ClassVar[int] = 0x48
    _live_count: ClassVar[int] = 0x4C
    _query: ClassVar[int] = 0x100
    _cache: ClassVar[int] = 0x1000
    _rectangle: ClassVar[int] = 0x1500
    _probe: ClassVar[int] = 0x2000
    _draw: ClassVar[int] = 0x2500
    _destroy: ClassVar[int] = 0x2800
    _scope: ClassVar[int] = 0x3000
    _group: ClassVar[int] = 0x3800
    _prepare: ClassVar[int] = 0x4000
    _validate: ClassVar[int] = 0x4500
    _release: ClassVar[int] = 0x4800
    _blt: ClassVar[int] = 0x4900
    _fast: ClassVar[int] = 0x4A00
    _unwind: ClassVar[int] = 0x4B00

    def abi(self, image: PEFile) -> VRGPSABI:
        """Resolve the private boundary without trusting retained runtime memory."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR GPS section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRGPSABI(
            base + self._enabled,
            base + self._query,
            base + self._probe,
            image.read_u32_va(base + self._world),
            base + self._cache,
        )

    def _dependencies(self, image: PEFile) -> NativeGPSHooksABI:
        scene = VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image)
        if (
            scene.enabled_va != self.world_enabled_va
            or image.read_u32_va(scene.recenter_va) & 2 == 0
        ):
            msg = "VR GPS requires the verified deferred world"
            raise PatchError(msg)
        return native_gps_hooks(image, self.profile)

    def _verify_native(self, image: PEFile) -> None:
        # These composed checks rebuild the complete shared Runtime2D image,
        # including GPS payload and redirects, rather than trusting its export.
        if image.get_section(VRHudCompiler.section_name) is not None:
            VRHudCompiler(profile=self.profile, world_enabled_va=self.world_enabled_va).postcheck(
                image
            )
        else:
            VRMenuCompiler(profile=self.profile, world_enabled_va=self.world_enabled_va).postcheck(
                image
            )

    def _links(self, base: int, hooks: NativeGPSHooksABI) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_gps")
        plan.pointer(
            label="GPS base draw",
            slot_va=self.profile.site("gps.bitmap_draw").va,
            expected=hooks.bitmap_draw_va,
            target_va=base + self._draw,
        )
        site = self.profile.site("gps.destroy")
        plan.branch(
            label="GPS destruction",
            opcode=BranchOpcode.JUMP,
            site_va=site.va,
            expected=encode_rel32_branch(
                opcode=BranchOpcode.JUMP, site_va=site.va, target_va=hooks.destroy_va
            ),
            target_va=base + self._destroy,
        )
        return plan

    def native_image(self, image: PEFile) -> PEFile:
        """Restore only verified GPS bindings for other composed-owner checks."""
        hooks = self._dependencies(image)
        base = self.abi(image).enabled_va - self._enabled
        self._links(base, hooks).verify(image)
        native = image.clone()
        native.write_u32_va(self.profile.site("gps.bitmap_draw").va, hooks.bitmap_draw_va)
        site = self.profile.site("gps.destroy")
        native.write_bytes(
            native.va_to_offset(site.va),
            encode_rel32_branch(
                opcode=BranchOpcode.JUMP, site_va=site.va, target_va=hooks.destroy_va
            ),
        )
        return native

    def apply(self, image: PEFile) -> None:
        """Verify the complete prior runtime before installing dormant hooks."""
        if image.get_section(self.section_name) is not None:
            msg = "VR GPS is already installed"
            raise PatchError(msg)
        hooks = self._dependencies(image)
        self._verify_native(image)
        preview = image.clone()
        section = preview.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = preview.rva_to_va(section.virtual_address)
        payload = self._payload(base, image, hooks)
        section = image.add_section(self.section_name, payload, 0xE0000060)
        if image.rva_to_va(section.virtual_address) != base:
            msg = "VR GPS section placement changed"
            raise PatchError(msg)
        self._links(base, hooks).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Rebuild every dormant byte and verify native dependencies and links."""
        hooks = self._dependencies(image)
        base = self.abi(image).enabled_va - self._enabled
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(
            base, image, hooks
        ):
            msg = "VR GPS payload failed verification"
            raise PatchError(msg)
        self._verify_native(self.native_image(image))

    def _payload(self, base: int, image: PEFile, hooks: NativeGPSHooksABI) -> bytes:
        cache = base + self._cache
        generation = TransitionFrameCompiler.runtime_abi(image).successful_flip_count_va
        p = self.profile
        payload = SegmentPayloadBuilder(
            owner="vr_gps", segment=self.section_name, size=self.section_size
        )
        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into("<I", header, self._world, self.world_enabled_va)
        payload.place(label="state", offset=0, payload=bytes(header))
        payload.place(label="cache", offset=self._cache, payload=menu_destination_state(cache))
        payload.reserve(label="physical crop", offset=self._rectangle, size=16)
        regions = (
            ("query", self._query, self._cache, self._build_query(base)),
            ("owner probe", self._probe, self._draw, self._build_probe(base, hooks)),
            ("capture gate", self._draw, self._destroy, self._build_draw(base, hooks)),
            ("destruction", self._destroy, self._scope, self._build_destroy(base, hooks)),
            ("native group", self._group, self._prepare, self._build_group(base, hooks)),
            (
                "capture scope",
                self._scope,
                self._group,
                build_menu_destination_scope(
                    wrapper_va=base + self._scope,
                    state_va=cache,
                    target_va=base + self._group,
                    class_vtable=hooks.bitmap_vtable_va,
                    toolbar=False,
                    resolve_resource_va=p.address("bitmap.resolve_resource"),
                    resource_manager_va=p.address("resource.manager"),
                    back_surface_va=p.address("transition.back_surface_ptr"),
                    directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                    readable_iat_va=p.address("win32.IsBadReadPtr"),
                    prepare_va=base + self._prepare,
                    blt_va=base + self._blt,
                    blt_fast_va=base + self._fast,
                    generation_va=generation,
                    unwind_va=base + self._unwind,
                    capture_only=True,
                ),
            ),
            (
                "prepare",
                self._prepare,
                self._validate,
                build_menu_cache_prepare(
                    wrapper_va=base + self._prepare,
                    state_va=cache,
                    release_va=base + self._release,
                    directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                ),
            ),
            (
                "validate",
                self._validate,
                self._release,
                build_menu_cache_validate(
                    wrapper_va=base + self._validate,
                    state_va=cache,
                    release_va=base + self._release,
                    class_vtable=hooks.bitmap_vtable_va,
                    directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                    dimensions_va=p.address("display.dimensions"),
                    generation_va=generation,
                    readable_iat_va=p.address("win32.IsBadReadPtr"),
                ),
            ),
            (
                "release",
                self._release,
                self._blt,
                build_menu_cache_release(wrapper_va=base + self._release, state_va=cache),
            ),
            (
                "Blt",
                self._blt,
                self._fast,
                build_menu_cache_blt_result(
                    wrapper_va=base + self._blt, state_va=cache, fast=False
                ),
            ),
            (
                "BltFast",
                self._fast,
                self._unwind,
                build_menu_cache_blt_result(
                    wrapper_va=base + self._fast, state_va=cache, fast=True
                ),
            ),
            (
                "unwind",
                self._unwind,
                self.section_size,
                build_menu_cache_unwind(
                    wrapper_va=base + self._unwind, state_va=cache, qualified=True
                ),
            ),
        )
        for label, offset, limit, code in regions:
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        return payload.build()

    def _build_probe(self, base: int, hooks: NativeGPSHooksABI) -> bytes:
        """Return the unique attached visible base, zero absent or -1 damaged."""
        e = X86Emitter(base_va=base + self._probe)

        def absolute(op: bytes, address: int, suffix: bytes = b"") -> None:
            e.raw(op + struct.pack("<I", address) + suffix)

        def readable(register: bytes, size: int) -> None:
            e.push_imm32(size)
            e.raw(register)
            absolute(b"\xff\x15", self.profile.address("win32.IsBadReadPtr"))
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.NOT_EQUAL, "unknown")

        e.raw(bytes.fromhex("9c 60"))
        absolute(b"\x8b\x35", hooks.owner_va)
        e.raw(bytes.fromhex("85 f6"))
        e.jump_if(Condition.EQUAL, "absent")
        absolute(b"\x3b\x35", self.profile.address("vr.room_global"))
        e.jump_if(Condition.NOT_EQUAL, "absent")
        readable(b"\x56", AUXILIARY_FIELD + 4)
        e.raw(
            b"\x81\x3e"
            + struct.pack("<I", self.profile.address("vr.coordinate_device_scene_vtable"))
        )
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(b"\x8d\xbe" + struct.pack("<I", _ROOT_MEMBER))
        e.raw(b"\x81\x3f" + struct.pack("<I", hooks.bitmap_vtable_va))
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(bytes.fromhex("80 7f 18 00"))
        e.jump_if(Condition.EQUAL, "absent")
        absolute(b"\x89\x35", base + self._live_scene)
        e.call_absolute(self.profile.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "absent")
        e.raw(bytes.fromhex("89 c3"))
        readable(b"\x53", 0x54)
        e.raw(b"\x81\x3b" + struct.pack("<I", self.profile.address("vr.room_layer_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "absent")
        absolute(b"\x89\x1d", base + self._live_room)
        e.raw(bytes.fromhex("8b 6b 50 81 fd") + struct.pack("<I", _MAX_CHILDREN))
        e.jump_if(Condition.ABOVE, "unknown")
        e.raw(bytes.fromhex("85 ed"))
        e.jump_if(Condition.EQUAL, "unknown")
        absolute(b"\x89\x2d", base + self._live_count)
        e.raw(bytes.fromhex("8b 5b 4c 85 db"))
        e.jump_if(Condition.EQUAL, "unknown")
        absolute(b"\x89\x1d", base + self._live_children)
        e.raw(bytes.fromhex("8d 04 ad 00 00 00 00 50 53"))
        absolute(b"\xff\x15", self.profile.address("win32.IsBadReadPtr"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(bytes.fromhex("31 f6"))
        e.label("scan")
        e.raw(bytes.fromhex("39 3b"))
        e.jump_if(Condition.NOT_EQUAL, "next")
        e.raw(bytes.fromhex("46 83 fe 01"))
        e.jump_if(Condition.ABOVE, "unknown")
        e.label("next")
        e.raw(bytes.fromhex("83 c3 04 4d"))
        e.jump_if(Condition.NOT_EQUAL, "scan")
        e.raw(bytes.fromhex("83 fe 01"))
        e.jump_if(Condition.NOT_EQUAL, "unknown")
        e.raw(bytes.fromhex("89 7c 24 1c"))
        e.jump("return")
        for label, value in (("absent", 0), ("unknown", 0xFFFFFFFF)):
            e.label(label)
            e.raw(bytes.fromhex("c7 44 24 1c") + struct.pack("<I", value))
            e.jump("return")
        e.label("return")
        e.raw(bytes.fromhex("61 9d c3"))
        return e.build()

    def _build_draw(self, base: int, hooks: NativeGPSHooksABI) -> bytes:
        e = X86Emitter(base_va=base + self._draw)
        e.raw(bytes.fromhex("51 ff 74 24 0c ff 74 24 0c"))
        e.call_absolute(hooks.bitmap_draw_va)
        e.raw(bytes.fromhex("59 50 9c 60"))
        for address, wanted in (
            (base + self._enabled, 1),
            (self.world_enabled_va, 1),
            (base + self._cache + 20, 0),
        ):
            e.raw(b"\x83\x3d" + struct.pack("<I", address) + bytes((wanted,)))
            e.jump_if(Condition.NOT_EQUAL, "return")
        e.call_absolute(base + self._probe)
        e.raw(bytes.fromhex("3b c1"))
        e.jump_if(Condition.NOT_EQUAL, "return")
        e.raw(b"\xc7\x05" + struct.pack("<II", base + self._cache, 1))
        e.raw(bytes.fromhex("ff 74 24 30 ff 74 24 30"))
        e.call_absolute(base + self._scope)
        e.label("return")
        e.raw(bytes.fromhex("61 9d 58 c2 08 00"))
        return e.build()

    def _build_destroy(self, base: int, hooks: NativeGPSHooksABI) -> bytes:
        e = X86Emitter(base_va=base + self._destroy)
        e.raw(bytes.fromhex("9c 60 8d 81") + struct.pack("<I", _ROOT_MEMBER))
        e.raw(b"\x3b\x05" + struct.pack("<I", base + self._cache + 32))
        e.jump_if(Condition.EQUAL, "withdraw")
        e.raw(b"\x3b\x0d" + struct.pack("<I", hooks.owner_va))
        e.jump_if(Condition.NOT_EQUAL, "return")
        e.label("withdraw")
        for offset in (0, 32, 0x70):
            e.raw(b"\xc7\x05" + struct.pack("<II", base + self._cache + offset, 0))
        e.call_absolute(base + self._release)
        e.label("return")
        e.raw(bytes.fromhex("61 9d"))
        e.jump_absolute(hooks.destroy_va)
        return e.build()

    def _build_group(self, base: int, hooks: NativeGPSHooksABI) -> bytes:
        """Filter the actual reverse native child traversal to the owned widgets."""
        e = X86Emitter(base_va=base + self._group)
        e.raw(
            bytes.fromhex("55 8b ec 83 ec 10 53 56 57 8b f1 81 ee")
            + struct.pack("<I", _ROOT_MEMBER)
        )
        e.raw(bytes.fromhex("c7 45 f0 00 00 00 00"))
        for offset, local in (
            (self._live_room, 0xFC),
            (self._live_children, 0xF8),
            (self._live_count, 0xF4),
        ):
            e.raw(b"\xa1" + struct.pack("<I", base + offset) + b"\x89\x45" + bytes((local,)))
        e.raw(bytes.fromhex("8b 5d f4 8b 7d f8 8d 3c 9f"))
        e.label("child")
        e.raw(bytes.fromhex("85 db"))
        e.jump_if(Condition.EQUAL, "return")
        e.raw(b"\x3b\x35" + struct.pack("<I", hooks.owner_va))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.call_absolute(self.profile.address("ui.current_layer"))
        e.raw(bytes.fromhex("3b 45 fc"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        for field, local in ((0x4C, 0xF8), (0x50, 0xF4)):
            e.raw(b"\x8b\x50" + bytes((field,)) + b"\x3b\x55" + bytes((local,)))
            e.jump_if(Condition.NOT_EQUAL, "failed")
        e.raw(bytes.fromhex("83 ef 04 8b 0f 85 c9"))
        e.jump_if(Condition.EQUAL, "next")
        e.call_absolute(hooks.member_va)
        e.jump_if(Condition.ABOVE_OR_EQUAL, "next")
        e.raw(
            bytes.fromhex("51 6a 2c 51 ff 15")
            + struct.pack("<I", self.profile.address("win32.IsBadReadPtr"))
        )
        e.raw(bytes.fromhex("59 85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        kinds = (0, 0, 0, 0, 1, 2, 2)
        for index, (offset, kind) in enumerate(zip(MEMBER_FIELDS, kinds, strict=True)):
            e.raw(b"\x8d\x86" + struct.pack("<I", offset) + bytes.fromhex("3b c1"))
            e.jump_if(Condition.NOT_EQUAL, f"member_{index}")
            e.raw(
                b"\x81\x39" + struct.pack("<I", self.profile.site(DRAW_SITES[kind]).va - _DRAW_SLOT)
            )
            e.jump_if(Condition.NOT_EQUAL, "failed")
            e.raw(b"\xba" + struct.pack("<I", 1 << index))
            e.jump("matched")
            e.label(f"member_{index}")
        e.raw(b"\x3b\x8e" + struct.pack("<I", AUXILIARY_FIELD))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.raw(b"\x81\x39" + struct.pack("<I", self.profile.site(DRAW_SITES[3]).va - _DRAW_SLOT))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.raw(b"\xba" + struct.pack("<I", 1 << len(MEMBER_FIELDS)))
        e.label("matched")
        e.raw(bytes.fromhex("85 55 f0"))
        e.jump_if(Condition.NOT_EQUAL, "failed")
        e.raw(bytes.fromhex("09 55 f0 80 79 18 00"))
        e.jump_if(Condition.EQUAL, "next")
        e.raw(bytes.fromhex("ff 75 0c ff 75 08 8b 01 ff 90 a0 00 00 00"))
        e.label("next")
        e.raw(bytes.fromhex("4b"))
        e.jump("child")
        e.label("failed")
        e.raw(b"\xc7\x05" + struct.pack("<II", base + self._cache + 0x64, 1))
        e.label("return")
        e.raw(bytes.fromhex("5f 5e 5b c9 c2 08 00"))
        return e.build()

    def _build_query(self, base: int) -> bytes:
        """Append only this frame's complete source or withdraw it atomically."""
        e = X86Emitter(base_va=base + self._query)
        cache = base + self._cache

        def absolute(op: bytes, address: int, suffix: bytes = b"") -> None:
            e.raw(op + struct.pack("<I", address) + suffix)

        e.raw(bytes.fromhex("9c 60 8b 7c 24 28 8b 87 bc 00 00 00"))
        absolute(b"\xa3", base + self._count_before)
        for address in (base + self._enabled, self.world_enabled_va):
            absolute(b"\x83\x3d", address, b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "absent")
        e.call_absolute(base + self._probe)
        e.raw(bytes.fromhex("83 f8 ff"))
        e.jump_if(Condition.EQUAL, "withdraw_failed")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "absent")
        absolute(b"\x3b\x05", cache + 32)
        e.jump_if(Condition.NOT_EQUAL, "withdraw_failed")
        e.raw(bytes.fromhex("89 c6"))
        e.call_absolute(base + self._validate)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "failed")
        # One GPS, at most three menu crops and the subsequent two labels.
        e.raw(bytes.fromhex("83 bf bc 00 00 00 0a"))
        e.jump_if(Condition.ABOVE, "failed")
        for index in range(4):
            e.raw(b"\x8b\x46" + bytes((0x1C + index * 4,)))
            absolute(b"\x3b\x05", cache + 0x180 + index * 4)
            e.jump_if(Condition.NOT_EQUAL, "failed")
            e.raw(b"\x3d" + struct.pack("<i", -_MAX_EDGE))
            e.jump_if(Condition.LESS, "failed")
            e.raw(b"\x3d" + struct.pack("<I", _MAX_EDGE))
            e.jump_if(Condition.GREATER, "failed")
            # Match GPSFeatureCompiler's signed floor on EVERY edge. At a
            # height <=768 the native transfer deliberately retains raw units.
            absolute(b"\x81\x3d", cache + 12, struct.pack("<I", 768))
            e.jump_if(Condition.BELOW_OR_EQUAL, f"edge_{index}")
            absolute(b"\x0f\xaf\x05", cache + 12)
            e.raw(bytes.fromhex("99 b9 00 03 00 00 f7 f9 85 d2"))
            e.jump_if(Condition.GREATER_OR_EQUAL, f"edge_{index}")
            e.raw(b"\x48")
            e.label(f"edge_{index}")
            absolute(b"\xa3", base + self._rectangle + index * 4)
        append_opaque_overlay(
            e, cache_va=cache, rectangle_va=base + self._rectangle, failed_label="failed"
        )
        e.raw(bytes.fromhex("83 4f 04 04"))
        e.jump("accepted")
        e.label("absent")
        self._emit_withdraw(e, base)
        e.label("accepted")
        e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00"))
        e.jump("return")
        e.label("withdraw_failed")
        self._emit_withdraw(e, base)
        e.label("failed")
        absolute(b"\xa1", base + self._count_before)
        e.raw(bytes.fromhex("89 87 bc 00 00 00 c7 44 24 1c 00 00 00 00"))
        e.label("return")
        e.raw(bytes.fromhex("61 9d c2 04 00"))
        return e.build()

    def _emit_withdraw(self, code: X86Emitter, base: int) -> None:
        # Keep capture enabled: a hidden source may become visible again next
        # traversal. Discard the retained root and ready state before Release.
        for offset in (32, 0x70):
            code.raw(b"\xc7\x05" + struct.pack("<II", base + self._cache + offset, 0))
        code.call_absolute(base + self._release)
