"""Synchronize native DirectDraw pages across 2D-to-3D transitions."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, decode_rel32_branch
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


@dataclass(frozen=True, slots=True)
class TransitionFrameABI:
    """Runtime state intentionally exported to dependent page presenters."""

    successful_flip_count_va: int
    room_presentation_active_va: int
    pre_flip_presenter_slot_va: int
    post_flip_presenter_slot_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionFrameCompiler:
    """Synchronize native DirectDraw pages when ownership crosses 2D and 3D.

    Outcome:
        Restore and room transitions cannot expose an uninitialized, black, or
        stale peer from GK3's two-page native flip chain.

    Before:
        GK3 retains separate background histories for two physical pages while
        DirectDraw exposes one stable back-surface interface. A page returned
        by ``Flip`` may therefore have neither current pixels nor a matching
        damage history, notably during Restore and the motorcycle transition.

    After:
        Both physical pages and their room-owned histories are initialized in
        successful-Flip generation order before normal frame presentation
        resumes.

    Strategy:
        A primary-surface 2D Blt arms a handoff. The next two room-owned scene
        generations copy the complete presented page into the returned back
        page and invoke GK3's whole-scene invalidation. The budget follows
        successful Flip generations and concrete layer ownership, never time,
        resolution, or a stable COM wrapper address. Typed callback slots let
        the fixed-interface runtime present overlays immediately before and
        after Flip without stacking another hook.

    Boundaries:
        Presentation remains GK3's native fullscreen ``Flip``. Fixed 2D
        interfaces own their own composition; surface creation, Direct3D
        drawing, mode selection, cadence, and frame limiting are unchanged.
    """

    id: ClassVar[str] = "prevent_transition_flicker"
    profile: BuildProfile

    _section_name: ClassVar[str] = ".gk3dd"
    section_name: ClassVar[str] = _section_name
    _section_size: ClassVar[int] = 0x800
    _section_characteristics: ClassVar[int] = 0xE0000020
    _magic: ClassVar[bytes] = b"GK3NDD1\0"
    _layout_version: ClassVar[int] = 162
    _native_flip_page_count: ClassVar[int] = 2
    _off_layout_version: ClassVar[int] = 0x08
    # Control state consumed by later hooks.
    _off_flips_since_begin: ClassVar[int] = 0x10
    _off_repair_active: ClassVar[int] = 0x14
    _off_seed_pages_remaining: ClassVar[int] = 0x3C
    _off_handoff_pending: ClassVar[int] = 0x44
    # Optional no-argument callback installed by the fixed-interface runtime.
    # This patch remains independently useful while the cell is zero.
    _off_pre_flip_presenter: ClassVar[int] = 0x48
    # IDirectDrawSurface::Flip lives inside GK3's bounded retry loop. A retry
    # still addresses the same completed back page, so overlays may be composed
    # only once for each pending Flip generation. BeginScene is not a valid
    # identity here: retained 2D screens can Flip repeatedly without entering
    # Direct3D, notably while Restore updates its progress bar and loading
    # cursor. The successful-Flip count advances only after DD_OK, so retries
    # of one page retain the same generation.
    _off_last_presented_flip_generation: ClassVar[int] = 0x4C
    _off_presenter_call_count: ClassVar[int] = 0x50
    _off_presenter_retry_skip_count: ClassVar[int] = 0x54
    # Optional no-argument callback for a retained 2D producer that must
    # initialize the page returned by a successful native Flip. Unlike the
    # pre-Flip room presenter, this callback runs once per DD_OK generation.
    _off_post_flip_presenter: ClassVar[int] = 0x58
    _off_post_flip_presenter_call_count: ClassVar[int] = 0x5C
    # Successful Flip generation is a small public runtime ABI consumed by the
    # fixed-interface TimeBlock page initializer. The remaining fields are
    # diagnostics only.
    _off_flip_count: ClassVar[int] = 0x0C
    _off_begin_count: ClassVar[int] = 0x18
    # The DirectDraw back-surface interface pointer remains stable while Flip
    # exchanges its underlying page memory.  This generation is therefore the
    # only reliable identity for a page seed.
    _off_last_seed_flip_generation: ClassVar[int] = 0x1C
    _off_last_flip_result: ClassVar[int] = 0x20
    _off_scene_invalidation_count: ClassVar[int] = 0x24
    _off_seed_count: ClassVar[int] = 0x28
    _off_last_seed_result: ClassVar[int] = 0x2C
    _off_2d_exit_count: ClassVar[int] = 0x30
    _off_blt_count: ClassVar[int] = 0x34
    _off_primary_blt_count: ClassVar[int] = 0x38
    _off_flip_wrapper: ClassVar[int] = 0x60
    # Diagnostic only: 1=native Flip entered, 2=Flip returned, 3=the following
    # BeginScene entered. Repair decisions never read this field.
    _off_frame_phase: ClassVar[int] = 0x40
    # The canonical renderer Blt helper retries one logical operation as many
    # as 99,999 times when DirectDraw reports a busy surface. Retain the caller
    # and bounded retry maxima so performance RCA can distinguish many cheap
    # UI transfers from one pathological blocking producer.
    _off_blt_retry_caller: ClassVar[int] = 0x420
    _off_blt_retry_current: ClassVar[int] = 0x424
    _off_blt_retry_max: ClassVar[int] = 0x428
    _off_blt_retry_max_caller: ClassVar[int] = 0x42C
    # This is presentation ownership, not transition-repair state. Every
    # concrete RoomLayer scene setup publishes it, including a save restored
    # directly into a room where no 2D-to-3D repair handoff was observed. The
    # first later Flip without a BeginScene clears it at the exact 3D-to-2D
    # boundary. Fixed-interface overlays consume this narrow runtime ABI.
    _off_room_presentation_active: ClassVar[int] = 0x430
    # Diagnostic record for the last canonical Blt whose concrete destination
    # was the physical primary surface.  This is deliberately observation-only:
    # the native COM frame remains untouched and the values are never consumed
    # by presentation logic.  A single record is sufficient because the
    # capture harness brackets each screenshot with the monotonically
    # increasing count.
    _off_primary_blt_trace_count: ClassVar[int] = 0x434
    _off_primary_blt_trace_caller: ClassVar[int] = 0x438
    _off_primary_blt_trace_source: ClassVar[int] = 0x43C
    _off_primary_blt_trace_flags: ClassVar[int] = 0x440
    _off_primary_blt_trace_dest_valid: ClassVar[int] = 0x444
    _off_primary_blt_trace_dest_rect: ClassVar[int] = 0x448
    _off_primary_blt_trace_source_valid: ClassVar[int] = 0x458
    _off_primary_blt_trace_source_rect: ClassVar[int] = 0x45C
    _off_scene_wrapper: ClassVar[int] = 0x180
    _off_begin_wrapper: ClassVar[int] = 0x400
    _off_blt_wrapper: ClassVar[int] = 0x500
    _anchors: ClassVar[tuple[tuple[str, str], ...]] = (
        ("transition.flip_retry_anchor", "Flip retry setup"),
        ("transition.flip_result_anchor", "Flip result handling"),
        ("transition.scene_setup_anchor", "3D frame setup"),
        ("transition.begin_scene_anchor", "Direct3D BeginScene wrapper"),
        ("transition.blt_result_anchor", "2D Blt result handling"),
    )

    @classmethod
    def runtime_abi(cls, pe: PEFile) -> TransitionFrameABI:
        """Validate and return the transition patch's narrow public ABI."""
        section = pe.get_section(cls._section_name)
        if section is None:
            msg = f"{cls.id} dependency section is missing"
            raise PatchError(msg)
        section_offset = section.pointer_to_raw_data
        section_va = pe.rva_to_va(section.virtual_address)
        if (
            pe.read_bytes(section_offset, len(cls._magic)) != cls._magic
            or pe.read_u32_va(section_va + cls._off_layout_version) != cls._layout_version
        ):
            msg = f"{cls.id} dependency ABI is incompatible"
            raise PatchError(msg)
        return TransitionFrameABI(
            successful_flip_count_va=section_va + cls._off_flip_count,
            # Scene setup raises this flag when a concrete RoomLayer begins
            # owning the repaired flip chain.  The first later Flip without a
            # BeginScene clears it before invoking the linked presenter.  It is
            # therefore the durable room-lifetime proof; stage allocation alone
            # is insufficient because GK3 retains that surface on pure 2D
            # screens such as TimeBlock.
            room_presentation_active_va=section_va + cls._off_room_presentation_active,
            pre_flip_presenter_slot_va=section_va + cls._off_pre_flip_presenter,
            post_flip_presenter_slot_va=(section_va + cls._off_post_flip_presenter),
        )

    def _check_anchors(self, pe: PEFile) -> None:
        for symbol, label in self._anchors:
            site = self.profile.site(symbol)
            got = pe.read_bytes(pe.va_to_offset(site.va), len(site.original))
            if got != site.original:
                msg = f"{self.id} precheck failed: unexpected {label} bytes"
                raise PatchError(msg)

    @staticmethod
    def _hook_target(site_va: int, payload: bytes) -> int | None:
        return decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=site_va,
            instruction=payload[:5],
        )

    def _build_flip_wrapper(
        self,
        *,
        wrapper_va: int,
        flip_count_va: int,
        flips_since_begin_va: int,
        repair_active_va: int,
        room_presentation_active_va: int,
        last_flip_result_va: int,
        handoff_pending_va: int,
        seed_pages_remaining_va: int,
        last_seed_flip_generation_va: int,
        exit_2d_count_va: int,
        frame_phase_va: int,
        pre_flip_presenter_slot_va: int,
        last_presented_flip_generation_va: int,
        presenter_call_count_va: int,
        presenter_retry_skip_count_va: int,
        post_flip_presenter_slot_va: int,
        post_flip_presenter_call_count_va: int,
    ) -> bytes:
        """Preserve native Flip and close repair after a 2D-only frame."""
        # EBX is live in the displaced retry loop, so preserve it even though
        # this wrapper itself uses only EAX for the COM result.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x53")
        # Room presentation is an independent lifetime from transition repair.
        # BeginScene resets flips_since_begin for every genuine 3D frame; a
        # later Flip which observes the prior successful generation therefore
        # marks the exact first 2D-only boundary.
        code.raw(b"\x83\x3d" + struct.pack("<I", room_presentation_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "repair_boundary")
        code.raw(b"\x83\x3d" + struct.pack("<I", flips_since_begin_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "repair_boundary")
        code.raw(b"\xc7\x05" + struct.pack("<I", room_presentation_active_va) + b"\x00\x00\x00\x00")
        code.label("repair_boundary")
        # BeginScene resets flips_since_begin immediately before a genuine 3D
        # frame. A nonzero value therefore identifies the first following 2D-
        # only presentation. End the repaired 3D session and arm exactly the
        # next 2D-to-3D handoff.
        code.raw(b"\x83\x3d" + struct.pack("<I", repair_active_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "invoke_flip")
        code.raw(b"\x83\x3d" + struct.pack("<I", flips_since_begin_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "invoke_flip")
        code.raw(b"\xc7\x05" + struct.pack("<I", repair_active_va) + b"\x00\x00\x00\x00")
        # This 2D-only boundary is the authoritative handoff owner. Arming here
        # also covers interfaces that return to 3D without another primary Blt.
        code.raw(b"\xc7\x05" + struct.pack("<I", handoff_pending_va) + b"\x01\x00\x00\x00")
        code.raw(
            b"\xc7\x05"
            + struct.pack("<I", seed_pages_remaining_va)
            + struct.pack("<I", self._native_flip_page_count)
        )
        code.raw(
            b"\xc7\x05" + struct.pack("<I", last_seed_flip_generation_va) + b"\xff\xff\xff\xff"
        )
        code.raw(b"\xff\x05" + struct.pack("<I", exit_2d_count_va))

        code.label("invoke_flip")
        # Give one linked presenter the completed back page immediately before
        # the first native Flip attempt for this pending page generation. The native code
        # retries DDERR_WASSTILLDRAWING/EXCLUSIVEMODEALREADYSET/SURFACELOST at
        # this exact call site without rebuilding the page. Presenting again on
        # a retry can paint a newly moved cursor beside the first one. The
        # monotonic successful-Flip generation is the exact page identity and
        # also advances across retained 2D frames with no BeginScene. Skip a
        # repeated attempt, but let the native Flip retry unchanged. This same
        # render-thread boundary prevents a window-message callback from
        # interleaving between initial composition and page exchange;
        # standalone transition repair leaves the callback cell null.
        code.raw(b"\xa1" + struct.pack("<I", flip_count_va))
        code.raw(b"\x3b\x05" + struct.pack("<I", last_presented_flip_generation_va))
        code.jump_if(Condition.EQUAL, "presenter_already_ran")
        code.raw(b"\xa3" + struct.pack("<I", last_presented_flip_generation_va))
        code.raw(b"\xa1" + struct.pack("<I", pre_flip_presenter_slot_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "flip_ready")
        code.raw(b"\xff\xd0")
        code.raw(b"\xff\x05" + struct.pack("<I", presenter_call_count_va))
        code.jump_short("flip_ready")
        code.label("presenter_already_ran")
        code.raw(b"\xff\x05" + struct.pack("<I", presenter_retry_skip_count_va))
        code.label("flip_ready")
        # Replay IDirectDrawSurface4::Flip(primary, NULL, ESI).
        code.raw(b"\xc7\x05" + struct.pack("<I", frame_phase_va) + b"\x01\x00\x00\x00")
        code.raw(
            b"\xa1" + struct.pack("<I", self.profile.address("transition.primary_surface_ptr"))
        )
        code.raw(b"\x56\x6a\x00\x50\x8b\x08\xff\x51\x2c")
        code.raw(b"\xa3" + struct.pack("<I", last_flip_result_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", frame_phase_va) + b"\x02\x00\x00\x00")
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "flip_done")
        # Publish the generation only after DD_OK. Fixed interfaces use this
        # monotonic value to distinguish physical flip pages behind DirectDraw's
        # stable back-surface interface pointer.
        code.raw(b"\xff\x05" + struct.pack("<I", flip_count_va))
        code.raw(b"\xff\x05" + struct.pack("<I", flips_since_begin_va))
        # A fixed 2D producer may need to populate the page which Flip just
        # returned as the new back page. Invoke its linked callback only after
        # DD_OK, so retries and failed exchanges cannot consume page state.
        code.raw(b"\xa1" + struct.pack("<I", post_flip_presenter_slot_va) + b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "flip_done")
        code.raw(b"\xff\xd0")
        code.raw(b"\xff\x05" + struct.pack("<I", post_flip_presenter_call_count_va))
        code.label("flip_done")
        code.raw(b"\xa1" + struct.pack("<I", last_flip_result_va))
        code.raw(b"\x5b")
        code.ret()
        return code.build()

    def _build_scene_wrapper(
        self,
        *,
        wrapper_va: int,
        repair_active_va: int,
        room_presentation_active_va: int,
        handoff_pending_va: int,
        scene_invalidation_count_va: int,
        seed_pages_remaining_va: int,
        flip_count_va: int,
        last_seed_flip_generation_va: int,
        seed_count_va: int,
        last_seed_result_va: int,
    ) -> bytes:
        """Repair the current page before GK3 prepares its 3D frame."""
        # Preserve every register across the preparatory page work;
        # the original scene-setup instruction expects the untouched context.
        code = X86Emitter(base_va=wrapper_va)
        code.raw(b"\x60")
        # Publish room ownership on every concrete RoomLayer scene setup. This
        # is deliberately independent of a pending transition seed: restoring
        # a save can enter 3D directly without a preceding primary 2D Blt.
        # EDI retains the same-frame concrete-layer proof for the optional seed
        # below, avoiding a second current-layer query in this hot wrapper.
        code.raw(b"\x31\xff")
        code.call_absolute(self.profile.address("ui.current_layer"))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "room_owner_ready")
        code.raw(
            b"\x81\x38" + struct.pack("<I", self.profile.address("transition.room_layer_vtable"))
        )
        code.jump_if(Condition.NOT_EQUAL, "room_owner_ready")
        code.raw(b"\xc7\x05" + struct.pack("<I", room_presentation_active_va) + b"\x01\x00\x00\x00")
        code.raw(b"\x47")
        code.label("room_owner_ready")
        # Initialize only the two physical pages owned by this handoff. The
        # earlier implementation invalidated the entire room on every later
        # frame; besides being unnecessary after both histories were rebuilt,
        # that made high-density output modes redraw every object at a few FPS.
        code.raw(b"\x83\x3d" + struct.pack("<I", seed_pages_remaining_va) + b"\x00")
        code.jump_if(Condition.EQUAL, "replay_scene_setup")
        # Multiple scene setups can occur before one presentation.  DirectDraw
        # keeps the same back-surface interface pointer across Flip, so consume
        # at most one seed for each successful-Flip generation instead of
        # assuming every setup already addresses the other page.
        code.raw(b"\xa1" + struct.pack("<I", flip_count_va))
        code.raw(b"\x3b\x05" + struct.pack("<I", last_seed_flip_generation_va))
        code.jump_if(Condition.EQUAL, "replay_scene_setup")
        # A modal compositor may execute scene setup while constructing a
        # captured-room bitmap. Neither seed nor invalidate under that modal:
        # wait until the concrete room layer owns both operations.
        code.raw(b"\x85\xff")
        code.jump_if(Condition.EQUAL, "replay_scene_setup")
        # Initialize each of the two actual page memories once. The complete
        # presented page is a deterministic base; the full-damage request then
        # makes GK3 draw the new 3D scene and matching history over that page.
        code.raw(b"\xa1" + struct.pack("<I", self.profile.address("transition.back_surface_ptr")))
        code.raw(
            b"\x8b\x15" + struct.pack("<I", self.profile.address("transition.primary_surface_ptr"))
        )
        # IDirectDrawSurface4::Blt(back, NULL, primary, NULL, DDBLT_WAIT, NULL)
        code.raw(b"\x6a\x10\x6a\x00\x52\x6a\x00\x6a\x00\x8b\x08\x50\xff\x51\x1c")
        code.raw(b"\xa3" + struct.pack("<I", last_seed_result_va))
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.NOT_EQUAL, "replay_scene_setup")
        code.raw(b"\xff\x05" + struct.pack("<I", seed_count_va))
        code.raw(b"\xff\x0d" + struct.pack("<I", seed_pages_remaining_va))
        code.raw(b"\xa1" + struct.pack("<I", flip_count_va))
        code.raw(b"\xa3" + struct.pack("<I", last_seed_flip_generation_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", repair_active_va) + b"\x01\x00\x00\x00")
        code.raw(b"\xc7\x05" + struct.pack("<I", handoff_pending_va) + b"\x00\x00\x00\x00")
        # Rebuild the matching page's retained damage history exactly once.
        code.raw(
            b"\x8b\x0d" + struct.pack("<I", self.profile.address("transition.engine_loop_ptr"))
        )
        code.raw(b"\x85\xc9")
        code.jump_if(Condition.EQUAL, "replay_scene_setup")
        code.call_absolute(self.profile.address("transition.invalidate_all_damage"))
        code.raw(b"\xff\x05" + struct.pack("<I", scene_invalidation_count_va))
        code.label("replay_scene_setup")
        code.raw(b"\x61\x83\xc4\x04")
        seed_site = self.profile.site("transition.seed_hook")
        code.raw(seed_site.original)
        code.jump_absolute(self.profile.address("transition.seed_continue"))
        return code.build()

    def _build_begin_wrapper(
        self,
        *,
        begin_count_va: int,
        flips_since_begin_va: int,
        frame_phase_va: int,
    ) -> bytes:
        """Record that the next Flip follows a genuine BeginScene."""
        code = X86Emitter(base_va=0)
        code.raw(b"\xc7\x05" + struct.pack("<I", frame_phase_va) + b"\x03\x00\x00\x00")
        code.raw(b"\xff\x05" + struct.pack("<I", begin_count_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", flips_since_begin_va) + b"\x00\x00\x00\x00")
        # Replay the original first instruction of FUN_005996c0; the function
        # itself performs BeginScene and retains its HRESULT handling.
        code.raw(self.profile.site("transition.begin_hook").original)
        code.ret()
        return code.build()

    def _build_blt_wrapper(
        self,
        *,
        wrapper_va: int,
        blt_count_va: int,
        handoff_pending_va: int,
        primary_blt_count_va: int,
        repair_active_va: int,
        seed_pages_remaining_va: int,
        last_seed_flip_generation_va: int,
        retry_caller_va: int,
        retry_current_va: int,
        retry_max_va: int,
        retry_max_caller_va: int,
        primary_blt_trace_va: int,
    ) -> bytes:
        """Arm a native 2D-to-3D handoff at the canonical primary Blt."""
        code = X86Emitter(base_va=wrapper_va)
        # EAX is the destination surface at hook entry. Retry diagnostics use
        # EAX as arithmetic scratch below, so preserve that producer identity
        # in volatile EDX before collecting them. The native tail reloads both
        # registers from the prebuilt COM frame and needs no restoration.
        code.raw(b"\x8b\xd0")
        code.raw(b"\xff\x05" + struct.pack("<I", blt_count_va))
        # [EBP+10h] is initialized to 99,999 before the first COM attempt and
        # decremented only after a busy result. That makes the first attempt a
        # semantic logical-operation boundary without changing HRESULT flow.
        code.raw(b"\x81\x7d\x10\x9f\x86\x01\x00")
        code.jump_if(Condition.NOT_EQUAL, "retry_count")
        code.raw(b"\xa1" + struct.pack("<I", retry_current_va))
        code.raw(b"\x3b\x05" + struct.pack("<I", retry_max_va))
        code.jump_if(Condition.BELOW_OR_EQUAL, "new_logical")
        code.raw(b"\xa3" + struct.pack("<I", retry_max_va))
        code.raw(b"\xa1" + struct.pack("<I", retry_caller_va))
        code.raw(b"\xa3" + struct.pack("<I", retry_max_caller_va))
        code.label("new_logical")
        code.raw(b"\x8b\x45\x04\xa3" + struct.pack("<I", retry_caller_va))
        code.raw(b"\xc7\x05" + struct.pack("<I", retry_current_va) + b"\x00\x00\x00\x00")
        code.label("retry_count")
        code.raw(b"\xff\x05" + struct.pack("<I", retry_current_va))
        # EDX is the preserved destination surface from the original COM site.
        # Observe only a 2D write to the physical primary; the wrapper never
        # substitutes a surface or changes the prebuilt COM argument frame.
        code.raw(
            b"\x3b\x15" + struct.pack("<I", self.profile.address("transition.primary_surface_ptr"))
        )
        code.jump_if(Condition.NOT_EQUAL, "invoke_blt")
        code.raw(b"\xff\x05" + struct.pack("<I", primary_blt_count_va))
        # Snapshot the untouched COM call frame for the exact primary write.
        # At this CALL hook [ESP+4] is `this`, followed by destination RECT,
        # source surface, source RECT, flags, and DDBLTFX.  EDX retains `this`;
        # EAX/ECX are safe scratch because the native tail reloads both.
        code.raw(b"\xff\x05" + struct.pack("<I", primary_blt_trace_va))
        code.raw(b"\x8b\x45\x04\xa3" + struct.pack("<I", primary_blt_trace_va + 4))
        code.raw(b"\x8b\x44\x24\x0c\xa3" + struct.pack("<I", primary_blt_trace_va + 8))
        code.raw(b"\x8b\x44\x24\x14\xa3" + struct.pack("<I", primary_blt_trace_va + 12))
        code.raw(b"\x8b\x4c\x24\x08\x85\xc9")
        code.jump_if(Condition.EQUAL, "primary_dest_full")
        code.raw(b"\xc7\x05" + struct.pack("<I", primary_blt_trace_va + 16) + b"\x01\x00\x00\x00")
        for offset in range(0, 16, 4):
            code.raw(b"\x8b\x41" + bytes((offset,)) + b"\xa3")
            code.raw(struct.pack("<I", primary_blt_trace_va + 20 + offset))
        code.jump_short("primary_dest_done")
        code.label("primary_dest_full")
        code.raw(b"\xc7\x05" + struct.pack("<I", primary_blt_trace_va + 16) + b"\x00\x00\x00\x00")
        code.label("primary_dest_done")
        code.raw(b"\x8b\x4c\x24\x10\x85\xc9")
        code.jump_if(Condition.EQUAL, "primary_source_full")
        code.raw(b"\xc7\x05" + struct.pack("<I", primary_blt_trace_va + 36) + b"\x01\x00\x00\x00")
        for offset in range(0, 16, 4):
            code.raw(b"\x8b\x41" + bytes((offset,)) + b"\xa3")
            code.raw(struct.pack("<I", primary_blt_trace_va + 40 + offset))
        code.jump_short("primary_source_done")
        code.label("primary_source_full")
        code.raw(b"\xc7\x05" + struct.pack("<I", primary_blt_trace_va + 36) + b"\x00\x00\x00\x00")
        code.label("primary_source_done")
        # Only 2D mode may arm the handoff. Once the stable 3D back buffer is
        # active, routine cursor/HUD Blts must not restore an earlier actor pose.
        code.raw(b"\x83\x3d" + struct.pack("<I", repair_active_va) + b"\x00")
        code.jump_if(Condition.NOT_EQUAL, "invoke_blt")
        # A 2D primary Blt records intent only. The first subsequent 3D scene
        # setup consumes it, so any number of UI redraws remain idempotent.
        code.raw(b"\xc7\x05" + struct.pack("<I", handoff_pending_va) + b"\x01\x00\x00\x00")
        code.raw(
            b"\xc7\x05"
            + struct.pack("<I", seed_pages_remaining_va)
            + struct.pack("<I", self._native_flip_page_count)
        )
        code.raw(
            b"\xc7\x05" + struct.pack("<I", last_seed_flip_generation_va) + b"\xff\xff\xff\xff"
        )
        code.label("invoke_blt")
        # Remove the hook CALL's return address so the original prebuilt COM
        # argument frame is at the top of the stack again.
        code.raw(b"\x8b\x44\x24\x04\x8b\x10\x83\xc4\x04\xff\x52\x14")
        code.raw(b"\x3d\xae\x01\x76\x88")
        code.jump_absolute(self.profile.address("transition.blt_continue"))
        return code.build()

    def _read_hook(self, pe: PEFile, site_va: int, original: bytes) -> bytes:
        return pe.read_bytes(pe.va_to_offset(site_va), len(original))

    def _hook_specs(self, section_va: int) -> tuple[tuple[int, bytes, int, str], ...]:
        flip = self.profile.site("transition.flip_hook")
        seed = self.profile.site("transition.seed_hook")
        begin = self.profile.site("transition.begin_hook")
        blt = self.profile.site("transition.blt_hook")
        return (
            (flip.va, flip.original, section_va + self._off_flip_wrapper, "Flip"),
            (
                seed.va,
                seed.original,
                section_va + self._off_scene_wrapper,
                "3D scene page repair",
            ),
            (
                begin.va,
                begin.original,
                section_va + self._off_begin_wrapper,
                "3D BeginScene",
            ),
            (
                blt.va,
                blt.original,
                section_va + self._off_blt_wrapper,
                "primary Blt gate",
            ),
        )

    def _build_wrappers(self, section_va: int) -> tuple[tuple[int, bytes], ...]:
        """Generate the complete immutable transition payload in section order."""
        wrappers = (
            (
                self._off_flip_wrapper,
                self._build_flip_wrapper(
                    wrapper_va=section_va + self._off_flip_wrapper,
                    flip_count_va=section_va + self._off_flip_count,
                    flips_since_begin_va=section_va + self._off_flips_since_begin,
                    repair_active_va=section_va + self._off_repair_active,
                    room_presentation_active_va=(section_va + self._off_room_presentation_active),
                    last_flip_result_va=section_va + self._off_last_flip_result,
                    handoff_pending_va=section_va + self._off_handoff_pending,
                    seed_pages_remaining_va=section_va + self._off_seed_pages_remaining,
                    last_seed_flip_generation_va=(section_va + self._off_last_seed_flip_generation),
                    exit_2d_count_va=section_va + self._off_2d_exit_count,
                    frame_phase_va=section_va + self._off_frame_phase,
                    pre_flip_presenter_slot_va=(section_va + self._off_pre_flip_presenter),
                    last_presented_flip_generation_va=(
                        section_va + self._off_last_presented_flip_generation
                    ),
                    presenter_call_count_va=section_va + self._off_presenter_call_count,
                    presenter_retry_skip_count_va=(
                        section_va + self._off_presenter_retry_skip_count
                    ),
                    post_flip_presenter_slot_va=(section_va + self._off_post_flip_presenter),
                    post_flip_presenter_call_count_va=(
                        section_va + self._off_post_flip_presenter_call_count
                    ),
                ),
            ),
            (
                self._off_scene_wrapper,
                self._build_scene_wrapper(
                    wrapper_va=section_va + self._off_scene_wrapper,
                    repair_active_va=section_va + self._off_repair_active,
                    room_presentation_active_va=(section_va + self._off_room_presentation_active),
                    handoff_pending_va=section_va + self._off_handoff_pending,
                    scene_invalidation_count_va=(section_va + self._off_scene_invalidation_count),
                    seed_pages_remaining_va=section_va + self._off_seed_pages_remaining,
                    flip_count_va=section_va + self._off_flip_count,
                    last_seed_flip_generation_va=(section_va + self._off_last_seed_flip_generation),
                    seed_count_va=section_va + self._off_seed_count,
                    last_seed_result_va=section_va + self._off_last_seed_result,
                ),
            ),
            (
                self._off_begin_wrapper,
                self._build_begin_wrapper(
                    begin_count_va=section_va + self._off_begin_count,
                    flips_since_begin_va=section_va + self._off_flips_since_begin,
                    frame_phase_va=section_va + self._off_frame_phase,
                ),
            ),
            (
                self._off_blt_wrapper,
                self._build_blt_wrapper(
                    wrapper_va=section_va + self._off_blt_wrapper,
                    blt_count_va=section_va + self._off_blt_count,
                    handoff_pending_va=section_va + self._off_handoff_pending,
                    primary_blt_count_va=section_va + self._off_primary_blt_count,
                    repair_active_va=section_va + self._off_repair_active,
                    seed_pages_remaining_va=section_va + self._off_seed_pages_remaining,
                    last_seed_flip_generation_va=(section_va + self._off_last_seed_flip_generation),
                    retry_caller_va=section_va + self._off_blt_retry_caller,
                    retry_current_va=section_va + self._off_blt_retry_current,
                    retry_max_va=section_va + self._off_blt_retry_max,
                    retry_max_caller_va=section_va + self._off_blt_retry_max_caller,
                    primary_blt_trace_va=(section_va + self._off_primary_blt_trace_count),
                ),
            ),
        )
        return tuple(sorted(wrappers, key=lambda item: item[0]))

    def _validate_wrapper_slots(self, wrappers: tuple[tuple[int, bytes], ...]) -> None:
        """Reject generated code that would overlap the next ABI slot."""
        state_offsets = {
            "layout_version": self._off_layout_version,
            "flip_count": self._off_flip_count,
            "flips_since_begin": self._off_flips_since_begin,
            "repair_active": self._off_repair_active,
            "begin_count": self._off_begin_count,
            "last_seed_flip_generation": self._off_last_seed_flip_generation,
            "last_flip_result": self._off_last_flip_result,
            "scene_invalidation_count": self._off_scene_invalidation_count,
            "seed_count": self._off_seed_count,
            "last_seed_result": self._off_last_seed_result,
            "2d_exit_count": self._off_2d_exit_count,
            "blt_count": self._off_blt_count,
            "primary_blt_count": self._off_primary_blt_count,
            "seed_pages_remaining": self._off_seed_pages_remaining,
            "frame_phase": self._off_frame_phase,
            "handoff_pending": self._off_handoff_pending,
            "pre_flip_presenter": self._off_pre_flip_presenter,
            "last_presented_flip_generation": self._off_last_presented_flip_generation,
            "presenter_call_count": self._off_presenter_call_count,
            "presenter_retry_skip_count": self._off_presenter_retry_skip_count,
            "post_flip_presenter": self._off_post_flip_presenter,
            "post_flip_presenter_call_count": self._off_post_flip_presenter_call_count,
            "blt_retry_caller": self._off_blt_retry_caller,
            "blt_retry_current": self._off_blt_retry_current,
            "blt_retry_max": self._off_blt_retry_max,
            "blt_retry_max_caller": self._off_blt_retry_max_caller,
            "room_presentation_active": self._off_room_presentation_active,
            "primary_blt_trace_count": self._off_primary_blt_trace_count,
            "primary_blt_trace_caller": self._off_primary_blt_trace_caller,
            "primary_blt_trace_source": self._off_primary_blt_trace_source,
            "primary_blt_trace_flags": self._off_primary_blt_trace_flags,
            "primary_blt_trace_dest_valid": self._off_primary_blt_trace_dest_valid,
            "primary_blt_trace_dest_left": self._off_primary_blt_trace_dest_rect,
            "primary_blt_trace_dest_top": self._off_primary_blt_trace_dest_rect + 4,
            "primary_blt_trace_dest_right": self._off_primary_blt_trace_dest_rect + 8,
            "primary_blt_trace_dest_bottom": self._off_primary_blt_trace_dest_rect + 12,
            "primary_blt_trace_source_valid": self._off_primary_blt_trace_source_valid,
            "primary_blt_trace_source_left": self._off_primary_blt_trace_source_rect,
            "primary_blt_trace_source_top": self._off_primary_blt_trace_source_rect + 4,
            "primary_blt_trace_source_right": self._off_primary_blt_trace_source_rect + 8,
            "primary_blt_trace_source_bottom": self._off_primary_blt_trace_source_rect + 12,
        }
        if len(set(state_offsets.values())) != len(state_offsets):
            duplicates = sorted(
                offset
                for offset in set(state_offsets.values())
                if tuple(state_offsets.values()).count(offset) > 1
            )
            msg = f"{self.id} has overlapping ABI state at {duplicates!r}"
            raise PatchError(msg)
        for name, offset in state_offsets.items():
            if offset % 4 or not (self._off_layout_version <= offset <= self._section_size - 4):
                msg = f"{self.id} ABI field {name} has invalid offset 0x{offset:x}"
                raise PatchError(msg)
            if any(
                wrapper_offset < offset + 4 and offset < wrapper_offset + len(wrapper)
                for wrapper_offset, wrapper in wrappers
            ):
                msg = f"{self.id} ABI field {name} overlaps generated code at 0x{offset:x}"
                raise PatchError(msg)
        for index, (offset, wrapper) in enumerate(wrappers):
            limit = wrappers[index + 1][0] if index + 1 < len(wrappers) else self._section_size
            if not (0 <= offset < limit <= self._section_size):
                msg = f"{self.id} wrapper at 0x{offset:x} has an invalid section slot"
                raise PatchError(msg)
            if offset + len(wrapper) > limit:
                msg = f"{self.id} wrapper at 0x{offset:x} does not fit"
                raise PatchError(msg)

    def _build_payload(self, *, section_va: int) -> bytes:
        """Build the complete transition section after validating its ABI slots."""
        wrappers = self._build_wrappers(section_va)
        self._validate_wrapper_slots(wrappers)
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=self._section_name,
            size=self._section_size,
        )
        payload.place(label="magic", offset=0, payload=self._magic)
        payload.place(
            label="layout version",
            offset=self._off_layout_version,
            payload=struct.pack("<I", self._layout_version),
        )
        # Generation zero is a pending first Flip. The sentinel lets a linked
        # presenter own it before the first successful DD_OK increment.
        payload.place(
            label="initial presenter generation",
            offset=self._off_last_presented_flip_generation,
            payload=struct.pack("<I", 0xFFFFFFFF),
        )
        for index, (offset, wrapper) in enumerate(wrappers):
            limit = wrappers[index + 1][0] if index + 1 < len(wrappers) else self._section_size
            payload.place(
                label=f"transition wrapper 0x{offset:x}",
                offset=offset,
                payload=wrapper,
                limit=limit,
            )
        return payload.build()

    def _mutation_plan(self, *, section_va: int) -> ExecutableMutationPlan:
        """Declare all four displaced native-call redirects as one transaction."""
        plan = ExecutableMutationPlan(owner=self.id)
        for site, original, wrapper, label in self._hook_specs(section_va):
            plan.branch(
                label=label,
                opcode=BranchOpcode.CALL,
                site_va=site,
                expected=original,
                target_va=wrapper,
                size=len(original),
            )
        return plan

    def precheck(self, pe: PEFile) -> None:
        """Validate pristine DirectDraw and Direct3D hook sites."""
        self._check_anchors(pe)
        if pe.get_section(self._section_name) is not None:
            msg = f"{self.id} requires a pristine executable"
            raise PatchError(msg)
        for site, original, _wrapper, label in self._hook_specs(0):
            if self._read_hook(pe, site, original) != original:
                msg = f"{self.id} precheck failed: unexpected {label} bytes"
                raise PatchError(msg)

    def apply(self, pe: PEFile) -> None:
        """Install transition state and page-synchronization wrappers."""
        if pe.get_section(self._section_name) is not None:
            msg = f"{self.id} section already exists"
            raise PatchError(msg)
        section = pe.add_section(
            self._section_name, b"\x00" * self._section_size, self._section_characteristics
        )
        if section.size_of_raw_data < self._section_size:
            msg = f"{self.id} section is too small"
            raise PatchError(msg)
        pe.set_section_characteristics(self._section_name, self._section_characteristics)
        section_va = pe.rva_to_va(section.virtual_address)
        # Publish every wrapper before redirecting any native call into it.
        pe.write_bytes(section.pointer_to_raw_data, self._build_payload(section_va=section_va))
        self._mutation_plan(section_va=section_va).apply(pe)

    def postcheck(self, pe: PEFile) -> None:
        """Verify the transition ABI and every redirected hook."""
        self._check_anchors(pe)
        section = pe.get_section(self._section_name)
        if section is None or section.size_of_raw_data < self._section_size:
            msg = f"{self.id} postcheck failed: section missing or too small"
            raise PatchError(msg)
        if section.characteristics != self._section_characteristics:
            msg = f"{self.id} postcheck failed: section is not executable"
            raise PatchError(msg)
        section_offset = section.pointer_to_raw_data
        section_va = pe.rva_to_va(section.virtual_address)
        if pe.read_bytes(section_offset, len(self._magic)) != self._magic:
            msg = f"{self.id} postcheck failed: bad section magic"
            raise PatchError(msg)
        version = struct.pack("<I", self._layout_version)
        if pe.read_bytes(section_offset + self._off_layout_version, len(version)) != version:
            msg = f"{self.id} postcheck failed: layout mismatch"
            raise PatchError(msg)
        sentinel = struct.pack("<I", 0xFFFFFFFF)
        if (
            pe.read_bytes(
                section_offset + self._off_last_presented_flip_generation,
                len(sentinel),
            )
            != sentinel
        ):
            msg = f"{self.id} postcheck failed: initial presenter generation mismatch"
            raise PatchError(msg)
        # The fixed-interface runtime publishes callbacks into +0x48/+0x58.
        # Verify this owner's immutable wrappers without claiming those linked
        # ABI slots or mutable telemetry as transition payload.
        wrappers = self._build_wrappers(section_va)
        self._validate_wrapper_slots(wrappers)
        for offset, wrapper in wrappers:
            if pe.read_bytes(section_offset + offset, len(wrapper)) != wrapper:
                msg = f"{self.id} postcheck failed: wrapper at 0x{offset:x} mismatch"
                raise PatchError(msg)
        self._mutation_plan(section_va=section_va).verify(pe)
