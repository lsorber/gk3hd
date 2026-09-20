"""Compile fitted Inventory layout and backing into the shared runtime."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.fingerprint_alpha import install_alpha_adapter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH
from gk3hd.patch.definitions.runtime2d.inventory_alpha import (
    build_effect_constructor_wrapper,
    build_item_draw_wrapper,
    build_scaled_alpha_callback,
    build_scaled_font_alpha_callback,
)
from gk3hd.patch.definitions.runtime2d.inventory_filter import install_area_adapter
from gk3hd.patch.definitions.runtime2d.layout import (
    FINGERPRINT_HD_SET_ACTIVE_OFFSET,
    FINGERPRINT_SEGMENT,
    FONT_BANK_ALPHA_SELECT_OFFSET,
    FONT_BANK_SEGMENT,
    INVENTORY_ACTIVE_ROOT_OFFSET,
    INVENTORY_ALPHA_CONSTRUCTOR_OFFSET,
    INVENTORY_ALPHA_HEIGHT_OFFSET,
    INVENTORY_ALPHA_OUTPUT_RECT_OFFSET,
    INVENTORY_ALPHA_SOURCE_RECT_OFFSET,
    INVENTORY_ALPHA_WIDTH_OFFSET,
    INVENTORY_FONT_ALPHA_VTABLE_OFFSET,
    INVENTORY_NAVIGATION_CLEAR_OFFSET,
    INVENTORY_NAVIGATION_SEGMENT,
    INVENTORY_SEGMENT,
    LOAD_SAVE_HUD_FONT_ACTIVE_OFFSET,
    LOAD_SAVE_HUD_FONT_ALPHA_TRANSFORM_COUNT_OFFSET,
    LOAD_SAVE_HUD_FONT_POINT_OFFSET,
    LOAD_SAVE_SEGMENT,
    SIDNEY_ALPHA_CONSTRUCTOR_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET,
    SYSTEM_CONTROL_HD_FONT_SOURCE_TRANSFORM_COUNT_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    SYSTEM_ROOT_POINTER_OFFSET,
    SYSTEM_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.ui_alpha import (
    install_alpha_adapter as install_ui_alpha_adapter,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
    from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI


@dataclass(frozen=True, slots=True, kw_only=True)
class InventoryFeatureCompiler:
    """Fit Inventory's composite layer while preserving its live room backing.

    Outcome:
        Inventory items, Exit, nested ActionMenu, hover targets, and transparency
        match the 1024x768 composition over a complete widescreen room capture.
    Before:
        GK3 mixes physical grid layout with authored art and hit rectangles; its
        software-alpha item path also bypasses the shared final-blit transform.
    After:
        Inventory owns one 1024x768 logical model and inverse affine, while its
        captured-room child remains full-physical and clean on both flip pages.
    Strategy:
        Retain logical item/Exit rectangles in the centered reference canvas. For
        the alpha-only path, preserve GK3's locks, clipping, tiling, and cleanup,
        but sample item and mask into the fitted final-page destination. Dense
        item reduction uses the renderer's exact area-blend capability; native
        images retain their original point sampling. Once per Inventory lifetime, refresh
        only the stock room-capture child from the private 3D stage, then give the
        concrete Draw hook one complete damage traversal for page coherence.
    Boundaries:
        ``CloseUpLayer`` has a different vtable and is intentionally excluded.
        This feature does not change ordinary 3D, transitions, or evidence views.
    """

    symbols: RuntimeSymbols
    profile: BuildProfile
    room_rendering_abi: RoomRenderingABI

    id: ClassVar[str] = "runtime2d.inventory"

    _section_name: ClassVar[str] = INVENTORY_SEGMENT.logical_name
    _section_size: ClassVar[int] = INVENTORY_SEGMENT.size
    _section_characteristics: ClassVar[int] = INVENTORY_SEGMENT.characteristics
    _magic: ClassVar[bytes] = INVENTORY_SEGMENT.magic
    _layout_version: ClassVar[int] = 42

    _off_layout_version: ClassVar[int] = 0x08
    _off_clear_count: ClassVar[int] = 0x0C
    _off_clear_result: ClassVar[int] = 0x10
    _off_clear_surface: ClassVar[int] = 0x14
    _off_active_inventory: ClassVar[int] = INVENTORY_ACTIVE_ROOT_OFFSET
    _off_bltfx: ClassVar[int] = 0x20
    _off_first_page_surface: ClassVar[int] = 0x88
    _off_second_page_surface: ClassVar[int] = 0x8C
    # Generic container Draw treats its second argument as a region collection
    # whose begin/end pointers live at +4/+8.  A static one-RECT collection is
    # safer than NULL: NULL suppresses Inventory's entire child traversal.
    _off_full_damage_region: ClassVar[int] = 0x90
    _off_full_damage_rect: ClassVar[int] = 0xA0
    _off_draw_wrapper: ClassVar[int] = 0x100
    _off_destructor_wrapper: ClassVar[int] = 0x240
    _off_hide_wrapper: ClassVar[int] = 0x2A0
    _off_clear_page_helper: ClassVar[int] = 0x300
    _off_layout_wrapper: ClassVar[int] = 0x400
    _off_selection_layout_wrapper: ClassVar[int] = 0x600
    _off_selection_grid_wrapper: ClassVar[int] = 0x680
    _off_item_draw_count: ClassVar[int] = 0xB0
    _off_item_draw_active: ClassVar[int] = 0xB4
    _off_item_alpha_handle: ClassVar[int] = 0xB8
    _off_item_dense_source: ClassVar[int] = 0xBC
    _off_item_draw_wrapper: ClassVar[int] = 0x700
    _off_effect_constructor_wrapper: ClassVar[int] = INVENTORY_ALPHA_CONSTRUCTOR_OFFSET
    # One constructor dispatches two exact effect owners. Inventory uses its
    # direct RGB565 scaler; fonts use a small coordinate mapper which delegates
    # every actual blend to GK3's stock callback. Keep code, vtables, and their
    # synchronous geometry record in one measured tail partition.
    _off_scaled_alpha_callback: ClassVar[int] = 0xC40
    _off_scaled_alpha_vtable: ClassVar[int] = 0xE20
    _off_scaled_font_alpha_vtable: ClassVar[int] = INVENTORY_FONT_ALPHA_VTABLE_OFFSET
    # The alpha constructor and scaled pixel virtual share this synchronous
    # geometry record. Nothing in it escapes one InventoryItem::Draw call.
    _off_effect_output_rect: ClassVar[int] = INVENTORY_ALPHA_OUTPUT_RECT_OFFSET
    _off_effect_source_rect: ClassVar[int] = INVENTORY_ALPHA_SOURCE_RECT_OFFSET
    _off_effect_dest_width: ClassVar[int] = INVENTORY_ALPHA_WIDTH_OFFSET
    _off_effect_dest_height: ClassVar[int] = INVENTORY_ALPHA_HEIGHT_OFFSET
    _off_effect_selected_vtable: ClassVar[int] = 0xE58
    _off_effect_transform_count: ClassVar[int] = 0xE5C
    _off_effect_denominator: ClassVar[int] = 0xE60
    _off_effect_numerator: ClassVar[int] = 0xE64
    _off_effect_x_offset: ClassVar[int] = 0xE68
    _off_effect_y_offset: ClassVar[int] = 0xE6C
    # Read-only validation trace for the uncommon font-alpha path. Keeping the
    # exact callback inputs makes future format/driver regressions diagnosable
    # without injecting another hook into GK3's inner pixel loop.
    _off_font_alpha_trace: ClassVar[int] = 0xE70
    _off_scaled_font_alpha_callback: ClassVar[int] = 0xEA0

    # Shared system-segment state. Inventory owns its class-specific lifetime and
    # layout hooks, while the central runtime remains the sole owner of the
    # final blitter and pointer dispatcher. Publishing this draw scope lets
    # both paths consume one reference-canvas affine.
    _system_render_depth_offset: ClassVar[int] = 0x0C
    _system_input_active_offset: ClassVar[int] = 0x10
    _system_clear_pending_offset: ClassVar[int] = 0x14
    _system_root_ptr_offset: ClassVar[int] = 0x1C
    _system_transform_mode_offset: ClassVar[int] = 0xE0
    _system_reference_canvas_mode: ClassVar[int] = 6

    # The InventoryLayer constructor at 0x004C0A96 installs this class-specific
    # vtable.  Slot +0xA0 inherits the generic container traversal at
    # 0x004DCA32, but the slot itself belongs only to InventoryLayer.  Hooking
    # it therefore avoids the CloseUpLayer vtable at 0x00674798 and keeps the
    # clear from leaking into evidence close-ups, rooms, or other overlays.
    # InventoryLayer constructs its captured-room drawable inline at +0x144.
    # Its stock animation owns visibility and alpha state; the patch changes
    # only this child's physical bounds and never freezes either end of its fade.
    # These are the same stock manager and handle resolver used by GK3's own
    # 2D drawable entry point at 0x0046709A.
    _ddbltfx_size: ClassVar[int] = 0x64
    _ddblt_colorfill_wait: ClassVar[int] = 0x01000400
    # The stock 1024x768 inventory backing is uniform RGB(8,4,16).  GK3's
    # 16-bit RGB565 display format represents that exact pixel as 0x0822.
    _background_fill_color: ClassVar[int] = 0x0822
    _ddblt_wait: ClassVar[int] = 0x01000000
    _reference_width: ClassVar[int] = AUTHORED_FRAME_WIDTH
    _reference_height: ClassVar[int] = AUTHORED_FRAME_HEIGHT

    # Inventory's grid helper reads this runtime pointer to the current width
    # and height.  The wrapper temporarily substitutes the authored reference
    # dimensions while calling the stock layout, then restores both words.
    @property
    def _inventory_vtable_va(self) -> int:
        return self.profile.address("inventory.vtable")

    @property
    def _inventory_destructor_slot_va(self) -> int:
        return self._inventory_vtable_va

    @property
    def _inventory_destructor_original_va(self) -> int:
        return self.profile.address("inventory.destructor")

    @property
    def _inventory_draw_slot_va(self) -> int:
        return self._inventory_vtable_va + 0xA0

    @property
    def _inventory_draw_original_va(self) -> int:
        return self.profile.address("ui.container_draw")

    @property
    def _inventory_hide_slot_va(self) -> int:
        return self._inventory_vtable_va + 0xDC

    @property
    def _inventory_hide_original_va(self) -> int:
        return self.profile.address("ui.hide")

    @property
    def _inventory_layout_slot_va(self) -> int:
        return self._inventory_vtable_va + 0x30

    @property
    def _inventory_layout_original_va(self) -> int:
        return self.profile.address("inventory.layout")

    @property
    def _inventory_reference_layout_va(self) -> int:
        return self.profile.address("inventory.reference_layout")

    @property
    def _inventory_grid_layout_va(self) -> int:
        return self.profile.address("inventory.grid_layout")

    @property
    def _inventory_item_draw_slot_va(self) -> int:
        return self.profile.address("inventory_item.vtable") + 0xA0

    @property
    def _inventory_item_draw_original_va(self) -> int:
        return self.profile.address("inventory_item.draw")

    @property
    def _bitmap_surface_manager_va(self) -> int:
        return self.profile.address("engine.loop")

    @property
    def _resolve_bitmap_resource_va(self) -> int:
        return self.profile.address("bitmap.resolve_resource")

    @property
    def _effect_constructor_site_va(self) -> int:
        return self.profile.site("inventory.effect_constructor_call").va

    @property
    def _effect_constructor_site_original(self) -> bytes:
        return self.profile.site("inventory.effect_constructor_call").original

    @property
    def _effect_constructor_original_va(self) -> int:
        return self.profile.address("bitmap.effect_constructor")

    @property
    def _selection_layout_call_site_va(self) -> int:
        return self.profile.site("inventory.selection_layout_call").va

    @property
    def _selection_layout_call_original(self) -> bytes:
        return self.profile.site("inventory.selection_layout_call").original

    @property
    def _selection_grid_call_site_va(self) -> int:
        return self.profile.site("inventory.selection_grid_call").va

    @property
    def _selection_grid_call_original(self) -> bytes:
        return self.profile.site("inventory.selection_grid_call").original

    @property
    def _effect_executor_va(self) -> int:
        return self.profile.address("bitmap.effect_executor")

    @property
    def _effect_callback_original_va(self) -> int:
        return self.profile.address("bitmap.effect_callback")

    @property
    def _physical_width_va(self) -> int:
        return self.profile.address("display.dimensions")

    @property
    def _native_primary_surface_ptr_va(self) -> int:
        return self.profile.address("directdraw.primary_surface")

    @property
    def _screen_dimensions_ptr_va(self) -> int:
        return self.profile.address("display.dimension_pointers")

    def _build_draw_wrapper(
        self,
        *,
        wrapper_va: int,
        clear_surface_va: int,
        active_inventory_va: int,
        first_page_surface_va: int,
        second_page_surface_va: int,
        full_damage_region_va: int,
        full_damage_rect_va: int,
        clear_page_helper_va: int,
        system_render_depth_va: int,
        system_input_active_va: int,
        system_clear_pending_va: int,
        system_root_ptr_va: int,
        system_transform_mode_va: int,
    ) -> bytes:
        """Recompose the complete active HD Inventory through stock Draw."""
        code = X86Emitter(base_va=wrapper_va)
        # The inherited visibility flag is the same one checked by the stock
        # Draw routine.  Avoid touching a page while an inactive inventory node
        # is merely present in the global UI tree.
        code.raw(b"\x80\x79\x18\x00")
        code.jump_if(Condition.EQUAL, "native")
        # The stock screenshot fade already works at 1024x768.  Keep that
        # authored path byte-for-byte at the reference mode and replace it only
        # when either physical dimension exceeds the reference surface.
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va))
        code.raw(struct.pack("<I", self._reference_width))
        code.jump_short_if(Condition.ABOVE, "repair_mode")
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", self._reference_height))
        code.jump_if(Condition.BELOW_OR_EQUAL, "native")
        code.label("repair_mode")
        # Publish the Inventory root before any child transfer. The shared
        # blitter maps authored 1024x768 item/control rectangles into the live
        # centered viewport, and the pointer dispatcher applies its exact
        # inverse while this root remains current. Keeping object rectangles
        # logical avoids the former split model where hit boxes were moved but
        # their native-size pixels were not enlarged.
        code.raw(b"\x89\x0d" + struct.pack("<I", system_root_ptr_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", system_input_active_va) + b"\x01\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", system_clear_pending_va) + b"\x01\x00\x00\x00")
        code.raw(
            b"\xc7\x05"
            + struct.pack("<I", system_transform_mode_va)
            + struct.pack("<I", self._system_reference_canvas_mode)
        )
        code.raw(b"\xff\x05" + struct.pack("<I", system_render_depth_va))
        # Stock owns the captured-room child's visibility and alpha animation;
        # this wrapper repairs only the stable backing and modern layout.
        # Treat a new InventoryLayer object as a new lifetime.  The first page
        # word doubles as the one-shot marker for clearing the native primary;
        # the resolved destination itself is intentionally filled every time.
        code.raw(b"\x3b\x0d" + struct.pack("<I", active_inventory_va))
        code.jump_short_if(Condition.EQUAL, "state_ready")
        code.raw(b"\x89\x0d" + struct.pack("<I", active_inventory_va))
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", first_page_surface_va))
        code.raw(b"\xa3" + struct.pack("<I", second_page_surface_va))
        code.label("state_ready")
        # Draw's first argument is GK3's destination bitmap handle.  PUSHAD
        # preserves the thiscall object and both original stack arguments while
        # the native resolver and COM method use their normal volatile state.
        code.raw(b"\x60")
        code.raw(b"\x8b\x44\x24\x24")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._bitmap_surface_manager_va))
        code.raw(b"\x50")
        code.call_absolute(self._resolve_bitmap_resource_va)
        code.raw(b"\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "invalid_surface")
        code.raw(b"\x8b\x40\x30\x85\xc0")
        code.jump_short_if(Condition.EQUAL, "invalid_surface")
        code.raw(b"\x8b\x70\x2c\x85\xf6")
        code.jump_short_if(Condition.NOT_EQUAL, "surface_ready")
        code.label("invalid_surface")
        code.jump("restore_registers")
        code.label("surface_ready")
        code.raw(b"\x89\x35" + struct.pack("<I", clear_surface_va))

        # Cursor motion re-enters this root with a small damage collection.
        # Clearing only once leaves the cursor compositor's old save-under
        # pixels on alternating pages; clearing on every traversal is correct
        # only because the call below also forces every child to repaint.
        code.call_absolute(clear_page_helper_va)

        # DirectDraw can be displaying a distinct primary interface when the
        # overlay first opens.  Initialize it once per Inventory lifetime to
        # avoid a one-frame room flash.  The marker is set only after DD_OK.
        code.raw(b"\x83\x3d" + struct.pack("<I", first_page_surface_va) + b"\x00")
        code.jump_short_if(Condition.NOT_EQUAL, "restore_registers")
        code.raw(b"\x8b\x35" + struct.pack("<I", self._native_primary_surface_ptr_va))
        code.raw(b"\x85\xf6")
        code.jump_short_if(Condition.EQUAL, "restore_registers")
        code.call_absolute(clear_page_helper_va)
        code.raw(b"\x85\xc0")
        code.jump_short_if(Condition.NOT_EQUAL, "restore_registers")
        code.raw(b"\x89\x35" + struct.pack("<I", first_page_surface_va))

        code.label("restore_registers")
        code.raw(b"\x61")

        # Materialize a complete physical RECT.  Unlike the disproven NULL-
        # damage experiment, this is a valid region collection and therefore
        # keeps the inherited Inventory child traversal active.
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\xa3" + struct.pack("<I", full_damage_rect_va + 8))
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", full_damage_rect_va + 12))
        # Call rather than tail-jump so the shared render scope brackets the
        # complete stock traversal. The persistent input/root state remains
        # live after Draw because GK3 may queue late dirty child transfers. Its
        # exact lifetime ends at InventoryLayer::Hide (ordinary Exit) or, as a
        # defensive fallback, at destruction.
        code.raw(b"\x51")
        code.raw(b"\x68" + struct.pack("<I", full_damage_region_va))
        code.raw(b"\xff\x74\x24\x0c")
        code.call_absolute(self._inventory_draw_original_va)
        code.raw(b"\x59\xff\x0d" + struct.pack("<I", system_render_depth_va))
        code.raw(b"\xc2\x08\x00")

        # Reference 1024x768 keeps the stock page and damage behavior exactly.
        code.label("native")
        code.jump_absolute(self._inventory_draw_original_va)
        return code.build()

    def _build_clear_page_helper(
        self,
        *,
        clear_count_va: int,
        clear_result_va: int,
        clear_surface_va: int,
        bltfx_va: int,
    ) -> bytes:
        """Color-fill ESI's complete DirectDraw page and return its HRESULT."""
        code = X86Emitter(base_va=0)
        code.raw(b"\x89\x35" + struct.pack("<I", clear_surface_va))
        # IDirectDrawSurface4::Blt(surface, NULL, NULL, NULL,
        # DDBLT_COLORFILL | DDBLT_WAIT, &DDBLTFX) fills the complete page.
        # DDBLTFX.dwFillColor carries the stock RGB565 backing pixel.
        code.raw(b"\x8b\x1e")
        code.raw(b"\x68" + struct.pack("<I", bltfx_va))
        code.raw(b"\x68" + struct.pack("<I", self._ddblt_colorfill_wait))
        code.raw(b"\x6a\x00\x6a\x00\x6a\x00\x56\xff\x53\x14")
        code.raw(b"\xa3" + struct.pack("<I", clear_result_va))
        code.raw(b"\x85\xc0")
        code.jump_short_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\xff\x05" + struct.pack("<I", clear_count_va))
        code.label("done")
        code.ret()
        return code.build()

    def _build_layout_wrapper(
        self,
        *,
        wrapper_va: int,
        active_inventory_va: int,
        system_input_active_va: int,
        system_clear_pending_va: int,
        system_root_ptr_va: int,
        system_transform_mode_va: int,
        denominator_va: int,
        numerator_va: int,
        x_offset_va: int,
        y_offset_va: int,
    ) -> bytes:
        """Lay out Inventory children in one authored 1024x768 coordinate space."""
        # The stock routine derives its 100-pixel item grid from the runtime
        # width/height structure, creating 18 columns at 1920x1080 while the
        # sprites and Exit control stay at their old pixel sizes. Its base half can
        # participate in display-mode initialization and must never see a fake
        # size. Invoke only that base half: running a physical grid first clamps
        # the retained scroll position to a different range when reopening.
        # Then run Inventory's private grid half (the thunk at 0x4c13b3) while
        # the dimensions structure temporarily says 1024x768.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x53\x56\x57\x8b\xf1")
        code.raw(b"\xff\x75\x0c\xff\x75\x08\x8b\xce")
        code.call_absolute(self.profile.address("inventory.base_layout"))
        code.raw(b"\x8b\x3d" + struct.pack("<I", self._screen_dimensions_ptr_va))
        code.raw(b"\x85\xff")
        code.jump_if(Condition.EQUAL, "layout_ready")
        code.raw(b"\xff\x37\xff\x77\x04")
        code.raw(b"\xc7\x07\x00\x04\x00\x00\xc7\x47\x04\x00\x03\x00\x00")
        # Bounds changes can synchronously invalidate and draw item sprites.
        # Activate the shared affine before the reference-grid replay, rather
        # than waiting for the later root Draw virtual, so those first static
        # transfers cannot escape at native pixel size.
        code.raw(b"\x89\x35" + struct.pack("<I", active_inventory_va))
        code.raw(b"\x89\x35" + struct.pack("<I", system_root_ptr_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", system_input_active_va) + b"\x01\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", system_clear_pending_va) + b"\x01\x00\x00\x00")
        code.raw(
            b"\xc7\x05"
            + struct.pack("<I", system_transform_mode_va)
            + struct.pack("<I", self._system_reference_canvas_mode)
        )
        code.raw(b"\x8b\xce")
        code.call_absolute(self._inventory_reference_layout_va)
        code.raw(b"\x58\x89\x47\x04\x58\x89\x07")
        code.label("layout_ready")

        # Inventory items use GK3's software alpha compositor and therefore
        # bypass the shared final blitter. Publish the same live fit once for
        # their staged output tiles while object geometry remains authored.
        code.raw(b"\x60")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x8b\xc1\x6b\xc0\x03\x8b\xf2\xc1\xe6\x02\x3b\xc6")
        code.jump_if(Condition.LESS, "layout_narrow")
        code.raw(b"\xc7\x05" + struct.pack("<I", denominator_va))
        code.raw(struct.pack("<I", self._reference_height))
        code.raw(b"\x89\x15" + struct.pack("<I", numerator_va))
        code.raw(b"\x8b\xc2\xc1\xe0\x02\x99\xbe\x03\x00\x00\x00\xf7\xfe")
        code.raw(b"\x2b\xc8\xd1\xf9\x89\x0d" + struct.pack("<I", x_offset_va))
        code.raw(b"\x31\xc0\xa3" + struct.pack("<I", y_offset_va))
        code.jump("layout_fit_ready")
        code.label("layout_narrow")
        code.raw(b"\xc7\x05" + struct.pack("<I", denominator_va))
        code.raw(struct.pack("<I", self._reference_width))
        code.raw(b"\x89\x0d" + struct.pack("<I", numerator_va))
        code.raw(b"\x8b\xc1\x6b\xc0\x03\xc1\xf8\x02")
        code.raw(b"\x2b\xd0\xd1\xfa\x89\x15" + struct.pack("<I", y_offset_va))
        code.raw(b"\x31\xc0\xa3" + struct.pack("<I", x_offset_va))
        code.label("layout_fit_ready")
        code.raw(b"\x61")

        # The root remains a physical full-page container. Every child stays
        # authored for the shared blitter and pointer inverse; item pixels use
        # the equivalent affine retained above by their staging hook.
        code.raw(b"\x31\xc0\x89\x46\x1c\x89\x46\x20")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va) + b"\x89\x46\x24")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4) + b"\x89\x46\x28")
        code.raw(b"\x8b\x7e\x4c\x8b\x5e\x50\x83\xfb\x01")
        code.jump_if(Condition.BELOW_OR_EQUAL, "done")
        code.raw(b"\x83\xc7\x04\x4b")
        code.label("child_loop")
        code.raw(b"\x8b\x0f\x85\xc9")
        code.jump_if(Condition.EQUAL, "next_child")

        # The inline captured-room sprite was initialized from GK3's live
        # screen rectangle, so retain its physical bounds. Deliberately leave
        # visibility/alpha untouched: the stock animation—not this layout
        # repair—decides when the captured room gives way to the dark backing.
        code.raw(b"\x8d\x86" + struct.pack("<I", 0x144))
        code.raw(b"\x3b\xc8")
        code.jump_short_if(Condition.NOT_EQUAL, "ordinary_child")
        code.raw(b"\x31\xc0")
        code.raw(b"\x89\x41\x1c\x89\x41\x20")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va) + b"\x89\x41\x24")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4) + b"\x89\x41\x28")
        code.jump("next_child")

        code.label("ordinary_child")
        # Exit is the only child that stock layout bottom-anchors after the
        # first real-dimension pass.  The private reference-grid replay leaves
        # that physical-height offset intact, so remove it before applying the
        # shared reference-canvas transform. It remains authored y=733..759;
        # the blitter presents that as y=1031..1067 at 1920x1080, while the
        # inverse dispatcher maps the visible Exit button back to this RECT.
        code.raw(b"\x83\xfb\x03")
        code.jump_if(Condition.NOT_EQUAL, "next_child")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x3d\x00\x03\x00\x00")
        code.jump_if(Condition.BELOW_OR_EQUAL, "next_child")
        code.raw(b"\x2d\x00\x03\x00\x00\x29\x41\x04\x29\x41\x0c")
        code.label("next_child")
        code.raw(b"\x83\xc7\x04\x4b")
        code.jump_if(Condition.NOT_EQUAL, "child_loop")

        code.label("done")
        # Exit is embedded at a stable root offset and stock layout anchors it
        # against the physical bottom edge. Set its authored rectangle
        # directly after the child pass; this is idempotent across repeated
        # mode/layout notifications and avoids depending on vector order.
        code.raw(b"\x81\x3d" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(struct.pack("<I", self._reference_height))
        code.jump_if(Condition.BELOW_OR_EQUAL, "exit_ready")
        for displacement, value in ((0x1F0, 5), (0x1F4, 733), (0x1F8, 63), (0x1FC, 759)):
            code.raw(b"\xc7\x86" + struct.pack("<I", displacement) + struct.pack("<I", value))
        code.label("exit_ready")
        code.raw(b"\x5f\x5e\x5b\x5d\xc2\x08\x00")
        return code.build()

    def _build_selection_layout_wrapper(self, *, wrapper_va: int, target_va: int) -> bytes:
        """Keep direct post-selection grid relayout in the 1024 model.

        Inventory's normal virtual Layout is not involved after choosing the
        hand/select verb. That handler calls the private grid routine directly,
        so at widescreen resolutions it sees the 1365-wide logical surface and
        collapses thirteen items into one row. Scope that one call to the same
        1024x768 dimension pair used by the normal wrapper, then restore the
        live dimensions and native return value exactly.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x56\x57\x8b\xf1")
        code.raw(b"\x8b\x3d" + struct.pack("<I", self._screen_dimensions_ptr_va))
        code.raw(b"\x85\xff")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\xff\x37\xff\x77\x04")
        code.raw(b"\xc7\x07\x00\x04\x00\x00")
        code.raw(b"\xc7\x47\x04\x00\x03\x00\x00")
        code.raw(b"\x8b\xce")
        code.call_absolute(target_va)
        code.raw(b"\x50")
        code.raw(b"\x8b\x4c\x24\x04\x89\x4f\x04")
        code.raw(b"\x8b\x4c\x24\x08\x89\x0f")
        code.raw(b"\x58\x83\xc4\x08\x5f\x5e\xc3")

        code.label("native")
        code.raw(b"\x8b\xce")
        code.call_absolute(target_va)
        code.raw(b"\x5f\x5e\xc3")
        return code.build()

    def _build_lifetime_wrapper(
        self,
        *,
        wrapper_va: int,
        target_va: int,
        active_inventory_va: int,
        first_page_surface_va: int,
        second_page_surface_va: int,
        system_render_depth_va: int,
        system_input_active_va: int,
        system_clear_pending_va: int,
        system_root_ptr_va: int,
        system_transform_mode_va: int,
    ) -> bytes:
        """Withdraw state when the active Inventory is hidden or destroyed."""
        code = X86Emitter(base_va=wrapper_va)
        if target_va == self._inventory_destructor_original_va:
            code.call_absolute(
                self.symbols.va(
                    INVENTORY_NAVIGATION_SEGMENT.logical_name, INVENTORY_NAVIGATION_CLEAR_OFFSET
                )
            )
        code.raw(b"\x3b\x0d" + struct.pack("<I", active_inventory_va))
        code.jump_short_if(Condition.NOT_EQUAL, "native")
        # Preserve EAX even though it is volatile at thiscall entry. Hide has
        # no arguments; the deleting destructor receives its flags on the
        # stack. ECX and either stack contract remain untouched.
        code.raw(b"\x50\x31\xc0")
        for address in (
            active_inventory_va,
            first_page_surface_va,
            second_page_surface_va,
        ):
            code.raw(b"\xa3" + struct.pack("<I", address))
        # Do not erase a newer modal scope (for example an evidence close-up)
        # if it replaced Inventory before the old layer object was destroyed.
        code.raw(b"\x3b\x0d" + struct.pack("<I", system_root_ptr_va))
        code.jump_short_if(Condition.NOT_EQUAL, "state_cleared")
        for address in (
            system_render_depth_va,
            system_input_active_va,
            system_clear_pending_va,
            system_root_ptr_va,
            system_transform_mode_va,
        ):
            code.raw(b"\xa3" + struct.pack("<I", address))
        code.label("state_cleared")
        code.raw(b"\x58")
        code.label("native")
        code.jump_absolute(target_va)
        return code.build()

    def precheck(self, pe: PEFile) -> None:
        """Validate pristine Inventory vtable ownership."""
        if pe.get_section(self._section_name) is not None:
            msg = f"{self.id} requires a pristine inventory section"
            raise PatchError(msg)
        if pe.read_u32_va(self._inventory_draw_slot_va) != self._inventory_draw_original_va:
            msg = f"{self.id} precheck failed: inventory Draw slot is already owned"
            raise PatchError(msg)
        if pe.read_u32_va(self._inventory_layout_slot_va) != self._inventory_layout_original_va:
            msg = f"{self.id} precheck failed: inventory layout slot is already owned"
            raise PatchError(msg)
        if (
            pe.read_u32_va(self._inventory_item_draw_slot_va)
            != self._inventory_item_draw_original_va
        ):
            msg = f"{self.id} precheck failed: inventory item Draw slot is already owned"
            raise PatchError(msg)
        effect_call = pe.read_bytes(
            pe.va_to_offset(self._effect_constructor_site_va),
            len(self._effect_constructor_site_original),
        )
        if effect_call != self._effect_constructor_site_original:
            msg = f"{self.id} precheck failed: alpha-effect call is already owned"
            raise PatchError(msg)
        if (
            pe.read_u32_va(self._inventory_destructor_slot_va)
            != self._inventory_destructor_original_va
        ):
            msg = f"{self.id} precheck failed: inventory destructor slot is already owned"
            raise PatchError(msg)
        if pe.read_u32_va(self._inventory_hide_slot_va) != self._inventory_hide_original_va:
            msg = f"{self.id} precheck failed: inventory Hide slot is already owned"
            raise PatchError(msg)

    def apply(self, pe: PEFile) -> None:
        """Emit Inventory draw, layout, clear, and lifetime wrappers."""
        section = install_runtime_segment(pe, INVENTORY_SEGMENT)

        section_va = pe.rva_to_va(section.virtual_address)
        section_offset = section.pointer_to_raw_data
        wrapper_va = section_va + self._off_draw_wrapper
        clear_page_helper_va = section_va + self._off_clear_page_helper
        layout_wrapper_va = section_va + self._off_layout_wrapper
        selection_layout_wrapper_va = section_va + self._off_selection_layout_wrapper
        selection_grid_wrapper_va = section_va + self._off_selection_grid_wrapper
        system_section_va = self.symbols.va(SYSTEM_SEGMENT.logical_name)
        system_control_section_va = self.symbols.va(SYSTEM_CONTROL_SEGMENT.logical_name)
        loadsave_section_va = self.symbols.va(LOAD_SAVE_SEGMENT.logical_name)
        wrapper = self._build_draw_wrapper(
            wrapper_va=wrapper_va,
            clear_surface_va=section_va + self._off_clear_surface,
            active_inventory_va=section_va + self._off_active_inventory,
            first_page_surface_va=section_va + self._off_first_page_surface,
            second_page_surface_va=section_va + self._off_second_page_surface,
            full_damage_region_va=section_va + self._off_full_damage_region,
            full_damage_rect_va=section_va + self._off_full_damage_rect,
            clear_page_helper_va=clear_page_helper_va,
            system_render_depth_va=system_section_va + self._system_render_depth_offset,
            system_input_active_va=system_section_va + self._system_input_active_offset,
            system_clear_pending_va=system_section_va + self._system_clear_pending_offset,
            system_root_ptr_va=system_section_va + self._system_root_ptr_offset,
            system_transform_mode_va=system_section_va + self._system_transform_mode_offset,
        )
        clear_page_helper = self._build_clear_page_helper(
            clear_count_va=section_va + self._off_clear_count,
            clear_result_va=section_va + self._off_clear_result,
            clear_surface_va=section_va + self._off_clear_surface,
            bltfx_va=section_va + self._off_bltfx,
        )
        layout_wrapper = self._build_layout_wrapper(
            wrapper_va=layout_wrapper_va,
            active_inventory_va=section_va + self._off_active_inventory,
            system_input_active_va=system_section_va + self._system_input_active_offset,
            system_clear_pending_va=system_section_va + self._system_clear_pending_offset,
            system_root_ptr_va=system_section_va + self._system_root_ptr_offset,
            system_transform_mode_va=system_section_va + self._system_transform_mode_offset,
            denominator_va=section_va + self._off_effect_denominator,
            numerator_va=section_va + self._off_effect_numerator,
            x_offset_va=section_va + self._off_effect_x_offset,
            y_offset_va=section_va + self._off_effect_y_offset,
        )
        selection_layout_wrapper = self._build_selection_layout_wrapper(
            wrapper_va=selection_layout_wrapper_va,
            target_va=self._inventory_reference_layout_va,
        )
        selection_grid_wrapper = self._build_selection_layout_wrapper(
            wrapper_va=selection_grid_wrapper_va,
            target_va=self._inventory_grid_layout_va,
        )
        destructor_wrapper_va = section_va + self._off_destructor_wrapper
        destructor_wrapper = self._build_lifetime_wrapper(
            wrapper_va=destructor_wrapper_va,
            target_va=self._inventory_destructor_original_va,
            active_inventory_va=section_va + self._off_active_inventory,
            first_page_surface_va=section_va + self._off_first_page_surface,
            second_page_surface_va=section_va + self._off_second_page_surface,
            system_render_depth_va=system_section_va + self._system_render_depth_offset,
            system_input_active_va=system_section_va + self._system_input_active_offset,
            system_clear_pending_va=system_section_va + self._system_clear_pending_offset,
            system_root_ptr_va=system_section_va + self._system_root_ptr_offset,
            system_transform_mode_va=system_section_va + self._system_transform_mode_offset,
        )
        hide_wrapper_va = section_va + self._off_hide_wrapper
        hide_wrapper = self._build_lifetime_wrapper(
            wrapper_va=hide_wrapper_va,
            target_va=self._inventory_hide_original_va,
            active_inventory_va=section_va + self._off_active_inventory,
            first_page_surface_va=section_va + self._off_first_page_surface,
            second_page_surface_va=section_va + self._off_second_page_surface,
            system_render_depth_va=system_section_va + self._system_render_depth_offset,
            system_input_active_va=system_section_va + self._system_input_active_offset,
            system_clear_pending_va=system_section_va + self._system_clear_pending_offset,
            system_root_ptr_va=system_section_va + self._system_root_ptr_offset,
            system_transform_mode_va=system_section_va + self._system_transform_mode_offset,
        )
        item_draw_wrapper_va = section_va + self._off_item_draw_wrapper
        item_draw_wrapper = build_item_draw_wrapper(
            self,
            wrapper_va=item_draw_wrapper_va,
            item_draw_count_va=section_va + self._off_item_draw_count,
            active_inventory_va=section_va + self._off_active_inventory,
            item_draw_active_va=section_va + self._off_item_draw_active,
            item_alpha_handle_va=section_va + self._off_item_alpha_handle,
            item_dense_source_va=section_va + self._off_item_dense_source,
        )
        scaled_alpha_callback_va = section_va + self._off_scaled_alpha_callback
        scaled_alpha_callback = build_scaled_alpha_callback(
            callback_va=scaled_alpha_callback_va,
            source_rect_va=section_va + self._off_effect_source_rect,
            dest_width_va=section_va + self._off_effect_dest_width,
            dest_height_va=section_va + self._off_effect_dest_height,
        )
        scaled_font_alpha_callback_va = section_va + self._off_scaled_font_alpha_callback
        scaled_font_alpha_callback = build_scaled_font_alpha_callback(
            self,
            callback_va=scaled_font_alpha_callback_va,
            source_rect_va=section_va + self._off_effect_source_rect,
            dest_width_va=section_va + self._off_effect_dest_width,
            dest_height_va=section_va + self._off_effect_dest_height,
            trace_va=section_va + self._off_font_alpha_trace,
        )
        scaled_alpha_vtable_va = section_va + self._off_scaled_alpha_vtable
        scaled_font_alpha_vtable_va = section_va + self._off_scaled_font_alpha_vtable
        effect_constructor_wrapper_va = section_va + self._off_effect_constructor_wrapper
        effect_constructor_wrapper = build_effect_constructor_wrapper(
            self,
            wrapper_va=effect_constructor_wrapper_va,
            item_draw_active_va=section_va + self._off_item_draw_active,
            output_rect_va=section_va + self._off_effect_output_rect,
            source_rect_va=section_va + self._off_effect_source_rect,
            dest_width_va=section_va + self._off_effect_dest_width,
            dest_height_va=section_va + self._off_effect_dest_height,
            transform_count_va=section_va + self._off_effect_transform_count,
            item_alpha_handle_va=section_va + self._off_item_alpha_handle,
            item_dense_source_va=section_va + self._off_item_dense_source,
            denominator_va=section_va + self._off_effect_denominator,
            numerator_va=section_va + self._off_effect_numerator,
            x_offset_va=section_va + self._off_effect_x_offset,
            y_offset_va=section_va + self._off_effect_y_offset,
            scaled_alpha_vtable_va=scaled_alpha_vtable_va,
            font_scaled_alpha_vtable_va=scaled_font_alpha_vtable_va,
            selected_vtable_va=section_va + self._off_effect_selected_vtable,
            hud_font_active_va=loadsave_section_va + LOAD_SAVE_HUD_FONT_ACTIVE_OFFSET,
            hud_font_point_va=loadsave_section_va + LOAD_SAVE_HUD_FONT_POINT_OFFSET,
            hud_font_alpha_transform_count_va=(
                loadsave_section_va + LOAD_SAVE_HUD_FONT_ALPHA_TRANSFORM_COUNT_OFFSET
            ),
            hd_font_active_va=(system_control_section_va + SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET),
            hd_font_source_transform_count_va=(
                system_control_section_va + SYSTEM_CONTROL_HD_FONT_SOURCE_TRANSFORM_COUNT_OFFSET
            ),
            physical_height_va=self._physical_width_va + 4,
            font_bank_select_va=self.symbols.va(
                FONT_BANK_SEGMENT.logical_name, FONT_BANK_ALPHA_SELECT_OFFSET
            ),
            fallback_constructor_va=install_ui_alpha_adapter(
                pe,
                profile=self.profile,
                fallback_va=install_alpha_adapter(
                    pe,
                    profile=self.profile,
                    root_va=self.symbols.va(
                        SYSTEM_SEGMENT.logical_name, SYSTEM_ROOT_POINTER_OFFSET
                    ),
                    hd_set_active_va=self.symbols.va(
                        FINGERPRINT_SEGMENT.logical_name, FINGERPRINT_HD_SET_ACTIVE_OFFSET
                    ),
                ),
            ),
        )
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=INVENTORY_SEGMENT.logical_name,
            size=INVENTORY_SEGMENT.size,
        )
        payload.place(label="magic", offset=0, payload=self._magic)
        payload.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._layout_version),
        )
        payload.reserve(label="clear and lifetime state", offset=self._off_clear_count, size=16)
        payload.reserve(
            label="DirectDraw page surfaces",
            offset=self._off_first_page_surface,
            size=8,
        )
        # Generic Draw's region object embeds vector-like begin/end pointers at
        # +4/+8.  The single RECT is completed with live dimensions at runtime.
        full_damage_rect_va = section_va + self._off_full_damage_rect
        payload.place(
            label="complete damage collection",
            offset=self._off_full_damage_region,
            payload=struct.pack("<IIII", 0, full_damage_rect_va, full_damage_rect_va + 16, 0)
            + bytes(16),
        )
        payload.reserve(label="item draw state", offset=self._off_item_draw_count, size=16)
        # DDBLTFX is otherwise zero-initialized; dwSize is mandatory and the
        # fill-color union at +0x50 receives the reference RGB565 pixel.
        bltfx = bytearray(self._ddbltfx_size)
        struct.pack_into("<I", bltfx, 0, self._ddbltfx_size)
        struct.pack_into("<I", bltfx, 0x50, self._background_fill_color)
        payload.place(
            label="background fill descriptor",
            offset=self._off_bltfx,
            payload=bytes(bltfx),
        )
        for label, offset, code, limit in (
            ("Inventory root draw", self._off_draw_wrapper, wrapper, self._off_destructor_wrapper),
            (
                "Inventory destructor",
                self._off_destructor_wrapper,
                destructor_wrapper,
                self._off_hide_wrapper,
            ),
            (
                "Inventory hide",
                self._off_hide_wrapper,
                hide_wrapper,
                self._off_clear_page_helper,
            ),
            (
                "page clear",
                self._off_clear_page_helper,
                clear_page_helper,
                self._off_layout_wrapper,
            ),
            (
                "Inventory layout",
                self._off_layout_wrapper,
                layout_wrapper,
                self._off_selection_layout_wrapper,
            ),
            (
                "post-selection Inventory layout",
                self._off_selection_layout_wrapper,
                selection_layout_wrapper,
                self._off_selection_grid_wrapper,
            ),
            (
                "post-selection Inventory grid",
                self._off_selection_grid_wrapper,
                selection_grid_wrapper,
                self._off_item_draw_wrapper,
            ),
            (
                "item draw",
                self._off_item_draw_wrapper,
                item_draw_wrapper,
                self._off_effect_constructor_wrapper,
            ),
            (
                "alpha constructor",
                self._off_effect_constructor_wrapper,
                effect_constructor_wrapper,
                self._off_scaled_alpha_callback,
            ),
            (
                "scaled alpha callback",
                self._off_scaled_alpha_callback,
                scaled_alpha_callback,
                self._off_scaled_alpha_vtable,
            ),
            (
                "scaled font alpha callback",
                self._off_scaled_font_alpha_callback,
                scaled_font_alpha_callback,
                self._section_size,
            ),
        ):
            payload.place(label=label, offset=offset, payload=code, limit=limit)
        payload.place(
            label="scaled alpha vtable",
            offset=self._off_scaled_alpha_vtable,
            payload=struct.pack(
                "<II",
                self._effect_executor_va,
                install_area_adapter(
                    pe,
                    profile=self.profile,
                    native_va=scaled_alpha_callback_va,
                    dense_source_va=section_va + self._off_item_dense_source,
                    source_rect_va=section_va + self._off_effect_source_rect,
                    dest_width_va=section_va + self._off_effect_dest_width,
                    dest_height_va=section_va + self._off_effect_dest_height,
                ),
            ),
        )
        payload.place(
            label="scaled font alpha vtable",
            offset=self._off_scaled_font_alpha_vtable,
            payload=struct.pack(
                "<II",
                self._effect_executor_va,
                scaled_font_alpha_callback_va,
            ),
        )
        payload.reserve(
            label="alpha transaction state",
            offset=self._off_effect_output_rect,
            size=self._off_scaled_font_alpha_callback - self._off_effect_output_rect,
        )
        pe.write_bytes(section_offset, payload.build())

        mutations = ExecutableMutationPlan(owner=self.id)
        for label, slot_va, expected, target_va in (
            (
                "Inventory draw",
                self._inventory_draw_slot_va,
                self._inventory_draw_original_va,
                wrapper_va,
            ),
            (
                "Inventory destructor",
                self._inventory_destructor_slot_va,
                self._inventory_destructor_original_va,
                destructor_wrapper_va,
            ),
            (
                "Inventory hide",
                self._inventory_hide_slot_va,
                self._inventory_hide_original_va,
                hide_wrapper_va,
            ),
            (
                "Inventory layout",
                self._inventory_layout_slot_va,
                self._inventory_layout_original_va,
                layout_wrapper_va,
            ),
            (
                "Inventory item draw",
                self._inventory_item_draw_slot_va,
                self._inventory_item_draw_original_va,
                item_draw_wrapper_va,
            ),
        ):
            mutations.pointer(
                label=label,
                slot_va=slot_va,
                expected=expected,
                target_va=target_va,
            )
        mutations.branch(
            label="post-selection Inventory layout",
            opcode=BranchOpcode.CALL,
            site_va=self._selection_layout_call_site_va,
            expected=self._selection_layout_call_original,
            target_va=selection_layout_wrapper_va,
            size=len(self._selection_layout_call_original),
        )
        mutations.branch(
            label="post-selection Inventory grid",
            opcode=BranchOpcode.CALL,
            site_va=self._selection_grid_call_site_va,
            expected=self._selection_grid_call_original,
            target_va=selection_grid_wrapper_va,
            size=len(self._selection_grid_call_original),
        )
        mutations.branch(
            label="Inventory alpha-effect constructor",
            opcode=BranchOpcode.CALL,
            site_va=self._effect_constructor_site_va,
            expected=self._effect_constructor_site_original,
            target_va=self.symbols.va(
                SIDNEY_PRESENTATION_SEGMENT.logical_name, SIDNEY_ALPHA_CONSTRUCTOR_OFFSET
            ),
            size=len(self._effect_constructor_site_original),
        )
        # ScrollBar's row-change callback re-enters the same grid helper after
        # opening layout has restored physical display dimensions. Keep this
        # relayout in the identical authored scope used after item selection.
        scroll_grid = self.profile.site("inventory.scrollbar_grid_call")
        mutations.branch(
            label="post-scroll Inventory grid",
            opcode=BranchOpcode.CALL,
            site_va=scroll_grid.va,
            expected=scroll_grid.original,
            target_va=selection_grid_wrapper_va,
        )
        mutations.apply(pe)

    def postcheck(self, pe: PEFile) -> None:
        """Require this owner's segment after deterministic compilation.

        Runtime2D independently rebuilds and compares every segment and native
        redirect. Re-emitting Inventory here duplicated that complete proof.
        """
        if pe.get_section(self._section_name) is None:
            msg = f"{self.id} postcheck failed: section missing"
            raise PatchError(msg)
