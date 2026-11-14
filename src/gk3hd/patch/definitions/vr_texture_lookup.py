"""Exact-case blink texture opens for the standalone Wine guest."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.model import PatchError
from gk3hd.textures.install.service import TEXTURE_DIRECTORY

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

_PREFIX = TEXTURE_DIRECTORY.replace("/", "\\").upper().encode("ascii") + b"\\"
_ROOTS = (_PREFIX, b".\\" + _PREFIX, b"C:\\GK3HD-VR\\" + _PREFIX)
_NAMES = (
    b"GAB_BLINK_01.BMP",
    b"GAB_BLINK_02.BMP",
    b"VIT_BLINK_01.BMP",
    b"VIT_BLINK_02.BMP",
    b"JEA_BLINK_01.BMP",
    b"JEA_BLINK_02.BMP",
)
_NAME_SIZE = len(_NAMES[0])
_CAPACITY = 64
_SECTION_SIZE = 1024


def _lookup_code(base_va: int, create_file: int, get_error: int, set_error: int) -> bytes:
    code = X86Emitter(base_va=base_va)
    # Local buffer at EBP-64; incoming last error at EBP-68.
    code.raw(bytes.fromhex("55 8b ec 83 ec 44 53 56 57 fc"))
    # GENERIC_READ, OPEN_EXISTING only. Keep delete-on-close on the native path.
    code.raw(bytes.fromhex("81 7d 0c 00 00 00 80"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("83 7d 18 03"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("f7 45 1c 00 00 00 04"))
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(bytes.fromhex("8b 75 08 85 f6"))
    code.jump_if(Condition.EQUAL, "native")
    code.raw(bytes.fromhex("8d 7d c0 b9") + struct.pack("<I", _CAPACITY))
    code.label("normalize")
    # Copy at most 64 bytes, folding ASCII and accepting both separators.
    code.raw(bytes.fromhex("ac 3c 2f"))
    code.jump_if(Condition.NOT_EQUAL, "fold")
    code.raw(bytes.fromhex("b0 5c"))
    code.label("fold")
    code.raw(bytes.fromhex("3c 61"))
    code.jump_if(Condition.BELOW, "store")
    code.raw(bytes.fromhex("3c 7a"))
    code.jump_if(Condition.ABOVE, "store")
    code.raw(bytes.fromhex("2c 20"))
    code.label("store")
    code.raw(bytes.fromhex("aa 84 c0"))
    code.jump_if(Condition.EQUAL, "root")
    code.raw(bytes.fromhex("49"))
    code.jump_if(Condition.NOT_EQUAL, "normalize")
    code.jump("native")

    code.label("root")
    # EBX counts the whole normalized path, including its terminator.
    code.raw(bytes.fromhex("8d 75 c0 89 fb 29 f3"))
    for index, prefix in enumerate(_ROOTS):
        following = f"root_{index + 1}"
        code.raw(bytes.fromhex("83 fb") + bytes((len(prefix) + _NAME_SIZE + 1,)))
        code.jump_if(Condition.NOT_EQUAL, following)
        code.raw(bytes.fromhex("8d 75 c0 bf"))
        code.absolute_label(f"prefix_{index}")
        code.raw(b"\xb9" + struct.pack("<I", len(prefix)) + b"\xf3\xa6")
        code.jump_if(Condition.EQUAL, "leaf")
        code.label(following)
    code.jump("native")

    code.label("leaf")
    # Match the complete leaf. ESI still points just past the recognized root.
    for index in range(len(_NAMES)):
        code.raw(b"\x56\xbf")
        code.absolute_label(f"name_{index}")
        code.raw(b"\xb9" + struct.pack("<I", _NAME_SIZE) + b"\xf3\xa6\x5e")
        code.jump_if(Condition.EQUAL, "exact")
    code.jump("native")

    code.label("exact")
    # Restore the caller's directory spelling and separators in the copy.
    code.raw(bytes.fromhex("8d 7d c0 89 f1 29 f9 8b 75 08 f3 a4"))
    code.raw(b"\xb9" + struct.pack("<I", _NAME_SIZE) + b"\xf3\xa6")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xff\x15" + struct.pack("<I", get_error) + bytes.fromhex("89 45 bc"))
    for offset in (32, 28, 24, 20, 16, 12):
        code.raw(bytes.fromhex("ff 75") + bytes((offset,)))
    code.raw(bytes.fromhex("8d 45 c0 50 ff 15") + struct.pack("<I", create_file))
    code.raw(bytes.fromhex("83 f8 ff"))
    code.jump_if(Condition.EQUAL, "fallback")
    code.raw(bytes.fromhex("5f 5e 5b c9 c2 1c 00"))
    code.label("fallback")
    code.raw(bytes.fromhex("ff 75 bc ff 15") + struct.pack("<I", set_error))
    code.label("native")
    code.raw(bytes.fromhex("5f 5e 5b c9 ff 25") + struct.pack("<I", create_file))

    for index, prefix in enumerate(_ROOTS):
        code.label(f"prefix_{index}")
        code.raw(prefix)
    for index, name in enumerate(_NAMES):
        code.label(f"name_{index}")
        code.raw(name)
    return code.build(maximum_size=_SECTION_SIZE)


def compile_texture_lookup(image: PEFile, profile: BuildProfile) -> None:
    """Apply the verified standalone-only file-open redirects."""
    sites = tuple(profile.site(f"vr.texture_open_{index}") for index in range(5))
    create_file = struct.unpack_from("<I", sites[0].original, 2)[0]
    imports = {
        item.function_name: image.image_base + item.iat_rva
        for item in image.iter_import_symbols()
        if item.dll_name.casefold() == "kernel32.dll"
    }
    if "GetLastError" not in imports or "SetLastError" not in imports:
        msg = "Standalone texture lookup requires the native last-error imports"
        raise PatchError(msg)
    section = image.add_section(".vrtex", bytes(_SECTION_SIZE), 0x60000020)
    entry = image.image_base + section.virtual_address
    code = _lookup_code(entry, create_file, imports["GetLastError"], imports["SetLastError"])
    plan = ExecutableMutationPlan(owner="standalone texture lookup")
    for site in sites:
        plan.branch(
            label=site.symbol,
            opcode=BranchOpcode.CALL
            if site.original.startswith(b"\xff\x15")
            else BranchOpcode.JUMP,
            site_va=site.va,
            expected=site.original,
            target_va=entry,
            size=len(site.original),
        )
    plan.apply(image)
    image.write_bytes(section.pointer_to_raw_data, code)
