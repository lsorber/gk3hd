"""Recognize self-describing paired fonts without changing their text metrics.

Registration is called after ordinary 4x marker normalization. It reads pixels
only for verified padded or row-bank geometries, stages metadata on its own stack,
and publishes a complete cache entry last. Glyphs use private stack storage
before delegating to the shared density, clipping and damage-aware font blitter.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.font_sampling import (
    build_font_scope,
    build_font_selector,
    build_font_source_copy,
    build_font_source_guard,
)
from gk3hd.patch.definitions.runtime2d.layout import (
    FONT_BANK_ALPHA_SELECT_OFFSET,
    FONT_BANK_DRAW_SCOPE_OFFSET,
    FONT_BANK_NATIVE_OFFSET,
    FONT_BANK_ROW_LAYOUTS_OFFSET,
    FONT_BANK_SCOPE_OFFSET,
    FONT_BANK_SEGMENT,
    FONT_BANK_SELECT_OFFSET,
    FONT_BANK_SOURCE_COPY_OFFSET,
    FONT_BANK_SOURCE_GUARD_OFFSET,
    install_runtime_segment,
)
from gk3hd.textures.upscale.fonts.bank import (
    FONT_BANK_SIGNATURE,
    FONT_PADDED_BANK_LAYOUTS,
    FONT_ROW_BANK_LAYOUTS,
    FONT_ROW_BANK_SIGNATURE,
)

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

FONT_BANK_CACHE_CAPACITY: Final = 64
FONT_BANK_CACHE_STRIDE: Final = 128
FONT_BANK_CACHE_SIZE: Final = FONT_BANK_CACHE_CAPACITY * FONT_BANK_CACHE_STRIDE
# Preserve the record ABI: selection bits fit inside the old 96-byte flag area.
_FLAG_STORAGE_BYTES: Final = 96
_STACK_SIZE: Final = 144


def font_row_layout_table() -> bytes:
    """Encode immutable geometry separately from the bounded registration code."""
    return b"".join(
        struct.pack(
            "<5I",
            layout.source_size[0],
            layout.source_size[1] // layout.line_count,
            layout.line_count,
            layout.glyph_count,
            layout.source_size[1],
        )
        for layout in FONT_ROW_BANK_LAYOUTS.values()
    )


def font_padded_layout_table() -> bytes:
    """Encode each padded atlas's geometry and independently bounded slot count."""
    return b"".join(
        struct.pack(
            "<6I",
            *layout.source_size,
            layout.max_advance,
            layout.glyph_count,
            layout.bank_distance,
            layout.image_size[1] // 4,
        )
        for layout in FONT_PADDED_BANK_LAYOUTS.values()
    )


@dataclass(frozen=True, slots=True)
class FontBankEntryPoints:
    """Two caller-owned entry points in the bounded font-bank runtime segment."""

    registration_va: int
    draw_va: int


