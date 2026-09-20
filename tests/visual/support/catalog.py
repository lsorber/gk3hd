"""Portable, curated scene recipes resolved against the player's camera assets."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from gk3hd.textures.brn import BarnArchive

_CAMERA_COMPONENTS = 5


class SuiteSize(StrEnum):
    """Nested coverage sets with a gallery-sized default."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

    @property
    def count(self) -> int:
        """Number of world views and UI states in this coverage tier."""
        return {self.SMALL: 12, self.MEDIUM: 25, self.LARGE: 100}[self]


@dataclass(frozen=True, slots=True)
class Scene:
    """One explicit scene/time/camera contract, independent of player saves."""

    room: str
    timeblock: str
    kind: str
    camera: str
    subject: str = ""
    setup: str = ""
    fov: float = 60.0
    pose: tuple[float, ...] | None = None

    @property
    def name(self) -> str:
        """Stable filesystem-safe capture identity."""
        if self.kind == "special":
            return self.camera.replace("_", "-")
        return f"{self.room}-{self.timeblock}-{self.camera}".lower()

    @property
    def description(self) -> str:
        """Compact human-readable subject label."""
        return self.subject or f"{self.room}: {self.camera.replace('_', ' ').title()}"


def scenes(size: SuiteSize = SuiteSize.SMALL) -> tuple[Scene, ...]:
    """Load an ordered, nested set without requiring Windows or a game install."""
    payload = json.loads(Path(__file__).with_name("scenes.json").read_text(encoding="utf-8"))
    result = tuple(
        Scene(*row[:7], pose=tuple(row[7]) if len(row) > 7 else None) for row in payload["scenes"]
    )
    if len(result) != SuiteSize.LARGE.count or len({scene.name for scene in result}) != len(result):
        msg = "visual catalog must have exactly 100 unique scene recipes"
        raise ValueError(msg)
    for scene in result:
        if scene.kind not in {
            "room",
            "inspect",
            "cinematic",
            "dialogue",
            "custom",
            "special",
        } or not all(
            re.fullmatch(r"[A-Za-z0-9_]+", value)
            for value in (scene.room, scene.timeblock, scene.camera)
        ):
            msg = f"invalid scene recipe: {scene}"
            raise ValueError(msg)
    return result[: size.count]


def camera_coordinates(payload: str, scene: Scene) -> tuple[float, ...]:
    """Read an explicit, unconditional authored camera; never guess a fallback."""
    section = f"[{scene.kind.upper()}_CAMERAS]"
    active = False
    for raw in payload.splitlines():
        line = raw.split("//", 1)[0].strip()
        if line.startswith("["):
            active = line.upper() == section
        if not active:
            continue
        name = re.search(r"(?:noun|name|model)\s*=\s*([^,]+)", line, re.IGNORECASE)
        identifier = name[1].strip() if name else line.split(",", 1)[0]
        if identifier.upper() != scene.camera.upper():
            continue
        angle = re.search(r"angle\s*=\s*\{([^}]+)\}", line, re.IGNORECASE)
        position = re.search(r"pos\s*=\s*\{([^}]+)\}", line, re.IGNORECASE)
        if angle and position:
            values = tuple(float(value) for value in f"{angle[1]},{position[1]}".split(","))
            if len(values) == _CAMERA_COMPONENTS and all(math.isfinite(value) for value in values):
                return values
    msg = f"authored {scene.kind} camera {scene.camera} not found in {scene.room}.SIF"
    raise ValueError(msg)


def resolve_cameras(data_directory: Path, selected: tuple[Scene, ...]) -> dict[str, str]:
    """Resolve authored cameras or reviewed explicit framing, identical in both modes."""
    archive = BarnArchive.open(data_directory)
    entries = {entry.name.upper(): entry for entry in archive.entries}
    result = {}
    seen: set[tuple[str, str, tuple[float, ...], float]] = set()
    with archive.reader() as read:
        for scene in selected:
            # A time-specific SIF can add authored character close-ups. Its
            # unconditional camera definitions take precedence over the base.
            time_entry = entries.get(f"{scene.room}{scene.timeblock}.SIF".upper())
            payload = read(time_entry).decode("latin1") + "\n" if time_entry else ""
            payload += read(entries[f"{scene.room}.SIF"]).decode("latin1")
            coords = scene.pose if scene.pose is not None else camera_coordinates(payload, scene)
            if (
                len(coords) != _CAMERA_COMPONENTS
                or not all(math.isfinite(value) for value in coords)
                or not math.isfinite(scene.fov)
                or not 0 < scene.fov < 180
            ):
                msg = f"invalid camera framing: {scene.name}"
                raise ValueError(msg)
            identity = scene.room.upper(), scene.timeblock.casefold(), coords, scene.fov
            if identity in seen:
                msg = f"duplicate camera coordinates in visual catalog: {scene.name}"
                raise ValueError(msg)
            seen.add(identity)
            # Sheep's native call boundary requires float literals: integer-looking
            # coordinates can otherwise arrive as integer bits, not float values.
            arguments = ",".join(str(float(value)) for value in coords)
            result[scene.name] = (
                f"{scene.setup}CutToCameraAngleX({arguments});SetCameraFOV({float(scene.fov)});"
            )
    return result
