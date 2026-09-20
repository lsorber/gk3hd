"""Compile SIDNEY's authored construction and retain dense laptop-frame sources."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, decode_rel32_branch
from gk3hd.patch.definitions.runtime2d.geometry import AUTHORED_FRAME_HEIGHT, AUTHORED_FRAME_WIDTH
from gk3hd.patch.definitions.runtime2d.layout import (
    SIDNEY_CONSTRUCTION_SEGMENT,
    SIDNEY_FINGERPRINT_DIMENSIONS_OFFSET,
    SIDNEY_FINGERPRINT_STATE_OFFSET,
    SIDNEY_FRAME_DIMENSIONS_OFFSET,
    SIDNEY_FRAME_DISCOVERY_OFFSET,
    SIDNEY_FRAME_RESIZE_OFFSET,
    SIDNEY_FRAME_SCRATCH_OFFSET,
    SIDNEY_FRAME_SOURCE_OFFSET,
    SIDNEY_FRAME_STATE_OFFSET,
    SIDNEY_FRAME_THUNKS_OFFSET,
    SIDNEY_IMAGE_DIMENSIONS_OFFSET,
    SIDNEY_PORTRAIT_STATE_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.sidney_frame import (
    build_dimensions,
    build_discovery,
    build_resize,
    build_resize_thunk,
    build_source,
    frame_state,
)
from gk3hd.patch.definitions.runtime2d.sidney_images import (
    FINGERPRINT_SURFACES_SIZE,
    build_fingerprint_dimensions,
    build_image_dimensions,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile, PatchSite

ABSOLUTE_LOAD_SIZE = 5
MOV_ABSOLUTE_LOAD_SIZE = 6
ABSOLUTE_LOAD_OPCODE = 0xA1
MOV_OPCODE = 0x8B


@dataclass(frozen=True, slots=True)
class _LoadSite:
    va: int
    kind: str
    orig: bytes

    def patched_bytes(self, *, width_ptr_va: int, height_ptr_va: int) -> bytes:
        target = width_ptr_va if self.kind == "width" else height_ptr_va
        if len(self.orig) == ABSOLUTE_LOAD_SIZE and self.orig[0] == ABSOLUTE_LOAD_OPCODE:
            return b"\xa1" + struct.pack("<I", target)
        if len(self.orig) == MOV_ABSOLUTE_LOAD_SIZE and self.orig[0] == MOV_OPCODE:
            return self.orig[:2] + struct.pack("<I", target)
        msg = "SIDNEY construction uses an unsupported dimension load"
        raise PatchError(msg)


@dataclass(frozen=True, slots=True, kw_only=True)
class SidneyConstructionCompiler:
    """Restore SIDNEY's native 1024x768 logical construction.

    Outcome:
        SIDNEY constructs the same complete laptop and panel hierarchy as the
        reference game regardless of the physical display dimensions.
    Before:
        SIDNEY's constructor reads physical width/height globals, so widescreen
        values corrupt its model geometry before presentation can transform it.
    After:
        Only confirmed SIDNEY-local reads see private 1024x768 constants; GK3's
        original arithmetic again derives the canonical ``(192, 144)`` origin.
    Strategy:
        Redirect the 20 profiled dimension loads to private authored constants
        and preserve the surrounding arithmetic. Frame-local resize hooks retain
        exact 4x sources while exposing their authored dimensions to layout.
        Restored controls can bypass resizing; shared dimension queries also
        rediscover the four exact named sources without changing saved geometry.
    Boundaries:
        Presentation, black pillars, inverse input, and teardown belong to the
        SIDNEY presentation owner. All other screen and 3D dimensions stay live.
    """

    profile: BuildProfile

    id: ClassVar[str] = "runtime2d.sidney_construction"

    _section_name: ClassVar[str] = SIDNEY_CONSTRUCTION_SEGMENT.logical_name
    # The shared runtime section is executable; this slice also retains the
    # frame-density helpers beside the construction constants they preserve.
    _section_size: ClassVar[int] = SIDNEY_CONSTRUCTION_SEGMENT.size
    _section_characteristics: ClassVar[int] = SIDNEY_CONSTRUCTION_SEGMENT.characteristics
    _magic: ClassVar[bytes] = SIDNEY_CONSTRUCTION_SEGMENT.magic

    # Presentation resolves the private width constant through this segment at
    # +0x18 rather than owning a duplicate SIDNEY-construction patch.
    _off_width_ptr: ClassVar[int] = 0x10
    _off_height_ptr: ClassVar[int] = 0x14
    _off_width_const: ClassVar[int] = 0x18
    _off_height_const: ClassVar[int] = 0x1C
    _site_shapes: ClassVar[tuple[tuple[str, str], ...]] = (
        ("sidney.construct.width_01", "width"),
        ("sidney.construct.height_01", "height"),
        ("sidney.construct.width_02", "width"),
        ("sidney.construct.width_03", "width"),
        ("sidney.construct.width_04", "width"),
        ("sidney.construct.height_02", "height"),
        ("sidney.construct.height_03", "height"),
        ("sidney.construct.width_05", "width"),
        ("sidney.construct.height_04", "height"),
        ("sidney.construct.height_05", "height"),
        ("sidney.construct.width_06", "width"),
        ("sidney.construct.height_06", "height"),
        ("sidney.construct.width_07", "width"),
        ("sidney.construct.width_08", "width"),
        ("sidney.construct.width_09", "width"),
        ("sidney.construct.height_07", "height"),
        ("sidney.construct.height_08", "height"),
        ("sidney.construct.height_09", "height"),
        ("sidney.construct.width_10", "width"),
    )

    @property
    def _sites(self) -> tuple[_LoadSite, ...]:
        return tuple(
            _LoadSite(site.va, kind, site.original)
            for name, kind in self._site_shapes
            for site in (self.profile.site(name),)
        )

    @property
    def _origin_center_site(self) -> PatchSite:
        return self.profile.site("sidney.construct.origin_width")

    @staticmethod
    def _origin_width_bytes(width_ptr_va: int) -> bytes:
        return b"\xa1" + struct.pack("<I", width_ptr_va)

    def precheck(self, pe: PEFile) -> None:
        """Validate every pristine SIDNEY-local dimension load."""
        if pe.get_section(self._section_name) is not None:
            msg = "SIDNEY construction requires a pristine executable"
            raise PatchError(msg)
        for site in self._sites:
            got = pe.read_bytes(pe.va_to_offset(site.va), len(site.orig))
            if got != site.orig:
                msg = f"SIDNEY construction precheck failed at 0x{site.va:08X}"
                raise PatchError(msg)

        origin_site = self._origin_center_site
        origin = pe.read_bytes(pe.va_to_offset(origin_site.va), len(origin_site.original))
        if origin != origin_site.original:
            msg = "SIDNEY construction precheck failed at origin width load"
            raise PatchError(msg)

    def apply(self, pe: PEFile) -> None:
        """Install private dimensions and redirect SIDNEY-local loads."""
        section = install_runtime_segment(pe, SIDNEY_CONSTRUCTION_SEGMENT)
        section_va = pe.rva_to_va(section.virtual_address)
        width_ptr_va = section_va + self._off_width_ptr
        height_ptr_va = section_va + self._off_height_ptr
        width_const_va = section_va + self._off_width_const
        height_const_va = section_va + self._off_height_const
        header = bytearray(0x20)
        header[: len(self._magic)] = self._magic
        struct.pack_into(
            "<IIII",
            header,
            self._off_width_ptr,
            width_const_va,
            height_const_va,
            AUTHORED_FRAME_WIDTH,
            AUTHORED_FRAME_HEIGHT,
        )
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=SIDNEY_CONSTRUCTION_SEGMENT.logical_name,
            size=SIDNEY_CONSTRUCTION_SEGMENT.size,
        )
        payload.place(label="private dimension table", offset=0, payload=bytes(header))
        mutations = ExecutableMutationPlan(owner=self.id)
        self._install_frame(payload, mutations, section_va=section_va)
        pe.write_bytes(section.pointer_to_raw_data, payload.build())
        for site in self._sites:
            patched = site.patched_bytes(
                width_ptr_va=width_ptr_va,
                height_ptr_va=height_ptr_va,
            )
            mutations.replace(
                label=f"SIDNEY {site.kind} load at 0x{site.va:08X}",
                va=site.va,
                expected=site.orig,
                payload=patched,
            )

        origin = self._origin_center_site
        mutations.replace(
            label="SIDNEY origin width load",
            va=origin.va,
            expected=origin.original,
            payload=self._origin_width_bytes(width_ptr_va),
        )
        mutations.apply(pe)

    def _install_frame(
        self, payload: SegmentPayloadBuilder, mutations: ExecutableMutationPlan, *, section_va: int
    ) -> None:
        state_va = section_va + SIDNEY_FRAME_STATE_OFFSET
        resize_va = section_va + SIDNEY_FRAME_RESIZE_OFFSET
        first = self.profile.site("sidney.frame.create_top")
        native_resize = decode_rel32_branch(
            site_va=first.va, instruction=first.original, opcode=BranchOpcode.CALL
        )
        if native_resize is None:
            msg = "SIDNEY frame resize site must be a direct call"
            raise PatchError(msg)
        payload.place(
            label="retain dense frame on resize",
            offset=SIDNEY_FRAME_RESIZE_OFFSET,
            payload=build_resize(
                wrapper_va=resize_va,
                state_va=state_va,
                resolve_va=self.profile.address("bitmap.resolve_resource"),
                resize_va=native_resize,
            ),
            limit=SIDNEY_FRAME_THUNKS_OFFSET,
        )
        dimensions_va = section_va + SIDNEY_FRAME_DIMENSIONS_OFFSET
        payload.place(
            label="frame logical dimensions",
            offset=SIDNEY_FRAME_DIMENSIONS_OFFSET,
            payload=build_dimensions(wrapper_va=dimensions_va, state_va=state_va),
            limit=SIDNEY_FRAME_SOURCE_OFFSET,
        )
        payload.place(
            label="frame physical source rectangle",
            offset=SIDNEY_FRAME_SOURCE_OFFSET,
            payload=build_source(
                wrapper_va=section_va + SIDNEY_FRAME_SOURCE_OFFSET,
                dimensions_va=dimensions_va,
                scratch_va=section_va + SIDNEY_FRAME_SCRATCH_OFFSET,
            ),
            limit=SIDNEY_FRAME_STATE_OFFSET,
        )
        payload.place(
            label="frame source slots", offset=SIDNEY_FRAME_STATE_OFFSET, payload=frame_state()
        )
        payload.reserve(label="frame source rectangle", offset=SIDNEY_FRAME_SCRATCH_OFFSET, size=16)
        payload.place(
            label="fingerprint source identities and logical size",
            offset=SIDNEY_FINGERPRINT_STATE_OFFSET,
            payload=bytes(FINGERPRINT_SURFACES_SIZE) + struct.pack("<II", 41, 51),
            limit=SIDNEY_FRAME_DISCOVERY_OFFSET,
        )
        payload.place(
            label="fingerprint logical dimensions",
            offset=SIDNEY_FINGERPRINT_DIMENSIONS_OFFSET,
            payload=build_fingerprint_dimensions(
                wrapper_va=section_va + SIDNEY_FINGERPRINT_DIMENSIONS_OFFSET,
                surfaces_va=section_va + SIDNEY_FINGERPRINT_STATE_OFFSET,
            ),
            limit=SIDNEY_IMAGE_DIMENSIONS_OFFSET,
        )
        payload.place(
            label="restored frame source discovery",
            offset=SIDNEY_FRAME_DISCOVERY_OFFSET,
            payload=build_discovery(
                wrapper_va=section_va + SIDNEY_FRAME_DISCOVERY_OFFSET, state_va=state_va
            ),
            limit=SIDNEY_FINGERPRINT_DIMENSIONS_OFFSET,
        )
        payload.place(
            label="illustration logical dimensions",
            offset=SIDNEY_IMAGE_DIMENSIONS_OFFSET,
            payload=build_image_dimensions(
                wrapper_va=section_va + SIDNEY_IMAGE_DIMENSIONS_OFFSET,
                surfaces_va=section_va
                + SIDNEY_PRESENTATION_SEGMENT.offset
                - SIDNEY_CONSTRUCTION_SEGMENT.offset
                + SIDNEY_PORTRAIT_STATE_OFFSET,
            ),
            limit=0xE00,
        )
        for index, side in enumerate(("top", "bottom", "left", "right")):
            offset = SIDNEY_FRAME_THUNKS_OFFSET + index * 16
            payload.place(
                label=f"{side} frame resize entry",
                offset=offset,
                payload=build_resize_thunk(
                    wrapper_va=section_va + offset, resize_va=resize_va, index=index
                ),
                limit=offset + 16,
            )
            for phase in ("create", "rebuild"):
                site = self.profile.site(f"sidney.frame.{phase}_{side}")
                mutations.branch(
                    label=f"SIDNEY {phase} {side} dense frame",
                    opcode=BranchOpcode.CALL,
                    site_va=site.va,
                    expected=site.original,
                    target_va=section_va + offset,
                )

    def postcheck(self, pe: PEFile) -> None:
        """Require this owner's segment after deterministic compilation.

        Runtime2D independently rebuilds and compares the complete segment and
        every declared redirect. Repeating the construction plan here would be
        a second implementation of the same proof.
        """
        section = pe.get_section(self._section_name)
        if section is None:
            msg = "SIDNEY construction postcheck failed: section missing"
            raise PatchError(msg)