def install_font_bank_adapter(
    image: PEFile, *, profile: BuildProfile, target_va: int, active_handle_va: int
) -> FontBankEntryPoints:
    """Install recognition, stack-local mapping and their bounded handle cache."""
    section = install_runtime_segment(image, FONT_BANK_SEGMENT)
    base = image.rva_to_va(section.virtual_address)
    runtime = FontBankRuntime(
        cache_va=base + 0x1000,
        cursor_va=base + 0x10,
        bitmap_manager_va=profile.address("bitmap.manager"),
        get_pixel_va=profile.address("bitmap.get_pixel"),
    )
    entries = FontBankEntryPoints(base + 0x100, base + FONT_BANK_DRAW_SCOPE_OFFSET)
    payload = SegmentPayloadBuilder(
        owner="runtime2d.font_banks",
        segment=FONT_BANK_SEGMENT.logical_name,
        size=FONT_BANK_SEGMENT.size,
    )
    payload.place(label="magic", offset=0, payload=FONT_BANK_SEGMENT.magic)
    payload.reserve(label="cache cursor", offset=0x10, size=4)
    payload.reserve(label="synchronous glyph scope", offset=FONT_BANK_SCOPE_OFFSET, size=4)
    payload.place(
        label="immutable row and padded font layouts",
        offset=FONT_BANK_ROW_LAYOUTS_OFFSET,
        payload=font_row_layout_table() + font_padded_layout_table(),
        limit=FONT_BANK_SEGMENT.size,
    )
    payload.reserve(label="validated font handles", offset=0x1000, size=FONT_BANK_CACHE_SIZE)
    payload.place(
        label="font registration",
        offset=0x100,
        payload=runtime.registration(
            entries.registration_va, row_layouts_va=base + FONT_BANK_ROW_LAYOUTS_OFFSET
        ),
        limit=0x500,
    )
    payload.place(
        label="native glyph coordinates",
        offset=0x500,
        payload=runtime.glyph_record(base + 0x500),
        limit=0x800,
    )
    payload.place(
        label="stack-local font transfer",
        offset=0x800,
        payload=runtime.draw(base + 0x800, record_va=base + 0x500, target_va=target_va),
        limit=0x1000,
    )
    payload.place(
        label="nested font scope",
        offset=FONT_BANK_DRAW_SCOPE_OFFSET,
        payload=build_font_scope(
            base_va=entries.draw_va,
            target_va=base + 0x800,
            record_va=base + 0x500,
            scope_va=base + FONT_BANK_SCOPE_OFFSET,
        ),
        limit=FONT_BANK_SELECT_OFFSET,
    )
    payload.place(
        label="final glyph sampling",
        offset=FONT_BANK_SELECT_OFFSET,
        payload=build_font_selector(
            base_va=base + FONT_BANK_SELECT_OFFSET,
            native_va=base + FONT_BANK_NATIVE_OFFSET,
            scope_va=base + FONT_BANK_SCOPE_OFFSET,
            manager_va=profile.address("bitmap.manager"),
        ),
        limit=FONT_BANK_NATIVE_OFFSET,
    )
    native = X86Emitter(base_va=base + FONT_BANK_NATIVE_OFFSET)
    native.raw(profile.site("runtime2d.final_blt_entry").original)
    native.jump_absolute(profile.address("runtime2d.final_blt_continue"))
    payload.place(
        label="native blit continuation", offset=FONT_BANK_NATIVE_OFFSET, payload=native.build()
    )
    payload.place(
        label="scoped font source identity",
        offset=FONT_BANK_SOURCE_GUARD_OFFSET,
        payload=build_font_source_guard(
            base_va=base + FONT_BANK_SOURCE_GUARD_OFFSET,
            active_handle_va=active_handle_va,
            manager_va=profile.address("bitmap.manager"),
        ),
        limit=FONT_BANK_SOURCE_GUARD_OFFSET + 0x100,
    )
    payload.place(
        label="pre-composition font bank selection",
        offset=FONT_BANK_ALPHA_SELECT_OFFSET,
        payload=build_font_selector(
            base_va=base + FONT_BANK_ALPHA_SELECT_OFFSET,
            native_va=base + FONT_BANK_SOURCE_COPY_OFFSET,
            scope_va=base + FONT_BANK_SCOPE_OFFSET,
            manager_va=profile.address("bitmap.manager"),
        ),
        limit=FONT_BANK_SOURCE_COPY_OFFSET,
    )
    payload.place(
        label="selected font source rectangle",
        offset=FONT_BANK_SOURCE_COPY_OFFSET,
        payload=build_font_source_copy(base_va=base + FONT_BANK_SOURCE_COPY_OFFSET),
        limit=FONT_BANK_SOURCE_COPY_OFFSET + 0x100,
    )
    image.write_bytes(section.pointer_to_raw_data, payload.build())
    return entries


