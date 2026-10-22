"""Native movie selection with bounded, executable-relative replacement paths."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.videos.catalog import MAX_MOVIE_ASSET_NAME, MOVIE_ASSET_PREFIX, MOVIE_INSTALL_PATH

MOVIE_OVERRIDE_PREFIX = MOVIE_INSTALL_PATH.replace("/", "\\").encode("ascii") + b"\\"
MOVIE_FILENAME_PREFIX = MOVIE_ASSET_PREFIX.encode("ascii")
MOVIE_PATH_PREFIX = MOVIE_OVERRIDE_PREFIX + MOVIE_FILENAME_PREFIX
_MAXIMUM_ASSET_STEM = MAX_MOVIE_ASSET_NAME - len(b".AVI")
_PATH_CAPACITY = 300  # Native AVI resolver's own buffer size.


def build_palette_key(
    *, wrapper_va: int, player_va: int, native_vtable: int, native_va: int, resume_va: int
) -> bytes:
    """Match original RLE palette green when the private decoder supplies RGB.

    GK3's diagram palettes store five-bit bin centers (3, 251, 3). Pure green
    and that palette color collapse to the same RGB555 key, but not RGB565.
    Match the real palette color for original AVI instances only. This changes
    neither the files nor decoded pixels, and leaves opaque movies untouched.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(bytes.fromhex("9c 833d") + struct.pack("<I", player_va) + b"\0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("813e") + struct.pack("<I", native_vtable))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("89d0 25ffffff00 3d00ff0000"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("81e2000000ff 81ca03fb0300"))
    code.label("native")
    code.raw(bytes.fromhex("9d 52"))
    code.call_absolute(native_va)
    code.jump_absolute(resume_va)
    return code.build()


@dataclass(frozen=True, slots=True)
class MovieOverrideImports:
    """Existing kernel32 IAT slots, resolved from the validated executable."""

    module_filename: int
    create_file: int
    close_handle: int


@dataclass(frozen=True, slots=True)
class MovieBlitABI:
    """Exact replacement identity, presentation scope, and native blit targets."""

    replacement_vtable: int
    sidney_depth: int
    dimensions: int
    native: int
    stretch: int


def build_embedded_blt(*, wrapper_va: int, abi: MovieBlitABI) -> bytes:
    """Fit replacement movies drawn by SIDNEY's logical-canvas UI controls.

    Native AVI::Draw reaches the final coordinate mapper only for same-size
    copies. A 4x source takes its direct stretch path instead. Adapt the caller's
    destination into a call-local RECT, then force native stretch, even when
    source and destination happen to match at a 4x display scale. Never map
    fullscreen movies, original instances or private offscreen surfaces here.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(bytes.fromhex("55 8bec 83ec10 53 56 57 89cb"))
    # This exact call site retains AVI::this + 0x40 in ESI.
    code.raw(bytes.fromhex("817ec0") + struct.pack("<I", abi.replacement_vtable))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("833d") + struct.pack("<I", abi.sidney_depth) + b"\x00")
    code.jump_if(Condition.EQUAL, "native")
    for offset, address in ((0x38, abi.dimensions), (0x3C, abi.dimensions + 4)):
        code.raw(b"\xa1" + struct.pack("<I", address) + bytes.fromhex("3943") + bytes([offset]))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x8b\x3d" + struct.pack("<I", abi.dimensions + 4))
    code.raw(bytes.fromhex("89f8 c1e002 99 b903000000 f7f9 8b35"))
    code.raw(struct.pack("<I", abi.dimensions))
    code.raw(bytes.fromhex("29c6 d1fe 8b4d0c"))
    for offset in (0, 4, 8, 12):
        code.raw(bytes.fromhex("8b41") + bytes([offset]))
        code.raw(bytes.fromhex("0fafc7 99 51 b900030000 f7f9 59"))
        if offset % 8 == 0:
            code.raw(bytes.fromhex("01f0"))
        code.raw(bytes.fromhex("8945") + bytes([0xF0 + offset]))
    code.raw(bytes.fromhex("ff7510 8d45f0 50 ff7508 89d9"))
    code.call_absolute(abi.stretch)
    code.jump("done")
    code.label("native")
    code.raw(bytes.fromhex("ff7510 ff750c ff7508 89d9"))
    code.call_absolute(abi.native)
    code.label("done")
    code.raw(bytes.fromhex("5f5e5b 8be5 5d c20c00"))
    return code.build()


def build_factory(
    *,
    wrapper_va: int,
    trampoline_va: int,
    vtable_va: int,
    prefix_va: int,
    imports: MovieOverrideImports,
) -> bytes:
    """Try one installed AVI, falling back to the original name on failure.

    Use a per-call stack buffer and preserve the cdecl factory's nonvolatile
    registers. Never replace an original file, change cwd, depend on the
    launcher's cwd, or recurse into this hook for an explicit AVI extension.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(bytes.fromhex("55 8bec 53 56 57 81ec30010000 8b5d08 85db"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("89de 89da b92c010000"))
    code.label("basename")
    code.raw(bytes.fromhex("8a02 84c0"))
    code.jump_if(Condition.EQUAL, "module")
    for value in (0x2F, 0x5C):
        code.raw(bytes((0x3C, value)))
        code.jump_if(Condition.EQUAL, "separator")
    code.jump("name_next")
    code.label("separator")
    code.raw(bytes.fromhex("8d7201"))
    code.label("name_next")
    code.raw(bytes.fromhex("42 49"))
    code.jump_if(Condition.NOT_EQUAL, "basename")
    code.jump("native")
    code.label("module")
    code.raw(bytes.fromhex("803e00"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("8dbdc4feffff"))
    code.push_imm32(_PATH_CAPACITY)
    code.raw(bytes.fromhex("57 6a00 ff15") + struct.pack("<I", imports.module_filename))
    code.raw(bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x3d" + struct.pack("<I", _PATH_CAPACITY))
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(bytes.fromhex("89f9 89fa"))  # ECX scan, EDX last directory separator.
    code.label("directory")
    code.raw(bytes.fromhex("8a01 84c0"))
    code.jump_if(Condition.EQUAL, "prefix")
    code.raw(bytes.fromhex("3c5c"))
    code.jump_if(Condition.NOT_EQUAL, "directory_next")
    code.raw(bytes.fromhex("8d5101"))
    code.label("directory_next")
    code.raw(bytes.fromhex("41"))
    code.jump("directory")
    code.label("prefix")
    code.raw(bytes.fromhex("89d7 8d45c4 39c7"))  # Keep prefix and suffix inside 300 bytes.
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(b"\x56\xbe" + struct.pack("<I", prefix_va))
    code.raw(b"\xb9" + struct.pack("<I", len(MOVIE_PATH_PREFIX)))
    code.raw(bytes.fromhex("fc f3a4 5e 897df0 31d2"))
    code.label("copy_name")
    code.raw(bytes.fromhex("8a06 84c0"))
    code.jump_if(Condition.EQUAL, "extension")
    code.raw(bytes.fromhex("3c3a"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("3c61"))
    code.jump_if(Condition.BELOW, "character")
    code.raw(bytes.fromhex("3c7a"))
    code.jump_if(Condition.ABOVE, "character")
    code.raw(bytes.fromhex("2c20"))
    code.label("character")
    code.raw(bytes.fromhex("3c2e"))
    code.jump_if(Condition.NOT_EQUAL, "copy_byte")
    code.raw(bytes.fromhex("89fa"))
    code.label("copy_byte")
    code.raw(bytes.fromhex("8807 47 46 8d45eb 39c7"))
    code.jump_if(Condition.BELOW, "copy_name")
    code.jump("native")
    code.label("extension")
    code.raw(bytes.fromhex("85d2"))
    code.jump_if(Condition.EQUAL, "suffix")
    code.raw(bytes.fromhex("89d7"))
    code.label("suffix")
    code.raw(bytes.fromhex("3b7df0"))
    code.jump_if(Condition.BELOW_OR_EQUAL, "native")
    code.raw(bytes.fromhex("8b75f0 83ee") + bytes((len(MOVIE_FILENAME_PREFIX),)))
    code.raw(bytes.fromhex("89f8 29f0 83f8"))
    code.raw(bytes((_MAXIMUM_ASSET_STEM,)))
    code.jump_if(Condition.ABOVE, "native")
    code.raw(bytes.fromhex("c7072e415649 c6470400 8dbdc4feffff"))
    # CreateFileA: read-only, share read/write/delete, OPEN_EXISTING, normal.
    code.raw(bytes.fromhex("6a00 6880000000 6a03 6a00 6a07 6800000080 57 ff15"))
    code.raw(struct.pack("<I", imports.create_file))
    code.raw(bytes.fromhex("83f8ff"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x50\xff\x15" + struct.pack("<I", imports.close_handle))
    code.raw(b"\x56")  # Short asset name, expanded by our executable-relative resolver.
    code.call_absolute(trampoline_va)
    code.raw(bytes.fromhex("83c404 85c0"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xc7\x00" + struct.pack("<I", vtable_va))
    code.jump("done")
    code.label("native")
    code.raw(b"\x53")
    code.call_absolute(trampoline_va)
    code.raw(bytes.fromhex("83c404"))
    code.label("done")
    code.raw(bytes.fromhex("8d65f4 5f 5e 5b 5d c3"))
    return code.build()


def build_embedded_size(*, wrapper_va: int, dimensions_va: int) -> bytes:
    """Scale only MovieLayer's embedded extent, not SIDNEY's logical asset sizes.

    The displaced virtual GetSize consumes one pointer argument. Duplicate it
    for the real call, preserve its result/registers, then consume the original
    pointer on return. Replay the caller's LEA against its restored EBP.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(bytes.fromhex("ff742404 ff504c 9c60 8b742428 85f6"))
    code.jump_if(Condition.EQUAL, "done")
    code.raw(bytes.fromhex("8b1e 8b6e04"))
    code.raw(b"\x8b\x0d" + struct.pack("<I", dimensions_va))
    code.raw(b"\x8b\x15" + struct.pack("<I", dimensions_va + 4))
    for register in ("85db", "85ed", "85c9", "85d2"):
        code.raw(bytes.fromhex(register))
        code.jump_if(Condition.LESS_OR_EQUAL, "done")
    for register in (b"\x81\xfb", b"\x81\xfd", b"\x81\xf9", b"\x81\xfa"):
        code.raw(register + struct.pack("<I", 32768))
        code.jump_if(Condition.ABOVE, "done")
    code.raw(bytes.fromhex("81f900040000"))
    code.jump_if(Condition.ABOVE, "scale")
    code.raw(bytes.fromhex("81fa00030000"))
    code.jump_if(Condition.BELOW_OR_EQUAL, "done")
    code.label("scale")
    code.raw(bytes.fromhex("69c100030000 69fa00040000 39f8"))
    code.jump_if(Condition.BELOW_OR_EQUAL, "width")
    code.raw(bytes.fromhex("89d7 b900030000"))
    code.jump("extent")
    code.label("width")
    code.raw(bytes.fromhex("89cf b900040000"))
    code.label("extent")
    for source, store in (("89d8", "8906"), ("89e8", "894604")):
        code.raw(bytes.fromhex(source + " 0fafc7 89ca d1ea 01d0 31d2 f7f1 " + store))
    code.label("done")
    code.raw(bytes.fromhex("619d 8d45f4 c20400"))
    return code.build()


def build_logical_size(*, wrapper_va: int, native_va: int) -> bytes:
    """Report the original logical size only for installed 4x AVI instances."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(bytes.fromhex("55 8bec 56 8b7508 56"))
    code.call_absolute(native_va)
    code.raw(bytes.fromhex("c12e02 c16e0402 5e 5d c20400"))
    return code.build()


def build_path_resolver(*, wrapper_va: int, prefix_va: int, imports: MovieOverrideImports) -> bytes:
    """Resolve our short AVI aliases beside GK3.exe without changing CUSTOM PATHS.

    Other movie names keep native FileManager lookup. The call-site's displaced
    local assignment is replayed before establishing thiscall's wrapper frame.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(bytes.fromhex("897df0 55 8bec 53 56 57 83ec04 89cb 8b7508"))
    for index, value in enumerate(MOVIE_FILENAME_PREFIX):
        code.raw(bytes((0x80, 0x7E, index, value)))
        code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("8b7d0c 8b4510 85c0"))
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code.raw(bytes.fromhex("3d2c010000"))
    code.jump_if(Condition.BELOW_OR_EQUAL, "capacity")
    code.raw(bytes.fromhex("b82c010000"))
    code.label("capacity")
    code.raw(bytes.fromhex("8d5407ff 8955f0 50 57 6a00 ff15"))
    code.raw(struct.pack("<I", imports.module_filename))
    code.raw(bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("8d0407 3b45f0"))
    code.jump_if(Condition.ABOVE, "native")
    code.raw(bytes.fromhex("89f9 89fa"))
    code.label("directory")
    code.raw(bytes.fromhex("8a01 84c0"))
    code.jump_if(Condition.EQUAL, "prefix")
    code.raw(bytes.fromhex("3c5c"))
    code.jump_if(Condition.NOT_EQUAL, "next")
    code.raw(bytes.fromhex("8d5101"))
    code.label("next")
    code.raw(b"\x41")
    code.jump("directory")
    code.label("prefix")
    code.raw(bytes.fromhex("8b45f0 29d0 83f8") + bytes((len(MOVIE_OVERRIDE_PREFIX),)))
    code.jump_if(Condition.BELOW_OR_EQUAL, "native")
    code.raw(b"\x89\xd7\x56\xbe" + struct.pack("<I", prefix_va))
    code.raw(b"\xb9" + struct.pack("<I", len(MOVIE_OVERRIDE_PREFIX)))
    code.raw(bytes.fromhex("fc f3a4 5e"))
    code.label("name")
    code.raw(bytes.fromhex("3b7df0"))
    code.jump_if(Condition.ABOVE, "native")
    code.raw(bytes.fromhex("8a06"))
    for value in (0x2F, 0x5C, 0x3A):
        code.raw(bytes((0x3C, value)))
        code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("8807 84c0"))
    code.jump_if(Condition.EQUAL, "exists")
    code.raw(bytes.fromhex("46 47"))
    code.jump("name")
    code.label("exists")
    code.raw(bytes.fromhex("6a00 6880000000 6a03 6a00 6a07 6800000080 ff750c ff15"))
    code.raw(struct.pack("<I", imports.create_file))
    code.raw(bytes.fromhex("83f8ff"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x50\xff\x15" + struct.pack("<I", imports.close_handle))
    code.raw(bytes.fromhex("b801000000"))
    code.jump("done")
    code.label("native")
    code.raw(bytes.fromhex("ff7510 ff750c ff7508 89d9 8b01 ff5048"))
    code.label("done")
    code.raw(bytes.fromhex("83c404 5f 5e 5b 5d c20c00"))
    return code.build()
