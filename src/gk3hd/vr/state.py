"""Portable ownership evidence for one opt-in, isolated VR player."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.system.files import is_sha256, json_bytes
from gk3hd.vr.transaction import FILES, STATE

if TYPE_CHECKING:
    from pathlib import Path

OWNED_FILES = tuple(name for name in FILES if name != STATE)


def validate_scale(value: float) -> None:
    """Require a finite positive calibration representable by the native ABI."""
    try:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            msg = "VR world scale must be finite and positive"
            raise ValueError(msg)
        native = struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error) as error:
        msg = "VR world scale is outside the native floating-point range"
        raise ValueError(msg) from error
    if not math.isfinite(native) or native <= 0:
        msg = "VR world scale is outside the native floating-point range"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class VRState:
    """Only fixed relative filenames, content hashes and world calibration."""

    units_per_meter: float
    files: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Reject malformed ownership instead of accepting arbitrary file paths."""
        validate_scale(self.units_per_meter)
        if (
            len(self.files) != len(OWNED_FILES)
            or {name for name, _ in self.files} != set(OWNED_FILES)
            or any(not is_sha256(digest) for _, digest in self.files)
        ):
            msg = "invalid VR ownership inventory"
            raise ValueError(msg)
        object.__setattr__(self, "files", tuple(sorted(self.files)))

    def to_bytes(self) -> bytes:
        """Persist deterministic state without machine-specific resource paths."""
        return json_bytes(
            {"schema": 1, "units_per_meter": self.units_per_meter, "files": dict(self.files)}
        )

    @classmethod
    def read(cls, path: Path) -> VRState:
        """Require the exact current development schema and fixed target set."""
        data = json.loads(path.read_bytes())
        if (
            not isinstance(data, dict)
            or set(data) != {"schema", "units_per_meter", "files"}
            or type(data["schema"]) is not int
            or data["schema"] != 1
            or not isinstance(data["files"], dict)
        ):
            msg = "invalid VR installation state"
            raise ValueError(msg)
        return cls(data["units_per_meter"], tuple(data["files"].items()))

    def require_owned(self, snapshot: dict[str, str | None]) -> None:
        """Refuse to replace or remove files modified outside the VR installer."""
        if any(snapshot.get(name) != digest for name, digest in self.files):
            msg = "VR-owned files changed; preserve them instead of replacing or removing them"
            raise ValueError(msg)
