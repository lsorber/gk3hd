"""Keep named SIDNEY illustrations logical while retaining dense source art."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter

IMAGES = (
    (b"gab_mugshot", 67, 78),
    (b"gra_mugshot", 67, 78),
    (b"s_schat_logo", 77, 76),
    (b"poussin", 407, 271),
    (b"teniers", 464, 309),
)
SURFACES_SIZE = len(IMAGES) * 4
_DWORD_BYTES = 4
FINGERPRINT_IDS = (
    b"abe",
    b"est",
    b"he2",
    b"lar",
    b"lho",
    b"mad",
    b"mon",
    b"mos",
    b"vit",
    b"wil",  # codespell:ignore wil
)
FINGERPRINT_SURFACES_SIZE = len(FINGERPRINT_IDS) * _DWORD_BYTES


def build_fingerprint_dimensions(*, wrapper_va: int, surfaces_va: int) -> bytes:
    """Keep the ten named suspect fingerprints at 41x51 logical pixels.

    ESI is the bitmap resource and EAX its surface. Return a logical dimension
    pair with carry set only for exact fourfold replacements. Other resources
    return the unchanged surface with carry clear.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x53\x0f\xb7\x56\x08\x81\xca\x20\x20\x00\x00")
    code.raw(b"\x81\xfa\x73\x7f\x00\x00")
    code.jump_if(Condition.NOT_EQUAL, "native")
    for offset, part, mask in ((13, b"_fpr", 0x20202020), (17, b"int\0", 0x00202020)):
        code.raw(b"\x8b\x56" + bytes([offset]) + b"\x81\xca" + struct.pack("<I", mask))
        code.raw(b"\x81\xfa" + struct.pack("<I", int.from_bytes(part, "little") | mask))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x8b\x56\x0a\x81\xe2\xff\xff\xff\x00\x81\xca\x20\x20\x20\x00")
    for index, identifier in enumerate(FINGERPRINT_IDS):
        code.raw(b"\x81\xfa" + identifier + b"\x00")
        code.jump_if(Condition.EQUAL, f"id_{index}")
    code.jump("native")
    for index in range(len(FINGERPRINT_IDS)):
        code.label(f"id_{index}")
        code.raw(b"\xbb" + struct.pack("<I", surfaces_va + index * _DWORD_BYTES))
        code.jump("matched")
    code.label("matched")
    code.raw(b"\xc7\x03" + bytes(4))
    for offset, size in ((0x38, 164), (0x3C, 204)):
        code.raw(b"\x81\x78" + bytes([offset]) + struct.pack("<I", size))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x89\x03\xb8" + struct.pack("<I", surfaces_va + FINGERPRINT_SURFACES_SIZE))
    code.raw(b"\x5b\xf9\xc3")
    code.label("native")
    code.raw(b"\x5b\xf8\xc3")
    return code.build()


def emit_dimensions(
    code: X86Emitter,
    *,
    surfaces_va: int,
    images: tuple[tuple[bytes, int, int], ...] = IMAGES,
) -> None:
    """Tag exact dense images; ESI is the resource and EAX its surface."""
    for index, (basename, width, height) in enumerate(images):
        name = basename + b"\0"
        label = f"portrait_next_{index}"
        # Resource names are inline at +8. Match case-insensitively, including
        # the terminating NUL, not a prefix or a size heuristic. Ignore bytes
        # beyond that terminator: a resource's trailing storage is not identity.
        for offset in range(0, len(name), _DWORD_BYTES):
            part = name[offset : offset + _DWORD_BYTES]
            mask = int.from_bytes(bytes(0x20 if byte else 0 for byte in part), "little")
            value = int.from_bytes(part, "little") | mask
            code.raw(b"\x8b\x56" + bytes([8 + offset]))
            if len(part) < _DWORD_BYTES:
                code.raw(b"\x81\xe2" + struct.pack("<I", (1 << (8 * len(part))) - 1))
            code.raw(b"\x81\xca" + struct.pack("<I", mask))
            code.raw(b"\x81\xfa" + struct.pack("<I", value))
            code.jump_if(Condition.NOT_EQUAL, label)
        slot = surfaces_va + index * 4
        code.raw(b"\xc7\x05" + struct.pack("<I", slot) + bytes(4))
        for offset, dimension in ((0x38, width * 4), (0x3C, height * 4)):
            code.raw(b"\x81\x78" + bytes([offset]) + struct.pack("<I", dimension))
            code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\xa3" + struct.pack("<I", slot))
        code.jump("dense")
        code.label(label)


