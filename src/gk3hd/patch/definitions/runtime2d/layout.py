"""Owned memory layout for GK3's generated fixed-interface runtime."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.image import Section
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from gk3hd.patch.binary.image import PEFile

RUNTIME_SEGMENT_MAGIC_SIZE = 8


@dataclass(frozen=True, slots=True)
class RuntimeSegment:
    """One local builder ABI within the shared runtime section."""

    logical_name: str
    offset: int
    size: int
    magic: bytes
    characteristics: int

    @property
    def end(self) -> int:
        """Return the exclusive end offset within the shared section."""
        return self.offset + self.size


SIDNEY_CONSTRUCTION_SEGMENT = RuntimeSegment(
    "sidney_construction", 0x1000, 0x1000, b"SIDCONST", 0xE0000020
)
SIDNEY_PRESENTATION_SEGMENT = RuntimeSegment(
    "sidney_presentation", 0x2000, 0x3000, b"SIDPRES\0", 0xE0000020
)
# The shared pointer dispatcher and SystemScreen's delayed-tooltip resolver
# both need the toolbar's one canonical target-to-source inverse.  Keep the
# helper address and its re-entrant call depth in the runtime layout owner so
# neither compiler duplicates a private hexadecimal ABI.  The depth occupies
# data-only header storage; the helper lives in SidneyPresentation's dedicated
# input page.
SIDNEY_TOOLBAR_INPUT_DEPTH_OFFSET = 0x10
SIDNEY_DRIVING_MAP_INPUT_DEPTH_OFFSET = 0x14
SIDNEY_TOOLBAR_INPUT_HELPER_OFFSET = 0x22C0
SIDNEY_INPUT_DISPATCHER_OFFSET = 0x2400
# Captured child drags bypass the root traversal but still need its POINT ABI.
SIDNEY_BUTTON_DISPATCH_ADAPTER_OFFSET = 0x2E00
SIDNEY_PORTRAIT_SOURCE_OFFSET = 0x1E00
SIDNEY_PORTRAIT_STATE_OFFSET = 0x1F80
# SIDNEY construction owns the frame and its protruding postcard strip.
SIDNEY_FRAME_RESIZE_OFFSET = 0x100
SIDNEY_FRAME_THUNKS_OFFSET = 0x200
SIDNEY_FRAME_DIMENSIONS_OFFSET = 0x280
SIDNEY_FRAME_SOURCE_OFFSET = 0x380
SIDNEY_FRAME_STATE_OFFSET = 0x480
SIDNEY_FRAME_SCRATCH_OFFSET = 0x4C0
SIDNEY_FINGERPRINT_STATE_OFFSET = 0x4D0
SIDNEY_FRAME_DISCOVERY_OFFSET = 0x500
SIDNEY_FINGERPRINT_DIMENSIONS_OFFSET = 0x900
SIDNEY_IMAGE_DIMENSIONS_OFFSET = 0xB00
# The generic SystemScreen target-to-source inverse is the non-D-pad fallback
# for Binocs. Publishing this cross-compiler entry avoids a duplicated literal
# ABI between the System and SIDNEY builders.
SIDNEY_SYSTEM_INPUT_HELPER_OFFSET = 0x21D0
# Several presentation owners occasionally need to submit an internal Blt
# without re-entering the public final-blitter hook at 0x0054F980.  SIDNEY's
# presentation page owns the one canonical trampoline containing the displaced
# native prologue; publish its ABI here so other compilers cannot silently
# duplicate its address or call the hooked entry recursively.
SIDNEY_NATIVE_BLT_TRAMPOLINE_OFFSET = 0x1B00
SIDNEY_ALPHA_CONSTRUCTOR_OFFSET = 0x1C00
INVENTORY_ALPHA_CONSTRUCTOR_OFFSET = 0x980
INVENTORY_FONT_ALPHA_VTABLE_OFFSET = 0xE28
INVENTORY_ALPHA_OUTPUT_RECT_OFFSET = 0xE30
INVENTORY_ALPHA_SOURCE_RECT_OFFSET = 0xE40
INVENTORY_ALPHA_WIDTH_OFFSET = 0xE50
INVENTORY_ALPHA_HEIGHT_OFFSET = 0xE54
INVENTORY_SEGMENT = RuntimeSegment("inventory", 0x5000, 0x1000, b"INVENTRY", 0xE0000020)
# Inventory and the shared pointer dispatcher both consume the exact active
# root publication. Keep that cross-segment ABI beside the segment definition.
INVENTORY_ACTIVE_ROOT_OFFSET = 0x18
RESOURCE_SEGMENT = RuntimeSegment("resources", 0x6000, 0x2000, b"RESOURCE", 0xE0000020)
# Public visual-diagnostics ABI: set after the driving map has rendered at
# least once in the current process.
RESOURCE_DRIVING_MAP_SEEN_OFFSET = 0xE28
RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET = 0xE2C
FINGERPRINT_SEGMENT = RuntimeSegment("fingerprint", 0x8000, 0x1000, b"FINGRPRT", 0xE0000020)
FINGERPRINT_LAYOUT_ACTIVE_OFFSET = 0xE54
FINGERPRINT_HD_SET_ACTIVE_OFFSET = 0x10
FINGERPRINT_TOOL_MATCH_OFFSET = 0xCA0
FINGERPRINT_DAMAGE_SELECTOR_OFFSET = 0xF40
SYSTEM_SEGMENT = RuntimeSegment("system", 0x9000, 0x1000, b"SYSTEM\0\0", 0xE0000020)
# Nested full-screen draws suspend this shared affine, then restore their parent.
SYSTEM_RENDER_DEPTH_OFFSET = 0x0C
SYSTEM_ROOT_POINTER_OFFSET = 0x1C
SYSTEM_INPUT_ACTIVE_OFFSET = 0x10
SYSTEM_TRANSFORM_MODE_OFFSET = 0xE0
# The shared software-alpha constructor is intercepted by Inventory because it
# already owns GK3's sole constructor call site.
SYSTEM_DEST_RECT_OFFSET = 0x40
# ActionMenu layout is consumed by both the system renderer and the shared
# pointer dispatcher.  Keep its cross-compiler ABI in this layout owner: the
# cached root at +0x20 proves that the physically enlarged verb buttons are
# currently presented and selects their icon-mask input adapter.  Duplicating
# the former control-segment address let ordinary room input read cursor scratch
# after this state moved, bypassing the stage inverse at larger output modes.
SYSTEM_ACTION_LAYOUT_STATE_OFFSET = 0xD00
SYSTEM_ACTION_PRESENTED_ROOT_OFFSET = SYSTEM_ACTION_LAYOUT_STATE_OFFSET + 0x20
SYSTEM_ACTION_LAYOUT_STATE_END_OFFSET = SYSTEM_ACTION_LAYOUT_STATE_OFFSET + 0x24
# System-screen policy includes the cursor's durable final-copy ownership and
# tooltip producer helpers. Keep one final executable page for those independent
# transactions rather than compressing them into unrelated feature slots.
SYSTEM_CONTROL_SEGMENT = RuntimeSegment("system_controls", 0xA000, 0x6000, b"SYSCTRL\0", 0xE0000020)
# Public diagnostic ABI within ``SYSTEM_CONTROL_SEGMENT``.  Runtime builders
# and the out-of-process capture tool must agree on these values, so keep them
# beside the segment declaration instead of duplicating numeric literals.
# The cursor state occupies data-only slack after ActionMenu state and before
# the first tail wrapper.
SYSTEM_CONTROL_CURSOR_STATE_OFFSET = 0x1440
# Shared one-RECT damage collection.  Several fixed-interface producers need
# to request one complete native traversal when a newly selected DirectDraw
# page has no matching retained history.  Export the offset from the layout
# owner instead of coupling those producers to SystemScreenCompiler internals.
SYSTEM_CONTROL_FULL_DAMAGE_REGION_OFFSET = 0x20
SYSTEM_CONTROL_FULL_DAMAGE_RECT_OFFSET = 0x30
# A font glyph is the only transfer whose logical metrics can intentionally
# address a 4x source atlas. The high-level font owner publishes a narrow
# synchronous scope and one private source RECT here; both the opaque final
# blitter and software-alpha path consume the same exact surface identities.
SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET = 0x40
SYSTEM_CONTROL_HD_FONT_SOURCE_RECT_OFFSET = 0x44
SYSTEM_CONTROL_HD_FONT_NORMALIZE_COUNT_OFFSET = 0x58
SYSTEM_CONTROL_HD_FONT_SOURCE_TRANSFORM_COUNT_OFFSET = 0x5C
SYSTEM_CONTROL_HD_FONT_HANDLE_COUNT_OFFSET = 0x60
SYSTEM_CONTROL_HD_FONT_HANDLES_OFFSET = 0x64
SYSTEM_CONTROL_HD_FONT_HANDLE_CAPACITY = 64
SYSTEM_CONTROL_HD_FONT_LAST_OBJECT_OFFSET = (
    SYSTEM_CONTROL_HD_FONT_HANDLES_OFFSET + SYSTEM_CONTROL_HD_FONT_HANDLE_CAPACITY * 2
)
SYSTEM_CONTROL_HD_FONT_LAST_CANDIDATE_OFFSET = SYSTEM_CONTROL_HD_FONT_LAST_OBJECT_OFFSET + 4
SYSTEM_CONTROL_HD_FONT_LAST_PREFIX_OFFSET = SYSTEM_CONTROL_HD_FONT_LAST_CANDIDATE_OFFSET + 4
SYSTEM_CONTROL_HD_FONT_STATE_END_OFFSET = SYSTEM_CONTROL_HD_FONT_LAST_PREFIX_OFFSET + 4
# The state retains the exact cursor point/source geometry (+0/+8), the latest
# completed physical destination (+24), per-call destination/source scratch
# (+40/+56), and its resolved source identity (+72) for diagnostics. The source
# paired with +24 is published separately at the named 0x3FEC record below;
# private composition calls legitimately replace +56 after the display copy.
# +76 scopes the concrete live drawable across
# its native bitmap submission. +80 retains the exact private cursor-composition
# wrapper learned inside that scope so delayed save-under sources bypass other
# UI affines; +84 counts transformed-screen manager points canonicalized to the
# live cursor position. +88 retains the save-under wrapper learned from one
# exact live-geometry match so an already-queued restore can be recognized
# after the manager advances its point. +92 and +108 retain the current and
# previous physical save-under bounds produced by CursorManager, and +124
# counts genuine bounds changes. +84 counts obsolete retained-SIDNEY points
# canonicalized to the current manager position. +128 retains the destination
# handle from the active native manager call; +132 publishes that handle only
# after its resolved +136 wrapper proves the current physical back page. +140
# counts authoritative staged-room cursor presentations at the pre-Flip owner,
# and +144 counts event-driven staged draws routed to that frame owner. +148
# retains the cursor platform's requested-capacity surface; the allocator
# publishes that wrapper and the doubled-capacity wrapper at +88 immediately
# after it creates them, before either can enter a transformed UI traversal.
# +152 publishes the exact drawable during its scoped bitmap call, allowing
# dense cursor sampling to resolve its current resource without cached pointers.
# +156 counts exact dropdown-highlight transforms at
# the solid-color object's own draw boundary. The reservation ends before +160:
# that address is the independent toolbar-frame repaint flag.
# These rectangles remain diagnostic evidence for producer-owned cursor damage;
# SIDNEY's deterministic full logical repaint no longer consumes them. The
# reservation ends exactly where the independent room-status state begins.
SYSTEM_CONTROL_CURSOR_STATE_SIZE = 0xA0
# RoomLayer's status TextBox publishes its live object and destination here,
# then deliberately defers the one actual Draw transaction to the staged-room
# pre-Flip owner. The final DWORD is a one-shot validity token for the bounded,
# patch-owned DamageCollection near the data-only tail below. Never retain the
# producer's native collection pointer: restore can traverse this TextBox
# before BeginScene, and that caller-owned vector can die before pre-Flip.
SYSTEM_CONTROL_ROOM_STATUS_OBJECT_PTR_OFFSET = 0x14E4
SYSTEM_CONTROL_ROOM_STATUS_DEST_HANDLE_OFFSET = 0x14E8
SYSTEM_CONTROL_ROOM_STATUS_DEFER_COUNT_OFFSET = 0x14EC
SYSTEM_CONTROL_ROOM_STATUS_PRESENT_COUNT_OFFSET = 0x14F0
SYSTEM_CONTROL_ROOM_STATUS_PRESENT_DEPTH_OFFSET = 0x14F4
SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_VALID_OFFSET = 0x14F8
SYSTEM_CONTROL_ROOM_STATUS_STATE_SIZE = 0x18
# Diagnostic evidence from the exact cursor-surface classifier: match count,
# last source/destination wrappers, result, and destination rectangle.
SYSTEM_CONTROL_CURSOR_CLASSIFIER_TRACE_OFFSET = 0x3F14
SYSTEM_CONTROL_CURSOR_CLASSIFIER_TRACE_SIZE = 0x20
# Shared cursor-ownership predicate, used before any interface affine.
SYSTEM_CONTROL_CURSOR_CLASSIFIER_OFFSET = 0x3E10
# The room caption's logical TextBox bounds are mapped here before joining its
# producer-owned physical damage accumulator. This scratch is synchronous;
# the shared recorder copies it immediately.
SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_RECT_OFFSET = 0x3F64
# ToolTip is a global overlay rather than a child owned by the staged room.
# Its event-time Draw publishes the live object, while the pre-Flip owner
# paints it once on the proven current back page. Retain the exact native root
# rectangle as diagnostic evidence; the final blitter applies a tooltip-local
# height affine about its already-physical top-left anchor.
SYSTEM_CONTROL_TOOLTIP_DRAW_DEPTH_OFFSET = 0x3F74
SYSTEM_CONTROL_TOOLTIP_DRAW_COUNT_OFFSET = 0x3F78
SYSTEM_CONTROL_TOOLTIP_PRESENTED_RECT_OFFSET = 0x3F7C
SYSTEM_CONTROL_TOOLTIP_FRAME_PRESENT_COUNT_OFFSET = 0x3F8C
SYSTEM_CONTROL_TOOLTIP_DAMAGE_PTR_OFFSET = 0x3F90
SYSTEM_CONTROL_TOOLTIP_DEST_HANDLE_OFFSET = 0x3F94
SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET = 0x3F98
# The cursor scaler records only framebuffer-owned transfers here. The
# distinction from private composition/save-under Blts is made from the live
# destination extent at the exact final transfer boundary.
SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_COUNT_OFFSET = 0x3F9C
SYSTEM_CONTROL_CURSOR_DISPLAY_BLT_RESULT_OFFSET = 0x3FA0
# The display-options resolution dropdown has a short page-seeding budget of
# its own. Keep the name scoped to that producer; it is unrelated to the
# in-room toolbar compositor occupying the adjacent state below.
SYSTEM_CONTROL_DROPDOWN_SEED_BUDGET_OFFSET = 0x3FA4
# Toolbar and ActionMenu direct rendering seed the entry frame plus both
# alternating DirectDraw pages. This counter is independent from the display
# options dropdown's page budget above.
SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET = 0x3FC0
# Tooltip's patch-owned panel must not borrow the common system destination
# and clip scratch: native text begins immediately afterward and consumes that
# live geometry. These two private RECTs keep the producer transaction local.
SYSTEM_CONTROL_TOOLTIP_OUTER_RECT_OFFSET = 0x3FC4
SYSTEM_CONTROL_TOOLTIP_INNER_RECT_OFFSET = 0x3FD4
# The frame presenter latches whether a physical tooltip generation has ever
# reached the flip chain. When native visibility ends, that transition queues
# the last outer rectangle exactly once into the staged renderer's ordinary
# two-page damage history. This is producer state, not a timing heuristic.
SYSTEM_CONTROL_TOOLTIP_VISIBLE_LATCH_OFFSET = 0x3FE4
SYSTEM_CONTROL_OVERLAY_PAGE_STATE_END_OFFSET = 0x3FE8
# One Boolean distinguishes a newly published tooltip generation from its
# completed composition cache. It is never a frame/time budget.
SYSTEM_CONTROL_TOOLTIP_COMPOSITION_PENDING_OFFSET = 0x3FE8
SYSTEM_CONTROL_TOOLTIP_STATE_END_OFFSET = 0x3FEC
# The final cursor wrapper publishes the complete source rectangle only when
# the same transaction publishes its framebuffer destination at cursor-state
# +24. Keeping this pair outside per-call source scratch prevents a private
# save-under composition immediately after Flip from making diagnostics compare
# the current arrow source with the preceding loading-orb destination.
SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_RECT_OFFSET = SYSTEM_CONTROL_TOOLTIP_STATE_END_OFFSET
SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_STATE_END_OFFSET = (
    SYSTEM_CONTROL_CURSOR_PRESENTED_SOURCE_RECT_OFFSET + 0x10
)
# Retained tooltip generations are identified by native producer data, not a
# timer or frame count.  The text pointer/length pair distinguishes movement
# between toolbar children whose bounds are otherwise identical.  A separate
# toolbar rectangle remains authoritative while the tooltip temporarily
# extends the stage's protected modal region below it.
SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET = 0x4800
SYSTEM_CONTROL_TOOLTIP_TEXT_LENGTH_OFFSET = 0x4804
# Native ToolTip visibility and text fields describe a producer pulse, not the
# complete display lifetime of the cached panel.  Retain the exact MouseManager
# owner and both hover identities which produced a generation.  A cached panel
# remains live only while that complete identity tuple is unchanged; moving to
# another control or destroying its controller therefore retires it without a
# timer, output-resolution branch, or stale-object dereference.
SYSTEM_CONTROL_TOOLTIP_MOUSE_OWNER_OFFSET = 0x4808
SYSTEM_CONTROL_TOOLTIP_HOVER_TARGET_OFFSET = 0x480C
SYSTEM_CONTROL_TOOLTIP_CAPTURED_HOVER_OWNER_OFFSET = 0x4810
SYSTEM_CONTROL_TOOLTIP_HOVER_IDENTITY_VALID_OFFSET = 0x4814
# A new/changed tooltip panel is painted onto the current back page and the
# one alternating peer identified by this successful-Flip deadline. Stable
# generations then remain resident inside the modal's protected rectangle;
# cursor motion can request an independent cache replay through its own visual
# generation deadline.
# Native ToolTip::Draw walks a DamageCollection and clips every glyph against
# each member RECT.  The event-time collection is caller-owned and can contain
# only the cursor-sized dirt which happened to trigger that traversal.  Keep a
# one-RECT collection whose member is the complete patch-owned output panel;
# the pre-Flip owner uses it only for one native composition transaction.
SYSTEM_CONTROL_TOOLTIP_RENDER_DAMAGE_REGION_OFFSET = 0x481C
# A persistent tooltip replays every pre-Flip frame. DirectDraw color-fill
# transactions synchronize even without DDBLT_WAIT on current Windows and
# halve 120 Hz presentation to 60 FPS. Cache the two-color panel in one tiny
# off-screen surface, compose native text into it once, then submit one
# ``BltFast`` of the completed panel.
SYSTEM_CONTROL_TOOLTIP_PANEL_SURFACE_OFFSET = 0x482C
SYSTEM_CONTROL_TOOLTIP_PANEL_OWNER_OFFSET = 0x4830
SYSTEM_CONTROL_TOOLTIP_PANEL_DIMENSIONS_OFFSET = 0x4834
SYSTEM_CONTROL_TOOLTIP_PANEL_SOURCE_RECT_OFFSET = 0x483C
SYSTEM_CONTROL_TOOLTIP_PANEL_LOCAL_INNER_RECT_OFFSET = 0x484C
SYSTEM_CONTROL_TOOLTIP_PANEL_DESCRIPTOR_OFFSET = 0x485C
SYSTEM_CONTROL_TOOLTIP_PANEL_WHITE_BLTFX_OFFSET = 0x48C8
SYSTEM_CONTROL_TOOLTIP_PANEL_CREATE_RESULT_OFFSET = 0x492C
SYSTEM_CONTROL_TOOLTIP_PANEL_FILL_RESULT_OFFSET = 0x4930
SYSTEM_CONTROL_TOOLTIP_PANEL_BLT_RESULT_OFFSET = 0x4934
SYSTEM_CONTROL_TOOLTIP_PANEL_CAPTURE_MODE_OFFSET = 0x4938
SYSTEM_CONTROL_TOOLTIP_PANEL_CAPTURE_RESULT_OFFSET = 0x493C
SYSTEM_CONTROL_RETAINED_OVERLAY_STATE_END_OFFSET = 0x4940
# The room caption's authored bounds are producer identity, not transform
# scratch. Retain them independently from the scaled cleanup rectangle so the
# staged renderer can reject only the exact deferred-overlay invalidation.
SYSTEM_CONTROL_ROOM_STATUS_AUTHORED_RECT_OFFSET = 0x4940
SYSTEM_CONTROL_ROOM_STATUS_AUTHORED_STATE_END_OFFSET = 0x4950
# CursorManager updates its contextual drawable before the room selects and
# consumes a retained page history. Track that exact drawable/frame signature
# here so a larger outgoing cursor footprint is invalidated before the next
# room traversal rather than surviving beneath a smaller cursor.
SYSTEM_CONTROL_CURSOR_RESOURCE_DRAWABLE_OFFSET = 0x4950
SYSTEM_CONTROL_CURSOR_RESOURCE_FRAME_OFFSET = 0x4954
SYSTEM_CONTROL_CURSOR_RESOURCE_VALID_OFFSET = 0x4958
SYSTEM_CONTROL_CURSOR_RESOURCE_INVALIDATION_COUNT_OFFSET = 0x495C
SYSTEM_CONTROL_CURSOR_RESOURCE_ROOM_ROOT_OFFSET = 0x4960
SYSTEM_CONTROL_CURSOR_RESOURCE_STATE_END_OFFSET = 0x4964
SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_COLLECTION_OFFSET = 0x4968
SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_RECT_OFFSET = 0x4978
SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_REFCOUNT_OFFSET = 0x4988
# Cursor lease: 0 unowned, 1 worker suspended, 2 dismissal cleanup pending,
# 3 first Draw pending, 4 worker resumed while the visible modal still owns cleanup.
SYSTEM_CONTROL_CONFIRM_QUIT_CURSOR_SUSPENDED_OFFSET = 0x498C
SYSTEM_CONTROL_CONFIRM_QUIT_ROOM_REPAIR_STATE_END_OFFSET = 0x4990
# Caption presentation and cleanup have different lifetimes. The producer
# snapshots its transient native damage vector into this one-RECT patch-owned
# vector; the pre-Flip owner consumes that snapshot exactly once. A separate
# flag/RECT then survives for two physical-page cleanup generations. Keeping
# both channels in this data-only tail prevents executable bytes or a newer UI
# traversal from aliasing either lifetime.
SYSTEM_CONTROL_ROOM_STATUS_DAMAGE_REGION_OFFSET = 0x50D4
SYSTEM_CONTROL_ROOM_STATUS_PENDING_VALID_OFFSET = 0x50E4
SYSTEM_CONTROL_ROOM_STATUS_PENDING_RECT_OFFSET = 0x50E8
# A native caption generation is initially painted on the current DirectDraw
# page only.  The presenter consumes this bounded budget on the two following
# pages, then returns to a zero-work steady state.  The adjacent count is
# diagnostic evidence that captures can distinguish native fade events from
# patch-owned peer initialization; runtime policy never reads the count.
SYSTEM_CONTROL_ROOM_STATUS_SEED_BUDGET_OFFSET = 0x50F8
SYSTEM_CONTROL_ROOM_STATUS_SEED_REPLAY_COUNT_OFFSET = 0x50FC
SYSTEM_CONTROL_ROOM_STATUS_PENDING_STATE_END_OFFSET = 0x5100
# The ActionMenu is a transient room child and therefore is not registered in
# MouseManager's two stock tooltip-root slots.  The resolver wrapper publishes
# a compact, read-only diagnostic transaction here so visual probes can prove
# which live root and physical point were queried.  This is deliberately a
# monotonic/copy-only trace: it never participates in tooltip policy.
SYSTEM_CONTROL_ACTION_TOOLTIP_CALL_COUNT_OFFSET = 0x5B00
SYSTEM_CONTROL_ACTION_TOOLTIP_FALLBACK_COUNT_OFFSET = 0x5B04
SYSTEM_CONTROL_ACTION_TOOLTIP_QUERY_COUNT_OFFSET = 0x5B08
SYSTEM_CONTROL_ACTION_TOOLTIP_HIT_COUNT_OFFSET = 0x5B0C
SYSTEM_CONTROL_ACTION_TOOLTIP_LAST_ROOT_OFFSET = 0x5B10
SYSTEM_CONTROL_ACTION_TOOLTIP_LAST_POINT_POINTER_OFFSET = 0x5B14
SYSTEM_CONTROL_ACTION_TOOLTIP_LAST_POINT_OFFSET = 0x5B18
SYSTEM_CONTROL_ACTION_TOOLTIP_LAST_QUERY_POINT_OFFSET = 0x5B20
SYSTEM_CONTROL_ACTION_TOOLTIP_LAST_DESCRIPTOR_OFFSET = 0x5B28
SYSTEM_CONTROL_ACTION_TOOLTIP_STATE_END_OFFSET = 0x5B2C
# ActionMenu's native destructor can run after a replacement layer has already
# become current. Presentation/input policy cannot use that delayed memory
# lifetime as proof that the transient menu is still on screen. The pre-Flip
# owner records each exact current-layer membership retirement here; these
# words are diagnostic only and never select rendering behavior.
SYSTEM_CONTROL_ACTION_LIFETIME_RETIRE_COUNT_OFFSET = 0x5B2C
SYSTEM_CONTROL_ACTION_LIFETIME_LAST_ROOT_OFFSET = 0x5B30
SYSTEM_CONTROL_ACTION_LIFETIME_LAST_LAYER_OFFSET = 0x5B34
SYSTEM_CONTROL_ACTION_TOOLTIP_VISIBILITY_PRESENT_COUNT_OFFSET = 0x5B38
# Counts every invocation of the final tooltip presenter, including cheap
# hidden/inactive exits. Comparing this with the visibility-edge count proves
# whether a requested native frame reached the final page owner.
SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_CALL_COUNT_OFFSET = 0x5B3C
# One exact hidden-to-visible ActionMenu tooltip edge requests a native page
# pair here. The fixed system-layer epilogue consumes the token after both the
# stock render pair and the delayed UI update have returned; the adjacent count
# records those semantic transactions for runtime verification.
SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_PENDING_OFFSET = 0x5B40
SYSTEM_CONTROL_ACTION_TOOLTIP_FRAME_REQUEST_CONSUME_COUNT_OFFSET = 0x5B44
SYSTEM_CONTROL_ACTION_LIFETIME_STATE_END_OFFSET = 0x5B48
# CloseUp replaces a staged room with a native full-screen 2D tree. Retain the
# exact destination and a two-page seed transaction in the data-only gap before
# the ActionMenu lifetime helper; the pre-Flip owner uses these words to repair
# both DirectDraw peers once, then returns to steady native presentation.
SYSTEM_CONTROL_CLOSEUP_DEST_HANDLE_OFFSET = 0x5B48
SYSTEM_CONTROL_CLOSEUP_LAST_OWNER_OFFSET = 0x5B4C
SYSTEM_CONTROL_CLOSEUP_SEED_BUDGET_OFFSET = 0x5B50
SYSTEM_CONTROL_CLOSEUP_PRESENT_COUNT_OFFSET = 0x5B54
SYSTEM_CONTROL_CLOSEUP_STATE_END_OFFSET = 0x5B58
# A modal toolbar/action root publishes its live local union while fixed
# canvases retain the complete-frame collection at +0x20. Those meanings are
# mutually exclusive: reusing one RECT allowed ActionMenu's nonzero origin to
# leak into the following CloseUp traversal. Give modal roots their own
# collection in the remaining data-only gap so complete damage is always
# intrinsically rooted at (0, 0), without repair instructions in every caller.
SYSTEM_CONTROL_MODAL_DAMAGE_REGION_OFFSET = 0x5B58
SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET = 0x5B68
SYSTEM_CONTROL_MODAL_DAMAGE_STATE_END_OFFSET = 0x5B78
# Counts delayed native tooltip lookups that arrived outside the button-event
# inverse and were routed through the toolbar's canonical coordinate adapter.
# This is diagnostic evidence only; runtime policy reads the input-depth and
# immutable toolbar affine, never this counter.
SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_COUNT_OFFSET = 0x5B78
SYSTEM_CONTROL_ACTION_TOOLTIP_TOOLBAR_INVERSE_STATE_END_OFFSET = 0x5B7C
# Executable ABI called by both the final-page owner and the shared input
# dispatcher after a native action callback. Publishing this offset here keeps
# the two runtime compilers linked by one named contract rather than a copied
# control-section literal.
SYSTEM_CONTROL_ACTION_LIFETIME_HELPER_OFFSET = 0x5B80
# Rendering rebuilds its source/target scratch for every toolbar child Blt.
# Pointer dispatch must not observe that hot, partially written state. The first
# completed toolbar transfer publishes one immutable affine for the complete
# popup lifetime; its class destructor clears only the validity token. Expanded
# rows share the same exact display-height scale and base anchor. Rounded
# rectangle endpoint ratios must not be extrapolated into expanded rows.
SYSTEM_CONTROL_TOOLBAR_INPUT_VALID_OFFSET = 0x4100
SYSTEM_CONTROL_TOOLBAR_INPUT_SOURCE_RECT_OFFSET = 0x4104
SYSTEM_CONTROL_TOOLBAR_INPUT_TARGET_RECT_OFFSET = 0x4114
SYSTEM_CONTROL_TOOLBAR_INPUT_STATE_END_OFFSET = 0x4124
# ConfirmQuit's dimmed backdrop is composed once outside its retained child
# tree. After the first complete page is presented, the post-Flip owner copies
# that authoritative front into the returned back page exactly once. It never
# writes to the scanned-out page and does no steady-state work.
SYSTEM_CONTROL_CONFIRM_QUIT_COPY_PENDING_OFFSET = 0x4124
SYSTEM_CONTROL_CONFIRM_QUIT_COPY_RESULT_OFFSET = 0x4128
SYSTEM_CONTROL_CONFIRM_QUIT_COPY_COUNT_OFFSET = 0x412C
SYSTEM_CONTROL_CONFIRM_QUIT_SEEDED_ROOT_OFFSET = 0x4130
SYSTEM_CONTROL_CONFIRM_QUIT_STATE_END_OFFSET = 0x4134
# Title's dense-source cache rectangles and its bounded result record belong
# with the other control-header data, not between executable tail helpers.
# Together with the dropdown record they fill the data-only slack after the
# toolbar ring and end exactly at the pending-popup pointer at 0x170.
SYSTEM_CONTROL_TITLE_CACHE_DEST_RECT_OFFSET = 0x110
SYSTEM_CONTROL_TITLE_CACHE_SOURCE_RECT_OFFSET = 0x120
SYSTEM_CONTROL_TITLE_CACHE_TRACE_OFFSET = 0x130
SYSTEM_CONTROL_DROPDOWN_HIGHLIGHT_TRACE_OFFSET = 0x150
SYSTEM_CONTROL_DROPDOWN_HIGHLIGHT_TRACE_SIZE = 0x20
LOAD_SAVE_SEGMENT = RuntimeSegment("load_save", 0x10000, 0x2000, b"LOADSAVE", 0xE0000020)
LOAD_SAVE_HUD_FONT_ACTIVE_OFFSET = 0x1C
LOAD_SAVE_TEXT_ACTIVE_OFFSET = 0x54
LOAD_SAVE_FONT_POINT_HELPER_OFFSET = 0xC80
LOAD_SAVE_HUD_FONT_POINT_OFFSET = 0x28
# +0x28..+0x2f contains the saved HUD POINT; counters must not alias its Y.
LOAD_SAVE_HUD_FONT_ALPHA_TRANSFORM_COUNT_OFFSET = 0x20
# RestoreProgressController brackets the two exact calls which can present its
# private dense canvas. ResourceDispatch consumes this counter only when the
# source has the exact replacement extent, at the first copy into the private
# logical-size canvas. This scoped producer/consumer ABI avoids retaining a
# resource pointer beyond the draw that owns it.
RESOURCE_PROGRESS_DRAW_DEPTH_OFFSET = 0xED0
RESOURCE_PROGRESS_TRANSFORM_COUNT_OFFSET = 0xED4
CAPTION_SEGMENT = RuntimeSegment("captions", 0x12000, 0x2000, b"CAPTION\0", 0xE0000020)
# Binocular controls are a local retained widget inside an otherwise fitted
# full-screen layer.  Their bitmap composition and pointer inverse share a
# small generated ABI, but neither belongs to the global SystemScreen scratch
# page or to SIDNEY's dispatcher implementation.  Keep that cross-compiler
# contract in its own final page.
BINOCULAR_SEGMENT = RuntimeSegment("binocular", 0x14000, 0x1000, b"BINOCULR", 0xE0000020)
# The modern backend renders Direct3D into GK3's physical back page. Keep the
# tiny identity ABI in its own segment so fixed-interface compilers do not
# depend on the obsolete private-stage section or its implementation offsets.
ROOM_RENDERING_SEGMENT = RuntimeSegment("room_rendering", 0x15000, 0x1000, b"ROOMABI\0", 0xE0000020)
# TimeBlock composition has a complete model-lifetime wrapper, a fitted final
# blitter, and retained control-partition state.  Give that cohesive feature a
# page of its own instead of interleaving executable bytes with the generic
# resource dispatcher's bitmap/map state.  The page boundary is an enforced
# ABI: future emitter growth fails during payload construction.
TIMEBLOCK_SEGMENT = RuntimeSegment("timeblock", 0x16000, 0x2000, b"TIMEBLCK", 0xE0000020)
INVENTORY_NAVIGATION_SEGMENT = RuntimeSegment(
    "inventory_navigation", 0x18000, 0x2000, b"INVNAV\0\0", 0xE0000020
)
INVENTORY_NAVIGATION_STATE_OFFSET = 0x20
INVENTORY_NAVIGATION_DIMENSIONS_OFFSET = 0x1000
INVENTORY_NAVIGATION_SOURCE_OFFSET = 0x500
INVENTORY_NAVIGATION_CLEAR_OFFSET = 0x100
INVENTORY_NAVIGATION_INPUT_OFFSET = 0xB00
INVENTORY_NAVIGATION_INPUT_STRIDE = 0x100
# Leave room for batch-reviewed action families without changing helper offsets.
UI_FRAMES_SEGMENT = RuntimeSegment("ui_frames", 0x1A000, 0x8000, b"UIFRAMES", 0xE0000020)
UI_FRAMES_DIMENSIONS_OFFSET = 0x800
UI_FRAMES_SOURCE_OFFSET = 0xC00
GPS_SEGMENT = RuntimeSegment("gps", 0x22000, 0x1000, b"GPSVIEW\0", 0xE0000020)
# The final-blit dispatcher calls this owner after source-density handling.
GPS_TRANSFER_OFFSET = 0xC00
CONSOLE_SEGMENT = RuntimeSegment("console", 0x23000, 0x1000, b"CONSOLE\0", 0xE0000020)
INVENTORY_FILTER_SEGMENT = RuntimeSegment(
    "inventory_filter", 0x24000, 0x1000, b"INVFILTR", 0xE0000020
)
ZODIAC_SEGMENT = RuntimeSegment("zodiac", 0x25000, 0x1000, b"ZODIAC\0\0", 0xE0000020)
# Load/Save bitmap state changes rebuild bounds and sample opacity separately
# from the root layout. Keep those two adapters in one bounded owner page.
LOAD_SAVE_BUTTON_SEGMENT = RuntimeSegment(
    "load_save_buttons", 0x26000, 0x1000, b"LSBUTTON", 0xE0000020
)
LOAD_SAVE_BUTTON_INITIAL_BOUNDS_OFFSET = 0x800
UI_FILTER_SEGMENT = RuntimeSegment("ui_filter", 0x27000, 0x8000, b"UIFILTER", 0xE0000020)
FINGERPRINT_ALPHA_SEGMENT = RuntimeSegment(
    "fingerprint_alpha", 0x2F000, 0x1000, b"FPALPHA\0", 0xE0000020
)
FINGERPRINT_ALPHA_NORMALIZE_OFFSET = 0xF00
CURSOR_BLEND_SEGMENT = RuntimeSegment("cursor_blend", 0x30000, 0x1000, b"CURBLEND", 0xE0000020)
UI_ALPHA_SEGMENT = RuntimeSegment("ui_alpha", 0x31000, 0x1000, b"UIALPHA\0", 0xE0000020)
FONT_BANK_SEGMENT = RuntimeSegment("font_banks", 0x32000, 0x4000, b"FONTBANK", 0xE0000020)
FONT_BANK_SCOPE_OFFSET = 0x14
FONT_BANK_DRAW_SCOPE_OFFSET = 0x3000
FONT_BANK_SELECT_OFFSET = 0x3200
FONT_BANK_NATIVE_OFFSET = 0x3500
FONT_BANK_SOURCE_GUARD_OFFSET = 0x3600
FONT_BANK_ALPHA_SELECT_OFFSET = 0x3700
FONT_BANK_SOURCE_COPY_OFFSET = 0x3A00
FONT_BANK_ROW_LAYOUTS_OFFSET = 0x3B00
SPRITE_CACHE_SEGMENT = RuntimeSegment("sprite_cache", 0x36000, 0x8000, b"SPRTCACH", 0xE0000020)
SPRITE_CACHE_TRANSFER_OFFSET = 0x1000
CONSOLE_OWNER_OFFSET = 0x10
CONSOLE_TRANSFER_OFFSET = 0x300
CONSOLE_DAMAGE_OFFSET = 0xE00
TIMEBLOCK_OVERLAY_SURFACE_OFFSET = 0xCB4
TIMEBLOCK_RAW_HEIGHT_OFFSET = 0xC34
TIMEBLOCK_LOGICAL_RECT_OFFSET = 0xC10
TIMEBLOCK_TARGET_RECT_OFFSET = 0xC20
TIMEBLOCK_LAYER_OFFSET = 0xC48
BINOCULAR_LAYOUT_VERSION_OFFSET = 0x08
BINOCULAR_VALID_OFFSET = 0x0C
BINOCULAR_ROOT_OFFSET = 0x10
BINOCULAR_SOURCE_GROUP_RECT_OFFSET = 0x14
BINOCULAR_TARGET_GROUP_RECT_OFFSET = 0x24
BINOCULAR_BLT_TRANSFORM_COUNT_OFFSET = 0x34
BINOCULAR_INPUT_TRANSFORM_COUNT_OFFSET = 0x38
BINOCULAR_BLT_HELPER_OFFSET = 0x100
BINOCULAR_INPUT_HELPER_OFFSET = 0x500
BINOCULAR_DENSE_STATE_OFFSET = 0x40
BINOCULAR_SIZE_HELPER_OFFSET = 0x800
BINOCULAR_SOURCE_HELPER_OFFSET = 0xB00
# Shared bitmap-resource helpers live after the binocular source helper.
CURSOR_DENSITY_PROBE_OFFSET = 0xC00
CURSOR_RESOURCE_MATCH_OFFSET = 0xD00
# The caption feature publishes only three cross-compiler symbols.  The system
# font hook reads the exact object/clip pair while Caption::Draw is active, the
# final page owner calls the no-argument presenter, and the staged renderer's
# existing damage callback chains through the caption-owned augmenter.
CAPTION_ACTIVE_OBJECT_OFFSET = 0x18
CAPTION_ACTIVE_CLIP_OFFSET = 0x1C
# The shared final-blit classifier publishes the exact union of clipped glyph
# rectangles while Caption::Draw rasterizes one cache generation.  The caption
# owner then uses this measured rectangle for both replay and stage cleanup,
# instead of transferring the object's intentionally full-width layout box.
CAPTION_GLYPH_RECT_VALID_OFFSET = 0x254
CAPTION_GLYPH_RECT_OFFSET = 0x258
CAPTION_CACHE_GENERATION_RECT_OFFSET = 0x268
CAPTION_GLYPH_RECORDER_OFFSET = 0x1500
CAPTION_PRESENTER_OFFSET = 0x600
CAPTION_DAMAGE_AUGMENTER_OFFSET = 0xE00
RUNTIME_SEGMENTS = (
    SIDNEY_CONSTRUCTION_SEGMENT,
    SIDNEY_PRESENTATION_SEGMENT,
    INVENTORY_SEGMENT,
    RESOURCE_SEGMENT,
    FINGERPRINT_SEGMENT,
    SYSTEM_SEGMENT,
    SYSTEM_CONTROL_SEGMENT,
    LOAD_SAVE_SEGMENT,
    CAPTION_SEGMENT,
    BINOCULAR_SEGMENT,
    ROOM_RENDERING_SEGMENT,
    TIMEBLOCK_SEGMENT,
    INVENTORY_NAVIGATION_SEGMENT,
    UI_FRAMES_SEGMENT,
    GPS_SEGMENT,
    CONSOLE_SEGMENT,
    INVENTORY_FILTER_SEGMENT,
    ZODIAC_SEGMENT,
    LOAD_SAVE_BUTTON_SEGMENT,
    UI_FILTER_SEGMENT,
    FINGERPRINT_ALPHA_SEGMENT,
    CURSOR_BLEND_SEGMENT,
    UI_ALPHA_SEGMENT,
    FONT_BANK_SEGMENT,
    SPRITE_CACHE_SEGMENT,
)


class RuntimeLayoutError(PatchError):
    """Report a violated invariant of the generated runtime layout."""

    @classmethod
    def duplicate_segment(cls, name: str) -> RuntimeLayoutError:
        """Build an error for a repeated logical segment name."""
        return cls(f"duplicate runtime segment: {name}")

    @classmethod
    def invalid_segment(cls, name: str) -> RuntimeLayoutError:
        """Build an error for malformed segment metadata."""
        return cls(f"invalid runtime segment declaration: {name!r}")

    @classmethod
    def overlapping_segment(cls, name: str) -> RuntimeLayoutError:
        """Build an error for overlapping segment ranges."""
        return cls(f"overlapping runtime segment: {name}")

    @classmethod
    def oversized_segment(cls, name: str) -> RuntimeLayoutError:
        """Build an error for a segment beyond the physical section."""
        return cls(f"runtime segment exceeds section: {name}")

    @classmethod
    def oversized_payload(cls, name: str) -> RuntimeLayoutError:
        """Build an error for a payload beyond its reserved segment."""
        return cls(f"payload exceeds runtime segment: {name}")

    @classmethod
    def installed_segment(cls, name: str) -> RuntimeLayoutError:
        """Build an error for an attempt to reinstall a segment."""
        return cls(f"runtime segment already exists: {name}")

    @classmethod
    def unrecognized_segment(cls, name: str) -> RuntimeLayoutError:
        """Build an error for nonzero data without current segment magic."""
        return cls(f"runtime segment contains unrecognized data: {name}")

    @classmethod
    def payload_mismatch(cls, name: str) -> RuntimeLayoutError:
        """Build an error for bytes that differ from a clean deterministic rebuild."""
        return cls(f"fixed-interface runtime payload does not match a clean rebuild: {name}")

    @classmethod
    def missing_shared_section(cls, name: str | None = None) -> RuntimeLayoutError:
        """Build an error for a missing physical runtime section."""
        if name is None:
            return cls("fixed-interface runtime section is missing")
        return cls(f"shared runtime section not found for {name}")

    @classmethod
    def missing_segments(cls, names: list[str]) -> RuntimeLayoutError:
        """Build an error listing absent required segments."""
        return cls(f"fixed-interface runtime segments are missing: {', '.join(names)}")

    @classmethod
    def section_too_small(cls) -> RuntimeLayoutError:
        """Build an error for a truncated physical section."""
        return cls("fixed-interface runtime section is too small")

    @classmethod
    def unsafe_characteristics(cls) -> RuntimeLayoutError:
        """Build an error for incorrect shared-section permissions."""
        return cls("fixed-interface runtime section has unsafe characteristics")

    @classmethod
    def incompatible_segment_characteristics(cls, name: str) -> RuntimeLayoutError:
        """Build an error for permissions outside a logical segment's ABI."""
        return cls(f"fixed-interface runtime segment has incompatible characteristics: {name}")

    @classmethod
    def incompatible_abi(cls) -> RuntimeLayoutError:
        """Build an error for an unrecognized shared header."""
        return cls("fixed-interface runtime header does not match the current ABI")

    @classmethod
    def requires_pristine(cls) -> RuntimeLayoutError:
        """Build an error for an already installed runtime."""
        return cls("fixed-interface runtime requires a pristine executable")

    @classmethod
    def unknown_segment(cls, name: str) -> RuntimeLayoutError:
        """Build an error for a symbol request outside the declared layout."""
        return cls(f"unknown fixed-interface runtime segment: {name}")


