"""Compile a hash-bound, Unicode-aware replacement entry point for Steam's menu."""

from __future__ import annotations

import hashlib
import struct

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.x86 import Condition, X86Emitter

STOCK_SHA256 = "7e2fa59edf71baa4d1b2f5e886cfeb8c40d4a1cfacdc0f0f8ae3c83de3e9267d"
API_NAMES = ("GetModuleFileNameW", "GetCommandLineW", "CreateProcessW", "GetExitCodeProcess")
API_BASE = 0x30060
LIMIT = 32768
_MAX_COMPONENT_UNITS = 255


def build_launcher(payload: bytes, *, game_directory: str, exe_name: str) -> bytes:
    """Bypass the menu, preserving command arguments, child cwd and exit status."""
    if hashlib.sha256(payload).hexdigest() != STOCK_SHA256:
        message = "unsupported Sierra launcher executable"
        raise ValueError(message)
    for value in (game_directory, exe_name):
        if (
            not value
            or value in (".", "..")
            or value.endswith((".", " "))
            or any(c in value for c in '/\\:"<>|?*')
            or any(not c.isprintable() for c in value)
            or len(value.encode("utf-16le")) // 2 > _MAX_COMPONENT_UNITS
        ):
            message = "launcher child must use simple relative names"
            raise ValueError(message)
    image = PEFile(payload)
    section = image.add_section(".gkstart", bytes(2048), 0x60000020)
    imports = {
        symbol.function_name: image.image_base + symbol.iat_rva
        for symbol in image.iter_import_symbols()
        if symbol.function_name is not None
    }
    output = _entrypoint(
        image.image_base + section.virtual_address,
        imports,
        game_directory=game_directory,
        exe_name=exe_name,
    )
    image.write_bytes(section.pointer_to_raw_data, output)
    image.write_bytes(image.optional_offset + 16, struct.pack("<I", section.virtual_address))
    image.write_bytes(image.optional_offset + 64, bytes(4))
    return image.to_bytes()


