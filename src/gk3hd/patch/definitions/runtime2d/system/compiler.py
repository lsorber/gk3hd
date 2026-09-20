"""Compile fixed system-screen policies into the shared runtime."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, encode_rel32_branch
from gk3hd.patch.definitions.runtime2d.font_bank import install_font_bank_adapter
from gk3hd.patch.definitions.runtime2d.layout import (
    BINOCULAR_SEGMENT,
    CURSOR_BLEND_SEGMENT,
    FONT_BANK_SEGMENT,
    LOAD_SAVE_BUTTON_SEGMENT,
    LOAD_SAVE_SEGMENT,
    SYSTEM_ACTION_LAYOUT_STATE_END_OFFSET,
    SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET,
    SYSTEM_CONTROL_HD_FONT_STATE_END_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_SEGMENT,
    UI_FILTER_SEGMENT,
    UI_FRAMES_SEGMENT,
    ZODIAC_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.system.binoculars import BinocularFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.blit_dispatch import BlitDispatchCompiler
from gk3hd.patch.definitions.runtime2d.system.bordered_screens import BorderedScreenFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.cursor import CursorFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.cursor_blend import install_blend_adapter
from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.load_save import LoadSaveFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.load_save_buttons import LoadSaveButtonCompiler
from gk3hd.patch.definitions.runtime2d.system.menus import MenuFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.room_status import RoomStatusFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext
from gk3hd.patch.definitions.runtime2d.system.zodiac import ZodiacFeatureCompiler
from gk3hd.patch.definitions.runtime2d.ui_filter import install_area_adapter
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile


@dataclass(frozen=True, slots=True, kw_only=True)
class SystemScreenCompiler(SystemCompilerContext):
    """Coordinate system-screen features behind the shared 2D dispatcher.

    Outcome:
        Death, Finished, binocular, Load/Save, title, confirmation, close-up,
        fingerprint, cursor, status, and menu owners compose coherently at the
        reference-relative scale.
    Before:
        These layers share final-blit, cursor, font, pointer, and lifetime entry
        points while using different combinations of authored and physical
        coordinates. Independent redirects become order-dependent.
    After:
        Feature compilers build their own payloads and native-hook plans against
        one immutable runtime context; this facade composes those bounded plans
        and verifies the resulting dispatch graph.
    Strategy:
        Allocate bounded logical segments, ask each feature owner for machine
        code, validate non-overlap, install class-scoped roots and dispatchers,
        and reconstruct the same payloads during postcheck.
    Boundaries:
        Feature-specific geometry belongs in its feature module. Ordinary room
        camera width, native Flip, refresh selection, and resource discovery are
        owned by adjacent patches.
    """

    def menu_feature(self) -> MenuFeatureCompiler:
        """Return the menu-domain compiler bound to this immutable runtime context."""
        return MenuFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def cursor_feature(self) -> CursorFeatureCompiler:
        """Return the cursor-domain compiler bound to this immutable runtime context."""
        return CursorFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def room_status_feature(self) -> RoomStatusFeatureCompiler:
        """Return the room-status compiler bound to this immutable runtime context."""
        return RoomStatusFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def load_save_feature(self) -> LoadSaveFeatureCompiler:
        """Return the Load/Save compiler bound to this immutable runtime context."""
        return LoadSaveFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def binocular_feature(self) -> BinocularFeatureCompiler:
        """Return the binocular compiler bound to this immutable runtime context."""
        return BinocularFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def fixed_screen_feature(self) -> FixedScreenFeatureCompiler:
        """Return the bounded-screen compiler for this immutable runtime context."""
        return FixedScreenFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def blit_dispatch_feature(self) -> BlitDispatchCompiler:
        """Return the shared final-blit dispatcher for this runtime context."""
        return BlitDispatchCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        )

    def precheck(self, pe: PEFile) -> None:
        """Require empty owned segments before compiling the complete plan.

        Feature-owned mutation plans validate all native source bytes together
        during clone compilation, before committing any external redirect.
        """
        self._hd_wrapper_va()
        for segment in (
            SYSTEM_SEGMENT,
            SYSTEM_CONTROL_SEGMENT,
            LOAD_SAVE_SEGMENT,
            LOAD_SAVE_BUTTON_SEGMENT,
            UI_FILTER_SEGMENT,
            BINOCULAR_SEGMENT,
            UI_FRAMES_SEGMENT,
            ZODIAC_SEGMENT,
            CURSOR_BLEND_SEGMENT,
            FONT_BANK_SEGMENT,
        ):
            if pe.get_section(segment.logical_name) is not None:
                msg = f"{self.id} requires a pristine {segment.logical_name} section"
                raise PatchError(msg)

    def apply(self, pe: PEFile) -> None:
        """Emit system, control, Load/Save, cursor, and HUD wrappers."""
        menu = self.menu_feature()
        cursor = self.cursor_feature()
        room_status = self.room_status_feature()
        load_save = self.load_save_feature()
        binoculars = self.binocular_feature()
        fixed_screens = self.fixed_screen_feature()
        blit_dispatch = self.blit_dispatch_feature()
        section = install_runtime_segment(pe, SYSTEM_SEGMENT)
        control_section = install_runtime_segment(pe, SYSTEM_CONTROL_SEGMENT)
        loadsave_section = install_runtime_segment(pe, LOAD_SAVE_SEGMENT)
        binocular_section = install_runtime_segment(pe, BINOCULAR_SEGMENT)

        section_offset = section.pointer_to_raw_data
        section_va = pe.rva_to_va(section.virtual_address)
        control_section_offset = control_section.pointer_to_raw_data
        control_section_va = pe.rva_to_va(control_section.virtual_address)
        loadsave_section_offset = loadsave_section.pointer_to_raw_data
        loadsave_section_va = pe.rva_to_va(loadsave_section.virtual_address)
        binocular_section_offset = binocular_section.pointer_to_raw_data
        binocular_section_va = pe.rva_to_va(binocular_section.virtual_address)
        system_payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=SYSTEM_SEGMENT.logical_name,
            size=SYSTEM_SEGMENT.size,
        )
        control_payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=SYSTEM_CONTROL_SEGMENT.logical_name,
            size=SYSTEM_CONTROL_SEGMENT.size,
        )
        loadsave_payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=LOAD_SAVE_SEGMENT.logical_name,
            size=LOAD_SAVE_SEGMENT.size,
        )
        binocular_payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=BINOCULAR_SEGMENT.logical_name,
            size=BINOCULAR_SEGMENT.size,
        )
        loadsave = load_save.emit_segment(
            loadsave_payload,
            system_va=section_va,
            control_va=control_section_va,
            loadsave_va=loadsave_section_va,
            cursor=cursor,
        )
        binocs_local_blt_helper_va = binoculars.emit_segment(
            binocular_payload,
            binocular_va=binocular_section_va,
            system_va=section_va,
        )
        primary_screens = fixed_screens.emit_primary_lifecycles(
            system_payload,
            system_va=section_va,
            control_va=control_section_va,
        )
        control_screens = fixed_screens.emit_control_lifecycles(
            control_payload,
            system_va=section_va,
            control_va=control_section_va,
        )
        loadsave_lifecycle = load_save.emit_lifecycle(
            system_payload,
            control_payload,
            system_va=section_va,
            control_va=control_section_va,
            loadsave_va=loadsave_section_va,
            segment=loadsave,
            fixed_screens=fixed_screens,
            font_bank=install_font_bank_adapter(
                pe,
                profile=self.profile,
                target_va=control_section_va + self._off_control_font_wrapper,
                active_handle_va=control_section_va + self._off_control_hd_font_active,
            ),
        )
        room_status.emit_state(control_payload, control_va=control_section_va)
        menu.emit_state(
            system_payload,
            control_payload,
            control_va=control_section_va,
        )
        fixed_screens.emit_state(control_payload)
        cursor.emit_state(control_payload)
        install_blend_adapter(pe, profile=self.profile)
        cursor_runtime = cursor.emit_primitives(
            system_payload,
            control_payload,
            system_va=section_va,
            control_va=control_section_va,
        )
        dropdown_runtime = menu.emit_dropdown_runtime(
            control_payload,
            system_va=section_va,
            control_va=control_section_va,
        )
        action_runtime = menu.emit_action_runtime(
            system_payload,
            control_payload,
            system_va=section_va,
            control_va=control_section_va,
            dropdown=dropdown_runtime,
            cursor_surface_classifier_va=cursor_runtime.surface_classifier_va,
            fixed_screens=fixed_screens,
        )
        tooltip_runtime = menu.emit_tooltip_runtime(
            control_payload,
            system_va=section_va,
            control_va=control_section_va,
            action=action_runtime,
        )
        binocs_lifecycle = binoculars.emit_lifecycle(
            system_payload,
            system_va=section_va,
            fixed_screens=fixed_screens,
        )
        blt_entry_va = section_va + self._off_blt_wrapper
        blt_wrapper_va = control_section_va + self._off_control_blt_wrapper
        room_text_draw_wrapper_va = control_section_va + self._off_room_text_draw_wrapper
        room_status_fill_wrapper_va = control_section_va + self._off_room_status_fill_wrapper
        room_text_draw_wrapper = room_status.build_room_text_draw_wrapper(
            wrapper_va=room_text_draw_wrapper_va,
            object_ptr_va=control_section_va + self._off_room_status_object_ptr,
            present_depth_va=control_section_va + self._off_room_status_present_depth,
            draw_count_va=control_section_va + self._off_room_status_present_count,
        )
        room_status_fill_wrapper = room_status.build_room_status_fill_wrapper(
            wrapper_va=room_status_fill_wrapper_va,
            present_depth_va=control_section_va + self._off_room_status_present_depth,
            fill_count_va=control_section_va + self._off_room_status_defer_count,
        )
        cursor_frame_presenter_va = cursor.emit_frame_presenter(
            control_payload,
            control_va=control_section_va,
            loadsave_va=loadsave_section_va,
            action_lifetime_helper_va=action_runtime.action_lifetime_helper_va,
            tooltip_frame_presenter_va=tooltip_runtime.frame_presenter_va,
            loadsave_frame_presenter_va=loadsave.frame_presenter_va,
            closeup_frame_presenter_va=control_screens.closeup_frame_presenter_va,
        )
        blt_wrapper = blit_dispatch.build_blt_wrapper(
            wrapper_va=blt_wrapper_va,
            downstream_va=install_area_adapter(
                pe, profile=self.profile, native_va=self._hd_wrapper_va()
            ),
            render_depth_va=section_va + self._off_render_depth,
            input_active_va=section_va + self._off_input_active,
            transform_mode_va=section_va + self._off_transform_mode,
            root_ptr_va=section_va + self._off_root_ptr,
            clear_pending_va=section_va + self._off_clear_pending,
            transform_count_va=section_va + self._off_transform_count,
            composite_surface_va=section_va + self._off_composite_surface,
            source_rect_va=section_va + self._off_source_rect,
            target_rect_va=section_va + self._off_target_rect,
            dest_rect_va=section_va + self._off_dest_rect,
            bltfx_va=section_va + self._off_bltfx,
            left_bar_rect_va=section_va + self._off_left_bar_rect,
            right_bar_rect_va=section_va + self._off_right_bar_rect,
            hud_font_active_va=loadsave_section_va + self._off_hud_font_active,
            hud_font_point_va=loadsave_section_va + self._off_hud_font_last_point,
            hud_transform_count_va=section_va + self._off_hud_transform_count,
            hud_last_rect_va=section_va + self._off_hud_last_rect,
            hd_font_active_va=control_section_va + self._off_control_hd_font_active,
            hd_font_source_rect_va=control_section_va + self._off_control_hd_font_source_rect,
            hd_font_source_transform_count_va=(
                control_section_va + self._off_control_hd_font_source_transform_count
            ),
            toolbar_blt_helper_va=action_runtime.toolbar_blt_helper_va,
            loadsave_background_helper_va=loadsave.background_helper_va,
            cursor_surface_classifier_va=cursor_runtime.surface_classifier_va,
            tooltip_draw_depth_va=control_section_va + self._off_tooltip_draw_depth,
            tooltip_transfer_affine_va=tooltip_runtime.transfer_affine_va,
            binocs_local_blt_helper_va=binocs_local_blt_helper_va,
        )
        blt_entry = encode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=blt_entry_va,
            target_va=blt_wrapper_va,
        )
        for label, offset, payload, limit in (
            (
                "blitter entry",
                self._off_blt_wrapper,
                blt_entry,
                self._off_death_button_layout,
            ),
        ):
            system_payload.place(label=label, offset=offset, payload=payload, limit=limit)
        if self._off_cursor_scope_wrapper < SYSTEM_ACTION_LAYOUT_STATE_END_OFFSET:
            msg = f"{self.id} ActionMenu layout state overlaps system code"
            raise PatchError(msg)

        for label, offset, payload, limit in (
            (
                "blitter",
                self._off_control_blt_wrapper,
                blt_wrapper,
                self._off_action_layout_helper,
            ),
            (
                "room status TextBox draw wrapper",
                self._off_room_text_draw_wrapper,
                room_text_draw_wrapper,
                self._off_room_text_draw_wrapper_limit,
            ),
            (
                "room status backing-fill affine",
                self._off_room_status_fill_wrapper,
                room_status_fill_wrapper,
                self._off_room_status_fill_wrapper_limit,
            ),
        ):
            control_payload.place(label=label, offset=offset, payload=payload, limit=limit)
        bltfx = bytearray(self._ddbltfx_size)
        struct.pack_into("<I", bltfx, 0, self._ddbltfx_size)
        system_payload.place(label="magic", offset=0, payload=self._magic)
        system_payload.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._layout_version),
        )
        system_payload.reserve(
            label="root traversal state", offset=self._off_render_depth, size=0x44
        )
        system_payload.reserve(label="transform scratch", offset=self._off_transform_mode, size=32)
        system_payload.place(label="fill descriptor", offset=self._off_bltfx, payload=bytes(bltfx))
        system_payload.reserve(
            label="composite surface publication",
            offset=self._off_composite_surface,
            size=4,
        )

        control_payload.place(label="magic", offset=0, payload=self._control_magic)
        control_payload.place(
            label="layout version",
            offset=self._off_control_layout_version,
            payload=struct.pack("<I", self._control_layout_version),
        )
        control_payload.reserve(
            label="clipped source rectangle",
            offset=self._off_control_clipped_source_rect,
            size=16,
        )
        control_full_damage_rect_va = control_section_va + self._off_control_full_damage_rect
        control_payload.place(
            label="complete damage collection",
            offset=self._off_control_full_damage_region,
            payload=struct.pack(
                "<IIII",
                0,
                control_full_damage_rect_va,
                control_full_damage_rect_va + 16,
                0,
            )
            + bytes(16),
        )
        control_payload.reserve(
            label="HD font transaction state",
            offset=SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET,
            size=SYSTEM_CONTROL_HD_FONT_STATE_END_OFFSET - SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET,
        )
        # Commit each validated logical segment as one deterministic image.
        pe.write_bytes(section_offset, system_payload.build())
        pe.write_bytes(control_section_offset, control_payload.build())
        pe.write_bytes(loadsave_section_offset, loadsave_payload.build())
        pe.write_bytes(binocular_section_offset, binocular_payload.build())
        mutations = ExecutableMutationPlan(owner=self.id)
        cursor.plan_hooks(
            mutations,
            frame_presenter_va=cursor_frame_presenter_va,
            capacity_wrapper_va=cursor_runtime.capacity_wrapper_va,
            scope_wrapper_va=cursor_runtime.scope_wrapper_va,
            prep_wrapper_va=cursor_runtime.prep_wrapper_va,
            final_wrapper_va=cursor_runtime.final_wrapper_va,
            manager_draw_wrapper_va=cursor_runtime.manager_draw_wrapper_va,
            bounds_wrapper_va=cursor_runtime.bounds_wrapper_va,
            resource_rebuild_wrapper_va=cursor_runtime.resource_rebuild_wrapper_va,
        )
        fixed_screens.plan_hooks(
            mutations,
            death=primary_screens.death,
            death_button_layout_va=primary_screens.death_button_layout_va,
            finished_draw_va=primary_screens.finished_draw_va,
            finished_destructor_va=primary_screens.finished_destructor_va,
            pause_draw_va=primary_screens.pause_draw_va,
            title=control_screens.title,
            confirm_quit=control_screens.confirm_quit,
            closeup=control_screens.closeup,
            fingerprint=control_screens.fingerprint,
            title_cache_wrapper_va=control_screens.title_cache_wrapper_va,
            physical_backdrop_wrapper_va=(control_screens.physical_backdrop_wrapper_va),
            console_draw_scope_va=control_screens.console_draw_scope_va,
            confirm_quit_post_flip_presenter_va=(
                control_screens.confirm_quit_post_flip_presenter_va
            ),
        )
        binoculars.plan_hooks(
            mutations,
            lifecycle=binocs_lifecycle,
        )
        load_save.plan_hooks(
            mutations,
            root_wrapper_va=loadsave_lifecycle.root_wrapper_va,
            show_wrapper_va=loadsave_lifecycle.show_wrapper_va,
            hide_wrapper_va=loadsave_lifecycle.hide_wrapper_va,
            load_destructor_wrapper_va=loadsave_lifecycle.load_destructor_wrapper_va,
            save_destructor_wrapper_va=loadsave_lifecycle.save_destructor_wrapper_va,
            layout_wrapper_va=loadsave.layout_wrapper_va,
            preview_attach_va=loadsave.preview_attach_va,
            font_entry_va=loadsave_lifecycle.font_entry_va,
            font_metrics_wrapper_va=loadsave_lifecycle.font_metrics_wrapper_va,
            text_draw_wrapper_va=loadsave_lifecycle.text_draw_wrapper_va,
            progress_background_wrapper_va=loadsave.progress_background_wrapper_va,
            progress_initial_show_wrapper_va=loadsave.progress_initial_show_wrapper_va,
            progress_canvas_update_wrapper_va=loadsave.progress_canvas_update_wrapper_va,
            scrollbar_input_stub_vas=loadsave.scrollbar_input_stub_vas,
            scrollbar_hit_test_wrapper_va=loadsave.scrollbar_hit_test_wrapper_va,
            scrollbar_arrow_left_down_stub_va=loadsave.scrollbar_arrow_left_down_stub_va,
            scrollbar_arrow_release_va=loadsave.scrollbar_arrow_release_va,
            scrollbar_thumb_move_stub_va=loadsave.scrollbar_thumb_move_stub_va,
        )
        menu.plan_hooks(
            mutations,
            action_root_wrapper_va=action_runtime.action_root_wrapper_va,
            action_destructor_wrapper_va=action_runtime.action_destructor_wrapper_va,
            toolbar_root_wrapper_va=action_runtime.toolbar_root_wrapper_va,
            toolbar_destructor_wrapper_va=action_runtime.toolbar_destructor_wrapper_va,
            toolbar_layout_va=action_runtime.toolbar_layout_va,
            toolbar_cursor_warp_va=action_runtime.toolbar_cursor_warp_va,
            tooltip_visibility_wrapper_va=tooltip_runtime.visibility_wrapper_va,
            tooltip_draw_wrapper_va=tooltip_runtime.draw_wrapper_va,
            dropdown_draw_wrapper_va=dropdown_runtime.draw_wrapper_va,
            dropdown_visibility_wrapper_va=dropdown_runtime.visibility_wrapper_va,
            dropdown_highlight_wrapper_va=dropdown_runtime.highlight_wrapper_va,
            tooltip_base_wrapper_va=tooltip_runtime.base_wrapper_va,
            tooltip_border_wrapper_va=tooltip_runtime.border_wrapper_va,
            modal_tooltip_resolver_va=tooltip_runtime.modal_resolver_va,
            fixed_layer_epilogue_wrapper_va=tooltip_runtime.fixed_layer_epilogue_va,
        )
        room_status.plan_hooks(
            mutations,
            draw_wrapper_va=room_text_draw_wrapper_va,
            fill_wrapper_va=room_status_fill_wrapper_va,
        )
        mutations.apply(pe)
        LoadSaveButtonCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        ).apply(pe)
        BorderedScreenFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        ).apply(pe)
        ZodiacFeatureCompiler(
            symbols=self.symbols,
            profile=self.profile,
            room_rendering_abi=self.room_rendering_abi,
            transition_abi=self.transition_abi,
        ).apply(pe)

    def postcheck(self, pe: PEFile) -> None:
        """Verify that this feature owns each declared runtime segment.

        Complete byte verification belongs to :class:`Runtime2DCompiler`,
        which deterministically rebuilds all segments and executable redirects
        after every feature has composed its shared hooks. Repeating that build
        here previously duplicated most of :meth:`apply` and made verification
        itself a second, independently drifting implementation.
        """
        for segment in (
            SYSTEM_SEGMENT,
            SYSTEM_CONTROL_SEGMENT,
            LOAD_SAVE_SEGMENT,
            BINOCULAR_SEGMENT,
            UI_FRAMES_SEGMENT,
            UI_FILTER_SEGMENT,
            ZODIAC_SEGMENT,
            CURSOR_BLEND_SEGMENT,
            FONT_BANK_SEGMENT,
        ):
            section = pe.get_section(segment.logical_name)
            if section is None:
                msg = f"{self.id} postcheck failed: missing {segment.logical_name} segment"
                raise PatchError(msg)
            if pe.read_bytes(section.pointer_to_raw_data, len(segment.magic)) != segment.magic:
                msg = f"{self.id} postcheck failed: invalid {segment.logical_name} magic"
                raise PatchError(msg)
