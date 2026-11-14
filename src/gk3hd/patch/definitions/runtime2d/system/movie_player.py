"""Load the private movie adapter beside the executable, never from cwd or the registry."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from gk3hd.patch.binary.x86 import Condition, X86Emitter

PLAYER_PATH = b"gk3hd\\videos\\installed\\gk3hd-videos.dll\0"
PLAYER_EXPORT = b"_Gk3hdOpenMovie@12\0"
PLAYER_STATE_EXPORT = b"_Gk3hdSetMovieState@8\0"
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
    cached_module: int


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
    code.raw(b"\xa3" + struct.pack("<I", abi.cached_module))
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


@dataclass(frozen=True, slots=True)
class MovieStateABI:
    """Reuse the executable-relative player already resolved during Open."""

    get_proc_address: int
    cached_module: int
    symbol: int
    cached_function: int


def build_movie_state_call(*, wrapper_va: int, abi: MovieStateABI) -> bytes:
    """Keep the stream/state stdcall ABI, falling back to its native method."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\xa1" + struct.pack("<I", abi.cached_function) + bytes.fromhex("85c0"))
    code.jump_if(Condition.NOT_EQUAL, "invoke")
    code.raw(b"\xa1" + struct.pack("<I", abi.cached_module) + bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "fallback")
    code.push_imm32(abi.symbol)
    code.raw(b"\x50\xff\x15" + struct.pack("<I", abi.get_proc_address))
    code.raw(bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "fallback")
    code.raw(b"\xa3" + struct.pack("<I", abi.cached_function))
    code.label("invoke")
    code.raw(bytes.fromhex("ffe0"))
    code.label("fallback")
    code.raw(bytes.fromhex("8b442404 8b00 ff601c"))
    return code.build()


def build_avi_state(*, wrapper_va: int, state_call_va: int, running: bool) -> bytes:
    """Translate the native AVI thiscall into its existing COM stream/state call."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(bytes.fromhex("8b4154") + bytes((0x6A, int(running), 0x50)))
    code.call_absolute(state_call_va)
    code.raw(b"\xc3")
    return code.build()


def build_native_movie_attach(
    *, entry_va: int, module_va: int, get_proc_address: int, complete_va: int
) -> bytes:
    """Offer the EDI full-screen replacement to an optional standalone provider.

    Inline fragment: preserve all registers/flags and fall through. A missing
    module/export retains the ordinary graph. The adapter must negotiate before
    changing the native object. Its symbol occupies only this call's stack.
    """
    symbol = b"_Gk3hdAttachNativeMovie@8\0"
    symbol += bytes(-len(symbol) % 4)
    code = X86Emitter(base_va=entry_va)
    code.raw(bytes.fromhex("9c60 a1") + struct.pack("<I", module_va) + bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "done")
    for offset in range(len(symbol) - 4, -1, -4):
        code.push_imm32(struct.unpack_from("<I", symbol, offset)[0])
    code.raw(bytes.fromhex("54 50 ff15") + struct.pack("<I", get_proc_address))
    code.raw(bytes((0x83, 0xC4, len(symbol))) + bytes.fromhex("85c0"))
    code.jump_if(Condition.EQUAL, "done")
    code.push_imm32(complete_va)
    code.raw(bytes.fromhex("57 ffd0"))
    code.label("done")
    code.raw(bytes.fromhex("619d"))
    return code.build()
