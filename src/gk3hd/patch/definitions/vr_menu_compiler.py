"""Verified native menu producers and current-frame interactive XR sources."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.compiler import Runtime2DCompiler
from gk3hd.patch.definitions.runtime2d.system.menus import MenuFeatureCompiler
from gk3hd.patch.definitions.vr_menu import (
    append_opaque_overlay,
    build_menu_cache_blt_result,
    build_menu_cache_destructor,
    build_menu_cache_prepare,
    build_menu_cache_release,
    build_menu_cache_unwind,
    build_menu_cache_validate,
    build_menu_destination_scope,
    menu_destination_state,
)
from gk3hd.patch.definitions.vr_menu_coverage import (
    BODY_RECT,
    COVERAGE_READY,
    POPUP_RECT,
    POPUP_ROOT,
    MenuCoverageABI,
    build_menu_coverage_capture,
    build_menu_coverage_validate,
)
from gk3hd.patch.definitions.vr_menu_mirror import build_menu_cache_mirror
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.system.menu_exports import NativeMenuHooksABI

_I386_MACHINE = 0x14C


@dataclass(frozen=True, slots=True)
class MenuCacheABI:
    """One independent native cache, qualified immediately before consumption."""

    surface_va: int
    ready_va: int
    root_va: int
    rect_va: int
    validate_va: int
    coverage: MenuCoverageABI | None = None


@dataclass(frozen=True, slots=True)
class VRMenuABI:
    """Dormant menu isolation and bounded atomic OverlayPart append callback."""

    enabled_va: int
    query_va: int
    world_enabled_va: int
    action: MenuCacheABI
    toolbar: MenuCacheABI


@dataclass(frozen=True, slots=True, kw_only=True)
class VRMenuCompiler:
    """Draw native menus once and mirror only qualified opaque crops.

    The independent cache never contains room pixels or inferred transparency.

    Install after the deferred world and complete Runtime2D, before the panel.
    The callback takes one OverlayPanelFrame pointer (stdcall, RET 4), preserves
    registers/flags except boolean EAX, and appends only current visible roots
    found in native child order. An unavailable source, unknown menu lifetime or
    unqualified footprint rolls back the entire append, retaining opaque fallback.
    This private compiler is dormant and not in the player-facing patch catalog.
    """

    profile: BuildProfile
    world_enabled_va: int

    section_name: ClassVar[str] = ".gk3vm"
    section_size: ClassVar[int] = 0x7000
    _magic: ClassVar[bytes] = b"GK3XRM02"
    _enabled: ClassVar[int] = 0x0C
    _world: ClassVar[int] = 0x10
    _count_before: ClassVar[int] = 0x14
    _query: ClassVar[int] = 0x100
    _states: ClassVar[tuple[int, int]] = (0x1000, 0x1500)
    _roots: ClassVar[tuple[int, int]] = (0x2000, 0x4000)

    def abi(self, image: PEFile) -> VRMenuABI:
        """Return the private versioned boundary without trusting runtime memory."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR menu section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        caches = tuple(
            MenuCacheABI(
                base + state + 4,
                base + state + 0x70,
                base + state + 32,
                base + state + 0x180,
                base + root + 0xC00,
                MenuCoverageABI(
                    base + state + BODY_RECT,
                    base + state + POPUP_RECT,
                    base + state + POPUP_ROOT,
                    base + state + COVERAGE_READY,
                    base + root + 0x1300,
                    base + root + 0x1A00,
                )
                if state == self._states[1]
                else None,
            )
            for state, root in zip(self._states, self._roots, strict=True)
        )
        return VRMenuABI(
            base + self._enabled,
            base + self._query,
            image.read_u32_va(base + self._world),
            caches[0],
            caches[1],
        )

    def _dependencies(self, image: PEFile) -> NativeMenuHooksABI:
        scene = VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image)
        if (
            scene.enabled_va != self.world_enabled_va
            or image.read_u32_va(scene.recenter_va) & 2 == 0
        ):
            msg = "VR menus require a verified deferred world"
            raise PatchError(msg)
        # Supported legacy executables have neither NO_SEH nor load-config
        # exception metadata. Never silently disable/erase a SafeSEH table.
        characteristics = struct.unpack("<H", image.read_bytes(image.optional_offset + 70, 2))[0]
        load_config = image.read_bytes(image.optional_offset + 96 + 10 * 8, 8)
        if image.machine != _I386_MACHINE or characteristics & 0x400 or any(load_config):
            msg = "VR menu exception metadata is unsupported"
            raise PatchError(msg)
        return MenuFeatureCompiler.native_hooks_abi(image, self.profile)

    def _verify_native(self, image: PEFile, hooks: NativeMenuHooksABI) -> None:
        # Other VR compilers may compose the pre-Flip callback. Restore only
        # native menu/presenter bindings in a clone, then rebuild every owned
        # Runtime2D payload and redirect. Never accept arbitrary helper bytes.
        native = image.clone()
        for root in (hooks.action, hooks.toolbar):
            native.write_u32_va(root.vtable_va, root.destructor_va)
            native.write_u32_va(root.vtable_va + 0xA0, root.draw_va)
        transition = TransitionFrameCompiler.runtime_abi(native)
        native.write_u32_va(transition.pre_flip_presenter_slot_va, hooks.frame_presenter_va)
        Runtime2DCompiler(profile=self.profile).postcheck(native)

    def _links(self, base: int, hooks: NativeMenuHooksABI) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_menu")
        for index, root in enumerate((hooks.action, hooks.toolbar)):
            code = base + self._roots[index]
            plan.pointer(
                label=f"menu {index} draw",
                slot_va=root.vtable_va + 0xA0,
                expected=root.draw_va,
                target_va=code,
            )
            plan.pointer(
                label=f"menu {index} destructor",
                slot_va=root.vtable_va,
                expected=root.destructor_va,
                target_va=code + 0xE00,
            )
        return plan

    def apply(self, image: PEFile) -> None:
        """Verify all dependencies before any mutation and install dormant roots."""
        if image.get_section(self.section_name) is not None:
            msg = "VR menu hooks are already installed"
            raise PatchError(msg)
        hooks = self._dependencies(image)
        for root in (hooks.action, hooks.toolbar):
            if (
                image.read_u32_va(root.vtable_va) != root.destructor_va
                or image.read_u32_va(root.vtable_va + 0xA0) != root.draw_va
            ):
                msg = "VR menu native binding changed"
                raise PatchError(msg)
        self._verify_native(image, hooks)
        # Build once at the predicted aligned base before allocating a section.
        preview = image.clone()
        section = preview.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = preview.rva_to_va(section.virtual_address)
        payload = self._payload(base, image, hooks)
        section = image.add_section(self.section_name, payload, 0xE0000060)
        if image.rva_to_va(section.virtual_address) != base:
            msg = "VR menu section placement changed"
            raise PatchError(msg)
        self._links(base, hooks).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Rebuild every dormant byte and verify roots and native dependencies."""
        hooks = self._dependencies(image)
        base = self.abi(image).enabled_va - self._enabled
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(
            base, image, hooks
        ):
            msg = "VR menu payload failed verification"
            raise PatchError(msg)
        self._links(base, hooks).verify(image)
        self._verify_native(image, hooks)

    def _payload(self, base: int, image: PEFile, hooks: NativeMenuHooksABI) -> bytes:
        payload = SegmentPayloadBuilder(
            owner="vr_menu", segment=self.section_name, size=self.section_size
        )
        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into("<I", header, self._world, self.world_enabled_va)
        payload.place(label="state", offset=0, payload=bytes(header))
        payload.place(
            label="query", offset=self._query, payload=self._build_query(base, hooks), limit=0x1000
        )
        generation = TransitionFrameCompiler.runtime_abi(image).successful_flip_count_va
        for index, root in enumerate((hooks.action, hooks.toolbar)):
            offset = self._roots[index]
            code, state = base + offset, base + self._states[index]
            mirror = base + 0x6000 + index * 0x800
            payload.place(
                label=f"menu {index} mirror",
                offset=0x6000 + index * 0x800,
                payload=build_menu_cache_mirror(
                    wrapper_va=mirror, state_va=state, toolbar=index == 1
                ),
                limit=0x6000 + (index + 1) * 0x800,
            )
            payload.place(
                label=f"cache {index}",
                offset=self._states[index],
                payload=menu_destination_state(state),
            )
            p = self.profile
            gate = X86Emitter(base_va=code)
            gate.raw(bytes.fromhex("9c 60"))
            self._emit_capture_ownership(gate, base)
            gate.raw(b"\xa3" + struct.pack("<I", state))
            gate.raw(bytes.fromhex("61 9d"))
            gate.jump_absolute(code + 0x100)
            regions = (
                (0, 0x100, gate.build()),
                (
                    0x100,
                    0x800,
                    build_menu_destination_scope(
                        wrapper_va=code + 0x100,
                        state_va=state,
                        target_va=root.draw_va,
                        class_vtable=root.vtable_va,
                        toolbar=index == 1,
                        resolve_resource_va=p.address("bitmap.resolve_resource"),
                        resource_manager_va=p.address("resource.manager"),
                        back_surface_va=p.address("transition.back_surface_ptr"),
                        directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                        readable_iat_va=p.address("win32.IsBadReadPtr"),
                        prepare_va=code + 0x800,
                        blt_va=code + 0xF00,
                        blt_fast_va=code + 0x1000,
                        generation_va=generation,
                        unwind_va=code + 0x1200,
                        coverage_va=code + 0x1300 if index == 1 else None,
                        mirror_va=mirror,
                    ),
                ),
                (
                    0x800,
                    0xC00,
                    build_menu_cache_prepare(
                        wrapper_va=code + 0x800,
                        state_va=state,
                        release_va=code + 0x1100,
                        directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                    ),
                ),
                (
                    0xC00,
                    0xE00,
                    build_menu_cache_validate(
                        wrapper_va=code + 0xC00,
                        state_va=state,
                        release_va=code + 0x1100,
                        class_vtable=root.vtable_va,
                        directdraw_owner_va=p.address("high_resolution_3d.directdraw_ptr"),
                        dimensions_va=p.address("display.dimensions"),
                        generation_va=generation,
                        readable_iat_va=p.address("win32.IsBadReadPtr"),
                    ),
                ),
                (
                    0xE00,
                    0xF00,
                    build_menu_cache_destructor(
                        wrapper_va=code + 0xE00,
                        state_va=state,
                        release_va=code + 0x1100,
                        target_va=root.destructor_va,
                    ),
                ),
                (
                    0xF00,
                    0x1000,
                    build_menu_cache_blt_result(
                        wrapper_va=code + 0xF00, state_va=state, fast=False
                    ),
                ),
                (
                    0x1000,
                    0x1100,
                    build_menu_cache_blt_result(
                        wrapper_va=code + 0x1000, state_va=state, fast=True
                    ),
                ),
                (
                    0x1100,
                    0x1200,
                    build_menu_cache_release(wrapper_va=code + 0x1100, state_va=state),
                ),
                (
                    0x1200,
                    0x1300,
                    build_menu_cache_unwind(
                        wrapper_va=code + 0x1200, state_va=state, qualified=True
                    ),
                ),
            )
            for start, end, data in regions:
                payload.place(
                    label=f"root {index} helper {start:x}",
                    offset=offset + start,
                    payload=data,
                    limit=offset + end,
                )
            if index == 1:
                for start, end, builder in (
                    (0x1300, 0x1A00, build_menu_coverage_capture),
                    (0x1A00, 0x2000, build_menu_coverage_validate),
                ):
                    payload.place(
                        label=f"toolbar coverage {start:x}",
                        offset=offset + start,
                        payload=builder(
                            wrapper_va=code + start,
                            state_va=state,
                            hooks=hooks,
                            dropdown_vtable=p.address("resolution_dropdown.vtable"),
                            readable_iat_va=p.address("win32.IsBadReadPtr"),
                        ),
                        limit=offset + end,
                    )
        return payload.build()

    def _emit_capture_ownership(self, code: X86Emitter, base: int) -> None:
        """Enable isolated crops only for the current readable room owner.

        SIDNEY retains world enablement while its authored canvas is current.
        Capturing that nested toolbar with the room affine clips its drawing.
        Non-room roots keep their ordinary destination and complete panel.
        Both native Draw and frame publication use this same lifetime policy.
        """
        p = self.profile
        for address in (base + self._enabled, self.world_enabled_va):
            code.raw(b"\x83\x3d" + struct.pack("<I", address) + b"\x01")
            code.jump_if(Condition.NOT_EQUAL, "capture_disabled")
        code.call_absolute(p.address("ui.current_layer"))
        code.raw(bytes.fromhex("85 c0"))
        code.jump_if(Condition.EQUAL, "capture_disabled")
        code.raw(bytes.fromhex("50 6a 04 50"))
        code.raw(b"\xff\x15" + struct.pack("<I", p.address("win32.IsBadReadPtr")))
        code.raw(bytes.fromhex("5a 85 c0"))
        code.jump_if(Condition.NOT_EQUAL, "capture_disabled")
        code.raw(b"\x81\x3a" + struct.pack("<I", p.address("vr.room_layer_vtable")))
        code.jump_if(Condition.NOT_EQUAL, "capture_disabled")
        code.raw(bytes.fromhex("b8 01 00 00 00"))
        code.jump("capture_ownership")
        code.label("capture_disabled")
        code.raw(bytes.fromhex("31 c0"))
        code.label("capture_ownership")

    def _build_query(self, base: int, hooks: NativeMenuHooksABI) -> bytes:
        """Validate both caches, then append all visible native menu children."""
        e = X86Emitter(base_va=base + self._query)
        p = self.profile

        def absolute(opcode: bytes, address: int) -> None:
            e.raw(opcode + struct.pack("<I", address))

        e.raw(bytes.fromhex("9c 60 8b 7c 24 28"))  # EDI is caller's frame.
        # A hidden root need not Draw again after XR is disabled. Synchronize
        # cache ownership here before validation, rather than retaining its
        # last Draw's enabled flag and independent COM allocation indefinitely.
        self._emit_capture_ownership(e, base)
        for state in self._states:
            absolute(b"\xa3", base + state)
        for root in self._roots:
            e.call_absolute(base + root + 0xC00)
        for address in (base + self._enabled, self.world_enabled_va):
            absolute(b"\x83\x3d", address)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "failed")
        # Reserve three menu crops and the later caption/tooltip parts within
        # the fixed sixteen-part frame, even when a caller already has parts.
        e.raw(bytes.fromhex("8b 87 bc 00 00 00 83 f8 0b"))
        e.jump_if(Condition.ABOVE, "failed")
        absolute(b"\xa3", base + self._count_before)
        e.call_absolute(p.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "rollback")
        e.raw(bytes.fromhex("50 6a 54 50"))
        absolute(b"\xff\x15", p.address("win32.IsBadReadPtr"))
        e.raw(bytes.fromhex("85 c0 58"))
        e.jump_if(Condition.NOT_EQUAL, "rollback")
        e.raw(b"\x81\x38" + struct.pack("<I", p.address("vr.room_layer_vtable")))
        e.jump_if(Condition.NOT_EQUAL, "rollback")
        e.raw(bytes.fromhex("8b 70 4c 8b 58 50 81 fb 00 01 00 00"))
        e.jump_if(Condition.ABOVE, "rollback")
        e.raw(bytes.fromhex("31 ed 85 db"))  # Class/visible-popup lifetime bits.
        e.jump_if(Condition.EQUAL, "accepted")
        e.raw(bytes.fromhex("85 f6"))
        e.jump_if(Condition.EQUAL, "rollback")
        e.raw(bytes.fromhex("8d 04 9d 00 00 00 00 50 56"))
        absolute(b"\xff\x15", p.address("win32.IsBadReadPtr"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "rollback")
        e.label("child")
        e.raw(bytes.fromhex("8b 16 85 d2"))
        e.jump_if(Condition.EQUAL, "next")
        e.raw(bytes.fromhex("52 6a 28 52"))
        absolute(b"\xff\x15", p.address("win32.IsBadReadPtr"))
        e.raw(bytes.fromhex("5a 85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "rollback")
        e.raw(bytes.fromhex("80 7a 18 00"))
        e.jump_if(Condition.EQUAL, "next")
        for index, root in enumerate((hooks.action, hooks.toolbar)):
            e.raw(b"\x81\x3a" + struct.pack("<I", root.vtable_va))
            e.jump_if(Condition.EQUAL, f"menu_{index}")
        e.raw(b"\x81\x3a" + struct.pack("<I", p.address("resolution_dropdown.vtable")))
        e.jump_if(Condition.EQUAL, "popup_child")
        e.jump("next")
        for index, state in enumerate(self._states):
            e.label(f"menu_{index}")
            e.raw(b"\xf7\xc5" + struct.pack("<I", 1 << index))
            e.jump_if(Condition.NOT_EQUAL, "rollback")
            e.raw(b"\x83\xcd" + bytes((1 << index,)))
            absolute(b"\x3b\x15", base + state + 32)
            e.jump_if(Condition.NOT_EQUAL, "rollback")
            absolute(b"\x83\x3d", base + state + 0x70)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "rollback")
            if index == 0:
                self._append_menu(e, base + state)
            else:
                e.call_absolute(base + self._roots[1] + 0x1A00)
                e.raw(bytes.fromhex("85 c0"))
                e.jump_if(Condition.EQUAL, "rollback")
                self._append_menu(e, base + state, rectangle=base + state + BODY_RECT)
                absolute(b"\x83\x3d", base + state + POPUP_ROOT)
                e.raw(b"\x00")
                e.jump_if(Condition.EQUAL, "next")
                # Native deferral presents the sibling list after its parent,
                # irrespective of its earlier insertion in the child array.
                self._append_menu(e, base + state, rectangle=base + state + POPUP_RECT)
            e.jump("next")
        e.label("popup_child")
        e.raw(bytes.fromhex("f7 c5 04 00 00 00"))
        e.jump_if(Condition.NOT_EQUAL, "rollback")
        absolute(b"\x3b\x15", hooks.dropdown_pending_va)
        e.jump_if(Condition.NOT_EQUAL, "rollback")
        e.raw(bytes.fromhex("83 cd 04"))
        e.label("next")
        e.raw(bytes.fromhex("83 c6 04 4b"))
        e.jump_if(Condition.NOT_EQUAL, "child")
        e.label("accepted")
        absolute(b"\x83\x3d", hooks.dropdown_pending_va)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "complete")
        e.raw(bytes.fromhex("89 e8 83 e0 06 83 f8 06"))
        e.jump_if(Condition.NOT_EQUAL, "rollback")
        e.label("complete")
        # Only a successfully appended native menu requests readable placement.
        # Empty room batches and rollback must never move captions/status text.
        e.raw(bytes.fromhex("8b 87 bc 00 00 00"))
        absolute(b"\x3b\x05", base + self._count_before)
        e.jump_if(Condition.BELOW_OR_EQUAL, "no_menu_placement")
        e.raw(bytes.fromhex("83 4f 04 04"))
        e.label("no_menu_placement")
        e.raw(bytes.fromhex("c7 44 24 1c 01 00 00 00"))
        e.jump("return")
        e.label("rollback")
        absolute(b"\xa1", base + self._count_before)
        e.raw(bytes.fromhex("89 87 bc 00 00 00"))
        e.label("failed")
        e.raw(bytes.fromhex("c7 44 24 1c 00 00 00 00"))
        e.label("return")
        e.raw(bytes.fromhex("61 9d c2 04 00"))
        return e.build()

    @staticmethod
    def _append_menu(e: X86Emitter, state: int, *, rectangle: int | None = None) -> None:
        """Clip the qualified opaque native footprint without rescaling it."""
        append_opaque_overlay(
            e,
            cache_va=state,
            rectangle_va=state + 0x180 if rectangle is None else rectangle,
            failed_label="rollback",
        )
