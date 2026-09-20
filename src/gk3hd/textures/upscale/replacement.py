"""Load reviewed replacement artwork, bound to the original texture's pixels."""

from __future__ import annotations

import hashlib
from importlib.resources import files
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable
    from pathlib import Path

SOURCE_STAMP = "gk3hd-source-rgb-sha256"


def replacement_asset(name: str) -> Traversable:
    """Resolve a flat texture name without accepting resource path traversal."""
    normalized = name.upper()
    if not normalized.endswith(".BMP") or any(c in normalized for c in "/\\:"):
        msg = f"invalid replacement texture name: {name}"
        raise ValueError(msg)
    return files("gk3hd").joinpath("assets/textures", normalized[:-4] + ".PNG")


def has_replacement(name: str) -> bool:
    """Report whether a policy can select a packaged replacement."""
    return replacement_asset(name).is_file()


def regenerate_replacement(source: Path) -> Image.Image:
    """Use reviewed pixels only with their matching original and 4x layout."""
    with (
        Image.open(source) as original,
        replacement_asset(source.name).open("rb") as stream,
        Image.open(stream) as replacement,
    ):
        digest = hashlib.sha256(original.convert("RGB").tobytes()).hexdigest()
        if replacement.info.get(SOURCE_STAMP) != digest:
            msg = f"{source.name}: reviewed replacement does not match original pixels"
            raise ValueError(msg)
        if replacement.mode != "RGB" or replacement.size != (
            original.width * 4,
            original.height * 4,
        ):
            msg = f"{source.name}: reviewed replacement must be a 4x RGB image"
            raise ValueError(msg)
        return replacement.copy()


def is_current_replacement(source: Path, destination: Path) -> bool:
    """Invalidate earlier AI outputs and replaced package artwork on resume."""
    expected = regenerate_replacement(source)
    with Image.open(destination) as actual:
        return (
            actual.mode == expected.mode
            and actual.size == expected.size
            and (actual.tobytes() == expected.tobytes())
        )
