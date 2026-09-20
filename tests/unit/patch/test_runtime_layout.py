"""Contract tests for the shared fixed-interface runtime layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest

from gk3hd.patch.binary.image import PEFile, Section
from gk3hd.patch.definitions.runtime2d.layout import (
    INVENTORY_SEGMENT,
    RUNTIME_SEGMENTS,
    SIDNEY_CONSTRUCTION_SEGMENT,
    RuntimeImage,
    RuntimeLayout,
    RuntimeLayoutError,
)

IMAGE_BASE = 0x00400000
SECTION_RVA = 0x0033A000
SECTION_RAW = 0x00000200
SECTION_HEADER = 0x000001D8


@dataclass
class FakeImage:
    """Provide the small mutable PE surface required by RuntimeImage."""

    data: bytearray = field(default_factory=bytearray)
    sections: list[Section] = field(default_factory=list)

    def get_section(self, name: str) -> Section | None:
        """Look up a synthetic physical section by name."""
        return next((section for section in self.sections if section.name == name), None)

    def add_section(self, name: str, payload: bytes, characteristics: int) -> Section:
        """Append one synthetic physical section and its payload."""
        section = Section(
            name=name,
            virtual_size=len(payload),
            virtual_address=SECTION_RVA,
            size_of_raw_data=len(payload),
            pointer_to_raw_data=SECTION_RAW,
            characteristics=characteristics,
            header_offset=SECTION_HEADER,
        )
        self.sections.append(section)
        self.write_bytes(SECTION_RAW, payload)
        return section

    def set_section_characteristics(self, name: str, characteristics: int) -> None:
        """Update the synthetic section permissions."""
        section = self.get_section(name)
        if section is None:
            raise AssertionError(name)
        section.characteristics = characteristics

    @staticmethod
    def rva_to_va(rva: int) -> int:
        """Translate a synthetic relative address to its absolute address."""
        return IMAGE_BASE + rva

    def read_bytes(self, offset: int, size: int) -> bytes:
        """Read bytes from the synthetic file image."""
        return bytes(self.data[offset : offset + size])

    def write_bytes(self, offset: int, payload: bytes) -> None:
        """Write bytes, extending the synthetic file image as needed."""
        end = offset + len(payload)
        if end > len(self.data):
            self.data.extend(b"\x00" * (end - len(self.data)))
        self.data[offset:end] = payload


def _runtime() -> tuple[FakeImage, RuntimeImage]:
    image = FakeImage()
    return image, RuntimeImage(cast("PEFile", image))


def test_segments_are_non_overlapping_and_bounded() -> None:
    """The source layout reserves one disjoint range per local builder ABI."""
    RuntimeLayout.validate_definition()
    assert RuntimeLayout.segments[0].offset == RuntimeLayout.header_size
    assert RuntimeLayout.segments[-1].end == RuntimeLayout.section_size


def test_segment_catalog_uses_semantic_current_names() -> None:
    """Logical slices describe responsibilities rather than patch lineage."""
    assert RuntimeLayout.segments is RUNTIME_SEGMENTS
    assert {segment.logical_name for segment in RUNTIME_SEGMENTS} == {
        "sidney_construction",
        "sidney_presentation",
        "inventory",
        "inventory_filter",
        "inventory_navigation",
        "ui_frames",
        "ui_filter",
        "ui_alpha",
        "gps",
        "console",
        "cursor_blend",
        "resources",
        "fingerprint",
        "fingerprint_alpha",
        "font_banks",
        "sprite_cache",
        "system",
        "system_controls",
        "load_save",
        "load_save_buttons",
        "captions",
        "binocular",
        "room_rendering",
        "timeblock",
        "zodiac",
    }


def test_logical_segments_share_one_physical_section() -> None:
    """Installing local payloads emits only the shared physical PE section."""
    image, runtime = _runtime()
    construction = RuntimeLayout.segment(SIDNEY_CONSTRUCTION_SEGMENT.logical_name)
    inventory = RuntimeLayout.segment(INVENTORY_SEGMENT.logical_name)
    assert construction is not None
    assert inventory is not None

    runtime.add_section(
        construction.logical_name,
        construction.magic,
        construction.characteristics,
    )
    runtime.add_section(inventory.logical_name, inventory.magic, inventory.characteristics)

    assert [section.name for section in image.sections] == [RuntimeLayout.section_name]
    construction_view = runtime.get_section(construction.logical_name)
    inventory_view = runtime.get_section(inventory.logical_name)
    assert construction_view is not None
    assert inventory_view is not None
    assert construction_view.virtual_address == SECTION_RVA + construction.offset
    assert inventory_view.pointer_to_raw_data == SECTION_RAW + inventory.offset
    assert image.read_bytes(SECTION_RAW, len(RuntimeLayout.magic)) == RuntimeLayout.magic


def test_symbol_table_resolves_local_raw_and_virtual_offsets() -> None:
    """Features receive typed addresses without inspecting peer payload bytes."""
    _image, runtime = _runtime()
    symbols = runtime.prepare()
    inventory = RuntimeLayout.segment(INVENTORY_SEGMENT.logical_name)
    assert inventory is not None

    assert symbols.raw(inventory.logical_name, 0x20) == SECTION_RAW + inventory.offset + 0x20
    assert (
        symbols.va(inventory.logical_name, 0x20)
        == IMAGE_BASE + SECTION_RVA + inventory.offset + 0x20
    )


def test_logical_segment_creation_rejects_undeclared_permissions() -> None:
    """The physical section cannot conceal a component's invalid local ABI."""
    image, runtime = _runtime()
    segment = INVENTORY_SEGMENT

    with pytest.raises(RuntimeLayoutError, match="incompatible characteristics"):
        runtime.add_section(segment.logical_name, segment.magic, 0x40000040)

    assert image.sections == []


def test_logical_segment_permission_update_rejects_undeclared_value() -> None:
    """A component cannot silently replace its declared logical permissions."""
    image, runtime = _runtime()
    segment = INVENTORY_SEGMENT
    runtime.add_section(segment.logical_name, segment.magic, segment.characteristics)

    with pytest.raises(RuntimeLayoutError, match="incompatible characteristics"):
        runtime.set_section_characteristics(segment.logical_name, 0x40000040)

    shared = image.get_section(RuntimeLayout.section_name)
    assert shared is not None
    assert shared.characteristics == RuntimeLayout.section_characteristics


def test_complete_layout_requires_every_declared_segment() -> None:
    """Final verification rejects a shared section with absent feature payloads."""
    _image, runtime = _runtime()
    first = RuntimeLayout.segments[0]
    runtime.add_section(first.logical_name, first.magic, first.characteristics)

    with pytest.raises(RuntimeLayoutError, match="segments are missing"):
        runtime.validate_complete()


def test_complete_layout_accepts_all_current_segments() -> None:
    """Every declared segment magic is sufficient for structural verification."""
    _image, runtime = _runtime()
    for segment in RuntimeLayout.segments:
        runtime.add_section(segment.logical_name, segment.magic, segment.characteristics)

    runtime.validate_complete()