@dataclass(frozen=True, slots=True)
class FontBankRuntime:
    """Explicit code/data addresses; no imported process state or fixed EXE addresses."""

    cache_va: int
    cursor_va: int
    bitmap_manager_va: int
    get_pixel_va: int

    def registration(self, wrapper_va: int, *, row_layouts_va: int) -> bytes:
        """Preserve registers/flags except EAX = corrected line height on success.

        ESI is the current native Font. Cache records contain handle, original
        width, original row height, maximum advance, then packed selection bits.
        Slots are little-endian bits in the reserved 96-byte flag area, leaving
        all trailing metadata and the fixed cache/stack extents unchanged.
        Offset 116 stores the padded slot count or the complete bank's row count.
        Complete row banks use that advance field for their glyph count and
        leave selection flags clear; trailing fields identify stride and layout.
        Clearing a reused handle before recognition prevents a plain replacement
        from inheriting an old bank. The bounded ring evicts entries, never grows.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(bytes.fromhex("9c 60 81ec") + struct.pack("<I", _STACK_SIZE))
        code.raw(bytes.fromhex("89e3 0fb76e04 85ed"))  # EBX locals, EBP handle.
        code.jump_if(Condition.EQUAL, "done")
        # Clear all flag capacity, including unused tail slots on a reused handle.
        code.raw(bytes.fromhex("8d7b18 31c0 b9") + struct.pack("<I", _FLAG_STORAGE_BYTES // 4))
        code.raw(bytes.fromhex("fc f3ab"))
        code.raw(bytes.fromhex("c7437800000000 bf") + struct.pack("<I", self.cache_va))
        code.raw(b"\xb9" + struct.pack("<I", FONT_BANK_CACHE_CAPACITY))
        code.label("invalidate")
        code.raw(bytes.fromhex("392f"))
        code.jump_if(Condition.NOT_EQUAL, "next_entry")
        code.raw(bytes.fromhex("c70700000000 897b78"))
        code.label("next_entry")
        code.raw(bytes.fromhex("81c7") + struct.pack("<I", FONT_BANK_CACHE_STRIDE))
        code.raw(b"\x49")
        code.jump_if(Condition.NOT_EQUAL, "invalidate")
        # Extra staged fields: metadata X, storage kind, row count, full height.
        for offset, value in ((128, 0), (132, 0), (136, 1)):
            code.raw(bytes.fromhex("c783") + struct.pack("<II", offset, value))
        code.raw(bytes.fromhex("837e4c01"))
        code.jump_if(Condition.NOT_EQUAL, "row_bank")
        code.raw(b"\xbf" + struct.pack("<I", row_layouts_va + len(font_row_layout_table())))
        code.raw(b"\xb9" + struct.pack("<I", len(FONT_PADDED_BANK_LAYOUTS)))
        code.label("padded_layout")
        code.raw(bytes.fromhex("8b07 48 394634"))
        code.jump_if(Condition.NOT_EQUAL, "next_padded_layout")
        code.raw(bytes.fromhex("8b4714 48 394638"))
        code.jump_if(Condition.NOT_EQUAL, "next_padded_layout")
        for source, destination in ((0, 8), (4, 12), (8, 16), (16, 124)):
            code.raw(bytes((0x8B, 0x47, source, 0x89, 0x43, destination)))
        for source, destination in ((12, 136), (4, 140)):
            code.raw(bytes((0x8B, 0x47, source, 0x89, 0x83)) + struct.pack("<I", destination))
        code.jump("anchors")
        code.label("next_padded_layout")
        code.raw(bytes.fromhex("83c718 49"))
        code.jump_if(Condition.NOT_EQUAL, "padded_layout")
        # A single-row font can also use complete side-by-side atlas banks.
        code.jump("row_bank")

        code.label("row_bank")
        # Compact immutable records share one checked staging path. Repeating
        # eight immediate stores per atlas exhausts the registration code region.
        code.raw(b"\xbf" + struct.pack("<I", row_layouts_va))
        code.raw(b"\xb9" + struct.pack("<I", len(FONT_ROW_BANK_LAYOUTS)))
        code.label("row_layout")
        code.raw(bytes.fromhex("8b07 8d4400ff 394634"))  # width * 2 - 1
        code.jump_if(Condition.NOT_EQUAL, "next_row_layout")
        code.raw(bytes.fromhex("8b4704 48 394638"))  # row height - 1
        code.jump_if(Condition.NOT_EQUAL, "next_row_layout")
        code.raw(bytes.fromhex("8b4708 39464c"))
        code.jump_if(Condition.NOT_EQUAL, "next_row_layout")
        for source, destination in ((0, 8), (4, 12), (12, 16)):
            code.raw(bytes((0x8B, 0x47, source, 0x89, 0x43, destination)))
        code.raw(bytes.fromhex("8b07 c1e002 89437c 898380000000"))
        code.raw(bytes.fromhex("c7838400000001000000"))
        for source, destination in ((8, 136), (16, 140)):
            code.raw(bytes((0x8B, 0x47, source, 0x89, 0x83)) + struct.pack("<I", destination))
        code.jump("anchors")
        code.label("next_row_layout")
        code.raw(bytes.fromhex("83c714 49"))
        code.jump_if(Condition.NOT_EQUAL, "row_layout")
        code.jump("done")

        code.label("anchors")
        for x, offset in ((1, 0), (2, 4)):
            code.raw(bytes.fromhex("8b8380000000 83c0") + bytes([x]) + bytes.fromhex("6a01 50"))
            self._pixel_call(code)
            code.raw(bytes((0x89, 0x43, offset)))
        code.raw(bytes.fromhex("3b03"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(bytes.fromhex("31ff c7431400000000"))
        code.label("pixel")
        code.raw(bytes.fromhex("8d4701 038380000000 6a02 50"))
        self._pixel_call(code)
        code.raw(bytes.fromhex("3b03"))
        code.jump_if(Condition.EQUAL, "zero")
        code.raw(bytes.fromhex("3b4304"))
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(bytes.fromhex("b801000000"))
        code.jump("bit")
        code.label("zero")
        code.raw(bytes.fromhex("31c0"))
        code.label("bit")
        code.raw(bytes.fromhex("83ff40"))
        code.jump_if(Condition.ABOVE_OR_EQUAL, "flag")
        code.raw(bytes.fromhex("d16314 094314"))  # Shift in signature, MSB first.
        for end, word, row_word in (
            (31, FONT_BANK_SIGNATURE[:4], FONT_ROW_BANK_SIGNATURE[:4]),
            (63, FONT_BANK_SIGNATURE[4:], FONT_ROW_BANK_SIGNATURE[4:]),
        ):
            label = f"signature_{end}"
            code.raw(bytes((0x83, 0xFF, end)))
            code.jump_if(Condition.NOT_EQUAL, label)
            code.raw(b"\xb8" + struct.pack("<I", int.from_bytes(word, "big")))
            code.raw(bytes.fromhex("83bb8400000000"))
            code.jump_if(Condition.EQUAL, f"{label}_compare")
            code.raw(b"\xb8" + struct.pack("<I", int.from_bytes(row_word, "big")))
            code.label(f"{label}_compare")
            code.raw(bytes.fromhex("394314"))
            code.jump_if(Condition.NOT_EQUAL, "done")
            code.label(label)
        code.jump("next_pixel")
        code.label("flag")
        code.raw(bytes.fromhex("85c0"))
        code.jump_if(Condition.EQUAL, "next_pixel")
        code.raw(bytes.fromhex("8d4fc0 0fab4b18"))  # BTS locals[24], index - 64.
        code.label("next_pixel")
        code.raw(bytes.fromhex("47 83ff40"))
        code.jump_if(Condition.NOT_EQUAL, "more_pixels")
        code.raw(bytes.fromhex("83bb8400000000"))
        code.jump_if(Condition.NOT_EQUAL, "ready")
        code.label("more_pixels")
        code.raw(bytes.fromhex("8b8388000000 83c040 39c7"))  # signature + this layout's slots
        code.jump_if(Condition.BELOW, "pixel")

        code.label("ready")
        code.raw(bytes.fromhex("8b7b78 85ff"))
        code.jump_if(Condition.NOT_EQUAL, "publish")
        code.raw(b"\xa1" + struct.pack("<I", self.cursor_va))
        code.raw(bytes.fromhex("83e03f 8d4801 83e13f 890d") + struct.pack("<I", self.cursor_va))
        code.raw(bytes.fromhex("c1e007 05") + struct.pack("<I", self.cache_va))
        code.raw(bytes.fromhex("89c7"))
        code.label("publish")
        code.raw(bytes.fromhex("c70700000000"))
        for source, destination in ((8, 4), (12, 8), (16, 12), (124, 112)):
            code.raw(bytes((0x8B, 0x43, source, 0x89, 0x47, destination)))
        for source, destination in ((136, 116), (140, 120), (132, 124)):
            code.raw(
                bytes.fromhex("8b83") + struct.pack("<I", source) + bytes((0x89, 0x47, destination))
            )
        code.raw(bytes.fromhex("8b4308 48 894634"))
        code.raw(bytes.fromhex("8b430c 48 894638 8983") + struct.pack("<I", _STACK_SIZE + 28))
        # All native calls are complete. Copy staged flags, then publish handle.
        code.raw(bytes.fromhex("89fa 83c710 8d7318 b9") + struct.pack("<I", _FLAG_STORAGE_BYTES))
        code.raw(bytes.fromhex("fc 83bb8400000000"))
        code.jump_if(Condition.NOT_EQUAL, "clear_flags")
        code.raw(bytes.fromhex("f3a4"))
        code.jump("handle")
        code.label("clear_flags")
        code.raw(bytes.fromhex("31c0 f3aa"))
        code.label("handle")
        code.raw(bytes.fromhex("892a"))
        code.label("done")
        code.raw(bytes.fromhex("81c4") + struct.pack("<I", _STACK_SIZE))
        code.raw(bytes.fromhex("61 9d c3"))
        return code.build()

    def _pixel_call(self, code: X86Emitter) -> None:
        """Finish a native GetPixel(handle, x, y) call after pushing y and x."""
        code.raw(bytes.fromhex("55 8b0d") + struct.pack("<I", self.bitmap_manager_va))
        code.call_absolute(self.get_pixel_va)

    def glyph_record(self, wrapper_va: int) -> bytes:
        """Resolve a selected glyph using native boundaries, not generated tables.

        Inputs are Font in EDX, slot in EAX, five-DWORD output in ECX. Success
        returns EAX=1 and writes original left, X/Y translation, advance, cache pointer.
        Failure returns zero without touching the output. Other registers and
        flags are preserved; no resource lookup occurs during glyph submission.
        """
        code = X86Emitter(base_va=wrapper_va)
        code.raw(bytes.fromhex("9c60 83ec14 89d6 89c3 89cd c744243000000000"))
        code.raw(bytes.fromhex("81fb00010000"))
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        code.raw(bytes.fromhex("0fb74604 85c0"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(b"\xbf" + struct.pack("<I", self.cache_va))
        code.raw(b"\xb9" + struct.pack("<I", FONT_BANK_CACHE_CAPACITY))
        code.label("entry")
        code.raw(bytes.fromhex("3907"))
        code.jump_if(Condition.EQUAL, "found")
        code.raw(bytes.fromhex("81c7") + struct.pack("<I", FONT_BANK_CACHE_STRIDE))
        code.raw(b"\x49")
        code.jump_if(Condition.NOT_EQUAL, "entry")
        code.jump("done")
        code.label("found")
        code.raw(bytes.fromhex("837f7c01"))
        code.jump_if(Condition.EQUAL, "row_record")
        code.raw(bytes.fromhex("837f7c00"))
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(bytes.fromhex("3b5f74"))  # Reject slots beyond this padded layout's count.
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        code.raw(bytes.fromhex("0fa35f10"))  # BT cache[16], slot.
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        for font_offset, cache_offset in ((0x34, 4), (0x38, 8)):
            code.raw(bytes((0x8B, 0x46, font_offset, 0x40, 0x3B, 0x47, cache_offset)))
            code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(bytes.fromhex("0fb7445e50 0fb7545e52 81faffff0000"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(bytes.fromhex("39c2"))
        code.jump_if(Condition.BELOW_OR_EQUAL, "done")
        code.raw(bytes.fromhex("890424 29c2 3b570c"))
        code.jump_if(Condition.ABOVE, "done")
        code.raw(bytes.fromhex("8954240c 8b4704 48 8b4f0c 83c102 31d2 f7f1 85c0"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(bytes.fromhex("89c1 89d8 31d2 f7f1"))  # EAX bank row, EDX column.
        code.raw(bytes.fromhex("8b4f08 41 0fafc1 034708 89442408"))
        code.raw(bytes.fromhex("8b470c 83c002 0fafc2 83c002 2b0424 89442404"))
        code.raw(bytes.fromhex("897c2410 c744243001000000"))
        code.jump("copy_record")
        code.label("row_record")
        code.raw(bytes.fromhex("3b5f0c"))
        code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
        for font_offset, cache_offset in ((0x34, 4), (0x38, 8)):
            code.raw(bytes((0x8B, 0x46, font_offset, 0x40, 0x3B, 0x47, cache_offset)))
            code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(bytes.fromhex("8b464c 3b4774"))
        code.jump_if(Condition.NOT_EQUAL, "done")
        code.raw(bytes.fromhex("31c0 890424 89442404 89442408 8944240c 897c2410 c744243001000000"))
        code.label("copy_record")
        code.raw(bytes.fromhex("89ef 89e6 b905000000 fc f3a5"))
        code.label("done")
        code.raw(bytes.fromhex("83c414 619d c3"))
        return code.build()

    def draw(self, wrapper_va: int, *, record_va: int, target_va: int) -> bytes:
        """Map clipped glyphs with call-local geometry, then use the shared blitter.

        This replaces the native five-argument glyph call. EDX is Font, EBX its
        drawable, and caller EBP-14h the resolved slot. Keep original advances
        and caller rectangles; expand intact edges only inside the drawable's
        existing clipping region. The delegated wrapper still owns density,
        screen transforms, damage and alpha behavior.
        """
        code = X86Emitter(base_va=wrapper_va)
        # Locals: point[0:8], source rect[8:24], derived record[24:44].
        # PUSHAD registers follow at44; original return address is at80.
        code.raw(bytes.fromhex("9c60 83ec2c 8b45ec 8d4c2418"))
        code.call_absolute(record_va)
        code.raw(bytes.fromhex("85c0"))
        code.jump_if(Condition.EQUAL, "native")
        # Full-atlas row banks keep the ordinary glyph RECT and clipping;
        # only the final, scoped sample selector changes their artwork half.
        code.raw(bytes.fromhex("8b442428 83787c01"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8d7c2418 8b74245c 8b06 890424 8b4604 89442404"))
        code.raw(bytes.fromhex("8b742460 8b0f 390e"))
        code.jump_if(Condition.LESS, "native")
        code.raw(bytes.fromhex("034f0c 394e08"))
        code.jump_if(Condition.GREATER, "native")
        code.raw(bytes.fromhex("837e0401"))
        code.jump_if(Condition.LESS, "native")
        code.raw(bytes.fromhex("8b4238 40 39460c"))
        code.jump_if(Condition.GREATER, "native")
        code.raw(bytes.fromhex("8b06 3b4608"))
        code.jump_if(Condition.GREATER_OR_EQUAL, "native")
        code.raw(bytes.fromhex("8b4604 3b460c"))
        code.jump_if(Condition.GREATER_OR_EQUAL, "native")
        for offset in (0, 4, 8, 12):
            code.raw(bytes((0x8B, 0x46, offset)))
            code.raw(bytes((0x03, 0x47, 4 if offset in (0, 8) else 8)))
            code.raw(bytes((0x89, 0x44, 0x24, offset + 8)))

        code.raw(bytes.fromhex("8b5c243c 8b07 3906"))
        code.jump_if(Condition.NOT_EQUAL, "right")
        code.raw(bytes.fromhex("8b0424 3b4328"))
        code.jump_if(Condition.LESS_OR_EQUAL, "right")
        code.raw(bytes.fromhex("ff0c24 ff4c2408"))
        code.label("right")
        code.raw(bytes.fromhex("8b07 03470c 394608"))
        code.jump_if(Condition.NOT_EQUAL, "top")
        code.raw(bytes.fromhex("8b0424 03442410 2b442408 3b4330"))
        code.jump_if(Condition.GREATER_OR_EQUAL, "top")
        code.raw(bytes.fromhex("ff442410"))
        code.label("top")
        code.raw(bytes.fromhex("837e0401"))
        code.jump_if(Condition.NOT_EQUAL, "bottom")
        code.raw(bytes.fromhex("8b442404 3b432c"))
        code.jump_if(Condition.LESS_OR_EQUAL, "bottom")
        code.raw(bytes.fromhex("ff4c2404 ff4c240c"))
        code.label("bottom")
        code.raw(bytes.fromhex("8b4238 40 39460c"))
        code.jump_if(Condition.NOT_EQUAL, "submit")
        code.raw(bytes.fromhex("8b442404 03442414 2b44240c 3b4334"))
        code.jump_if(Condition.GREATER_OR_EQUAL, "submit")
        code.raw(bytes.fromhex("ff442414"))
        code.label("submit")
        code.raw(bytes.fromhex("8d1424 8d442408 ff742464 50 52 ff742464 ff742464 8b4c2458"))
        code.call_absolute(target_va)
        code.raw(bytes.fromhex("89442448 83c42c 619d c21400"))
        code.label("native")
        code.raw(bytes.fromhex("83c42c 619d"))
        code.jump_absolute(target_va)
        return code.build()