class RuntimeLayout:
    """Declare and validate the one current fixed-interface runtime ABI.

    Feature builders intentionally use cohesive local offsets. Those address
    spaces map to bounded non-overlapping slices here, so the executable owns
    one physical section and one explicit ABI rather than a collection of
    independently appended sections.
    """

    section_name: ClassVar[str] = ".gk2d"
    section_size: ClassVar[int] = 0x3E000
    section_characteristics: ClassVar[int] = 0xE0000020
    magic: ClassVar[bytes] = b"GK3RT2D\0"
    abi_version: ClassVar[int] = 158
    header_size: ClassVar[int] = 0x1000

    segments: ClassVar[tuple[RuntimeSegment, ...]] = RUNTIME_SEGMENTS
    _by_name: ClassVar[Mapping[str, RuntimeSegment]] = MappingProxyType(
        {segment.logical_name: segment for segment in segments}
    )

    @classmethod
    def segment(cls, logical_name: str) -> RuntimeSegment | None:
        """Return the declared segment for a builder-local section name."""
        return cls._by_name.get(logical_name)

    @classmethod
    def header(cls) -> bytes:
        """Build the stable header stored at the start of the shared section."""
        header = bytearray(cls.header_size)
        header[: len(cls.magic)] = cls.magic
        struct.pack_into("<III", header, 0x08, cls.abi_version, cls.section_size, len(cls.segments))
        return bytes(header)

    @classmethod
    def validate_definition(cls) -> None:
        """Reject overlaps and out-of-bounds segments in the source layout."""
        previous_end = cls.header_size
        names: set[str] = set()
        for segment in cls.segments:
            if (
                not segment.logical_name
                or segment.offset < 0
                or segment.size <= 0
                or len(segment.magic) != RUNTIME_SEGMENT_MAGIC_SIZE
                or segment.characteristics <= 0
            ):
                raise RuntimeLayoutError.invalid_segment(segment.logical_name)
            if segment.logical_name in names:
                raise RuntimeLayoutError.duplicate_segment(segment.logical_name)
            if segment.offset < previous_end:
                raise RuntimeLayoutError.overlapping_segment(segment.logical_name)
            if segment.end > cls.section_size:
                raise RuntimeLayoutError.oversized_segment(segment.logical_name)
            names.add(segment.logical_name)
            previous_end = segment.end


