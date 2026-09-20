"""Compile bordered Help, keyboard configuration and message-dialog screens."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_SEGMENT,
    UI_FRAMES_DIMENSIONS_OFFSET,
    UI_FRAMES_SEGMENT,
    UI_FRAMES_SOURCE_OFFSET,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext
from gk3hd.patch.definitions.runtime2d.ui_frames import (
    BLIT_ONLY_IMAGES,
    build_bitmap_object_dimensions,
    build_blit_match,
    build_dimensions,
    build_high_dimensions,
    build_resource_match,
    build_source,
    build_surface_match,
)

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile

_RESOURCE_MATCH = 0x2000
_SURFACE_MATCH = 0x100
_HIGH_DIMENSIONS = 0xB00
_BITMAP_OBJECT_DIMENSIONS = 0xA80
_VISIBILITY = 0x1A00
_BLIT_RESOURCE_MATCH = 0x7000
_BLIT_SURFACE_MATCH = 0x7800
_BLIT_MATCH = 0x7C00
_SCREEN_OFFSETS = (("help", 0xE00), ("keyboard_config", 0x1400), ("message_box", 0x1B00))


@dataclass(frozen=True, slots=True, kw_only=True)
class BorderedScreenFeatureCompiler(SystemCompilerContext):
    """Own source sampling and complete lifetimes of the shared-border screens."""

    def build_visibility(self, *, wrapper_va: int) -> bytes:
        """Retire the previous fitted page's damage when visibility/layout changes.

        Help selects a new native page then calls SetVisible(1). Its ordinary
        dirty region covers only native-sized bounds, leaving the wider previous
        fitted page behind. Invalidate the engine's retained damage at this edge,
        not in the frame loop. Small modes keep their original invalidation.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\xff\x74\x24\x04")
        code.call_absolute(self.profile.address("ui.set_visible"))
        code.raw(b"\x9c\x60")
        code.raw(b"\x81\x3d" + struct.pack("<II", self._physical_width_va, 1024))
        code.jump_if(Condition.ABOVE, "invalidate")
        code.raw(b"\x81\x3d" + struct.pack("<II", self._physical_width_va + 4, 768))
        code.jump_if(Condition.BELOW_OR_EQUAL, "done")
        code.label("invalidate")
        code.raw(
            b"\x8b\x0d" + struct.pack("<I", self.profile.address("transition.engine_loop_ptr"))
        )
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "done")
        code.call_absolute(self.profile.address("transition.invalidate_all_damage"))
        code.label("done")
        code.raw(b"\x61\x9d\xc2\x04\x00")
        return code.build()

    def apply(self, image: PEFile) -> None:
        """Install the bounded border helpers and class-scoped screen wrappers."""
        section = install_runtime_segment(image, UI_FRAMES_SEGMENT)
        base = image.rva_to_va(section.virtual_address)
        system = self.symbols.va(SYSTEM_SEGMENT.logical_name)
        control = self.symbols.va(SYSTEM_CONTROL_SEGMENT.logical_name)
        payload = SegmentPayloadBuilder(
            owner=self.id, segment=UI_FRAMES_SEGMENT.logical_name, size=UI_FRAMES_SEGMENT.size
        )
        payload.place(label="identity", offset=0, payload=UI_FRAMES_SEGMENT.magic)
        payload.reserve(label="logical dimension pair", offset=0x20, size=8)
        payload.reserve(label="private dense source rectangle", offset=0x30, size=16)
        high_site = self.profile.site("runtime2d.high_blt_dimensions")
        helpers = (
            (
                _RESOURCE_MATCH,
                build_resource_match(wrapper_va=base + _RESOURCE_MATCH),
                _BLIT_RESOURCE_MATCH,
            ),
            (
                UI_FRAMES_DIMENSIONS_OFFSET,
                build_dimensions(
                    wrapper_va=base + UI_FRAMES_DIMENSIONS_OFFSET,
                    match_va=base + _RESOURCE_MATCH,
                    logical_va=base + 0x20,
                ),
                _BITMAP_OBJECT_DIMENSIONS,
            ),
            (
                _BITMAP_OBJECT_DIMENSIONS,
                build_bitmap_object_dimensions(
                    wrapper_va=base + _BITMAP_OBJECT_DIMENSIONS,
                    dimensions_va=self.profile.address("bitmap.dimensions"),
                    surface_match_va=base + _BLIT_SURFACE_MATCH,
                    logical_va=base + 0x20,
                ),
                _HIGH_DIMENSIONS,
            ),
            (
                _SURFACE_MATCH,
                build_surface_match(
                    wrapper_va=base + _SURFACE_MATCH,
                    resource_match_va=base + _RESOURCE_MATCH,
                    manager_va=self.profile.address("resource.manager"),
                ),
                UI_FRAMES_DIMENSIONS_OFFSET,
            ),
            (
                _HIGH_DIMENSIONS,
                build_high_dimensions(
                    wrapper_va=base + _HIGH_DIMENSIONS,
                    surface_match_va=base + _BLIT_MATCH,
                    original=high_site.original,
                    return_va=high_site.va + len(high_site.original),
                ),
                UI_FRAMES_SOURCE_OFFSET,
            ),
            (
                UI_FRAMES_SOURCE_OFFSET,
                build_source(
                    wrapper_va=base + UI_FRAMES_SOURCE_OFFSET,
                    surface_match_va=base + _BLIT_MATCH,
                    scratch_va=base + 0x30,
                    manager_va=self.profile.address("resource.manager"),
                    dimensions_va=self._physical_width_va,
                    callers=(
                        self.profile.address("runtime2d.high_blt_final_return"),
                        self.profile.address("runtime2d.high_blt_fallback_return"),
                    ),
                ),
                _SCREEN_OFFSETS[0][1],
            ),
            (_VISIBILITY, self.build_visibility(wrapper_va=base + _VISIBILITY), 0x1B00),
            (
                _BLIT_RESOURCE_MATCH,
                build_resource_match(
                    wrapper_va=base + _BLIT_RESOURCE_MATCH, images=BLIT_ONLY_IMAGES
                ),
                _BLIT_SURFACE_MATCH,
            ),
            (
                _BLIT_SURFACE_MATCH,
                build_surface_match(
                    wrapper_va=base + _BLIT_SURFACE_MATCH,
                    resource_match_va=base + _BLIT_RESOURCE_MATCH,
                    manager_va=self.profile.address("resource.manager"),
                    images=BLIT_ONLY_IMAGES,
                ),
                _BLIT_MATCH,
            ),
            (
                _BLIT_MATCH,
                build_blit_match(
                    wrapper_va=base + _BLIT_MATCH,
                    ui_match_va=base + _SURFACE_MATCH,
                    extra_match_va=base + _BLIT_SURFACE_MATCH,
                ),
                UI_FRAMES_SEGMENT.size,
            ),
        )
        for offset, code, limit in helpers:
            payload.place(
                label=f"border helper {offset:x}", offset=offset, payload=code, limit=limit
            )
        fixed = FixedScreenFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )
        plan = ExecutableMutationPlan(owner=self.id)
        for name, offset in _SCREEN_OFFSETS:
            draw = fixed.build_root_draw_wrapper(
                wrapper_va=base + offset,
                render_depth_va=system + self._off_render_depth,
                input_active_va=system + self._off_input_active,
                clear_pending_va=system + self._off_clear_pending,
                root_ptr_va=system + self._off_root_ptr,
                transform_mode_va=system + self._off_transform_mode,
                transform_mode=self._mode_local_root_canvas,
                input_enabled=True,
                target_va=self.profile.address(f"{name}.draw"),
                full_damage_region_va=control + self._off_control_full_damage_region,
                full_damage_rect_va=control + self._off_control_full_damage_rect,
            )
            payload.place(label=f"{name} draw", offset=offset, payload=draw, limit=offset + 0x300)
            for edge, relative, slot, value in (("show", 0x300, 0xD8, 1), ("hide", 0x380, 0xDC, 0)):
                target = base + offset + relative
                code = fixed.build_state_wrapper(
                    wrapper_va=target,
                    state_va=system + self._off_input_active,
                    value=value,
                    target_va=self.profile.address(f"ui.{edge}"),
                )
                payload.place(
                    label=f"{name} {edge}",
                    offset=offset + relative,
                    payload=code,
                    limit=offset + relative + 0x80,
                )
                plan.pointer(
                    label=f"{name} {edge}",
                    slot_va=self.profile.address(f"{name}.vtable") + slot,
                    expected=self.profile.address(f"ui.{edge}"),
                    target_va=target,
                )
            destructor = fixed.build_destructor_wrapper(
                wrapper_va=base + offset + 0x400,
                render_depth_va=system + self._off_render_depth,
                input_active_va=system + self._off_input_active,
                clear_pending_va=system + self._off_clear_pending,
                root_ptr_va=system + self._off_root_ptr,
                transform_mode_va=system + self._off_transform_mode,
                target_va=self.profile.address(f"{name}.destructor"),
            )
            payload.place(
                label=f"{name} destructor",
                offset=offset + 0x400,
                payload=destructor,
                limit=offset + 0x500,
            )
            for edge, slot, target in (
                ("draw", 0xA0, base + offset),
                ("destructor", 0, base + offset + 0x400),
                ("set_visible", 0xB0, base + _VISIBILITY),
            ):
                plan.pointer(
                    label=f"{name} {edge}",
                    slot_va=self.profile.address(f"{name}.vtable") + slot,
                    expected=self.profile.address(
                        f"{'ui' if edge == 'set_visible' else name}.{edge}"
                    ),
                    target_va=target,
                )
        plan.branch(
            label="logical tiled-border dimensions",
            opcode=BranchOpcode.JUMP,
            site_va=high_site.va,
            expected=high_site.original,
            target_va=base + _HIGH_DIMENSIONS,
            size=len(high_site.original),
        )
        for symbol in ("bitmap.set_image_dimensions", "sidney.preview_dimensions"):
            dimensions = self.profile.site(symbol)
            plan.branch(
                label=f"{symbol} shared-artwork logical dimensions",
                opcode=BranchOpcode.CALL,
                site_va=dimensions.va,
                expected=dimensions.original,
                target_va=base + _BITMAP_OBJECT_DIMENSIONS,
            )
        image.write_bytes(section.pointer_to_raw_data, payload.build())
        plan.apply(image)
