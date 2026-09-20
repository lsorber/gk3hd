"""Conservative GK3 texture semantic classification."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd.textures.model import TextureFeatures, TextureKind

if TYPE_CHECKING:
    from collections.abc import Mapping

    from gk3hd.textures.bmp import BmpInfo

_SKYBOX_DATA_RE = re.compile(r"_[0-9]+(?:FT|BK|LF|RT|UP|DN)_MASK$")
_BOUNDARY_DATA_RE = re.compile(r"(?:WALK|WLK|WK).*?(?:BOUND|BND)|(?:BOUND|BNDS)|^BNDRY[0-9_]*$")
_MENU_BUTTON_SIZE = 32


def classify_texture(
    name: str,
    info: BmpInfo,
    images: Mapping[str, BmpInfo],
    *,
    action_button: bool = False,
    toolbar_button: bool = False,
) -> TextureFeatures:
    """Classify one BMP using format facts, names, and companion presence.

    Tiling describes how the game consumes a texture and cannot be proven from
    BMP pixels. It therefore defaults to false and can be supplied through the
    analyzer's archive usage scan or explicit override manifest.
    """
    normalized = Path(name).name.upper()
    stem = Path(normalized).stem
    kind = _kind(stem, info, images)
    alphatest = kind is TextureKind.COLOR and info.has_color_key
    exact_raster = kind is TextureKind.COLOR and _is_exact_raster_art(
        stem, info, action_button=action_button, toolbar_button=toolbar_button
    )
    return TextureFeatures(
        name=normalized,
        kind=kind,
        tiled=False,
        alphatest=alphatest,
        exact_raster=exact_raster,
        constant_color=info.constant_color,
        alpha_silhouette=kind is TextureKind.ALPHA and info.alpha_silhouette,
        font_atlas=kind is not TextureKind.DATA and stem.startswith("F_"),
    )


def _kind(stem: str, info: BmpInfo, images: Mapping[str, BmpInfo]) -> TextureKind:
    """Determine whether pixels are visible color, opacity, or indexed data."""
    # Semantic resource names are authoritative. Most walker maps are indexed,
    # but BNDRY1 is a 24-bit binary hotel-exterior navigation mask; requiring a
    # palette silently routes it through AI and changes both its dimensions and
    # boundary pixels.
    if _is_data_name(stem):
        return TextureKind.DATA
    if info.palettized and _is_alpha_name(stem, info, images):
        return TextureKind.ALPHA
    return TextureKind.COLOR


def _is_data_name(stem: str) -> bool:
    """Recognize GK3's palette-index walker and skybox hit maps."""
    return bool(_BOUNDARY_DATA_RE.search(stem) or _SKYBOX_DATA_RE.search(stem))


def _is_alpha_name(stem: str, info: BmpInfo, images: Mapping[str, BmpInfo]) -> bool:
    """Recognize explicit opacity names and same-size A-suffix companions."""
    if stem.endswith(("_OP", "_ALPHA")):
        return True
    if not stem.endswith("A"):
        return False
    companion = images.get(f"{stem[:-1]}.BMP")
    return companion is not None and (companion.width, companion.height) == (
        info.width,
        info.height,
    )


def _is_exact_raster_art(
    stem: str, info: BmpInfo, *, action_button: bool, toolbar_button: bool
) -> bool:
    """Select conservative raster-retention candidates, not proven pixel art.

    The menu/cursor families mix pixel-defined symbols with shaded artwork.
    Size and resource usage alone do not justify permanent retention; reviewed
    reconstruction and engine validation are still needed for those families.
    Explicit exclusions and outstanding work belong in the packaged texture policy.

    ``C_*`` is GK3's cursor family. Every ``I_*`` source in the shipped corpus
    is a 32x32 left-click action-menu state, while the 32x32 ``RC_*`` sources
    are the corresponding right-click menu states. Larger ``RC_*`` panels and
    text buttons remain continuous-color artwork. VERBS.TXT identifies menu
    sprites outside these naming families; only their 32x32 states qualify.
    TBLAYOUT/OBLAYOUT identify the earlier small toolbar icons, including bevels
    and symbols whose geometry must stay stable. Only states at most 32x32 qualify;
    larger panels, previews and arbitrary small materials do not.
    Font-atlas usage comes from FON references rather than image-shape guesswork.
    Verified exceptions to these heuristics belong in texture-policy.json.
    Reconstruction modules validate the source geometry they require.
    """
    if stem.startswith("C_"):
        return True
    if (toolbar_button or stem.startswith("TBBT")) and max(
        info.width, info.height
    ) <= _MENU_BUTTON_SIZE:
        return True
    return (info.width, info.height) == (_MENU_BUTTON_SIZE, _MENU_BUTTON_SIZE) and (
        action_button or stem.startswith(("I_", "RC_"))
    )
