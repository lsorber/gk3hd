"""Strict renderer ownership records, independent of executable patch plans."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.manifest import ExternalChange

if TYPE_CHECKING:
    from pathlib import Path

STATE_FILENAME = ".gk3hd-renderer.json"
JOURNAL_FILENAME = ".gk3hd-renderer-journal.json"


@dataclass(frozen=True)
class RendererState:
    """Exact installed values and the original values to restore on uninstall."""

    changes: tuple[ExternalChange, ...]
    executable: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the single supported ownership schema."""
        return {
            "schema": 1,
            "exe": self.executable,
            "changes": [asdict(change) for change in self.changes],
        }

    @property
    def digest(self) -> str:
        """Return the validated DLL identity."""
        return next(change.installed[7:] for change in self.changes if change.key == "ddraw.dll")

    @classmethod
    def parse(cls, payload: object, *, exe: Path) -> RendererState:
        """Reject malformed or out-of-scope targets before any recovery mutation."""
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != 1
            or set(payload) != {"schema", "exe", "changes"}
            or payload.get("exe") != exe.name
        ):
            msg = "invalid renderer state schema"
            raise ValueError(msg)
        rows = payload["changes"]
        if not isinstance(rows, list):
            msg = "invalid renderer change list"
            raise TypeError(msg)
        allowed = {
            ("file:d7vk-binary", "ddraw.dll"),
            ("file", "dxvk.conf"),
            (
                (
                    "registry:HKCU\\Software\\Microsoft\\Windows NT\\CurrentVersion"
                    "\\AppCompatFlags\\Layers"
                ),
                str(exe.resolve()),
            ),
            (rf"registry:HKCU\Software\Wine\AppDefaults\{exe.name}\DllOverrides", "ddraw"),
        }
        changes = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"surface", "key", "previous", "installed"}:
                msg = "invalid renderer change"
                raise ValueError(msg)
            change = ExternalChange(**row)
            identity = (change.surface, change.key)
            if identity not in allowed or identity in seen:
                msg = "unsupported or duplicate renderer target"
                raise ValueError(msg)
            if change.key == "ddraw.dll" and any(
                value is not None and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
                for value in (change.previous, change.installed)
            ):
                msg = "invalid renderer DLL digest"
                raise ValueError(msg)
            seen.add(identity)
            changes.append(change)
        if not {("file:d7vk-binary", "ddraw.dll"), ("file", "dxvk.conf")} <= seen:
            msg = "renderer state is missing required files"
            raise ValueError(msg)
        return cls(tuple(changes), exe.name)

    @classmethod
    def load(cls, exe: Path) -> RendererState | None:
        """Read only this game's adjacent installation record."""
        path = exe.with_name(STATE_FILENAME)
        return cls.parse(json.loads(path.read_bytes()), exe=exe) if path.is_file() else None

    @classmethod
    def owner(cls, directory: Path) -> RendererState | None:
        """Read the managed executable identity without accepting paths in the record."""
        path = directory / STATE_FILENAME
        if not path.is_file():
            return None
        payload = json.loads(path.read_bytes())
        name = payload.get("exe") if isinstance(payload, dict) else None
        if (
            not isinstance(name, str)
            or not name.lower().endswith(".exe")
            or any(char in name for char in "/\\:")
        ):
            msg = "invalid renderer executable identity"
            raise ValueError(msg)
        return cls.parse(payload, exe=directory / name)
