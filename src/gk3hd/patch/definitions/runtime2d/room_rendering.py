"""Typed room-rendering boundary consumed by fixed-interface features."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.definitions.runtime2d.layout import ROOM_RENDERING_SEGMENT, install_runtime_segment
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols


@dataclass(frozen=True, slots=True)
class RoomRenderingABI:
    """The three live facts shared with fixed-interface features."""

    width_va: int
    height_va: int
    fixed_canvas_owner_va: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class DirectRoomRenderingCompiler:
    """Publish the identity room/display ABI for a modern DirectDraw backend.

    Outcome:
        Fixed-interface input and overlay code address GK3's native-resolution
        room target directly, without a private intermediate surface.

    Before:
        The UI runtime imported dimensions, projection helpers, and retention
        state from a 2,500-line private Direct3D stage which capped rendering at
        1920 pixels and copied every completed frame to the display.

    After:
        Room dimensions are the live physical dimensions, the target is GK3's
        current back page, and fixed-interface code imports no private-stage
        projection or presentation state.
        The shared boundary contains only live dimensions and the exact owner
        of a retained fixed canvas; no frame-copy or staging state exists.

    Strategy:
        Export existing GK3 dimension globals and one ownership cell through a
        bounded runtime segment. The modern backend publishes the native target
        itself, so projection adapters and presentation tokens are unnecessary.

    Boundaries:
        DirectDraw implementation and presentation timing belong to the
        independently selected graphics backend; UI geometry remains with its
        feature compilers.
    """

    symbols: RuntimeSymbols
    profile: BuildProfile

    _layout_version: ClassVar[int] = 2
    _off_layout_version: ClassVar[int] = 0x08
    _off_fixed_canvas_owner: ClassVar[int] = 0x0C

    def abi(self) -> RoomRenderingABI:
        """Return the direct identity boundary before or after installation."""
        base = self.symbols.va(ROOM_RENDERING_SEGMENT.logical_name)
        dimensions_va = self.profile.address("display.dimensions")
        return RoomRenderingABI(
            width_va=dimensions_va,
            height_va=dimensions_va + 4,
            fixed_canvas_owner_va=base + self._off_fixed_canvas_owner,
        )

    def precheck(self, image: PEFile) -> None:
        """Require an empty declared runtime segment."""
        if image.get_section(ROOM_RENDERING_SEGMENT.logical_name) is not None:
            message = "direct room-rendering ABI is already installed"
            raise PatchError(message)

    def apply(self, image: PEFile) -> None:
        """Install the direct ABI record."""
        section = install_runtime_segment(image, ROOM_RENDERING_SEGMENT)
        payload = bytearray(ROOM_RENDERING_SEGMENT.size)
        payload[: len(ROOM_RENDERING_SEGMENT.magic)] = ROOM_RENDERING_SEGMENT.magic
        struct.pack_into("<I", payload, self._off_layout_version, self._layout_version)
        image.write_bytes(section.pointer_to_raw_data, bytes(payload))

    def postcheck(self, image: PEFile) -> None:
        """Verify the complete deterministic identity ABI."""
        section = image.get_section(ROOM_RENDERING_SEGMENT.logical_name)
        if section is None:
            message = "direct room-rendering ABI is missing"
            raise PatchError(message)
        if image.read_bytes(section.pointer_to_raw_data, len(ROOM_RENDERING_SEGMENT.magic)) != (
            ROOM_RENDERING_SEGMENT.magic
        ):
            message = "direct room-rendering ABI has invalid magic"
            raise PatchError(message)
        if (
            image.read_u32_va(image.rva_to_va(section.virtual_address) + self._off_layout_version)
            != self._layout_version
        ):
            message = "direct room-rendering ABI has an incompatible version"
            raise PatchError(message)
