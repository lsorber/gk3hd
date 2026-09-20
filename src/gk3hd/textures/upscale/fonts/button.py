"""Produce source-faithful 4x copies of buttons with embedded labels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image

from gk3hd.textures.upscale.fonts.atlas import SCALE


@dataclass(frozen=True, slots=True)
class FontButtonRecipe:
    """One known embedded label and its exact shipped bitmap dimensions."""

    name: str
    label: str
    size: tuple[int, int]


_BUTTON_FAMILIES: Final = {
    "ADVANCED": ("Advanced Options", (169, 17), ("STD", "HOV", "DWN")),
    "QUIT": ("Quit Game", (67, 17), ("STD", "HOV", "DWN")),
    "RESTORE": ("Restore", (85, 17), ("STD", "HOV", "DWN", "DIS")),
    "SAVE": ("Save", (60, 17), ("STD", "HOV", "DWN")),
}
_RECIPES: Final = {
    f"RC_SO_{family}_{state}.BMP": FontButtonRecipe(
        f"RC_SO_{family}_{state}.BMP",
        label,
        size,
    )
    for family, (label, size, states) in _BUTTON_FAMILIES.items()
    for state in states
}
FONT_BUTTON_SIZES: Final = {name: recipe.size for name, recipe in _RECIPES.items()}


def font_button_recipe(name: str) -> FontButtonRecipe | None:
    """Return the exact contract for a recognized button basename."""
    return _RECIPES.get(Path(name).name.upper())


def regenerable_font_button_names() -> frozenset[str]:
    """Return every embedded-label bitmap with a known native size."""
    return frozenset(_RECIPES)


def regenerate_font_button(source: Path, *, scale: int = SCALE) -> Image.Image:
    """Enlarge chrome and every embedded-label pixel without changing either."""
    if scale != SCALE:
        msg = f"font buttons support {SCALE}x regeneration, not {scale}x"
        raise ValueError(msg)
    recipe = font_button_recipe(source.name)
    if recipe is None:
        msg = f"no faithful font-button recipe exists for {source.name}"
        raise ValueError(msg)
    with Image.open(source) as image:
        button = image.convert("RGB")
    if button.size != recipe.size:
        expected = f"{recipe.size[0]}x{recipe.size[1]}"
        msg = f"{source.name}: expected {expected}, got {button.width}x{button.height}"
        raise ValueError(msg)
    return button.resize(
        (button.width * scale, button.height * scale),
        Image.Resampling.NEAREST,
    )