def build_image_dimensions(
    *,
    wrapper_va: int,
    surfaces_va: int,
    images: tuple[tuple[bytes, int, int], ...] = IMAGES,
) -> bytes:
    """Return logical metrics for exact dense artwork, with carry indicating a match.

    Kept in SIDNEY's construction segment so adding proven artwork does not
    exhaust the shared getter's fixed code budget. EAX remains the untouched
    surface on a miss. The logical pair follows the private source-RECT scratch.
    """
    code = X86Emitter(base_va=wrapper_va)
    logical_va = surfaces_va + len(images) * 4 + 16
    emit_dimensions(code, surfaces_va=surfaces_va, images=images)
    code.jump("native")
    code.label("dense")
    for offset, target in ((0x38, logical_va), (0x3C, logical_va + 4)):
        code.raw(b"\x8b\x50" + bytes([offset]) + b"\xc1\xfa\x02")
        code.raw(b"\x89\x15" + struct.pack("<I", target))
    code.raw(b"\xb8" + struct.pack("<I", logical_va) + b"\xf9\xc3")
    code.label("native")
    code.raw(b"\xf8\xc3")
    return code.build()


def build_source(
    *, wrapper_va: int, surfaces_va: int, scratch_va: int, fingerprint_surfaces_va: int
) -> bytes:
    """Expand clipped source coordinates only within SIDNEY's owned blit."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8d\x6c\x24\x24")  # caller's original blit stack
    code.raw(b"\x8b\x45\x04\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    for index, (_, width, height) in enumerate(IMAGES):
        label = f"source_next_{index}"
        code.raw(b"\x3b\x05" + struct.pack("<I", surfaces_va + index * 4))
        code.jump_if(Condition.NOT_EQUAL, label)
        for offset, dimension in ((0x38, width * 4), (0x3C, height * 4)):
            code.raw(b"\x81\x78" + bytes([offset]) + struct.pack("<I", dimension))
            code.jump_if(Condition.NOT_EQUAL, "done")
        code.jump("matched")
        code.label(label)
    code.raw(b"\xba" + struct.pack("<I", fingerprint_surfaces_va))
    code.raw(b"\xb9" + struct.pack("<I", len(FINGERPRINT_IDS)))
    code.label("fingerprint_next")
    code.raw(b"\x3b\x02")
    code.jump_short_if(Condition.EQUAL, "fingerprint_matched")
    code.raw(b"\x83\xc2\x04\x49")
    code.jump_short_if(Condition.NOT_EQUAL, "fingerprint_next")
    code.jump("done")
    code.label("fingerprint_matched")
    for offset, size in ((0x38, 164), (0x3C, 204)):
        code.raw(b"\x81\x78" + bytes([offset]) + struct.pack("<I", size))
        code.jump_if(Condition.NOT_EQUAL, "done")
    code.label("matched")
    code.raw(b"\x8b\x75\x0c\x85\xf6")
    code.jump_if(Condition.EQUAL, "done")  # null already means full dense image
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\xc1\xe0\x02")
        code.raw(b"\xa3" + struct.pack("<I", scratch_va + offset))
    code.raw(b"\xc7\x45\x0c" + struct.pack("<I", scratch_va))
    code.label("done")
    code.raw(b"\x61\xc3")
    return code.build()
