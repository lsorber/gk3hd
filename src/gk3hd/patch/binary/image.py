"""Focused PE32 parser and private mutable image used by gk3hd.

This is intentionally not a full PE library. It implements just enough of the
format to support surgical, reversible patches:

- read core headers + section table
- map virtual addresses to file offsets
- read and write exact in-memory byte ranges
- add verified generated runtime sections

Disk publication deliberately does not belong here. The installer serializes
the final bytes through its atomic transaction boundary.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


class PEError(Exception):
    """Report malformed images, invalid mappings, and unsafe PE mutations."""


_MINIMUM_DOS_HEADER_SIZE = 0x40
_PE32_OPTIONAL_HEADER_MAGIC = 0x10B
_MAX_SECTION_NAME_BYTES = 8


@dataclass
class Section:
    """Parsed IMAGE_SECTION_HEADER fields used by the patcher."""

    name: str
    virtual_size: int
    virtual_address: int
    size_of_raw_data: int
    pointer_to_raw_data: int
    characteristics: int
    header_offset: int

    @property
    def span(self) -> int:
        """Return the section's complete mapped extent."""
        return max(self.virtual_size, self.size_of_raw_data)


@dataclass
class ImportSymbol:
    """One decoded PE import thunk and its IAT location."""

    dll_name: str
    function_name: str | None
    ordinal: int | None
    iat_rva: int
    thunk_rva: int
    hint_name_rva: int | None


@dataclass
class ImportDescriptor:
    """One decoded IMAGE_IMPORT_DESCRIPTOR."""

    dll_name: str
    original_first_thunk: int
    first_thunk: int
    descriptor_rva: int


