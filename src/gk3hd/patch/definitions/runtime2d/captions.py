"""Retain native dialogue captions above staged Direct3D frames."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT
from gk3hd.patch.definitions.runtime2d.layout import (
    CAPTION_ACTIVE_CLIP_OFFSET,
    CAPTION_ACTIVE_OBJECT_OFFSET,
    CAPTION_CACHE_GENERATION_RECT_OFFSET,
    CAPTION_DAMAGE_AUGMENTER_OFFSET,
    CAPTION_GLYPH_RECORDER_OFFSET,
    CAPTION_GLYPH_RECT_OFFSET,
    CAPTION_GLYPH_RECT_VALID_OFFSET,
    CAPTION_PRESENTER_OFFSET,
    CAPTION_SEGMENT,
    SYSTEM_CONTROL_CURSOR_STATE_OFFSET,
    install_runtime_segment,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
    from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptionFeatureCompiler:
    """Retain dialogue captions above staged rooms at reference-relative scale.

    Outcome:
        Dialogue glyphs remain sharp, stable, and correctly scaled above the
        completed room until their native lifetime ends.
    Before:
        GK3 positions a caption against the live framebuffer but keeps 1024x768
        font metrics, then draws it before the staged-room copy that can erase it.
    After:
        A complete caption generation is composed at mapped bounds on the final
        page, and its outgoing footprint is cleaned on both DirectDraw pages.
    Strategy:
        Hook only Caption's Draw/destructor slots, defer the at-most-three live
        CaptionMgr objects to the pre-Flip owner, and key one transparent cache
        by object identity plus mapped bounds. Replay uses one color-keyed
        ``BltFast``; allocation failure falls back to the same-frame native draw.
        The shared font hook height-scales glyph positions and extents about the
        live box centre/bottom, and the damage callback carries two generations.
    Boundaries:
        This feature recognizes neither output resolutions nor text content and
        does not own room presentation, menu tooltips, or status-line glyphs.
    """

    symbols: RuntimeSymbols
    profile: BuildProfile
    room_rendering_abi: RoomRenderingABI
    transition_abi: TransitionFrameABI

    id: ClassVar[str] = "runtime2d.captions"
    _section_name: ClassVar[str] = CAPTION_SEGMENT.logical_name
    _section_size: ClassVar[int] = CAPTION_SEGMENT.size
    _section_characteristics: ClassVar[int] = CAPTION_SEGMENT.characteristics
    _magic: ClassVar[bytes] = CAPTION_SEGMENT.magic
    _layout_version: ClassVar[int] = 3

    _off_layout_version: ClassVar[int] = 0x08
    _off_queue_count: ClassVar[int] = 0x0C
    _off_defer_count: ClassVar[int] = 0x10
    _off_present_count: ClassVar[int] = 0x14
    _off_active_object: ClassVar[int] = CAPTION_ACTIVE_OBJECT_OFFSET
    _off_active_clip: ClassVar[int] = CAPTION_ACTIVE_CLIP_OFFSET
    _off_overflow_count: ClassVar[int] = 0x20
    _off_destructor_cleanup_count: ClassVar[int] = 0x24
    _off_damage_augment_count: ClassVar[int] = 0x28
    _off_pending_valid: ClassVar[int] = 0x2C
    _off_pending_rect: ClassVar[int] = 0x30
    _off_entries: ClassVar[int] = 0x40
    _entry_stride: ClassVar[int] = 0x38
    _entry_capacity: ClassVar[int] = 3
    _entry_object: ClassVar[int] = 0x00
    _entry_destination: ClassVar[int] = 0x04
    _entry_damage_region: ClassVar[int] = 0x08
    _entry_native_rect: ClassVar[int] = 0x18
    _entry_scaled_rect: ClassVar[int] = 0x28
    _off_cleanup_native_rect: ClassVar[int] = 0xE8
    _off_cleanup_scaled_rect: ClassVar[int] = 0xF8
    # Transparent caption cache. A retained Caption is immutable after native
    # construction (the capture oracle snapshots all 0x108 bytes across every
    # cadence interval), so object identity plus mapped bounds is a complete
    # generation key. The actual surface remains full-frame because GK3's
    # bitmap wrapper continues to advertise the physical framebuffer extent
    # while its COM pointer is temporarily redirected during cache creation.
    _off_cache_surface: ClassVar[int] = 0x108
    _off_cache_owner: ClassVar[int] = 0x10C
    _off_cache_ready: ClassVar[int] = 0x110
    _off_cache_object_count: ClassVar[int] = 0x114
    _off_cache_objects: ClassVar[int] = 0x118
    _off_cache_rect: ClassVar[int] = 0x124
    _off_cache_current_rect: ClassVar[int] = 0x134
    _off_cache_descriptor: ClassVar[int] = 0x150
    _off_cache_bltfx: ClassVar[int] = 0x1C0
    _off_cache_color_key: ClassVar[int] = 0x228
    _off_cache_create_result: ClassVar[int] = 0x230
    _off_cache_fill_result: ClassVar[int] = 0x234
    _off_cache_key_result: ClassVar[int] = 0x238
    _off_cache_present_result: ClassVar[int] = 0x23C
    _off_cache_build_count: ClassVar[int] = 0x240
    _off_cache_replay_count: ClassVar[int] = 0x244
    _off_cache_release_count: ClassVar[int] = 0x248
    _off_cache_destination_wrapper: ClassVar[int] = 0x24C
    _off_cache_destination_surface: ClassVar[int] = 0x250
    _off_glyph_rect_valid: ClassVar[int] = CAPTION_GLYPH_RECT_VALID_OFFSET
    _off_glyph_rect: ClassVar[int] = CAPTION_GLYPH_RECT_OFFSET
    # The broad immutable object geometry keys the cache independently from
    # the measured, tightly cropped glyph rectangle used for replay.
    _off_cache_generation_rect: ClassVar[int] = CAPTION_CACHE_GENERATION_RECT_OFFSET

    _off_draw_wrapper: ClassVar[int] = 0x300
    _off_draw_wrapper_limit: ClassVar[int] = 0x480
    _off_destructor_wrapper: ClassVar[int] = 0x480
    _off_destructor_wrapper_limit: ClassVar[int] = CAPTION_PRESENTER_OFFSET
    _off_presenter: ClassVar[int] = CAPTION_PRESENTER_OFFSET
    _off_presenter_limit: ClassVar[int] = 0xC00
    _off_geometry_helper: ClassVar[int] = 0xC00
    _off_geometry_helper_limit: ClassVar[int] = CAPTION_DAMAGE_AUGMENTER_OFFSET
    _off_damage_augmenter: ClassVar[int] = CAPTION_DAMAGE_AUGMENTER_OFFSET
    _off_damage_augmenter_limit: ClassVar[int] = 0x1100
    _off_damage_record_helper: ClassVar[int] = 0x1100
    _off_damage_record_helper_limit: ClassVar[int] = 0x1180
    _off_cache_ensure_helper: ClassVar[int] = 0x1180
    _off_cache_ensure_helper_limit: ClassVar[int] = 0x1500
    _off_glyph_recorder: ClassVar[int] = CAPTION_GLYPH_RECORDER_OFFSET
    _off_glyph_recorder_limit: ClassVar[int] = 0x1580

    _ddsd_size: ClassVar[int] = 0x6C
    _ddsd_caps_height_width: ClassVar[int] = 0x00000007
    _offscreen_caps: ClassVar[int] = 0x00000040
    _ddbltfx_size: ClassVar[int] = 0x64
    _ddblt_colorfill_wait: ClassVar[int] = 0x01000400
    # The presenter already runs at the serialized pre-Flip edge.  Asking the
    # legacy blitter to wait again makes a tiny keyed caption transfer consume
    # another synchronization interval and caps a 120-Hz room near 70 FPS.
    # Submit the source-key operation immediately; a busy/error HRESULT takes
    # the existing exact native fallback rather than presenting stale text.
    _ddbltfast_source_key: ClassVar[int] = 0x00000010
    _ddckey_source_blt: ClassVar[int] = 0x00000008
    # A one-bit-blue RGB565 value is outside the caption's native magenta/black
    # ramp while preserving its true black outline during keyed replay.
    _cache_transparent_pixel: ClassVar[int] = 0x00000001

    @property
    def _draw_slot_va(self) -> int:
        return self.profile.address("caption.vtable") + 0xA0

    @property
    def _destructor_slot_va(self) -> int:
        return self.profile.address("caption.vtable")

    @property
    def _physical_width_va(self) -> int:
        return self.profile.address("display.dimensions")

    @staticmethod
    def _build_damage_record_helper(*, wrapper_va: int) -> bytes:
        """Union ESI's valid RECT into EDI/EDX's valid flag and RECT."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x8b\x06\x3b\x46\x08")
        code.jump_if(Condition.GREATER_OR_EQUAL, "done")
        code.raw(b"\x8b\x4e\x04\x3b\x4e\x0c")
        code.jump_if(Condition.GREATER_OR_EQUAL, "done")
        code.raw(b"\x83\x3f\x00")
        code.jump_if(Condition.NOT_EQUAL, "union")
        for source_offset, target_offset in ((0, 0), (4, 4), (8, 8), (12, 12)):
            code.raw(b"\x8b\x46" + bytes([source_offset]))
            code.raw(b"\x89\x02" if target_offset == 0 else b"\x89\x42" + bytes([target_offset]))
        code.raw(b"\xc7\x07\x01\x00\x00\x00")
        code.jump("done")
        code.label("union")
        for source_offset, target_offset, condition, label in (
            (0, 0, Condition.GREATER_OR_EQUAL, "top"),
            (4, 4, Condition.GREATER_OR_EQUAL, "right"),
            (8, 8, Condition.LESS_OR_EQUAL, "bottom"),
            (12, 12, Condition.LESS_OR_EQUAL, "done"),
        ):
            code.raw(b"\x8b\x46" + bytes([source_offset]))
            code.raw(b"\x3b\x02" if target_offset == 0 else b"\x3b\x42" + bytes([target_offset]))
            code.jump_if(condition, label)
            code.raw(b"\x89\x02" if target_offset == 0 else b"\x89\x42" + bytes([target_offset]))
            if label != "done":
                code.label(label)
        code.label("done")
        code.raw(b"\xc3")
        return code.build()

    def _build_geometry_helper(
        self,
        *,
        wrapper_va: int,
        damage_record_helper_va: int,
        pending_valid_va: int,
        pending_rect_va: int,
        cache_ready_va: int,
        cache_object_count_va: int,
        cache_objects_va: int,
    ) -> bytes:
        """Copy ECX's native bounds and map them into ESI/EDI rectangles.

        ESI receives the native rectangle consumed by Caption::Draw. EDI
        receives the complete scaled physical footprint used for clipping and
        stage cleanup. The affine is centred horizontally and bottom-anchored
        vertically, matching Caption's live layout contract.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\x8b\xd9")
        for dimension_va in (self._physical_width_va, self._physical_width_va + 4):
            code.raw(b"\x83\x3d" + struct.pack("<I", dimension_va) + b"\x00")
            code.jump_if(Condition.LESS_OR_EQUAL, "done")

        # Keep the native damage domain byte-for-byte identical to the live
        # object. Caption::Draw intersects against these bounds before it asks
        # the shared font path to apply the scaled point and clip.
        for source_offset, target_offset in ((0x1C, 0), (0x20, 4), (0x24, 8), (0x28, 12)):
            code.raw(b"\x8b\x43" + bytes([source_offset]))
            code.raw(b"\x89\x06" if target_offset == 0 else b"\x89\x46" + bytes([target_offset]))

        code.raw(b"\x8b\x43\x1c\x03\x43\x24\xd1\xf8\x50")  # centre X
        code.raw(b"\xff\x73\x28")  # bottom Y
        for source_offset, target_offset, anchor_stack_offset, dimension_va, name in (
            (0x1C, 0, 4, self._physical_width_va, "left"),
            (0x20, 4, 0, self._physical_width_va + 4, "top"),
            (0x24, 8, 4, self._physical_width_va, "right"),
            (0x28, 12, 0, self._physical_width_va + 4, "bottom"),
        ):
            code.raw(b"\x8b\x43" + bytes([source_offset]))
            code.raw(b"\x2b\x44\x24" + bytes([anchor_stack_offset]))
            code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self._physical_width_va + 4))
            code.raw(b"\x99\xb9" + struct.pack("<I", AUTHORED_FRAME_HEIGHT) + b"\xf7\xf9")
            code.raw(b"\x03\x44\x24" + bytes([anchor_stack_offset]))
            code.raw(b"\x85\xc0")
            code.jump_if(Condition.GREATER_OR_EQUAL, f"{name}_nonnegative")
            code.raw(b"\x31\xc0")
            code.label(f"{name}_nonnegative")
            code.raw(b"\x3b\x05" + struct.pack("<I", dimension_va))
            code.jump_if(Condition.LESS_OR_EQUAL, f"{name}_clamped")
            code.raw(b"\xa1" + struct.pack("<I", dimension_va))
            code.label(f"{name}_clamped")
            code.raw(b"\x89\x07" if target_offset == 0 else b"\x89\x47" + bytes([target_offset]))
        code.raw(b"\x83\xc4\x08")

        # Once this exact object belongs to the immutable cache generation,
        # replay writes the same glyph pixels over both pages and needs no
        # stage cleanup. Re-publishing its footprint here forced one otherwise
        # unnecessary staged DirectDraw transfer before every cache replay.
        # A newly added Caption is not in the key yet, so it conservatively
        # publishes its broad mapped box before the presenter rasterizes the
        # replacement generation. Destruction independently publishes the
        # measured final footprint exactly once.
        code.raw(b"\x8b\xf7")
        code.raw(b"\x83\x3d" + struct.pack("<I", cache_ready_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "record")
        code.raw(b"\x31\xc9")
        code.label("cache_object_loop")
        code.raw(b"\x3b\x0d" + struct.pack("<I", cache_object_count_va))
        code.jump_if(Condition.ABOVE_OR_EQUAL, "record")
        code.raw(b"\x3b\x1c\x8d" + struct.pack("<I", cache_objects_va))
        code.jump_if(Condition.EQUAL, "cached_object")
        code.raw(b"\x41")
        code.jump("cache_object_loop")
        code.label("cached_object")
        code.jump("done")
        code.label("record")
        # The shared recorder consumes the selected rectangle synchronously.
        code.raw(b"\xbf" + struct.pack("<I", pending_valid_va))
        code.raw(b"\xba" + struct.pack("<I", pending_rect_va))
        code.call_absolute(damage_record_helper_va)
        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()

    @staticmethod
    def _build_glyph_recorder(
        *,
        wrapper_va: int,
        active_object_va: int,
        glyph_rect_valid_va: int,
        glyph_rect_va: int,
        damage_record_helper_va: int,
    ) -> bytes:
        """Union ESI's final clipped glyph only during Caption rasterization."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60")
        code.raw(b"\x83\x3d" + struct.pack("<I", active_object_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\xbf" + struct.pack("<I", glyph_rect_valid_va))
        code.raw(b"\xba" + struct.pack("<I", glyph_rect_va))
        code.call_absolute(damage_record_helper_va)
        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()

    def _build_draw_wrapper(
        self,
        *,
        wrapper_va: int,
        geometry_helper_va: int,
        queue_count_va: int,
        entries_va: int,
        defer_count_va: int,
        overflow_count_va: int,
        room_presentation_active_va: int,
    ) -> bytes:
        """Publish one exact Caption::Draw transaction for this room frame."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x53\x56\x57\x8b\xd9")
        code.raw(b"\x83\x3d" + struct.pack("<I", room_presentation_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\xa1" + struct.pack("<I", queue_count_va))
        code.raw(b"\x83\xf8" + bytes([self._entry_capacity]))
        code.jump_if(Condition.ABOVE_OR_EQUAL, "overflow")
        code.raw(b"\x6b\xc0" + bytes([self._entry_stride]))
        code.raw(b"\x05" + struct.pack("<I", entries_va) + b"\x8b\xf8")
        code.raw(b"\x89\x1f")
        code.raw(b"\x8b\x45\x08\x89\x47" + bytes([self._entry_destination]))
        code.raw(b"\x8d\x77" + bytes([self._entry_native_rect]))
        code.raw(b"\x8d\x7f" + bytes([self._entry_scaled_rect]))
        code.raw(b"\x8b\xcb")
        code.call_absolute(geometry_helper_va)
        code.raw(b"\xff\x05" + struct.pack("<I", queue_count_va))
        code.raw(b"\xff\x05" + struct.pack("<I", defer_count_va))
        code.raw(b"\x31\xc0")
        code.jump("done")
        code.label("overflow")
        code.raw(b"\xff\x05" + struct.pack("<I", overflow_count_va))
        code.label("native")
        code.raw(b"\xff\x75\x0c\xff\x75\x08\x8b\xcb")
        code.call_absolute(self.profile.address("caption.draw"))
        code.label("done")
        code.raw(b"\x5f\x5e\x5b\x5d\xc2\x08\x00")
        return code.build()

    def _build_destructor_wrapper(
        self,
        *,
        wrapper_va: int,
        geometry_helper_va: int,
        cleanup_native_rect_va: int,
        cleanup_scaled_rect_va: int,
        cleanup_count_va: int,
        cache_ready_va: int,
        cache_object_count_va: int,
        room_presentation_active_va: int,
    ) -> bytes:
        """Publish the final scaled footprint before Caption storage dies."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x55\x8b\xec\x53\x56\x57\x8b\xd9")
        code.raw(b"\x83\x3d" + struct.pack("<I", room_presentation_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\xbe" + struct.pack("<I", cleanup_native_rect_va))
        code.raw(b"\xbf" + struct.pack("<I", cleanup_scaled_rect_va))
        code.raw(b"\x8b\xcb")
        code.call_absolute(geometry_helper_va)
        code.raw(b"\xff\x05" + struct.pack("<I", cleanup_count_va))
        # Caption storage is immutable while alive. Destruction is therefore
        # the exact generation-retirement boundary for the raster cache.
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", cache_ready_va))
        code.raw(b"\xa3" + struct.pack("<I", cache_object_count_va))
        code.label("native")
        code.raw(b"\xff\x75\x08\x8b\xcb")
        code.call_absolute(self.profile.address("caption.destructor"))
        code.raw(b"\x5f\x5e\x5b\x5d\xc2\x04\x00")
        return code.build()

    def _build_cache_ensure_helper(
        self,
        *,
        wrapper_va: int,
        ddraw_va: int,
        surface_va: int,
        owner_va: int,
        ready_va: int,
        descriptor_va: int,
        color_key_va: int,
        create_result_va: int,
        key_result_va: int,
        release_count_va: int,
    ) -> bytes:
        """Return one with a live full-frame, source-keyed caption surface.

        The high-level font path resolves dimensions through GK3's bitmap
        wrapper, so the temporary COM replacement must match those physical
        dimensions exactly. Owner and descriptor equality make reuse safe;
        mode/device changes release the stale allocation before creation.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\x31\xc0")
        code.raw(b"\x8b\x3d" + struct.pack("<I", ddraw_va) + b"\x85\xff")
        code.jump_if(Condition.EQUAL, "done")
        for dimension_va in (self._physical_width_va, self._physical_width_va + 4):
            code.raw(b"\x83\x3d" + struct.pack("<I", dimension_va) + b"\x00")
            code.jump_if(Condition.LESS_OR_EQUAL, "done")

        code.raw(b"\x8b\x35" + struct.pack("<I", surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "create")
        code.raw(b"\x3b\x3d" + struct.pack("<I", owner_va))
        code.jump_if(Condition.NOT_EQUAL, "release")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x3b\x05" + struct.pack("<I", descriptor_va + 0x0C))
        code.jump_if(Condition.NOT_EQUAL, "release")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\x3b\x05" + struct.pack("<I", descriptor_va + 0x08))
        code.jump_if(Condition.NOT_EQUAL, "release")
        code.raw(b"\xc7\x44\x24\x1c\x01\x00\x00\x00")
        code.jump("done")

        code.label("release")
        code.raw(b"\x8b\x06\x56\xff\x50\x08")
        code.raw(b"\xff\x05" + struct.pack("<I", release_count_va))
        code.raw(b"\x31\xc0")
        for state_va in (surface_va, owner_va, ready_va):
            code.raw(b"\xa3" + struct.pack("<I", state_va))

        code.label("create")
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", descriptor_va + 0x08))
        code.raw(b"\xa1" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\xa3" + struct.pack("<I", descriptor_va + 0x0C))
        code.raw(b"\x31\xc0\xa3" + struct.pack("<I", ready_va))
        code.raw(b"\x8b\x07\x6a\x00")
        code.raw(b"\x68" + struct.pack("<I", surface_va))
        code.raw(b"\x68" + struct.pack("<I", descriptor_va))
        code.raw(b"\x57\xff\x50\x18")
        code.raw(b"\xa3" + struct.pack("<I", create_result_va) + b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(b"\x8b\x35" + struct.pack("<I", surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\x89\x3d" + struct.pack("<I", owner_va))

        # IDirectDrawSurface::SetColorKey(DDCKEY_SRCBLT, &key). The cache uses
        # a deliberately uncommon one-bit-blue value, leaving Caption's true
        # black outline and magenta antialiasing untouched during replay.
        code.raw(b"\x8b\x06")
        code.raw(b"\x68" + struct.pack("<I", color_key_va))
        code.raw(b"\x6a" + bytes([self._ddckey_source_blt]))
        code.raw(b"\x56\xff\x50\x74")
        code.raw(b"\xa3" + struct.pack("<I", key_result_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "created")
        code.raw(b"\x8b\x06\x56\xff\x50\x08")
        code.raw(b"\xff\x05" + struct.pack("<I", release_count_va))
        code.raw(b"\x31\xc0")
        for state_va in (surface_va, owner_va, ready_va):
            code.raw(b"\xa3" + struct.pack("<I", state_va))
        code.jump("done")
        code.label("created")
        code.raw(b"\xc7\x44\x24\x1c\x01\x00\x00\x00")
        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()

    def _build_presenter(
        self,
        *,
        wrapper_va: int,
        queue_count_va: int,
        entries_va: int,
        active_object_va: int,
        active_clip_va: int,
        present_count_va: int,
        destination_handle_va: int,
        room_presentation_active_va: int,
        cache_ensure_helper_va: int,
        cache_surface_va: int,
        cache_ready_va: int,
        cache_object_count_va: int,
        cache_objects_va: int,
        cache_rect_va: int,
        cache_generation_rect_va: int,
        current_rect_va: int,
        glyph_rect_valid_va: int,
        glyph_rect_va: int,
        cache_bltfx_va: int,
        cache_fill_result_va: int,
        cache_present_result_va: int,
        cache_build_count_va: int,
        cache_replay_count_va: int,
        cache_destination_wrapper_va: int,
        cache_destination_surface_va: int,
    ) -> bytes:
        """Replay one transparent retained-caption cache on the final page.

        A caption generation is rasterized once into a same-format off-screen
        surface by temporarily replacing only the resolved destination
        wrapper's COM pointer. Stable frames then require one small keyed
        BltFast instead of one DirectDraw transaction per character. Any cache
        failure falls back to the exact native draw loop in the same frame.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x9c\x60\x6a\x00")
        code.raw(b"\x83\x3d" + struct.pack("<I", room_presentation_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "retire")
        code.raw(b"\x8b\x2d" + struct.pack("<I", destination_handle_va) + b"\x85\xed")
        code.jump_if(Condition.EQUAL, "retire")
        code.raw(b"\x8b\x0d" + struct.pack("<I", queue_count_va))
        code.raw(b"\x83\xf9" + bytes([self._entry_capacity]))
        code.jump_if(Condition.BELOW_OR_EQUAL, "count_ready")
        code.raw(b"\xb9" + struct.pack("<I", self._entry_capacity))
        code.label("count_ready")
        code.raw(b"\x89\x0c\x24")
        code.raw(b"\xc7\x05" + struct.pack("<I", queue_count_va) + b"\x00\x00\x00\x00")
        code.raw(b"\x31\xf6")
        code.label("validate_loop")
        code.raw(b"\x3b\x34\x24")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "validated")
        code.raw(b"\x8b\xc6\x6b\xc0" + bytes([self._entry_stride]))
        code.raw(b"\x05" + struct.pack("<I", entries_va) + b"\x8b\xf8")
        code.raw(b"\x8b\x1f\x85\xdb")
        code.jump_if(Condition.EQUAL, "retire")
        code.raw(b"\x68\x08\x01\x00\x00\x53\xff\x15")
        code.raw(struct.pack("<I", self.profile.address("win32.IsBadReadPtr")))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "retire")
        code.raw(b"\x81\x3b" + struct.pack("<I", self.profile.address("caption.vtable")))
        code.jump_if(Condition.NOT_EQUAL, "retire")

        # Build the exact union of mapped Caption bounds. It is both the keyed
        # replay rectangle and the cache-generation geometry key.
        code.raw(b"\x8d\x57" + bytes([self._entry_scaled_rect]))
        code.raw(b"\x85\xf6")
        code.jump_if(Condition.NOT_EQUAL, "union")
        for offset in range(0, 16, 4):
            code.raw(b"\x8b\x42" + bytes([offset]))
            if offset == 0:
                code.raw(b"\xa3" + struct.pack("<I", current_rect_va))
            else:
                code.raw(b"\xa3" + struct.pack("<I", current_rect_va + offset))
        code.jump("validated_next")
        code.label("union")
        for offset, condition, label in (
            (0, Condition.GREATER_OR_EQUAL, "union_top"),
            (4, Condition.GREATER_OR_EQUAL, "union_right"),
            (8, Condition.LESS_OR_EQUAL, "union_bottom"),
            (12, Condition.LESS_OR_EQUAL, "validated_next"),
        ):
            code.raw(b"\x8b\x42" + bytes([offset]))
            code.raw(b"\x3b\x05" + struct.pack("<I", current_rect_va + offset))
            code.jump_if(condition, label)
            code.raw(b"\xa3" + struct.pack("<I", current_rect_va + offset))
            if label != "validated_next":
                code.label(label)
        code.label("validated_next")
        code.raw(b"\x46")
        code.jump("validate_loop")

        code.label("validated")
        code.raw(b"\x83\x3d" + struct.pack("<I", cache_ready_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "rebuild")
        code.raw(b"\xa1" + struct.pack("<I", cache_object_count_va))
        code.raw(b"\x3b\x04\x24")
        code.jump_if(Condition.NOT_EQUAL, "rebuild")
        code.raw(b"\x31\xf6")
        code.label("key_object_loop")
        code.raw(b"\x3b\x34\x24")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "key_rect")
        code.raw(b"\x8b\xc6\x6b\xc0" + bytes([self._entry_stride]))
        code.raw(b"\x8b\x98" + struct.pack("<I", entries_va))
        code.raw(b"\x3b\x1c\xb5" + struct.pack("<I", cache_objects_va))
        code.jump_if(Condition.NOT_EQUAL, "rebuild")
        code.raw(b"\x46")
        code.jump("key_object_loop")
        code.label("key_rect")
        for offset in range(0, 16, 4):
            code.raw(b"\xa1" + struct.pack("<I", current_rect_va + offset))
            code.raw(b"\x3b\x05" + struct.pack("<I", cache_generation_rect_va + offset))
            code.jump_if(Condition.NOT_EQUAL, "rebuild")
        code.jump("replay")

        code.label("rebuild")
        code.call_absolute(cache_ensure_helper_va)
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "native_fallback")
        code.raw(b"\x8b\x35" + struct.pack("<I", cache_surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "native_fallback")
        # Clear the complete cache only when the immutable caption generation
        # changes. DDBLT_COLORFILL accepts the RGB565 transparent-key pixel in
        # the ordinary DDBLTFX union at +0x50.
        code.raw(b"\x8b\x06")
        code.raw(b"\x68" + struct.pack("<I", cache_bltfx_va))
        code.raw(b"\x68" + struct.pack("<I", self._ddblt_colorfill_wait))
        code.raw(b"\x6a\x00\x6a\x00\x6a\x00\x56\xff\x50\x14")
        code.raw(b"\xa3" + struct.pack("<I", cache_fill_result_va) + b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "invalidate_fallback")

        # Resolve the engine Bitmap wrapper once, replace only its raw COM
        # surface for the bounded native glyph loop, and restore it before any
        # other producer can observe the temporary cache destination.
        code.raw(b"\x8b\x0d" + struct.pack("<I", self.profile.address("resource.manager")))
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "invalidate_fallback")
        code.raw(b"\x55")
        code.call_absolute(self.profile.address("bitmap.resolve_resource"))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "invalidate_fallback")
        code.raw(b"\x8b\x78\x30\x85\xff")
        code.jump_if(Condition.EQUAL, "invalidate_fallback")
        code.raw(b"\x89\x3d" + struct.pack("<I", cache_destination_wrapper_va))
        code.raw(b"\x8b\x47\x2c")
        code.raw(b"\xa3" + struct.pack("<I", cache_destination_surface_va))
        code.raw(b"\x89\x77\x2c")
        # The final-blit classifier will union every clipped, transformed
        # glyph into this cross-compiler rectangle during the native loop.
        code.raw(b"\xc7\x05" + struct.pack("<I", glyph_rect_valid_va) + b"\x00\x00\x00\x00")
        code.raw(b"\x31\xf6")
        code.label("raster_loop")
        code.raw(b"\x3b\x34\x24")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "raster_done")
        code.raw(b"\x8b\xc6\x6b\xc0" + bytes([self._entry_stride]))
        code.raw(b"\x05" + struct.pack("<I", entries_va) + b"\x8b\xf8")
        code.raw(b"\x8b\x1f")
        code.raw(b"\x89\x1d" + struct.pack("<I", active_object_va))
        code.raw(b"\x8d\x47" + bytes([self._entry_scaled_rect]))
        code.raw(b"\xa3" + struct.pack("<I", active_clip_va))
        code.raw(b"\x8d\x47" + bytes([self._entry_damage_region]) + b"\x50\x55\x8b\xcb")
        code.call_absolute(self.profile.address("caption.draw"))
        code.raw(b"\x46")
        code.jump("raster_loop")
        code.label("raster_done")
        code.raw(b"\x8b\x3d" + struct.pack("<I", cache_destination_wrapper_va))
        code.raw(b"\xa1" + struct.pack("<I", cache_destination_surface_va))
        code.raw(b"\x89\x47\x2c")
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", active_object_va))
        code.raw(b"\xa3" + struct.pack("<I", active_clip_va))
        code.raw(b"\x83\x3d" + struct.pack("<I", glyph_rect_valid_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "invalidate_fallback")
        code.raw(b"\x8b\x0c\x24")
        code.raw(b"\x89\x0d" + struct.pack("<I", cache_object_count_va))
        code.raw(b"\x31\xf6")
        code.label("publish_object_loop")
        code.raw(b"\x3b\xf1")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "publish_rect")
        code.raw(b"\x8b\xc6\x6b\xc0" + bytes([self._entry_stride]))
        code.raw(b"\x8b\x98" + struct.pack("<I", entries_va))
        code.raw(b"\x89\x1c\xb5" + struct.pack("<I", cache_objects_va))
        code.raw(b"\x46")
        code.jump("publish_object_loop")
        code.label("publish_rect")
        for offset in range(0, 16, 4):
            code.raw(b"\xa1" + struct.pack("<I", current_rect_va + offset))
            code.raw(b"\xa3" + struct.pack("<I", cache_generation_rect_va + offset))
            code.raw(b"\xa1" + struct.pack("<I", glyph_rect_va + offset))
            code.raw(b"\xa3" + struct.pack("<I", cache_rect_va + offset))
        code.raw(b"\xc7\x05" + struct.pack("<I", cache_ready_va) + b"\x01\x00\x00\x00")
        code.raw(b"\xff\x05" + struct.pack("<I", cache_build_count_va))

        code.label("replay")
        code.raw(b"\x8b\x35" + struct.pack("<I", cache_surface_va) + b"\x85\xf6")
        code.jump_if(Condition.EQUAL, "native_fallback")
        code.raw(
            b"\x8b\x3d" + struct.pack("<I", self.profile.address("transition.back_surface_ptr"))
        )
        code.raw(b"\x85\xff")
        code.jump_if(Condition.EQUAL, "native_fallback")
        code.raw(b"\x8b\x07")
        code.raw(b"\x6a" + bytes([self._ddbltfast_source_key]))
        code.raw(b"\x68" + struct.pack("<I", cache_rect_va))
        code.raw(b"\x56")
        code.raw(b"\xff\x35" + struct.pack("<I", cache_rect_va + 4))
        code.raw(b"\xff\x35" + struct.pack("<I", cache_rect_va))
        code.raw(b"\x57\xff\x50\x1c")
        code.raw(b"\xa3" + struct.pack("<I", cache_present_result_va) + b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "invalidate_fallback")
        code.raw(b"\xff\x05" + struct.pack("<I", cache_replay_count_va))
        code.raw(b"\x8b\x04\x24\x01\x05" + struct.pack("<I", present_count_va))
        code.jump("done")

        code.label("invalidate_fallback")
        code.raw(b"\xc7\x05" + struct.pack("<I", cache_ready_va) + b"\x00\x00\x00\x00")
        code.label("native_fallback")
        code.raw(b"\x31\xf6")
        code.label("native_loop")
        code.raw(b"\x3b\x34\x24")
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        code.raw(b"\x8b\xc6\x6b\xc0" + bytes([self._entry_stride]))
        code.raw(b"\x05" + struct.pack("<I", entries_va) + b"\x8b\xf8")
        code.raw(b"\x8b\x1f")
        code.raw(b"\x89\x1d" + struct.pack("<I", active_object_va))
        code.raw(b"\x8d\x47" + bytes([self._entry_scaled_rect]))
        code.raw(b"\xa3" + struct.pack("<I", active_clip_va))
        code.raw(b"\x8d\x47" + bytes([self._entry_damage_region]) + b"\x50\x55\x8b\xcb")
        code.call_absolute(self.profile.address("caption.draw"))
        code.raw(b"\xff\x05" + struct.pack("<I", present_count_va))
        code.raw(b"\x46")
        code.jump("native_loop")
        code.label("retire")
        code.raw(b"\xc7\x05" + struct.pack("<I", queue_count_va) + b"\x00\x00\x00\x00")
        code.label("done")
        code.raw(b"\x31\xc0")
        code.raw(b"\xa3" + struct.pack("<I", active_object_va))
        code.raw(b"\xa3" + struct.pack("<I", active_clip_va))
        code.raw(b"\x83\xc4\x04\x61\x9d\xc3")
        return code.build()

    def _build_damage_augmenter(
        self,
        *,
        wrapper_va: int,
        pending_valid_va: int,
        pending_rect_va: int,
        augment_count_va: int,
    ) -> bytes:
        """Map one caption cleanup union into ECX/EDX's stage damage."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60\x8b\xf1\x8b\xfa")
        for dimension_va in (
            self._physical_width_va,
            self._physical_width_va + 4,
            self.room_rendering_abi.width_va,
            self.room_rendering_abi.height_va,
        ):
            code.raw(b"\x83\x3d" + struct.pack("<I", dimension_va) + b"\x00")
            code.jump_if(Condition.LESS_OR_EQUAL, "done")
        code.raw(b"\x83\x3d" + struct.pack("<I", pending_valid_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "done")

        # Clamp the physical producer rectangle before converting it into the
        # private stage domain. Near edges use floor; far edges use ceil.
        for register_load, register_test, register_zero, dimension_va, rect_offset, suffix in (
            (b"\x8b\x1d", b"\x85\xdb", b"\x31\xdb", self._physical_width_va, 0, "left"),
            (b"\x8b\x2d", b"\x85\xed", b"\x31\xed", self._physical_width_va + 4, 4, "top"),
            (b"\x8b\x0d", b"\x85\xc9", b"\x31\xc9", self._physical_width_va, 8, "right"),
            (b"\x8b\x15", b"\x85\xd2", b"\x31\xd2", self._physical_width_va + 4, 12, "bottom"),
        ):
            code.raw(register_load + struct.pack("<I", pending_rect_va + rect_offset))
            code.raw(register_test)
            code.jump_if(Condition.GREATER_OR_EQUAL, f"{suffix}_nonnegative")
            code.raw(register_zero)
            code.label(f"{suffix}_nonnegative")
            compare_opcode = {
                b"\x8b\x1d": b"\x3b\x1d",
                b"\x8b\x2d": b"\x3b\x2d",
                b"\x8b\x0d": b"\x3b\x0d",
                b"\x8b\x15": b"\x3b\x15",
            }[register_load]
            code.raw(compare_opcode + struct.pack("<I", dimension_va))
            code.jump_if(Condition.LESS_OR_EQUAL, f"{suffix}_clamped")
            code.raw(register_load + struct.pack("<I", dimension_va))
            code.label(f"{suffix}_clamped")
        code.raw(b"\x3b\xd9")
        code.jump_if(Condition.GREATER_OR_EQUAL, "consume")
        code.raw(b"\x3b\xea")
        code.jump_if(Condition.GREATER_OR_EQUAL, "consume")

        # Store mapped edges in the original pending rectangle as temporary
        # scratch; it is consumed below and never exposed as physical state.
        code.raw(b"\x8b\xc3\x0f\xaf\x05" + struct.pack("<I", self.room_rendering_abi.width_va))
        code.raw(b"\x31\xd2\xf7\x35" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\xa3" + struct.pack("<I", pending_rect_va))
        code.raw(b"\x8b\xc5\x0f\xaf\x05" + struct.pack("<I", self.room_rendering_abi.height_va))
        code.raw(b"\x31\xd2\xf7\x35" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", pending_rect_va + 4))
        code.raw(b"\x8b\xc1\x0f\xaf\x05" + struct.pack("<I", self.room_rendering_abi.width_va))
        code.raw(b"\x03\x05" + struct.pack("<I", self._physical_width_va) + b"\x48")
        code.raw(b"\x31\xd2\xf7\x35" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\xa3" + struct.pack("<I", pending_rect_va + 8))
        # Reload physical bottom because the preceding DIV consumed EDX.
        code.raw(b"\xa1" + struct.pack("<I", pending_rect_va + 12))
        code.raw(b"\x0f\xaf\x05" + struct.pack("<I", self.room_rendering_abi.height_va))
        code.raw(b"\x03\x05" + struct.pack("<I", self._physical_width_va + 4) + b"\x48")
        code.raw(b"\x31\xd2\xf7\x35" + struct.pack("<I", self._physical_width_va + 4))
        code.raw(b"\xa3" + struct.pack("<I", pending_rect_va + 12))

        code.raw(b"\x83\x3f\x00")
        code.jump_if(Condition.NOT_EQUAL, "union")
        for source_offset, target_offset in ((0, 0), (4, 4), (8, 8), (12, 12)):
            code.raw(b"\xa1" + struct.pack("<I", pending_rect_va + source_offset))
            code.raw(b"\x89\x06" if target_offset == 0 else b"\x89\x46" + bytes([target_offset]))
        code.raw(b"\xc7\x07\x01\x00\x00\x00")
        code.jump("count")
        code.label("union")
        for source_offset, target_offset, condition, label in (
            (0, 0, Condition.GREATER_OR_EQUAL, "union_top"),
            (4, 4, Condition.GREATER_OR_EQUAL, "union_right"),
            (8, 8, Condition.LESS_OR_EQUAL, "union_bottom"),
            (12, 12, Condition.LESS_OR_EQUAL, "count"),
        ):
            code.raw(b"\xa1" + struct.pack("<I", pending_rect_va + source_offset))
            code.raw(b"\x3b\x06" if target_offset == 0 else b"\x3b\x46" + bytes([target_offset]))
            code.jump_if(condition, label)
            code.raw(b"\x89\x06" if target_offset == 0 else b"\x89\x46" + bytes([target_offset]))
            if label != "count":
                code.label(label)
        code.label("count")
        code.raw(b"\xff\x05" + struct.pack("<I", augment_count_va))
        code.label("consume")
        code.raw(b"\xc7\x05" + struct.pack("<I", pending_valid_va) + b"\x00\x00\x00\x00")
        code.label("done")
        code.raw(b"\x61\xc3")
        return code.build()

    def _payload(self, *, section_va: int) -> bytes:
        """Build the deterministic caption segment and validate every slot."""
        queue_count_va = section_va + self._off_queue_count
        entries_va = section_va + self._off_entries
        geometry_helper_va = section_va + self._off_geometry_helper
        damage_record_helper_va = section_va + self._off_damage_record_helper
        cache_ensure_helper_va = section_va + self._off_cache_ensure_helper
        glyph_recorder_va = section_va + self._off_glyph_recorder
        draw_wrapper = self._build_draw_wrapper(
            wrapper_va=section_va + self._off_draw_wrapper,
            geometry_helper_va=geometry_helper_va,
            queue_count_va=queue_count_va,
            entries_va=entries_va,
            defer_count_va=section_va + self._off_defer_count,
            overflow_count_va=section_va + self._off_overflow_count,
            room_presentation_active_va=self.transition_abi.room_presentation_active_va,
        )
        destructor_wrapper = self._build_destructor_wrapper(
            wrapper_va=section_va + self._off_destructor_wrapper,
            geometry_helper_va=geometry_helper_va,
            cleanup_native_rect_va=section_va + self._off_cleanup_native_rect,
            cleanup_scaled_rect_va=section_va + self._off_cleanup_scaled_rect,
            cleanup_count_va=section_va + self._off_destructor_cleanup_count,
            cache_ready_va=section_va + self._off_cache_ready,
            cache_object_count_va=section_va + self._off_cache_object_count,
            room_presentation_active_va=self.transition_abi.room_presentation_active_va,
        )
        cache_ensure_helper = self._build_cache_ensure_helper(
            wrapper_va=cache_ensure_helper_va,
            ddraw_va=self.profile.address("high_resolution_3d.directdraw_ptr"),
            surface_va=section_va + self._off_cache_surface,
            owner_va=section_va + self._off_cache_owner,
            ready_va=section_va + self._off_cache_ready,
            descriptor_va=section_va + self._off_cache_descriptor,
            color_key_va=section_va + self._off_cache_color_key,
            create_result_va=section_va + self._off_cache_create_result,
            key_result_va=section_va + self._off_cache_key_result,
            release_count_va=section_va + self._off_cache_release_count,
        )
        presenter = self._build_presenter(
            wrapper_va=section_va + self._off_presenter,
            queue_count_va=queue_count_va,
            entries_va=entries_va,
            active_object_va=section_va + self._off_active_object,
            active_clip_va=section_va + self._off_active_clip,
            present_count_va=section_va + self._off_present_count,
            destination_handle_va=(
                self.symbols.va("system_controls") + SYSTEM_CONTROL_CURSOR_STATE_OFFSET + 128
            ),
            room_presentation_active_va=self.transition_abi.room_presentation_active_va,
            cache_ensure_helper_va=cache_ensure_helper_va,
            cache_surface_va=section_va + self._off_cache_surface,
            cache_ready_va=section_va + self._off_cache_ready,
            cache_object_count_va=section_va + self._off_cache_object_count,
            cache_objects_va=section_va + self._off_cache_objects,
            cache_rect_va=section_va + self._off_cache_rect,
            cache_generation_rect_va=section_va + self._off_cache_generation_rect,
            current_rect_va=section_va + self._off_cache_current_rect,
            glyph_rect_valid_va=section_va + self._off_glyph_rect_valid,
            glyph_rect_va=section_va + self._off_glyph_rect,
            cache_bltfx_va=section_va + self._off_cache_bltfx,
            cache_fill_result_va=section_va + self._off_cache_fill_result,
            cache_present_result_va=section_va + self._off_cache_present_result,
            cache_build_count_va=section_va + self._off_cache_build_count,
            cache_replay_count_va=section_va + self._off_cache_replay_count,
            cache_destination_wrapper_va=(section_va + self._off_cache_destination_wrapper),
            cache_destination_surface_va=(section_va + self._off_cache_destination_surface),
        )
        geometry_helper = self._build_geometry_helper(
            wrapper_va=geometry_helper_va,
            damage_record_helper_va=damage_record_helper_va,
            pending_valid_va=section_va + self._off_pending_valid,
            pending_rect_va=section_va + self._off_pending_rect,
            cache_ready_va=section_va + self._off_cache_ready,
            cache_object_count_va=section_va + self._off_cache_object_count,
            cache_objects_va=section_va + self._off_cache_objects,
        )
        damage_augmenter = self._build_damage_augmenter(
            wrapper_va=section_va + self._off_damage_augmenter,
            pending_valid_va=section_va + self._off_pending_valid,
            pending_rect_va=section_va + self._off_pending_rect,
            augment_count_va=section_va + self._off_damage_augment_count,
        )
        damage_record_helper = self._build_damage_record_helper(wrapper_va=damage_record_helper_va)
        glyph_recorder = self._build_glyph_recorder(
            wrapper_va=glyph_recorder_va,
            active_object_va=section_va + self._off_active_object,
            glyph_rect_valid_va=section_va + self._off_glyph_rect_valid,
            glyph_rect_va=section_va + self._off_glyph_rect,
            damage_record_helper_va=damage_record_helper_va,
        )
        for label, offset, payload, limit in (
            ("Draw wrapper", self._off_draw_wrapper, draw_wrapper, self._off_draw_wrapper_limit),
            (
                "destructor wrapper",
                self._off_destructor_wrapper,
                destructor_wrapper,
                self._off_destructor_wrapper_limit,
            ),
            ("presenter", self._off_presenter, presenter, self._off_presenter_limit),
            (
                "geometry helper",
                self._off_geometry_helper,
                geometry_helper,
                self._off_geometry_helper_limit,
            ),
            (
                "damage augmenter",
                self._off_damage_augmenter,
                damage_augmenter,
                self._off_damage_augmenter_limit,
            ),
            (
                "damage recorder",
                self._off_damage_record_helper,
                damage_record_helper,
                self._off_damage_record_helper_limit,
            ),
            (
                "cache ensure helper",
                self._off_cache_ensure_helper,
                cache_ensure_helper,
                self._off_cache_ensure_helper_limit,
            ),
            (
                "glyph recorder",
                self._off_glyph_recorder,
                glyph_recorder,
                self._off_glyph_recorder_limit,
            ),
        ):
            if offset + len(payload) > limit:
                msg = f"{self.id} {label} exceeds its reserved slot"
                raise PatchError(msg)

        payload = bytearray(self._section_size)
        payload[: len(self._magic)] = self._magic
        struct.pack_into("<I", payload, self._off_layout_version, self._layout_version)
        descriptor = bytearray(self._ddsd_size)
        struct.pack_into("<II", descriptor, 0, self._ddsd_size, self._ddsd_caps_height_width)
        struct.pack_into("<I", descriptor, 0x68, self._offscreen_caps)
        payload[self._off_cache_descriptor : self._off_cache_descriptor + self._ddsd_size] = (
            descriptor
        )
        bltfx = bytearray(self._ddbltfx_size)
        struct.pack_into("<I", bltfx, 0, self._ddbltfx_size)
        struct.pack_into("<I", bltfx, 0x50, self._cache_transparent_pixel)
        payload[self._off_cache_bltfx : self._off_cache_bltfx + self._ddbltfx_size] = bltfx
        struct.pack_into(
            "<II",
            payload,
            self._off_cache_color_key,
            self._cache_transparent_pixel,
            self._cache_transparent_pixel,
        )
        for index in range(self._entry_capacity):
            entry_offset = self._off_entries + index * self._entry_stride
            native_rect_va = section_va + entry_offset + self._entry_native_rect
            struct.pack_into(
                "<IIII",
                payload,
                entry_offset + self._entry_damage_region,
                0,
                native_rect_va,
                native_rect_va + 16,
                0,
            )
        for offset, body in (
            (self._off_draw_wrapper, draw_wrapper),
            (self._off_destructor_wrapper, destructor_wrapper),
            (self._off_presenter, presenter),
            (self._off_geometry_helper, geometry_helper),
            (self._off_damage_augmenter, damage_augmenter),
            (self._off_damage_record_helper, damage_record_helper),
            (self._off_cache_ensure_helper, cache_ensure_helper),
            (self._off_glyph_recorder, glyph_recorder),
        ):
            payload[offset : offset + len(body)] = body
        return bytes(payload)

    def precheck(self, image: PEFile) -> None:
        """Require pristine Caption vtable ownership and an absent segment."""
        if image.get_section(self._section_name) is not None:
            msg = f"{self.id} requires a pristine caption segment"
            raise PatchError(msg)
        for label, slot, expected in (
            ("Draw", self._draw_slot_va, self.profile.address("caption.draw")),
            ("destructor", self._destructor_slot_va, self.profile.address("caption.destructor")),
        ):
            actual = image.read_u32_va(slot)
            if actual != expected:
                msg = (
                    f"{self.id} {label} slot mismatch: expected 0x{expected:08x}, "
                    f"got 0x{actual:08x}"
                )
                raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Install the caption segment and redirect its two unique slots."""
        section_va = self.symbols.va(self._section_name)
        section = install_runtime_segment(image, CAPTION_SEGMENT)
        image.write_bytes(section.pointer_to_raw_data, self._payload(section_va=section_va))
        image.write_u32_va(self._draw_slot_va, section_va + self._off_draw_wrapper)
        image.write_u32_va(self._destructor_slot_va, section_va + self._off_destructor_wrapper)

    def postcheck(self, image: PEFile) -> None:
        """Verify the complete deterministic caption payload and redirects."""
        section = image.get_section(self._section_name)
        if section is None:
            msg = f"{self.id} caption segment is missing"
            raise PatchError(msg)
        section_va = image.rva_to_va(section.virtual_address)
        expected = self._payload(section_va=section_va)
        actual = image.read_bytes(section.pointer_to_raw_data, len(expected))
        if actual != expected:
            msg = f"{self.id} caption payload mismatch"
            raise PatchError(msg)
        for label, slot, expected_va in (
            ("Draw", self._draw_slot_va, section_va + self._off_draw_wrapper),
            ("destructor", self._destructor_slot_va, section_va + self._off_destructor_wrapper),
        ):
            actual_va = image.read_u32_va(slot)
            if actual_va != expected_va:
                msg = f"{self.id} {label} redirect mismatch"
                raise PatchError(msg)
