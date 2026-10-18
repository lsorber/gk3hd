"""Verified native scene subclasses sharing the ordinary room/input layout."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Literal

from gk3hd.patch.binary.x86 import Condition
from gk3hd.patch.builds import NATIVE_USER_SCENE_SUBCLASSES
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.binary.x86 import X86Emitter
    from gk3hd.patch.builds import BuildProfile

NATIVE_SCENE_TYPES = (
    "vr.user_scene_vtable",
    *(f"vr.{name}_scene_vtable" for name, *_anchors in NATIVE_USER_SCENE_SUBCLASSES),
)


def check_native_scene_types(image: PEFile, profile: BuildProfile) -> None:
    """Verify each native subclass's base construction, identity and input."""
    for name, *_anchors in NATIVE_USER_SCENE_SUBCLASSES:
        for kind in ("base", "type", "input", "pick"):
            site = profile.site(f"vr.{name}_scene_{kind}")
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR native scene anchor changed: {site.symbol}"
                raise PatchError(msg)


def emit_native_scene_guard(
    e: X86Emitter,
    profile: BuildProfile,
    *,
    register: Literal["eax", "ecx"],
    rejected: str,
) -> None:
    """Accept only ordinary UserScene and its verified native puzzle subclasses.

    The caller checks a non-null scene first. Unknown/modal types remain rejected;
    camera-lock and scripted-controller ownership checks remain independent.
    """
    accepted = f"{rejected}_native_scene"
    opcode = b"\x81\x38" if register == "eax" else b"\x81\x39"
    for name in NATIVE_SCENE_TYPES:
        e.raw(opcode + struct.pack("<I", profile.address(name)))
        e.jump_if(Condition.EQUAL, accepted)
    e.jump(rejected)
    e.label(accepted)