def _entrypoint(
    base_va: int, imports: dict[str, int], *, game_directory: str, exe_name: str
) -> bytes:
    code = X86Emitter(base_va=base_va)

    def imm(value: int) -> bytes:
        return struct.pack("<I", value)

    def push_label(label: str) -> None:
        code.raw(b"\x68")
        code.absolute_label(label)

    def mov_label(op: int, label: str) -> None:
        code.raw(bytes([op]))
        code.absolute_label(label)

    def iat(name: str) -> None:
        code.raw(b"\xff\x15" + imm(imports[name]))

    def api(name: str) -> None:
        code.raw(b"\xff\x93" + imm(API_BASE + 4 * API_NAMES.index(name)))

    def check() -> None:
        code.raw(b"\x85\xc0")
        code.jump_if(Condition.EQUAL, "last_error")

    # Keep executable code RX. All scratch storage is a zeroed RW allocation.
    code.raw(b"\xfc")  # cld
    code.push_imm8(4)
    code.push_imm32(0x3000)
    code.push_imm32(0x31000)
    code.push_imm8(0)
    iat("VirtualAlloc")
    check()
    code.raw(b"\x8b\xd8")  # ebx = storage
    push_label("kernel")
    iat("GetModuleHandleA")
    check()
    code.raw(b"\x8b\xe8")
    for index, name in enumerate(API_NAMES):
        push_label(name)
        code.raw(b"\x55")
        iat("GetProcAddress")
        check()
        code.raw(b"\x89\x83" + imm(API_BASE + 4 * index))
    code.push_imm32(LIMIT)
    code.raw(b"\x53")
    code.push_imm8(0)
    api("GetModuleFileNameW")
    check()
    code.raw(b"\x3d" + imm(LIMIT))
    code.jump_if(Condition.ABOVE_OR_EQUAL, "too_long")
    code.raw(b"\x8d\x3c\x43")  # edi = path + length*2
    code.label("find_directory")
    code.raw(b"\x3b\xfb")
    code.jump_if(Condition.EQUAL, "bad_path")
    code.raw(b"\x66\x83\x7f\xfe\x5c")
    code.jump_if(Condition.EQUAL, "directory_found")
    code.raw(b"\x66\x83\x7f\xfe\x2f")
    code.jump_if(Condition.EQUAL, "directory_found")
    code.raw(b"\x83\xef\x02")
    code.jump("find_directory")
    code.label("directory_found")
    suffix = (game_directory + "\\" + exe_name + "\0").encode("utf-16le")
    code.raw(b"\x8b\xc7\x2b\xc3\x05" + imm(len(suffix)))
    code.raw(b"\x3d" + imm(LIMIT * 2))
    code.jump_if(Condition.ABOVE, "too_long")
    mov_label(0xBE, "child_directory")  # esi = immutable directory string
    code.raw(b"\xb9" + imm(len((game_directory + "\\").encode("utf-16le")) // 2) + b"\x66\xf3\xa5")
    code.raw(b"\x8b\xef\x66\xc7\x07\x00\x00")  # ebp = append pointer; temporary terminator
    code.raw(b"\x8b\xcf\x2b\xcb\x83\xc1\x02\x8b\xf3\x8d\xbb" + imm(0x10000) + b"\xf3\xa4")
    code.raw(b"\x8b\xfd")
    mov_label(0xBE, "child_exe")
    code.raw(b"\xb9" + imm(len((exe_name + "\0").encode("utf-16le")) // 2) + b"\x66\xf3\xa5")

    # Replace only the program-name token. Preserve the argument tail verbatim,
    # including whitespace and quoting; the game also receives its own argv[0].
    api("GetCommandLineW")
    check()
    code.raw(b"\x8b\xf0\x33\xd2")
    code.label("skip_program")
    code.raw(b"\x66\xad\x66\x85\xc0")
    code.jump_if(Condition.EQUAL, "tail_found")
    code.raw(b"\x66\x83\xf8\x22")
    code.jump_if(Condition.NOT_EQUAL, "program_character")
    code.raw(b"\x83\xf2\x01")
    code.jump("skip_program")
    code.label("program_character")
    code.raw(b"\x85\xd2")
    code.jump_if(Condition.NOT_EQUAL, "skip_program")
    for value in (32, 9):
        code.raw(b"\x66\x83\xf8" + bytes([value]))
        code.jump_if(Condition.EQUAL, "tail_found")
    code.jump("skip_program")
    code.label("tail_found")
    code.raw(b"\x8d\x6e\xfe\x8b\xf3\x8d\xbb" + imm(0x20000) + b"\xb9" + imm(LIMIT - 2))
    code.raw(b"\x66\xb8\x22\x00\x66\xab")
    code.label("copy_program")
    code.raw(b"\x66\xad\x66\x85\xc0")
    code.jump_if(Condition.EQUAL, "close_quote")
    code.raw(b"\x66\xab")
    code.loop_short("copy_program")
    code.jump("too_long")
    code.label("close_quote")
    code.raw(b"\x66\xb8\x22\x00\x66\xab\x8b\xf5")
    code.label("copy_command")
    code.raw(b"\x66\xad\x66\xab\x66\x85\xc0")
    code.jump_if(Condition.EQUAL, "launch")
    code.loop_short("copy_command")
    code.jump("too_long")
    code.label("launch")
    code.raw(b"\xc7\x83" + imm(0x30000) + imm(68))  # STARTUPINFOW.cb
    code.raw(b"\x8d\x83" + imm(0x30044) + b"\x50")  # PROCESS_INFORMATION
    code.raw(b"\x8d\x83" + imm(0x30000) + b"\x50")  # STARTUPINFOW
    code.raw(b"\x8d\x83" + imm(0x10000) + b"\x50")  # child cwd
    for _ in range(5):
        code.push_imm8(0)  # env, flags, inherit, thread attrs, process attrs
    code.raw(b"\x8d\x83" + imm(0x20000) + b"\x50\x53")  # mutable command, application
    api("CreateProcessW")
    check()
    code.raw(b"\xff\xb3" + imm(0x30048))
    iat("CloseHandle")
    code.push_imm8(-1)
    code.raw(b"\xff\xb3" + imm(0x30044))
    iat("WaitForSingleObject")
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.NOT_EQUAL, "last_error")
    code.raw(b"\x8d\x83" + imm(0x30054) + b"\x50\xff\xb3" + imm(0x30044))
    api("GetExitCodeProcess")
    check()
    code.raw(b"\xff\xb3" + imm(0x30044))
    iat("CloseHandle")
    code.raw(b"\xff\xb3" + imm(0x30054))
    iat("ExitProcess")
    code.label("too_long")
    code.raw(b"\xb8" + imm(122))
    code.jump("error")
    code.label("bad_path")
    code.raw(b"\xb8" + imm(3))
    code.jump("error")
    code.label("last_error")
    iat("GetLastError")
    code.label("error")
    code.raw(b"\x8b\xf0")
    code.push_imm8(0x10)
    push_label("title")
    push_label("message")
    code.push_imm8(0)
    iat("MessageBoxA")
    code.raw(b"\x56")
    iat("ExitProcess")
    for name, value in (
        ("kernel", b"kernel32.dll\0"),
        ("child_directory", (game_directory + "\\").encode("utf-16le")),
        ("child_exe", (exe_name + "\0").encode("utf-16le")),
        ("title", b"gk3hd\0"),
        ("message", b"Could not start GK3. Verify or reinstall gk3hd.\0"),
        *((name, name.encode("ascii") + b"\0") for name in API_NAMES),
    ):
        code.label(name)
        code.raw(value)
    return code.build(maximum_size=2048)