# Fail during import rather than after a partially built executable if source
# edits ever make the single runtime ABI internally inconsistent.
RuntimeLayout.validate_definition()


@dataclass(frozen=True, slots=True)
class RuntimeSegmentAddress:
    """Resolved raw and virtual bases for one runtime segment."""

    segment: RuntimeSegment
    raw_offset: int
    rva: int
    va: int


@dataclass(frozen=True, slots=True)
class RuntimeSymbols:
    """Typed symbol table exported to every runtime feature compiler."""

    segments: tuple[RuntimeSegmentAddress, ...]

    def require(self, logical_name: str) -> RuntimeSegmentAddress:
        """Return one required segment base or reject an undeclared name."""
        for address in self.segments:
            if address.segment.logical_name == logical_name:
                return address
        raise RuntimeLayoutError.unknown_segment(logical_name)

    def va(self, logical_name: str, local_offset: int = 0) -> int:
        """Resolve a builder-local offset to an absolute virtual address."""
        address = self.require(logical_name)
        self._validate_local_offset(address.segment, local_offset)
        return address.va + local_offset

    def raw(self, logical_name: str, local_offset: int = 0) -> int:
        """Resolve a builder-local offset to an on-disk byte offset."""
        address = self.require(logical_name)
        self._validate_local_offset(address.segment, local_offset)
        return address.raw_offset + local_offset

    @staticmethod
    def _validate_local_offset(segment: RuntimeSegment, local_offset: int) -> None:
        if not 0 <= local_offset < segment.size:
            raise RuntimeLayoutError.oversized_payload(segment.logical_name)


