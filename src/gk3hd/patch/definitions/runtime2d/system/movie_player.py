"""Load the private AV1 adapter beside the executable, never from cwd or the registry."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gk3hd.patch.binary.x86 import Condition, X86Emitter

PLAYER_PATH = b"gk3hd\\videos\\installed\\gk3hd-videos.dll\0"
PLAYER_EXPORT = b"_Gk3hdOpenMovie@12\0"
_PATH_CAPACITY = 300  # Match the native movie resolver's bounded path capacity.


@dataclass(frozen=True, slots=True)
class MoviePlayerABI:
    """Existing kernel32 imports and private payload data addresses."""

    module_filename: int
    load_library: int
    get_proc_address: int
    path: int
    symbol: int
    cached_function: int


def build_open_movie(*, wrapper_va: int, abi: MoviePlayerABI) -> bytes:
    """Tail-call the adapter with the unchanged three-argument stdcall contract.

    A missing adapter keeps native playback available. A loaded adapter checks
    file magic and delegates original media to the original player itself.
    Never load a DLL from a relative cwd path or overrun the native path limit.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\xa1" + struct.pack("<I", abi.cached_function) + bytes.fromhex("85c0"))
    code.jump_if(Condition.NOT_EQUAL, "invoke")
    code.raw(bytes.fromhex("55 8bec 53 56 57 81ec2c010000 8dbdc8feffff"))
    code.push_imm32(_PATH_CAPACITY)
    code.raw(bytes.fromhex("57 6a00 ff15") + struct.pack("<I", abi.module_filename))
    code.raw(bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "fallback")
    code.raw(b"\x3d" + struct.pack("<I", _PATH_CAPACITY))
    code.jump_if(Condition.ABOVE_OR_EQUAL, "fallback")
    code.raw(bytes.fromhex("89f9 31d2"))
    code.label("directory")
    code.raw(bytes.fromhex("8a01 84c0"))
    code.jump_if(Condition.EQUAL, "suffix")
    for separator in (0x2F, 0x5C):
        code.raw(bytes((0x3C, separator)))
        code.jump_if(Condition.EQUAL, "separator")
    code.jump("next")
    code.label("separator")
    code.raw(bytes.fromhex("8d5101"))
    code.label("next")
    code.raw(b"\x41")
    code.jump("directory")
    code.label("suffix")
    code.raw(bytes.fromhex("85d2"))
    code.jump_if(Condition.EQUAL, "fallback")
    code.raw(bytes.fromhex("8d8200000000"))
    code.raw(b"\x05" + struct.pack("<I", len(PLAYER_PATH)))
    code.raw(bytes.fromhex("8d9f2c010000 39d8"))
    code.jump_if(Condition.ABOVE, "fallback")
    code.raw(bytes.fromhex("57 89d7 be") + struct.pack("<I", abi.path))
    code.raw(b"\xb9" + struct.pack("<I", len(PLAYER_PATH)) + bytes.fromhex("fc f3a4 5f"))
    code.raw(b"\x57\xff\x15" + struct.pack("<I", abi.load_library) + bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "fallback")
    code.push_imm32(abi.symbol)
    code.raw(b"\x50\xff\x15" + struct.pack("<I", abi.get_proc_address) + bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "fallback")
    code.raw(b"\xa3" + struct.pack("<I", abi.cached_function))
    code.raw(bytes.fromhex("8d65f4 5f5e5b 5d"))
    code.label("invoke")
    code.raw(bytes.fromhex("ffe0"))
    code.label("fallback")
    code.raw(bytes.fromhex("8d65f4 5f5e5b 5d 8b442404 8b00 ff6040"))
    return code.build()
