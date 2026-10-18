"""Private final-page bridge for native OpenXR interface panels."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from gk3hd.patch.definitions.vr_gps import VRGPSCompiler
from gk3hd.patch.definitions.vr_hud_compiler import VRHudCompiler
from gk3hd.patch.definitions.vr_menu_compiler import VRMenuCompiler
from gk3hd.patch.definitions.vr_movie import movie_extent
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.captions import CaptionCacheABI
    from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipCacheABI
    from gk3hd.patch.definitions.vr_gps import VRGPSABI
    from gk3hd.patch.definitions.vr_hud_compiler import VRHudABI
    from gk3hd.patch.definitions.vr_menu_compiler import VRMenuABI


@dataclass(frozen=True, slots=True)
class VRPanelABI:
    """Explicit panel-mode controls, results and controller output."""

    enabled_va: int
    recenter_va: int
    result_va: int
    submitted_frames_va: int
    presenter_calls_va: int
    frame_va: int
    completion_result_va: int
    composition_presenter_va: int
    world_enabled_va: int
    ownership_query_slot_va: int

    @property
    def pointing_hand_va(self) -> int:
        """Preferred left/right pointer in the shared panel request, not its output."""
        return self.frame_va + 16

    @property
    def renderer_bridge_slot_va(self) -> int:
        """Resolved, versioned renderer entry, shared with scene retirement."""
        return self.enabled_va + 16


@dataclass(frozen=True, slots=True, kw_only=True)
class VRPanelCompiler:
    """Capture the completed game page after its existing UI presenter.

    This private gate deliberately requires the caller to identify the existing
    presenter. It never replaces cursor/page composition with a VR-only path.
    A paired deferred world is finalized here with an optional panel, using one
    XR tracking/input snapshot. Without a world, it presents a panel-only frame.
    An optional native ownership callback selects panel, world-only completion,
    or closure. World-only completion retains the current predicted controller
    snapshot without a quad. Completed-page panels are still opaque, not isolated
    transparent UI. Explicitly isolated captions/tooltips share a current-frame
    overlay batch without creating a panel pointer hit. VRInputCompiler can
    consume either completed input snapshot.
    """

    profile: BuildProfile
    expected_presenter_va: int = 0
    world_enabled_va: int = 0
    caption: CaptionCacheABI | None = None
    tooltip: TooltipCacheABI | None = None
    menus: VRMenuABI | None = None
    hud: VRHudABI | None = None
    gps: VRGPSABI | None = None

    section_name: ClassVar[str] = ".gk3vp"
    section_size: ClassVar[int] = 0x1000
    _magic: ClassVar[bytes] = b"GK3XRP01"
    _enabled: ClassVar[int] = 0x0C
    _result: ClassVar[int] = 0x10
    _frames: ClassVar[int] = 0x14
    _calls: ClassVar[int] = 0x18
    _bridge: ClassVar[int] = 0x1C
    _resolved: ClassVar[int] = 0x20
    _visible: ClassVar[int] = 0x24
    _previous: ClassVar[int] = 0x28
    _world_enabled: ClassVar[int] = 0x2C
    _completion_result: ClassVar[int] = 0x30
    _ownership_query: ClassVar[int] = 0x34
    _operation: ClassVar[int] = 0x38
    _caption_before: ClassVar[int] = 0x3C
    _tooltip_before: ClassVar[int] = 0x40
    _menus_ready: ClassVar[int] = 0x44
    _hud_ready: ClassVar[int] = 0x48
    _gps_ready: ClassVar[int] = 0x4C
    _movie_scratch: ClassVar[int] = 0x50
    _movie_width: ClassVar[int] = 0x58
    _movie_height: ClassVar[int] = 0x5C
    _movie_extent: ClassVar[int] = 0xC00
    _code: ClassVar[int] = 0x100
    _frame: ClassVar[int] = 0x800
    _renderer_name: ClassVar[int] = 0xB60
    _export_name: ClassVar[int] = 0xB80

    def abi(self, image: PEFile) -> VRPanelABI:
        """Return the versioned private panel boundary."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR panel section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRPanelABI(
            base + self._enabled,
            base + self._frame + 4,
            base + self._result,
            base + self._frames,
            base + self._calls,
            base + self._frame,
            base + self._completion_result,
            image.read_u32_va(base + self._previous),
            image.read_u32_va(base + self._world_enabled),
            base + self._ownership_query,
        )

    def precheck(self, image: PEFile) -> None:
        """Require an explicit, unchanged presentation dependency before writes."""
        if image.get_section(self.section_name) is not None:
            msg = "VR panel hooks are already installed"
            raise PatchError(msg)
        transition = TransitionFrameCompiler.runtime_abi(image)
        if image.read_u32_va(transition.pre_flip_presenter_slot_va) != self.expected_presenter_va:
            msg = "VR panel precheck failed: unexpected final-page presenter"
            raise PatchError(msg)
        if self.expected_presenter_va:
            image.va_to_offset(self.expected_presenter_va)
        if self.world_enabled_va:
            scene = VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image)
            if (
                scene.enabled_va != self.world_enabled_va
                or image.read_u32_va(scene.recenter_va) & 2 == 0
            ):
                msg = "VR panel requires a verified deferred world bridge"
                raise PatchError(msg)
        if self.caption is not None and (
            not self.world_enabled_va or CaptionFeatureCompiler.cache_abi(image) != self.caption
        ):
            msg = "VR captions require the verified keyed producer and deferred world"
            raise PatchError(msg)
        if self.tooltip is not None and (
            not self.world_enabled_va or TooltipFeatureCompiler.cache_abi(image) != self.tooltip
        ):
            msg = "VR tooltips require the verified isolated producer and deferred world"
            raise PatchError(msg)
        native = image
        if self.gps is not None:
            gps = VRGPSCompiler(profile=self.profile, world_enabled_va=self.world_enabled_va)
            if (
                self.tooltip is None
                or self.menus is None
                or self.hud is None
                or self.gps.world_enabled_va != self.world_enabled_va
                or gps.abi(image) != self.gps
            ):
                msg = "VR GPS requires verified overlay producers"
                raise PatchError(msg)
            gps.postcheck(image)
            native = gps.native_image(image)
        if self.hud is not None:
            hud = VRHudCompiler(profile=self.profile, world_enabled_va=self.world_enabled_va)
            if (
                self.tooltip is None
                or self.hud.world_enabled_va != self.world_enabled_va
                or hud.abi(image) != self.hud
            ):
                msg = "VR HUD requires verified sources and the overlay batch"
                raise PatchError(msg)
            hud.postcheck(native)
            native = hud.native_image(native)
        if self.menus is not None:
            compiler = VRMenuCompiler(profile=self.profile, world_enabled_va=self.world_enabled_va)
            if (
                self.tooltip is None
                or self.menus.world_enabled_va != self.world_enabled_va
                or compiler.abi(image) != self.menus
            ):
                msg = "VR menus require verified producers and the overlay batch"
                raise PatchError(msg)
            compiler.postcheck(native)

    def apply(self, image: PEFile) -> None:
        """Link after the existing presenter, keeping native Flip untouched."""
        self.precheck(image)
        transition = TransitionFrameCompiler.runtime_abi(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        image.write_bytes(
            section.pointer_to_raw_data,
            self._payload(base, world_frame_pending_va=self._pending_world_va(image)),
        )
        plan = ExecutableMutationPlan(owner="vr_panel")
        plan.pointer(
            label="completed page presenter",
            slot_va=transition.pre_flip_presenter_slot_va,
            expected=self.expected_presenter_va,
            target_va=base + self._code,
        )
        plan.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify the full dormant bridge and its composed final-page redirect."""
        abi = self.abi(image)
        base = abi.enabled_va - self._enabled
        if image.read_bytes(image.va_to_offset(base), self.section_size) != self._payload(
            base, world_frame_pending_va=self._pending_world_va(image)
        ):
            msg = "VR panel payload failed verification"
            raise PatchError(msg)
        transition = TransitionFrameCompiler.runtime_abi(image)
        if image.read_u32_va(transition.pre_flip_presenter_slot_va) != base + self._code:
            msg = "VR panel presenter failed verification"
            raise PatchError(msg)

    def _pending_world_va(self, image: PEFile) -> int:
        if not self.world_enabled_va:
            return 0
        scene = VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image)
        if scene.enabled_va != self.world_enabled_va:
            msg = "VR panel world completion boundary changed"
            raise PatchError(msg)
        return scene.frame_pending_va

    def _payload(self, base: int, *, world_frame_pending_va: int = 0) -> bytes:
        e = X86Emitter(base_va=base + self._code)

        def absolute(opcode: bytes, address: int) -> None:
            e.raw(opcode + struct.pack("<I", address))

        def state(opcode: bytes, offset: int) -> None:
            absolute(opcode, base + offset)

        def store(offset: int, value: int) -> None:
            state(b"\xc7\x05", offset)
            e.raw(struct.pack("<I", value))

        e.raw(bytes.fromhex("9c 60"))
        producer_switches = tuple(
            producer.enabled_va
            for producer in (self.hud, self.menus, self.gps)
            if producer is not None
        )
        if producer_switches:
            # Both render halves own HUD/menu capture, independently of input.
            # Publish before ordinary UI composition and withdraw disabled
            # sources even when hidden native widgets never Draw again.
            e.raw(bytes.fromhex("31 c0"))
            for address in (base + self._enabled, self.world_enabled_va):
                absolute(b"\x83\x3d", address)
                e.raw(b"\x01")
                e.jump_if(Condition.NOT_EQUAL, "producers_disabled")
            e.raw(b"\x40")
            e.label("producers_disabled")
            for address in producer_switches:
                absolute(b"\xa3", address)
        if self.tooltip is not None:
            # Publish ownership before the shared producer runs. A previous
            # frame's flag must not survive either half being disabled.
            e.raw(b"\x31\xc0")
            state(b"\x83\x3d", self._enabled)
            e.raw(b"\x00")
            e.jump_if(Condition.EQUAL, "tooltip_owner_ready")
            absolute(b"\x83\x3d", self.world_enabled_va)
            e.raw(b"\x00\x0f\x95\xc0")
            e.label("tooltip_owner_ready")
            absolute(b"\xa3", self.tooltip.isolation_enabled_va)
        if self.caption is not None:
            absolute(b"\xa1", self.caption.replay_count_va)
            state(b"\xa3", self._caption_before)
        if self.tooltip is not None:
            absolute(b"\xa1", self.tooltip.replay_count_va)
            state(b"\xa3", self._tooltip_before)
        if self.expected_presenter_va:
            e.call_absolute(self.expected_presenter_va)
        state(b"\xff\x05", self._calls)
        if self.hud is not None:
            store(self._frame + 188, 0)
            state(b"\x68", self._frame)
            e.call_absolute(self.hud.query_va)
            state(b"\xa3", self._hud_ready)
        state(b"\x83\x3d", self._enabled)
        e.raw(b"\x00")
        if not self.world_enabled_va:
            e.jump_if(Condition.NOT_EQUAL, "resolve")
            state(b"\x83\x3d", self._visible)
            e.raw(b"\x00")
            e.jump_if(Condition.EQUAL, "done")
        # Paired worlds must always reach the finalizer, including a control
        # being disabled between the world draw and this pre-Flip callback.
        e.label("resolve")
        state(b"\x83\x3d", self._resolved)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "resolved")
        store(self._resolved, 1)
        state(b"\x68", self._renderer_name)
        absolute(b"\xff\x15", self.profile.address("win32.GetModuleHandleA"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "unavailable")
        state(b"\x68", self._export_name)
        e.raw(b"\x50")
        absolute(b"\xff\x15", self.profile.address("win32.GetProcAddress"))
        state(b"\xa3", self._bridge)
        e.label("resolved")
        state(b"\x83\x3d", self._bridge)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "unavailable")
        state(b"\x83\x3d", self._enabled)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "close")
        store(self._operation, 0)
        # Preserve an explicit recenter request, never retain caption alpha
        # when the next frame belongs to an ordinary opaque interface.
        state(b"\x83\x25", self._frame + 4)
        e.raw(b"\xf9")  # Retire transparency/menu placement, retain recenter.
        if self.tooltip is not None and self.hud is None:
            store(self._frame + 188, 0)  # Batch count never survives a frame.
        if self.gps is not None:
            # Device below menus, so menu pixels and picking retain priority.
            state(b"\x68", self._frame)
            e.call_absolute(self.gps.query_va)
            state(b"\xa3", self._gps_ready)
        if self.menus is not None:
            # Validate/withdraw caches on every live interface frame, including
            # a modal transition or a hidden menu that does not call Draw.
            state(b"\x68", self._frame)
            e.call_absolute(self.menus.query_va)
            state(b"\xa3", self._menus_ready)
        state(b"\x83\x3d", self._ownership_query)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "owned_panel")
        state(b"\xff\x15", self._ownership_query)
        e.raw(bytes.fromhex("a8 02"))
        if self.menus is None:
            e.jump_if(Condition.NOT_EQUAL, "owned_panel")
        else:
            e.jump_if(Condition.EQUAL, "world_labels")
            e.raw(bytes.fromhex("a8 01"))
            e.jump_if(Condition.EQUAL, "owned_panel")
            state(b"\x83\x3d", self._menus_ready)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "owned_panel")
        e.label("world_labels")
        e.raw(bytes.fromhex("a8 01"))
        e.jump_if(Condition.EQUAL, "close")
        if self.gps is not None:
            state(b"\x83\x3d", self._gps_ready)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "owned_panel")
        if self.hud is not None:
            state(b"\x83\x3d", self._hud_ready)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "owned_panel")
        store(self._operation, 2)  # Finish current world, retain its input, no quad.
        if self.tooltip is not None:
            # World-only ownership may contain independently isolated labels.
            # Ordinary room menus still use their opaque panel until their
            # own producer and coverage-aware input are explicitly isolated.
            self._emit_overlays(e, base)
        elif self.caption is not None:
            absolute(b"\xa1", self.caption.replay_count_va)
            state(b"\x3b\x05", self._caption_before)
            e.jump_if(Condition.EQUAL, "owned_panel")
            absolute(b"\x83\x3d", self.caption.ready_va)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "owned_panel")
            absolute(b"\xa1", self.caption.surface_va)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "owned_panel")
            state(b"\xa3", self._frame + 188)
            for offset in range(0, 16, 4):
                absolute(b"\xa1", self.caption.rect_va + offset)
                state(b"\xa3", self._frame + 196 + offset)
            store(self._operation, 3)
            state(b"\x83\x0d", self._frame + 4)
            e.raw(b"\x02")
        e.label("owned_panel")
        if self.menus is not None or self.hud is not None:
            state(b"\x83\x3d", self._operation)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "batch_retained")
            store(self._frame + 188, 0)
            e.label("batch_retained")
        if self.caption is not None and self.tooltip is not None:
            # An opaque cinematic/native page can carry readable dialogue
            # without borrowing world ownership or adding another frame loop.
            # The renderer mattes the baked glyph region in its private copy,
            # then submits the same isolated source at the VR subtitle scale.
            state(b"\x83\x3d", self._operation)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "modal_subtitle_ready")
            self._emit_modal_subtitle(e, base)
            e.label("modal_subtitle_ready")
        # Opaque modal pages need a wider physical canvas for readable text.
        # Do not enlarge the separate world/menu/caption/HUD planes. Publish
        # the size through the shared renderer ABI so controller picking uses
        # precisely the geometry that OpenXR displays, including transitions.
        store(self._frame + 20, struct.unpack("<I", struct.pack("<f", 1.6))[0])
        state(b"\x83\x3d", self._operation)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "opaque_panel_width")
        e.raw(b"\x83\x3d" + struct.pack("<I", base + self._operation) + b"\x05")
        e.jump_if(Condition.NOT_EQUAL, "panel_width_ready")
        e.label("opaque_panel_width")
        store(self._frame + 20, struct.unpack("<I", struct.pack("<f", 2.4))[0])
        e.label("panel_width_ready")
        for pointer, offset in (
            ("high_resolution_3d.display_width_ptr", self._frame + 8),
            ("high_resolution_3d.display_height_ptr", self._frame + 12),
        ):
            absolute(b"\xa1", self.profile.address(pointer))
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "disable")
            e.raw(bytes.fromhex("8b 00"))
            state(b"\xa3", offset)
        e.call_absolute(base + self._movie_extent)
        e.call("device")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "done")
        store(self._visible, 1)
        state(b"\x68", self._frame)
        state(b"\xff\x35", self._operation)
        e.raw(b"\x50")
        state(b"\xff\x15", self._bridge)
        state(b"\xa3", self._result)
        state(b"\xa3", self._completion_result)
        store(self._frame + 4, 0)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.SIGN, "disable")
        e.jump_if(Condition.NOT_EQUAL, "done")
        state(b"\xff\x05", self._frames)
        e.jump("done")
        e.label("unavailable")
        if self.tooltip is not None:
            absolute(b"\xc7\x05", self.tooltip.isolation_enabled_va)
            e.raw(bytes(4))
        store(self._result, 0x80004002)
        store(self._completion_result, 0x80004002)
        store(self._enabled, 0)
        if self.world_enabled_va:
            absolute(b"\xc7\x05", self.world_enabled_va)
            e.raw(bytes(4))
        e.jump("done")
        e.label("disable")
        store(self._enabled, 0)
        e.label("close")
        if self.tooltip is not None:
            absolute(b"\xc7\x05", self.tooltip.isolation_enabled_va)
            e.raw(bytes(4))
        if not self.world_enabled_va:
            state(b"\x83\x3d", self._visible)
            e.raw(b"\x00")
            e.jump_if(Condition.EQUAL, "done")
        e.call("device")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "done")
        e.raw(bytes.fromhex("6a 00 6a 01 50"))
        state(b"\xff\x15", self._bridge)
        state(b"\xa3", self._completion_result)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_SIGN, "closed")
        store(self._enabled, 0)
        if self.world_enabled_va:
            absolute(b"\xc7\x05", self.world_enabled_va)
            e.raw(bytes(4))
        e.label("closed")
        store(self._visible, 0)
        # Never leave controller presses or stale coordinates after closing.
        state(b"\xbf", self._frame + 28)
        e.raw(bytes.fromhex("31 c0 b9 28 00 00 00 fc f3 ab"))
        e.label("done")
        if world_frame_pending_va:
            # The world may be drawn again only after this completed-page
            # transaction has finalized or cancelled its runtime frame. Native
            # repair draws before this point share the existing XR sample.
            absolute(b"\xc7\x05", world_frame_pending_va)
            e.raw(bytes(4))
        e.raw(bytes.fromhex("61 9d c3"))
        e.label("device")
        absolute(b"\xa1", self.profile.address("high_resolution_3d.render_wrapper_ptr"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "no_device")
        e.raw(bytes.fromhex("8b 80 e8 04 00 00"))
        e.label("no_device")
        e.raw(b"\xc3")

        payload = SegmentPayloadBuilder(
            owner="vr_panel", segment=self.section_name, size=self.section_size
        )
        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into(
            "<2I", header, self._previous, self.expected_presenter_va, self.world_enabled_va
        )
        struct.pack_into("<f", header, self._movie_width, 2.4)
        struct.pack_into("<f", header, self._movie_height, 1.5)
        payload.place(label="state", offset=0, payload=bytes(header))
        payload.place(label="presenter", offset=self._code, payload=e.build(maximum_size=0x700))
        frame = struct.pack("<5I2f", 188, 0, 0, 0, 1, 1.6, 1.6) + bytes(160)
        if self.tooltip is not None:
            frame += bytes(4 + 16 * 40)
        elif self.caption is not None:
            frame += struct.pack("<2I4i", 0, self.caption.key, 0, 0, 0, 0)
        payload.place(label="panel frame", offset=self._frame, payload=frame)
        payload.place(label="renderer", offset=self._renderer_name, payload=b"ddraw.dll\0")
        payload.place(label="export", offset=self._export_name, payload=b"Gk3hdXrPanelV1\0")
        payload.place(
            label="movie cinema extent",
            offset=self._movie_extent,
            payload=movie_extent(
                self.profile,
                entry=base + self._movie_extent,
                frame=base + self._frame,
                scratch=base + self._movie_scratch,
                width=base + self._movie_width,
                height=base + self._movie_height,
                operation=base + self._operation,
            ),
        )
        return payload.build()

    def _emit_modal_subtitle(self, e: X86Emitter, base: int) -> None:
        """Append only a fresh, ready caption to an opaque completed page."""
        if self.caption is None:
            return
        caption = self.caption
        e.raw(b"\xa1" + struct.pack("<I", caption.replay_count_va))
        e.raw(b"\x3b\x05" + struct.pack("<I", base + self._caption_before))
        e.jump_if(Condition.EQUAL, "modal_caption_absent")
        e.raw(b"\x83\x3d" + struct.pack("<I", caption.ready_va) + b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "modal_caption_absent")
        e.raw(b"\xa1" + struct.pack("<I", caption.surface_va) + bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "modal_caption_absent")
        part = base + self._frame + 192
        e.raw(b"\xbf" + struct.pack("<I", part) + bytes.fromhex("89 07"))
        for offset, value in ((4, 9), (8, caption.key), (36, 0x3F800000)):
            e.raw(b"\xc7\x47" + bytes((offset,)) + struct.pack("<I", value))
        for offset in range(0, 16, 4):
            e.raw(b"\xa1" + struct.pack("<I", caption.rect_va + offset))
            e.raw(b"\x89\x47" + bytes((12 + offset,)))
            if offset in (0, 4):
                e.raw(b"\x89\x47" + bytes((28 + offset,)))
        for offset, value in ((self._frame + 188, 1), (self._operation, 5)):
            e.raw(b"\xc7\x05" + struct.pack("<I", base + offset) + struct.pack("<I", value))
        e.label("modal_caption_absent")

    def _emit_overlays(self, e: X86Emitter, base: int) -> None:
        """Append current native caption then tooltip pixels to one XR frame.

        Only the renderer writes input/geometry. Labels are noninteractive,
        and modal ownership never enters this path. Source rectangles belong
        to their producer, not to the desktop page or another overlay.
        """
        if self.tooltip is None:
            msg = "isolated overlays require a tooltip producer"
            raise PatchError(msg)

        def absolute(opcode: bytes, address: int) -> None:
            e.raw(opcode + struct.pack("<I", address))

        def append(
            *,
            source: int,
            destination: int,
            key: int | None,
            menu_companion: bool = False,
            subtitle: bool = False,
        ) -> None:
            # EDI selects one 40-byte part after the sized PanelFrame/count.
            absolute(b"\x8b\x3d", base + self._frame + 188)
            e.raw(b"\x6b\xff\x28\x81\xc7" + struct.pack("<I", base + self._frame + 192))
            e.raw(b"\x89\x07")  # EAX is the producer's live Surface1.
            flags = int(key is not None) | (4 if menu_companion else 0) | (8 if subtitle else 0)
            for offset, value in ((4, flags), (8, key or 0)):
                e.raw(b"\xc7\x47" + bytes([offset]) + struct.pack("<I", value))
            for offset in range(0, 16, 4):
                absolute(b"\xa1", source + offset)
                e.raw(b"\x89\x47" + bytes([12 + offset]))
            for offset in (0, 4):
                absolute(b"\xa1", destination + offset)
                e.raw(b"\x89\x47" + bytes([28 + offset]))
            e.raw(bytes.fromhex("c7 47 24 00 00 80 3f"))  # Producer opacity = 1.
            absolute(b"\xff\x05", base + self._frame + 188)

        if self.caption is not None:
            absolute(b"\xa1", self.caption.replay_count_va)
            absolute(b"\x3b\x05", base + self._caption_before)
            e.jump_if(Condition.EQUAL, "overlay_tooltip")
            absolute(b"\x83\x3d", self.caption.ready_va)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "overlay_tooltip")
            absolute(b"\xa1", self.caption.surface_va)
            e.raw(b"\x85\xc0")
            e.jump_if(Condition.EQUAL, "overlay_tooltip")
            append(
                source=self.caption.rect_va,
                destination=self.caption.rect_va,
                key=self.caption.key,
                subtitle=True,
            )
        e.label("overlay_tooltip")
        absolute(b"\xa1", self.tooltip.replay_count_va)
        absolute(b"\x3b\x05", base + self._tooltip_before)
        e.jump_if(Condition.EQUAL, "overlays_done")
        for address, value in ((self.tooltip.visible_va, 1), (self.tooltip.pending_va, 0)):
            absolute(b"\x83\x3d", address)
            e.raw(bytes([value]))
            e.jump_if(Condition.NOT_EQUAL, "overlays_done")
        absolute(b"\xa1", self.tooltip.surface_va)
        e.raw(b"\x85\xc0")
        e.jump_if(Condition.EQUAL, "overlays_done")
        append(
            source=self.tooltip.source_rect_va,
            destination=self.tooltip.destination_rect_va,
            key=None,
            menu_companion=True,
        )
        e.label("overlays_done")
        absolute(b"\x83\x3d", base + self._frame + 188)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "owned_panel")
        absolute(b"\xc7\x05", base + self._operation)
        e.raw(struct.pack("<I", 4))
        absolute(b"\x83\x0d", base + self._frame + 4)
        e.raw(b"\x02")