class RuntimeImage:
    """Present builder-local segment views over one physical PE section.

    Reverse-engineered feature builders retain cohesive local address spaces
    while the emitted executable receives only ``.gk2d``. New code consumes
    :class:`RuntimeLayout` directly and must not introduce an undeclared alias.
    """

    def __init__(self, image: PEFile) -> None:
        """Wrap one mutable image without changing it eagerly."""
        self._image = image

    def __getattr__(self, name: str) -> object:
        """Delegate ordinary PE operations that do not address section names."""
        return getattr(self._image, name)

    def get_section(self, name: str) -> Section | None:
        """Return an installed logical segment or an ordinary physical section."""
        segment = RuntimeLayout.segment(name)
        if segment is None:
            return self._image.get_section(name)

        shared = self._image.get_section(RuntimeLayout.section_name)
        if shared is None:
            return None
        self._validate_shared(shared)
        raw_offset = shared.pointer_to_raw_data + segment.offset
        if self._image.read_bytes(raw_offset, len(segment.magic)) != segment.magic:
            return None
        return self._segment_section(shared, segment)

    def add_section(self, name: str, payload: bytes, characteristics: int) -> Section:
        """Install one logical payload into its reserved shared-section slice."""
        segment = RuntimeLayout.segment(name)
        if segment is None:
            return self._image.add_section(name, payload, characteristics)
        if characteristics != segment.characteristics:
            raise RuntimeLayoutError.incompatible_segment_characteristics(name)
        if len(payload) > segment.size:
            raise RuntimeLayoutError.oversized_payload(name)
        if self.get_section(name) is not None:
            raise RuntimeLayoutError.installed_segment(name)

        shared = self._ensure_shared_section()
        raw_offset = shared.pointer_to_raw_data + segment.offset
        existing = self._image.read_bytes(raw_offset, segment.size)
        if any(existing):
            raise RuntimeLayoutError.unrecognized_segment(name)
        self._image.write_bytes(raw_offset, payload)
        return self._segment_section(shared, segment)

    def set_section_characteristics(self, name: str, characteristics: int) -> None:
        """Keep the shared section executable regardless of local data policy."""
        segment = RuntimeLayout.segment(name)
        if segment is None:
            self._image.set_section_characteristics(name, characteristics)
            return
        if characteristics != segment.characteristics:
            raise RuntimeLayoutError.incompatible_segment_characteristics(name)
        shared = self._image.get_section(RuntimeLayout.section_name)
        if shared is None:
            raise RuntimeLayoutError.missing_shared_section(name)
        self._image.set_section_characteristics(
            RuntimeLayout.section_name,
            RuntimeLayout.section_characteristics,
        )

    def validate_complete(self) -> None:
        """Verify the shared header and every declared builder segment."""
        shared = self._image.get_section(RuntimeLayout.section_name)
        if shared is None:
            raise RuntimeLayoutError.missing_shared_section()
        self._validate_shared(shared)
        missing = [
            segment.logical_name
            for segment in RuntimeLayout.segments
            if self.get_section(segment.logical_name) is None
        ]
        if missing:
            raise RuntimeLayoutError.missing_segments(missing)

    def prepare(self) -> RuntimeSymbols:
        """Create the shared section and export all fixed segment addresses."""
        shared = self._ensure_shared_section()
        section_va = self._image.rva_to_va(shared.virtual_address)
        return RuntimeSymbols(
            segments=tuple(
                RuntimeSegmentAddress(
                    segment=segment,
                    raw_offset=shared.pointer_to_raw_data + segment.offset,
                    rva=shared.virtual_address + segment.offset,
                    va=section_va + segment.offset,
                )
                for segment in RuntimeLayout.segments
            )
        )

    def _ensure_shared_section(self) -> Section:
        shared = self._image.get_section(RuntimeLayout.section_name)
        if shared is None:
            shared = self._image.add_section(
                RuntimeLayout.section_name,
                b"\x00" * RuntimeLayout.section_size,
                RuntimeLayout.section_characteristics,
            )
            self._image.write_bytes(shared.pointer_to_raw_data, RuntimeLayout.header())
        self._validate_shared(shared)
        return shared

    def _validate_shared(self, shared: Section) -> None:
        if shared.size_of_raw_data < RuntimeLayout.section_size:
            raise RuntimeLayoutError.section_too_small()
        if shared.characteristics != RuntimeLayout.section_characteristics:
            raise RuntimeLayoutError.unsafe_characteristics()
        expected = RuntimeLayout.header()[:0x14]
        actual = self._image.read_bytes(shared.pointer_to_raw_data, len(expected))
        if actual != expected:
            raise RuntimeLayoutError.incompatible_abi()

    @staticmethod
    def _segment_section(shared: Section, segment: RuntimeSegment) -> Section:
        return Section(
            name=segment.logical_name,
            virtual_size=segment.size,
            virtual_address=shared.virtual_address + segment.offset,
            size_of_raw_data=segment.size,
            pointer_to_raw_data=shared.pointer_to_raw_data + segment.offset,
            characteristics=segment.characteristics,
            header_offset=shared.header_offset,
        )


def install_runtime_segment(image: PEFile, segment: RuntimeSegment) -> Section:
    """Install one empty logical segment through the shared runtime owner.

    Feature compilers own payload semantics, while this primitive owns the
    repeated section-existence, capacity, and permission contract. Keeping it
    here prevents six compilers from gradually accepting different layouts.
    """
    if image.get_section(segment.logical_name) is not None:
        raise RuntimeLayoutError.installed_segment(segment.logical_name)
    section = image.add_section(
        segment.logical_name,
        b"\x00" * segment.size,
        segment.characteristics,
    )
    if section.size_of_raw_data < segment.size:
        raise RuntimeLayoutError.oversized_segment(segment.logical_name)
    image.set_section_characteristics(segment.logical_name, segment.characteristics)
    return section
