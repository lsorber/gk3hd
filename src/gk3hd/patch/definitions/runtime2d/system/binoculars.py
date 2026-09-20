"""Compile binocular composition and D-pad input as one local widget."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    BINOCULAR_BLT_HELPER_OFFSET,
    BINOCULAR_BLT_TRANSFORM_COUNT_OFFSET,
    BINOCULAR_DENSE_STATE_OFFSET,
    BINOCULAR_INPUT_HELPER_OFFSET,
    BINOCULAR_INPUT_TRANSFORM_COUNT_OFFSET,
    BINOCULAR_LAYOUT_VERSION_OFFSET,
    BINOCULAR_ROOT_OFFSET,
    BINOCULAR_SEGMENT,
    BINOCULAR_SIZE_HELPER_OFFSET,
    BINOCULAR_SOURCE_GROUP_RECT_OFFSET,
    BINOCULAR_SOURCE_HELPER_OFFSET,
    BINOCULAR_TARGET_GROUP_RECT_OFFSET,
    BINOCULAR_VALID_OFFSET,
    CURSOR_DENSITY_PROBE_OFFSET,
    CURSOR_RESOURCE_MATCH_OFFSET,
    INVENTORY_NAVIGATION_DIMENSIONS_OFFSET,
    INVENTORY_NAVIGATION_SEGMENT,
    SIDNEY_CONSTRUCTION_SEGMENT,
    SIDNEY_FINGERPRINT_DIMENSIONS_OFFSET,
    SIDNEY_FRAME_DIMENSIONS_OFFSET,
    SIDNEY_FRAME_DISCOVERY_OFFSET,
    SIDNEY_IMAGE_DIMENSIONS_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    SIDNEY_SYSTEM_INPUT_HELPER_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    TIMEBLOCK_OVERLAY_SURFACE_OFFSET,
    TIMEBLOCK_SEGMENT,
    UI_FRAMES_DIMENSIONS_OFFSET,
    UI_FRAMES_SEGMENT,
)
from gk3hd.patch.definitions.runtime2d.system.cursor_density import (
    build_density_probe,
    build_resource_match,
)
from gk3hd.patch.definitions.runtime2d.system.lifecycle import ScreenLifecycleTargets
from gk3hd.patch.definitions.runtime2d.system.resource_dimensions import (
    build_dimensions,
    build_source_rect,
)
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.mutations import ExecutableMutationPlan
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder
    from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler


@dataclass(frozen=True, slots=True, kw_only=True)
class BinocularFeatureCompiler(SystemCompilerContext):
    """Fit the binocular screen and its local controls through one affine.

    Outcome:
        The binocular image, direction pad, hover states, and clicks retain the
        reference composition at every live display size.
    Before:
        The full-screen root and nested D-pad use different authored rectangles,
        while the input tree tests their untransformed bounds.
    After:
        Root presentation, the local control group, and inverse hit testing use
        one published source/target pair for the widget lifetime.
    Strategy:
        Scope the concrete binocular root, record the D-pad group during final
        blits, and export its exact inverse to the shared pointer dispatcher.
    Boundaries:
        Ordinary room field of view, menu input, cursor composition, and page
        synchronization retain their existing owners.
    """

    def emit_segment(
        self,
        payload: SegmentPayloadBuilder,
        *,
        binocular_va: int,
        system_va: int,
    ) -> int:
        """Compile the complete binocular widget segment and export its blitter."""
        local_blt_helper_va = binocular_va + BINOCULAR_BLT_HELPER_OFFSET
        input_helper_va = binocular_va + BINOCULAR_INPUT_HELPER_OFFSET
        local_blt_helper = self.build_binocs_local_blt_helper(
            wrapper_va=local_blt_helper_va,
            root_ptr_va=system_va + self._off_root_ptr,
            target_rect_va=system_va + self._off_target_rect,
            dest_rect_va=system_va + self._off_dest_rect,
            valid_va=binocular_va + BINOCULAR_VALID_OFFSET,
            owner_root_va=binocular_va + BINOCULAR_ROOT_OFFSET,
            source_group_rect_va=binocular_va + BINOCULAR_SOURCE_GROUP_RECT_OFFSET,
            target_group_rect_va=binocular_va + BINOCULAR_TARGET_GROUP_RECT_OFFSET,
            transform_count_va=binocular_va + BINOCULAR_BLT_TRANSFORM_COUNT_OFFSET,
        )
        input_helper = self.build_binocs_input_helper(
            wrapper_va=input_helper_va,
            generic_input_wrapper_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name,
                SIDNEY_SYSTEM_INPUT_HELPER_OFFSET,
            ),
            root_ptr_va=system_va + self._off_root_ptr,
            binocular_vtable_va=self.profile.address("binocular.vtable"),
            valid_va=binocular_va + BINOCULAR_VALID_OFFSET,
            owner_root_va=binocular_va + BINOCULAR_ROOT_OFFSET,
            source_group_rect_va=binocular_va + BINOCULAR_SOURCE_GROUP_RECT_OFFSET,
            target_group_rect_va=binocular_va + BINOCULAR_TARGET_GROUP_RECT_OFFSET,
            transform_count_va=binocular_va + BINOCULAR_INPUT_TRANSFORM_COUNT_OFFSET,
        )
        payload.place(label="magic", offset=0, payload=BINOCULAR_SEGMENT.magic)
        payload.place(
            label="layout version",
            offset=BINOCULAR_LAYOUT_VERSION_OFFSET,
            payload=struct.pack("<I", 13),
        )
        payload.reserve(
            label="widget state",
            offset=BINOCULAR_VALID_OFFSET,
            size=BINOCULAR_INPUT_TRANSFORM_COUNT_OFFSET + 4 - BINOCULAR_VALID_OFFSET,
        )
        payload.place(
            label="local-blit helper",
            offset=BINOCULAR_BLT_HELPER_OFFSET,
            payload=local_blt_helper,
            limit=BINOCULAR_INPUT_HELPER_OFFSET,
        )
        payload.place(
            label="input helper",
            offset=BINOCULAR_INPUT_HELPER_OFFSET,
            payload=input_helper,
            limit=BINOCULAR_SIZE_HELPER_OFFSET,
        )
        state_va = binocular_va + BINOCULAR_DENSE_STATE_OFFSET
        site = self.profile.site("bitmap.dimensions_return")
        payload.reserve(label="dense source state", offset=BINOCULAR_DENSE_STATE_OFFSET, size=28)
        payload.place(
            label="logical control dimensions",
            offset=BINOCULAR_SIZE_HELPER_OFFSET,
            payload=build_dimensions(
                cursor_match_va=binocular_va + CURSOR_RESOURCE_MATCH_OFFSET,
                fingerprint_dimensions_va=self.symbols.va(
                    SIDNEY_CONSTRUCTION_SEGMENT.logical_name, SIDNEY_FINGERPRINT_DIMENSIONS_OFFSET
                ),
                frame_discovery_va=self.symbols.va(
                    SIDNEY_CONSTRUCTION_SEGMENT.logical_name, SIDNEY_FRAME_DISCOVERY_OFFSET
                ),
                frame_dimensions_va=self.symbols.va(
                    SIDNEY_CONSTRUCTION_SEGMENT.logical_name, SIDNEY_FRAME_DIMENSIONS_OFFSET
                ),
                wrapper_va=binocular_va + BINOCULAR_SIZE_HELPER_OFFSET,
                state_va=state_va,
                return_va=site.va + len(site.original),
                preview_surface_va=self.symbols.va(
                    SYSTEM_CONTROL_SEGMENT.logical_name, self._off_toolbar_preview_surface
                ),
                root_va=system_va + self._off_root_ptr,
                toolbar_vtable_va=self.profile.address("ingame_toolbar.vtable"),
                timeblock_surface_va=self.symbols.va(
                    TIMEBLOCK_SEGMENT.logical_name, TIMEBLOCK_OVERLAY_SURFACE_OFFSET
                ),
                image_dimensions_va=self.symbols.va(
                    SIDNEY_CONSTRUCTION_SEGMENT.logical_name, SIDNEY_IMAGE_DIMENSIONS_OFFSET
                ),
                inventory_dimensions_va=self.symbols.va(
                    INVENTORY_NAVIGATION_SEGMENT.logical_name,
                    INVENTORY_NAVIGATION_DIMENSIONS_OFFSET,
                ),
                border_dimensions_va=self.symbols.va(
                    UI_FRAMES_SEGMENT.logical_name, UI_FRAMES_DIMENSIONS_OFFSET
                ),
            ),
            limit=BINOCULAR_SOURCE_HELPER_OFFSET,
        )
        payload.place(
            label="dense control source coordinates",
            offset=BINOCULAR_SOURCE_HELPER_OFFSET,
            payload=build_source_rect(
                wrapper_va=binocular_va + BINOCULAR_SOURCE_HELPER_OFFSET,
                state_va=state_va,
                root_ptr_va=system_va + self._off_root_ptr,
                root_vtable_va=self.profile.address("binocular.vtable"),
            ),
            limit=CURSOR_DENSITY_PROBE_OFFSET,
        )
        payload.place(
            label="exact cursor density",
            offset=CURSOR_DENSITY_PROBE_OFFSET,
            payload=build_density_probe(
                wrapper_va=binocular_va + CURSOR_DENSITY_PROBE_OFFSET,
                manager_va=self.profile.address("resource.manager"),
                resolve_va=self.profile.address("bitmap.resolve_resource"),
                match_va=binocular_va + CURSOR_RESOURCE_MATCH_OFFSET,
            ),
            limit=CURSOR_RESOURCE_MATCH_OFFSET,
        )
        payload.place(
            label="cursor resource layouts",
            offset=CURSOR_RESOURCE_MATCH_OFFSET,
            payload=build_resource_match(wrapper_va=binocular_va + CURSOR_RESOURCE_MATCH_OFFSET),
        )
        return local_blt_helper_va

    def emit_lifecycle(
        self,
        payload: SegmentPayloadBuilder,
        *,
        system_va: int,
        fixed_screens: FixedScreenFeatureCompiler,
    ) -> ScreenLifecycleTargets:
        """Compile and place the binocular root's complete class lifecycle."""
        lifecycle = ScreenLifecycleTargets(
            draw_va=system_va + self._off_binocs_root_draw_wrapper,
            show_va=system_va + self._off_binocs_show_wrapper,
            hide_va=system_va + self._off_binocs_hide_wrapper,
            destructor_va=system_va + self._off_binocs_destructor_wrapper,
        )
        root_wrapper = fixed_screens.build_root_draw_wrapper(
            wrapper_va=lifecycle.draw_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            transform_mode=self._mode_composite,
            input_enabled=True,
            target_va=self._native_binocs_draw_va,
            post_clear_surface_va=system_va + self._off_composite_surface,
            post_clear_bltfx_va=system_va + self._off_bltfx,
            post_clear_rect_vas=(
                system_va + self._off_left_bar_rect,
                system_va + self._off_right_bar_rect,
            ),
        )
        show_wrapper = fixed_screens.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=1,
            target_va=self._native_show_va,
            wrapper_va=lifecycle.show_va,
        )
        hide_wrapper = fixed_screens.build_state_wrapper(
            state_va=system_va + self._off_input_active,
            value=0,
            target_va=self._native_hide_va,
            wrapper_va=lifecycle.hide_va,
        )
        destructor_wrapper = fixed_screens.build_destructor_wrapper(
            wrapper_va=lifecycle.destructor_va,
            render_depth_va=system_va + self._off_render_depth,
            input_active_va=system_va + self._off_input_active,
            clear_pending_va=system_va + self._off_clear_pending,
            root_ptr_va=system_va + self._off_root_ptr,
            transform_mode_va=system_va + self._off_transform_mode,
            target_va=self._native_binocs_destructor_va,
        )
        for label, offset, code, limit in (
            (
                "Binocular root",
                self._off_binocs_root_draw_wrapper,
                root_wrapper,
                self._off_binocs_show_wrapper,
            ),
            (
                "Binocular show",
                self._off_binocs_show_wrapper,
                show_wrapper,
                self._off_binocs_hide_wrapper,
            ),
            (
                "Binocular hide",
                self._off_binocs_hide_wrapper,
                hide_wrapper,
                self._off_binocs_destructor_wrapper,
            ),
            (
                "Binocular destructor",
                self._off_binocs_destructor_wrapper,
                destructor_wrapper,
                self._off_loadgame_root_draw_wrapper,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        return lifecycle

    def plan_hooks(
        self,
        plan: ExecutableMutationPlan,
        *,
        lifecycle: ScreenLifecycleTargets,
    ) -> None:
        """Own all four binocular screen lifecycle redirects."""
        site = self.profile.site("bitmap.dimensions_return")
        plan.branch(
            label="Binocular logical bitmap dimensions",
            opcode=BranchOpcode.JUMP,
            site_va=site.va,
            expected=site.original,
            target_va=self.symbols.va(BINOCULAR_SEGMENT.logical_name, BINOCULAR_SIZE_HELPER_OFFSET),
            size=len(site.original),
        )
        for edge, slot_va, expected_va, target_va in (
            ("draw", self._binocs_draw_slot_va, self._native_binocs_draw_va, lifecycle.draw_va),
            ("show", self._binocs_show_slot_va, self._native_show_va, lifecycle.show_va),
            ("hide", self._binocs_hide_slot_va, self._native_hide_va, lifecycle.hide_va),
            (
                "destructor",
                self._binocs_destructor_slot_va,
                self._native_binocs_destructor_va,
                lifecycle.destructor_va,
            ),
        ):
            plan.pointer(
                label=f"Binocular {edge}",
                slot_va=slot_va,
                expected=expected_va,
                target_va=target_va,
            )

    def build_binocs_local_blt_helper(
        self,
        *,
        wrapper_va: int,
        root_ptr_va: int,
        target_rect_va: int,
        dest_rect_va: int,
        valid_va: int,
        owner_root_va: int,
        source_group_rect_va: int,
        target_group_rect_va: int,
        transform_count_va: int,
    ) -> bytes:
        """Keep Binocs' four arrow sprites registered to their local D-pad.

        GK3 lays out Binocs against the live framebuffer, but its four arrow
        objects retain authored pixel offsets from the separately drawn D-pad
        backing. The generic composite affine scales each transfer about its
        own screen-space centre, so it enlarges both pieces without enlarging
        their local offsets. The backing's embedded arrows and active button
        sprites consequently separate into doubled controls.

        Discover the exact four command objects from the live child vector,
        derive their union, and apply one local affine to a matching final
        transfer. Publish the same source/target union for pointer dispatch.
        No output resolution, allocation address, bitmap name, or child index
        is part of the policy.

        ``ECX`` points to the outer blitter's PUSHAD frame. ``EAX`` returns one
        only after this helper has replaced ``dest_rect_va``.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\x8b\xe9")  # PUSHAD; EBP = outer blitter frame.
        code.raw(b"\xc7\x44\x24\x1c\x00\x00\x00\x00")
        code.raw(b"\x8b\x35" + struct.pack("<I", root_ptr_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x81\x3e" + struct.pack("<I", self.profile.address("binocular.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "done")

        # Binocs owns one direct container child. Consume GK3's bounded
        # pointer/count vectors instead of relying on allocation adjacency.
        code.raw(b"\x8b\x7e\x4c\x8b\x4e\x50\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x83\xf9\x01")
        code.jump_if(Condition.LESS, "done")
        code.raw(b"\x83\xf9\x20")
        code.jump_if(Condition.GREATER, "done")
        code.raw(b"\x8b\x37\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x8b\x7e\x4c\x8b\x4e\x50\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.LESS_OR_EQUAL, "done")
        code.raw(b"\x83\xf9\x20")
        code.jump_if(Condition.GREATER, "done")

        code.raw(b"\xc7\x05" + struct.pack("<I", source_group_rect_va))
        code.raw(b"\xff\xff\xff\x7f")
        code.raw(b"\xc7\x05" + struct.pack("<I", source_group_rect_va + 4))
        code.raw(b"\xff\xff\xff\x7f")
        code.raw(b"\xc7\x05" + struct.pack("<I", source_group_rect_va + 8))
        code.raw(b"\x00\x00\x00\x80")
        code.raw(b"\xc7\x05" + struct.pack("<I", source_group_rect_va + 12))
        code.raw(b"\x00\x00\x00\x80")
        code.raw(b"\x31\xdb")  # EBX = number of discovered arrow commands.

        code.label("child_loop")
        code.raw(b"\x8b\x17\x85\xd2")
        code.jump_if(Condition.EQUAL, "next_child")
        code.raw(b"\x81\x3a" + struct.pack("<I", self.profile.address("ui.button_vtable")))
        code.jump_if(Condition.NOT_EQUAL, "next_child")
        code.raw(b"\x8b\x82\x8c\x00\x00\x00\x48\x83\xf8\x03")
        code.jump_if(Condition.ABOVE, "next_child")
        code.raw(b"\x43")

        for displacement, condition, label in (
            (0, Condition.GREATER_OR_EQUAL, "left_kept"),
            (4, Condition.GREATER_OR_EQUAL, "top_kept"),
            (8, Condition.LESS_OR_EQUAL, "right_kept"),
            (12, Condition.LESS_OR_EQUAL, "bottom_kept"),
        ):
            code.raw(b"\x8b\x42" + bytes([0x1C + displacement]))
            code.raw(b"\x3b\x05" + struct.pack("<I", source_group_rect_va + displacement))
            code.jump_short_if(condition, label)
            code.raw(b"\xa3" + struct.pack("<I", source_group_rect_va + displacement))
            code.label(label)

        # Mark only a transfer whose incoming rectangle is one of those four
        # command objects; unrelated small sprites retain the generic affine.
        code.raw(b"\x8b\x75\x28")
        for displacement in range(0, 16, 4):
            code.raw(b"\x8b\x46" + bytes([displacement]))
            code.raw(b"\x3b\x42" + bytes([0x1C + displacement]))
            code.jump_if(Condition.NOT_EQUAL, "next_child")
        code.raw(b"\xc7\x44\x24\x1c\x01\x00\x00\x00")

        code.label("next_child")
        code.raw(b"\x83\xc7\x04\x49")
        code.jump_if(Condition.NOT_EQUAL, "child_loop")
        code.raw(b"\x83\xfb\x04")
        code.jump_if(Condition.NOT_EQUAL, "not_owned")
        code.raw(b"\x83\x7c\x24\x1c\x00")
        code.jump_if(Condition.EQUAL, "not_owned")

        def emit_local_axis(
            *,
            input_rect_va: int,
            output_rect_va: int,
            near: int,
            far: int,
            physical_size_va: int,
        ) -> None:
            """Emit one axis of the D-pad-relative affine."""
            # EBX = authored group centre.
            code.raw(b"\x8b\x1d" + struct.pack("<I", source_group_rect_va + near))
            code.raw(b"\x03\x1d" + struct.pack("<I", source_group_rect_va + far))
            code.raw(b"\xd1\xfb")
            # EDI = group centre after the ordinary full-composite mapping.
            code.raw(b"\x8b\xc3")
            code.raw(b"\x8b\x0d" + struct.pack("<I", target_rect_va + far))
            code.raw(b"\x2b\x0d" + struct.pack("<I", target_rect_va + near))
            code.raw(b"\x0f\xaf\xc1\x99")
            code.raw(b"\x8b\x0d" + struct.pack("<I", physical_size_va) + b"\xf7\xf9")
            code.raw(b"\x03\x05" + struct.pack("<I", target_rect_va + near) + b"\x8b\xf8")
            # Add the input centre's local offset at target-height/768 scale.
            code.raw(b"\x8b\x35" + struct.pack("<I", input_rect_va + near))
            code.raw(b"\x03\x35" + struct.pack("<I", input_rect_va + far) + b"\xd1\xfe")
            code.raw(b"\x2b\xf3\x8b\xc6")
            code.raw(b"\x8b\x0d" + struct.pack("<I", target_rect_va + 12))
            code.raw(b"\x2b\x0d" + struct.pack("<I", target_rect_va + 4))
            code.raw(b"\x0f\xaf\xc1\x99\xb9\x00\x03\x00\x00\xf7\xf9\x03\xf8")
            # Scale the input extent through that exact same local ratio.
            code.raw(b"\xa1" + struct.pack("<I", input_rect_va + far))
            code.raw(b"\x2b\x05" + struct.pack("<I", input_rect_va + near))
            code.raw(b"\x8b\x0d" + struct.pack("<I", target_rect_va + 12))
            code.raw(b"\x2b\x0d" + struct.pack("<I", target_rect_va + 4))
            code.raw(b"\x0f\xaf\xc1\x99\xb9\x00\x03\x00\x00\xf7\xf9")
            code.raw(b"\x8b\xc8\xd1\xf8\x2b\xf8")
            code.raw(b"\x89\x3d" + struct.pack("<I", output_rect_va + near))
            code.raw(b"\x03\xcf\x89\x0d" + struct.pack("<I", output_rect_va + far))

        for input_va, output_va in (
            (source_group_rect_va, target_group_rect_va),
            (0, dest_rect_va),
        ):
            actual_input_va = input_va
            if input_va == 0:
                # Copy the caller-owned incoming RECT before overwriting it.
                code.raw(b"\x8b\x75\x28\xbf" + struct.pack("<I", dest_rect_va))
                code.raw(b"\xb9\x04\x00\x00\x00\xf3\xa5")
                actual_input_va = dest_rect_va
            emit_local_axis(
                input_rect_va=actual_input_va,
                output_rect_va=output_va,
                near=0,
                far=8,
                physical_size_va=self._physical_width_va,
            )
            emit_local_axis(
                input_rect_va=actual_input_va,
                output_rect_va=output_va,
                near=4,
                far=12,
                physical_size_va=self._physical_width_va + 4,
            )

        code.raw(b"\xa1" + struct.pack("<I", root_ptr_va))
        code.raw(b"\xa3" + struct.pack("<I", owner_root_va))
        code.raw(b"\xff\x05" + struct.pack("<I", transform_count_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", valid_va) + b"\x01\x00\x00\x00")
        code.jump("done")

        code.label("not_owned")
        code.raw(b"\xc7\x44\x24\x1c\x00\x00\x00\x00")
        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()

    @staticmethod
    def build_binocs_input_helper(
        *,
        wrapper_va: int,
        generic_input_wrapper_va: int,
        root_ptr_va: int,
        binocular_vtable_va: int,
        valid_va: int,
        owner_root_va: int,
        source_group_rect_va: int,
        target_group_rect_va: int,
        transform_count_va: int,
    ) -> bytes:
        """Apply the exact inverse of the local D-pad affine to input.

        Events outside the published D-pad union tail-enter the ordinary
        full-composite inverse, which fixes Binocs' Exit/Zoom hit rectangles as
        well. The native MouseManager point is restored before returning so
        cursor producers remain in physical framebuffer coordinates.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x50")  # retain EAX, the native event target.
        code.raw(b"\x83\x3d" + struct.pack("<I", valid_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "generic_restore")
        code.raw(b"\x8b\x15" + struct.pack("<I", root_ptr_va) + b"\x85\xd2")
        code.jump_if(Condition.EQUAL, "generic_restore")
        code.raw(b"\x3b\x15" + struct.pack("<I", owner_root_va))
        code.jump_if(Condition.NOT_EQUAL, "generic_restore")
        code.raw(b"\x81\x3a" + struct.pack("<I", binocular_vtable_va))
        code.jump_if(Condition.NOT_EQUAL, "generic_restore")
        code.raw(b"\x8b\x54\x24\x08\x85\xd2")
        code.jump_if(Condition.EQUAL, "generic_restore")

        code.raw(b"\x8b\x02")
        code.raw(b"\x3b\x05" + struct.pack("<I", target_group_rect_va))
        code.jump_if(Condition.LESS, "generic_restore")
        code.raw(b"\x3b\x05" + struct.pack("<I", target_group_rect_va + 8))
        code.jump_if(Condition.GREATER_OR_EQUAL, "generic_restore")
        code.raw(b"\x8b\x42\x04")
        code.raw(b"\x3b\x05" + struct.pack("<I", target_group_rect_va + 4))
        code.jump_if(Condition.LESS, "generic_restore")
        code.raw(b"\x3b\x05" + struct.pack("<I", target_group_rect_va + 12))
        code.jump_if(Condition.GREATER_OR_EQUAL, "generic_restore")

        code.raw(b"\x58")  # restore the native target before normal prologue.
        code.raw(b"\x53\x56\x57\x55\x51")
        code.raw(b"\x8b\xf8\x8b\x74\x24\x18\x8b\x1e\x8b\x6e\x04")
        for source_value, point_offset, near, far in (
            (b"\x8b\xc3", 0, 0, 8),
            (b"\x8b\xc5", 4, 4, 12),
        ):
            code.raw(source_value)
            code.raw(b"\x2b\x05" + struct.pack("<I", target_group_rect_va + near))
            code.raw(b"\x8b\x0d" + struct.pack("<I", source_group_rect_va + far))
            code.raw(b"\x2b\x0d" + struct.pack("<I", source_group_rect_va + near))
            code.raw(b"\x0f\xaf\xc1\x99")
            code.raw(b"\x8b\x0d" + struct.pack("<I", target_group_rect_va + far))
            code.raw(b"\x2b\x0d" + struct.pack("<I", target_group_rect_va + near))
            code.raw(b"\xf7\xf9")
            code.raw(b"\x03\x05" + struct.pack("<I", source_group_rect_va + near))
            if point_offset == 0:
                code.raw(b"\x89\x06")
            else:
                code.raw(b"\x89\x46\x04")
        code.raw(b"\xff\x05" + struct.pack("<I", transform_count_va))
        code.raw(b"\x59\xff\x74\x24\x14\xff\xd7")
        code.raw(b"\x89\x1e\x89\x6e\x04\x5d\x5f\x5e\x5b\xc2\x04\x00")

        code.label("generic_restore")
        code.raw(b"\x58")
        code.jump_absolute(generic_input_wrapper_va)
        return code.build()