class PEFile:
    """Parse and mutate the focused PE32 subset required by gk3hd."""

    def __init__(self, data: bytes | bytearray) -> None:
        """Parse a private mutable copy of one complete executable image."""
        self.data = bytearray(data)
        self._parse_headers()

    @classmethod
    def from_path(cls, path: str | Path) -> PEFile:
        """Read and parse an executable from disk."""
        with Path(path).open("rb") as handle:
            return cls(handle.read())

    def _parse_headers(self) -> None:
        if len(self.data) < _MINIMUM_DOS_HEADER_SIZE:
            msg = "file too small"
            raise PEError(msg)

        # DOS header.
        e_magic = self.data[:2]
        if e_magic != b"MZ":
            msg = "missing MZ header"
            raise PEError(msg)

        # NT headers offset stored in the DOS stub at 0x3C.
        self.pe_offset = self._read_u32(0x3C)
        if self.pe_offset + 4 + 20 > len(self.data):
            msg = "invalid PE offset"
            raise PEError(msg)

        if self.data[self.pe_offset : self.pe_offset + 4] != b"PE\x00\x00":
            msg = "missing PE signature"
            raise PEError(msg)

        self.coff_offset = self.pe_offset + 4
        self.machine = self._read_u16(self.coff_offset)
        self.number_of_sections = self._read_u16(self.coff_offset + 2)
        self.size_of_optional_header = self._read_u16(self.coff_offset + 16)

        self.optional_offset = self.coff_offset + 20
        self.optional_magic = self._read_u16(self.optional_offset)
        if self.optional_magic != _PE32_OPTIONAL_HEADER_MAGIC:
            msg = f"unsupported optional header magic: 0x{self.optional_magic:04x}"
            raise PEError(msg)

        # PE32 optional header fields we care about. Offsets are from the PE spec.
        self.address_of_entry_point = self._read_u32(self.optional_offset + 16)
        self.image_base = self._read_u32(self.optional_offset + 28)
        self.section_alignment = self._read_u32(self.optional_offset + 32)
        self.file_alignment = self._read_u32(self.optional_offset + 36)
        self.size_of_image = self._read_u32(self.optional_offset + 56)
        self.size_of_headers = self._read_u32(self.optional_offset + 60)
        self.number_of_rva_and_sizes = self._read_u32(self.optional_offset + 92)

        # Section table follows immediately after the optional header.
        self.section_table_offset = self.optional_offset + self.size_of_optional_header
        self.sections: list[Section] = []
        for index in range(self.number_of_sections):
            offset = self.section_table_offset + index * 40
            if offset + 40 > len(self.data):
                msg = "section header out of bounds"
                raise PEError(msg)
            (
                raw_name,
                virtual_size,
                virtual_address,
                size_of_raw_data,
                pointer_to_raw_data,
                _pointer_to_relocations,
                _pointer_to_linenumbers,
                _number_of_relocations,
                _number_of_linenumbers,
                characteristics,
            ) = struct.unpack_from("<8sIIIIIIHHI", self.data, offset)
            name = raw_name.split(b"\0", 1)[0].decode("latin-1")
            self.sections.append(
                Section(
                    name=name,
                    virtual_size=virtual_size,
                    virtual_address=virtual_address,
                    size_of_raw_data=size_of_raw_data,
                    pointer_to_raw_data=pointer_to_raw_data,
                    characteristics=characteristics,
                    header_offset=offset,
                )
            )

    def clone(self) -> PEFile:
        """Return an independently parsed copy of the current image."""
        return PEFile(self.data)

    def to_bytes(self) -> bytes:
        """Return the complete current file image."""
        return bytes(self.data)

    def _read_u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def _read_u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    def _write_u16(self, offset: int, value: int) -> None:
        struct.pack_into("<H", self.data, offset, value)

    def _write_u32(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.data, offset, value)

    def va_to_rva(self, va: int) -> int:
        """Translate an absolute virtual address to an RVA."""
        return va - self.image_base

    def rva_to_va(self, rva: int) -> int:
        """Translate an RVA to an absolute virtual address."""
        return self.image_base + rva

    def rva_to_offset(self, rva: int) -> int:
        """Translate a mapped RVA to its on-disk file offset."""
        if rva < self.size_of_headers:
            return rva

        for section in self.sections:
            start = section.virtual_address
            end = start + section.span
            if start <= rva < end:
                return section.pointer_to_raw_data + (rva - start)

        msg = f"RVA 0x{rva:08x} is not mapped to a file offset"
        raise PEError(msg)

    def va_to_offset(self, va: int) -> int:
        """Translate an absolute virtual address to its file offset."""
        return self.rva_to_offset(self.va_to_rva(va))

    def get_section(self, name: str) -> Section | None:
        """Return the named physical PE section when present."""
        for section in self.sections:
            if section.name == name:
                return section
        return None

    def set_section_characteristics(self, name: str, characteristics: int) -> None:
        """Replace the named section's memory and content flags."""
        section = self.get_section(name)
        if section is None:
            msg = f"section not found: {name}"
            raise PEError(msg)
        section.characteristics = characteristics
        self._write_u32(section.header_offset + 36, characteristics)

    def get_data_directory(self, index: int) -> tuple[int, int]:
        """Return one optional-header data-directory RVA and size."""
        if index >= self.number_of_rva_and_sizes:
            msg = f"data directory {index} out of range"
            raise PEError(msg)
        directory_offset = self.optional_offset + 96 + index * 8
        return (self._read_u32(directory_offset), self._read_u32(directory_offset + 4))

    def read_c_string_at_offset(self, offset: int) -> str:
        """Decode a null-terminated Latin-1 string at a file offset."""
        end = offset
        data_len = len(self.data)
        while end < data_len and self.data[end] != 0:
            end += 1
        return self.data[offset:end].decode("latin-1", errors="replace")

    def read_c_string_at_rva(self, rva: int) -> str:
        """Decode a null-terminated Latin-1 string at an RVA."""
        return self.read_c_string_at_offset(self.rva_to_offset(rva))

    def iter_import_descriptors(self) -> Iterable[ImportDescriptor]:
        """Yield decoded import descriptors until the terminating entry."""
        import_rva, import_size = self.get_data_directory(1)
        if import_rva == 0 or import_size == 0:
            return

        descriptor_rva = import_rva
        max_rva = import_rva + import_size
        while descriptor_rva < max_rva:
            descriptor_offset = self.rva_to_offset(descriptor_rva)
            (
                original_first_thunk,
                _time_date_stamp,
                _forwarder_chain,
                name_rva,
                first_thunk,
            ) = struct.unpack_from("<IIIII", self.data, descriptor_offset)

            if original_first_thunk == 0 and name_rva == 0 and first_thunk == 0:
                break

            dll_name = self.read_c_string_at_rva(name_rva)
            yield ImportDescriptor(
                dll_name=dll_name,
                original_first_thunk=original_first_thunk,
                first_thunk=first_thunk,
                descriptor_rva=descriptor_rva,
            )
            descriptor_rva += 20

    def iter_import_symbols(self) -> Iterable[ImportSymbol]:
        """Yield named and ordinal imports from every descriptor."""
        for descriptor in self.iter_import_descriptors():
            thunk_rva = descriptor.original_first_thunk or descriptor.first_thunk
            index = 0
            while True:
                current_thunk_rva = thunk_rva + index * 4
                thunk_offset = self.rva_to_offset(current_thunk_rva)
                thunk_value = self._read_u32(thunk_offset)
                if thunk_value == 0:
                    break

                iat_rva = descriptor.first_thunk + index * 4
                if thunk_value & 0x80000000:
                    ordinal = thunk_value & 0xFFFF
                    yield ImportSymbol(
                        dll_name=descriptor.dll_name,
                        function_name=None,
                        ordinal=ordinal,
                        iat_rva=iat_rva,
                        thunk_rva=current_thunk_rva,
                        hint_name_rva=None,
                    )
                else:
                    hint_name_rva = thunk_value
                    name_offset = self.rva_to_offset(hint_name_rva)
                    function_name = self.read_c_string_at_offset(name_offset + 2)
                    yield ImportSymbol(
                        dll_name=descriptor.dll_name,
                        function_name=function_name,
                        ordinal=None,
                        iat_rva=iat_rva,
                        thunk_rva=current_thunk_rva,
                        hint_name_rva=hint_name_rva,
                    )
                index += 1

    def find_import_iat_rva(self, dll_name: str, function_name: str) -> int | None:
        """Return the IAT RVA for a case-insensitive DLL/function pair."""
        target_dll = dll_name.casefold()
        target_fn = function_name.casefold()
        for symbol in self.iter_import_symbols():
            if symbol.function_name is None:
                continue
            if (
                symbol.dll_name.casefold() == target_dll
                and symbol.function_name.casefold() == target_fn
            ):
                return symbol.iat_rva
        return None

    def read_bytes(self, offset: int, size: int) -> bytes:
        """Return bytes at one exact file range."""
        return bytes(self.data[offset : offset + size])

    def write_bytes(self, offset: int, payload: bytes) -> None:
        """Overwrite bytes at one exact file offset."""
        self.data[offset : offset + len(payload)] = payload

    def read_u32_va(self, va: int) -> int:
        """Read one little-endian 32-bit value at an absolute virtual address."""
        return self._read_u32(self.va_to_offset(va))

    def write_u32_va(self, va: int, value: int) -> None:
        """Write one little-endian 32-bit value at an absolute virtual address."""
        self._write_u32(self.va_to_offset(va), value)

    def align(self, value: int, alignment: int) -> int:
        """Round a value up to the requested alignment boundary."""
        if alignment <= 0:
            msg = f"invalid alignment: {alignment}"
            raise PEError(msg)
        return (value + alignment - 1) & ~(alignment - 1)

    def add_section(self, name: str, payload: bytes, characteristics: int) -> Section:
        """Append one aligned section and update the PE headers."""
        if len(name.encode("latin-1")) > _MAX_SECTION_NAME_BYTES:
            msg = "section name must be at most 8 bytes"
            raise PEError(msg)
        if self.get_section(name) is not None:
            msg = f"section already exists: {name}"
            raise PEError(msg)

        # The section table is a fixed-size array inside the headers. We can only
        # append a new section header if there is slack space before the first
        # section's raw data (i.e. still inside SizeOfHeaders).
        new_header_offset = self.section_table_offset + self.number_of_sections * 40
        first_raw_pointer = min(section.pointer_to_raw_data for section in self.sections)
        if new_header_offset + 40 > first_raw_pointer:
            msg = "no room in PE headers for a new section header"
            raise PEError(msg)

        # Compute the new section's raw data location and RVA, respecting the
        # file/section alignment requirements from the optional header.
        last_section = max(
            self.sections,
            key=lambda section: section.pointer_to_raw_data + section.size_of_raw_data,
        )
        new_raw_pointer = self.align(
            last_section.pointer_to_raw_data + last_section.size_of_raw_data,
            self.file_alignment,
        )
        new_virtual_address = self.align(
            last_section.virtual_address + last_section.span,
            self.section_alignment,
        )

        virtual_size = len(payload)
        raw_size = self.align(max(1, len(payload)), self.file_alignment)

        # Ensure the file is long enough for the new section and write the payload,
        # padding it out to the raw size.
        if len(self.data) < new_raw_pointer:
            self.data.extend(b"\x00" * (new_raw_pointer - len(self.data)))

        padded_payload = payload + b"\x00" * (raw_size - len(payload))
        self.data[new_raw_pointer : new_raw_pointer + raw_size] = padded_payload

        # Append the section header. The fields we don't care about (relocations,
        # line numbers) are written as zeros.
        name_field = name.encode("latin-1") + b"\x00" * (8 - len(name.encode("latin-1")))
        struct.pack_into(
            "<8sIIIIIIHHI",
            self.data,
            new_header_offset,
            name_field,
            virtual_size,
            new_virtual_address,
            raw_size,
            new_raw_pointer,
            0,
            0,
            0,
            0,
            characteristics,
        )

        # Update COFF NumberOfSections and optional header SizeOfImage.
        self.number_of_sections += 1
        self._write_u16(self.coff_offset + 2, self.number_of_sections)

        new_size_of_image = self.align(new_virtual_address + virtual_size, self.section_alignment)
        self.size_of_image = new_size_of_image
        self._write_u32(self.optional_offset + 56, self.size_of_image)

        # Re-parse to refresh the section list and cached header fields.
        self._parse_headers()
        created = self.get_section(name)
        if created is None:
            msg = "new section was not created"
            raise PEError(msg)
        return created
