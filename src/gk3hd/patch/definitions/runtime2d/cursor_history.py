"""Select cursor save-under history from an explicit renderer capability."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from gk3hd.patch.binary.x86 import Condition, X86Emitter

if TYPE_CHECKING:
    from gk3hd.patch.binary.payload import SegmentPayloadBuilder
    from gk3hd.patch.builds import BuildProfile

HISTORY_OFFSET = 0x3900
_NAMES_OFFSET = 0x3A00
_CACHE_OFFSET = 0x3A40
_EXPORT_NAME = b"Gk3hdSurfaceHistoryDepth\0"


def build_history_adapter(*, profile: BuildProfile, control_va: int) -> bytes:
    """Adapt only a proven retained two-page target; preserve all other histories."""
    code = X86Emitter(base_va=control_va + HISTORY_OFFSET)
    # The original thiscall has no stack arguments. Keep its result unless the
    # renderer explicitly identifies this exact current target as retained.
    code.raw(b"\x53\x56\x57\x89\xce")  # EBX/ESI/EDI; ESI=BitmapManager
    code.call_absolute(profile.site("high_resolution_3d.damage_history").va)
    code.raw(b"\x89\xc3\x83\xf8\x02")
    code.jump_if(Condition.NOT_EQUAL, "done")
    code.raw(b"\x8b\x3d" + struct.pack("<I", control_va + _CACHE_OFFSET))
    code.raw(b"\x83\xff\xff")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x85\xff")
    code.jump_if(Condition.NOT_EQUAL, "query")
    code.raw(b"\x68" + struct.pack("<I", control_va + _NAMES_OFFSET))
    code.raw(b"\xff\x15" + struct.pack("<I", profile.address("win32.GetModuleHandleA")))
    code.raw(b"\x85\xc0")
    # Do not cache absence before DirectDraw is loaded.
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x68" + struct.pack("<I", control_va + _NAMES_OFFSET + 16) + b"\x50")
    code.raw(b"\xff\x15" + struct.pack("<I", profile.address("win32.GetProcAddress")))
    code.raw(b"\x89\xc7\x85\xc0")
    code.jump_if(Condition.NOT_EQUAL, "cache")
    code.raw(b"\x83\xcf\xff")  # loaded renderer has no capability export
    code.label("cache")
    code.raw(b"\x89\x3d" + struct.pack("<I", control_va + _CACHE_OFFSET))
    code.raw(b"\x83\xff\xff")
    code.jump_if(Condition.EQUAL, "done")
    code.label("query")
    code.raw(b"\xff\x76\x18\x89\xf1")  # current back-page encoded bitmap handle
    code.call_absolute(profile.address("bitmap.resolve_resource"))
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x89\xc1")
    code.call_absolute(profile.address("high_resolution_3d.current_renderer"))
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x8b\x40\x2c\x85\xc0")  # renderer's IDirectDrawSurface, as in native Blt
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x50\xff\xd7\x83\xf8\x01")  # optional stdcall capability
    code.jump_if(Condition.NOT_EQUAL, "done")
    code.raw(b"\xbb\x01\x00\x00\x00")
    code.label("done")
    code.raw(b"\x89\xd8\x5f\x5e\x5b\xc3")
    return code.build(maximum_size=_NAMES_OFFSET - HISTORY_OFFSET)


def emit_history_adapter(
    *, profile: BuildProfile, payload: SegmentPayloadBuilder, control_va: int
) -> None:
    """Place immutable capability names/code and one cached export pointer."""
    payload.place(
        label="cursor surface-history capability adapter",
        offset=HISTORY_OFFSET,
        payload=build_history_adapter(profile=profile, control_va=control_va),
        limit=_NAMES_OFFSET,
    )
    payload.place(
        label="cursor renderer capability names",
        offset=_NAMES_OFFSET,
        payload=b"ddraw.dll\0".ljust(16, b"\0") + _EXPORT_NAME,
        limit=_CACHE_OFFSET,
    )
    payload.reserve(label="cursor renderer capability cache", offset=_CACHE_OFFSET, size=4)
