"""Restore facial-layer detail with the authored face and eyeballs as context.

This optional AI variant preserves the source layer's low-frequency anatomy,
binary aperture and partial-opacity transition. Inferred fine detail is admitted
only inside fully covered skin, away from every coverage boundary. The actual
eyeball remains a separate engine layer and is never baked into eyelid artwork.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter, maximum_filter, minimum_filter

from gk3hd.textures.analyze.usage import discover_data_directory
from gk3hd.textures.brn import BarnArchive
from gk3hd.textures.flat import actual_files
from gk3hd.textures.upscale.pipeline import upscale_smooth_color

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from gk3hd.textures.upscale.pipeline import ColorUpscaler

_RECIPE = b"contextual-face-layer-detail-v2"
_SCALE = 4
_OPAQUE_COVERAGE = 250


@dataclass(frozen=True, slots=True)
class FaceContext:
    """A native inference image and its exact layer crop and dependencies."""

    image: Image.Image
    artwork: Image.Image
    coverage: np.ndarray
    origin: tuple[int, int]
    stamp: str


def _parse_faces(text: str) -> dict[str, dict[str, str]]:
    """Read original-coordinate face definitions, including shared defaults."""
    sections: dict[str, dict[str, str]] = {}
    section = "DEFAULT"
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].upper()
        elif "=" in line:
            key, value = line.split("=", 1)
            sections.setdefault(section, {})[key.strip().casefold()] = value.strip()
    return sections


@lru_cache(maxsize=8)
def _archived_faces(directory: Path, _catalog_mtime: int) -> str:
    """Read the player's original metadata, never the installed 4x override."""
    archive = BarnArchive.open(directory)
    entry = next(e for e in archive.entries if e.name.upper() == "FACES.TXT")
    with archive.reader() as read:
        return read(entry).decode("latin1")


def _face_text(source: Path) -> str:
    """Allow explicit original metadata beside extracted developer fixtures."""
    local = actual_files(source.parent, suffix=".txt").get("faces.txt")
    if local is not None:
        return local.read_text(encoding="latin1")
    directory = discover_data_directory(source.parent)
    if directory is None:
        msg = (
            f"{source.name}: face-layer AI requires original FACES.TXT or the game's Data directory"
        )
        raise ValueError(msg)
    core = actual_files(directory, suffix=".brn")["core.brn"]
    return _archived_faces(directory, core.stat().st_mtime_ns)


def _point(value: str) -> tuple[int, int]:
    x, y = value.split(",")
    return int(x), int(y)


def _face_config(sections: dict[str, dict[str, str]], prefix: str) -> dict[str, str]:
    """Prefer actor identity, then the explicit layer binding, then shared artwork.

    Different characters can share a face atlas while using different eye
    colors and opacity masks. An atlas-name match alone cannot choose between
    them. Never resolve a genuinely ambiguous binding by file order.
    """
    active = {name: values for name, values in sections.items() if not name.endswith("-XXX")}
    if prefix in active:
        return sections.get("DEFAULT", {}) | active[prefix]
    for field, expected in (
        ("eyelids alpha channel", f"{prefix}_EYELIDS_ALPHA"),
        ("face name", f"{prefix}_FACE"),
    ):
        matches = [
            values for values in active.values() if values.get(field, "").upper() == expected
        ]
        if len(matches) == 1:
            return sections.get("DEFAULT", {}) | matches[0]
        if matches:
            msg = f"ambiguous original face definition for {prefix}"
            raise ValueError(msg)
    msg = f"no original face definition for {prefix}"
    raise ValueError(msg)


def prepare_face_context(source: Path) -> FaceContext:
    """Compose the native face, dynamic eye sources and exact expression layer."""
    paths = actual_files(source.parent, suffix=".bmp")
    prefix = source.stem.split("_", 1)[0].upper()
    text = _face_text(source)
    sections = _parse_faces(text)
    config = _face_config(sections, prefix)
    digest = hashlib.sha256(_RECIPE + text.encode("latin1"))

    def load(name: str) -> Image.Image:
        path = paths.get(name.casefold())
        if path is None:
            msg = f"{source.name}: missing face context source {name}"
            raise ValueError(msg)
        digest.update(name.upper().encode("ascii"))
        digest.update(path.read_bytes())
        with Image.open(path) as image:
            return image.convert("RGB")

    artwork = load(source.name)
    face = load(config.get("face name", f"{prefix}_FACE") + ".BMP")
    x, y = _point(config["eyelids offset"])
    if x < 0 or y < 0 or x + artwork.width > face.width or y + artwork.height > face.height:
        msg = f"{source.name}: original eyelid coordinates exceed the native face atlas"
        raise ValueError(msg)
    coverage = _coverage(source, artwork, config, paths, load)
    # Eye sheets include opaque surround, not just the visible iris. Expose
    # them only inside the authored expression footprint. Magenta outside
    # that footprint means unchanged face, not an additional eye aperture.
    eyes = face.copy()
    _place_eyes(eyes, config, sections, load)
    footprint = (~np.all(np.asarray(artwork) == (255, 0, 255), axis=2) * 255).astype("uint8")
    face.paste(
        eyes.crop((x, y, x + artwork.width, y + artwork.height)),
        (x, y),
        Image.fromarray(footprint),
    )
    bounds = (
        max(0, x - 36),
        max(0, y - 42),
        min(face.width, x + artwork.width + 36),
        min(face.height, y + artwork.height + 52),
    )
    face.paste(artwork, (x, y), Image.fromarray(coverage))
    return FaceContext(
        face.crop(bounds),
        artwork,
        coverage,
        (x - bounds[0], y - bounds[1]),
        digest.hexdigest(),
    )


def _coverage(
    source: Path,
    artwork: Image.Image,
    config: dict[str, str],
    paths: dict[str, Path],
    load: Callable[[str], Image.Image],
) -> np.ndarray:
    """Read scalar coverage separately from the layer's binary magenta key."""
    coverage = (~np.all(np.asarray(artwork) == (255, 0, 255), axis=2) * 255).astype("uint8")
    alpha_name = f"{source.stem}_ALPHA.BMP"
    if source.stem.upper().endswith("_EYELIDS"):
        alpha_name = config.get("eyelids alpha channel", "") + ".BMP"
    elif "_WINK_" in source.stem.upper():
        alpha_name = f"{source.stem.split('_', 1)[0]}_WINK_01_ALPHA.BMP"
    if alpha_name.casefold() in paths:
        alpha = load(alpha_name).convert("L")
        if alpha.size != artwork.size:
            msg = f"{source.name}: opacity dimensions do not match expression artwork"
            raise ValueError(msg)
        coverage = np.minimum(coverage, np.asarray(alpha))
    return coverage


def _place_eyes(
    face: Image.Image,
    config: dict[str, str],
    sections: dict[str, dict[str, str]],
    load: Callable[[str], Image.Image],
) -> None:
    """Put the original downsampled eyeballs behind the transparent expression."""
    for side in ("left", "right"):
        name = config[f"{side} eye name"]
        eye = load(name + ".BMP")
        specification = sections.get("EYES", {}).get(name.casefold(), "4x4")
        sx, sy = (int(v) for v in specification.split(",", 1)[0].strip().split("x"))
        if sx <= 0 or sy <= 0 or eye.width % sx or eye.height % sy:
            msg = "unsupported authored eye sampling grid"
            raise ValueError(msg)
        if "downsampleonly" in specification.casefold():
            eye = eye.resize((eye.width // sx, eye.height // sy), Image.Resampling.BICUBIC)
        eye_x, eye_y = _point(config[f"{side} eye offset"])
        if (
            eye_x < 0
            or eye_y < 0
            or eye_x + eye.width > face.width
            or eye_y + eye.height > face.height
        ):
            msg = "eye context exceeds the native face atlas"
            raise ValueError(msg)
        face.paste(eye, (eye_x, eye_y))


def face_layer_stamp(source: Path, *, detail_sharpening: bool = False) -> str:
    """Invalidate output when original geometry, eyes, face or opacity changes."""
    stamp = prepare_face_context(source).stamp
    return f"{stamp}:detail-sharpening-v1" if detail_sharpening else stamp


def restore_face_layer(
    context: FaceContext, upscaler: ColorUpscaler, *, detail_sharpening: bool = False
) -> Image.Image:
    """Keep authored anatomy and coverage while adding bounded contextual detail."""
    if upscaler.scale != _SCALE:
        msg = "face-layer restoration requires a 4x backend"
        raise ValueError(msg)
    generated = upscaler.upscale(context.image)
    if generated.mode != "RGB" or generated.size != (
        context.image.width * 4,
        context.image.height * 4,
    ):
        msg = "face-layer backend must return a complete 4x RGB context"
        raise ValueError(msg)
    x, y = context.origin
    w, h = context.artwork.size
    crop = np.asarray(generated.crop((x * 4, y * 4, (x + w) * 4, (y + h) * 4)), dtype=np.float64)
    keyed = bool(np.any(np.all(np.asarray(context.artwork) == (255, 0, 255), axis=2)))
    source = upscale_smooth_color(context.artwork, periodic=False, alphatest=keyed)
    pixels = np.asarray(source, dtype=np.float64)
    interior = (
        np.asarray(Image.fromarray(context.coverage).resize(source.size, Image.Resampling.NEAREST))
        >= _OPAQUE_COVERAGE
    )
    # Do not bake inferred eyeballs into partially transparent eyelids, alter
    # aperture geometry, or transfer broad invented folds from the prediction.
    amount = np.clip((distance_transform_edt(interior) - 3) / 5, 0, 1)
    detail = crop - gaussian_filter(crop, (2.0, 2.0, 0), mode="nearest")
    result = np.clip(np.rint(pixels + detail * amount[:, :, None]), 0, 255).astype("uint8")
    result[~interior] = np.asarray(source)[~interior]
    result[np.all(pixels == (255, 0, 255), axis=2)] = (255, 0, 255)
    if detail_sharpening:
        result = _sharpen_opaque_detail(result, interior)
    return Image.fromarray(result)


def _sharpen_opaque_detail(pixels: np.ndarray, interior: np.ndarray) -> np.ndarray:
    """Refine soft covered skin without moving an aperture or amplifying ringing."""
    keyed = np.all(pixels == (255, 0, 255), axis=2)
    covered = interior & ~keyed
    if not covered.any():
        return pixels.copy()
    indices = distance_transform_edt(keyed, return_distances=False, return_indices=True)
    filled = pixels[tuple(indices)].astype(np.float64)
    detail = filled - gaussian_filter(filled, (0.8, 0.8, 0), mode="nearest")
    low = minimum_filter(filled, size=(3, 3, 1), mode="nearest")
    high = maximum_filter(filled, size=(3, 3, 1), mode="nearest")
    refined = np.clip(filled + detail * 0.5, low, high)
    result = pixels.copy()
    result[covered] = np.clip(np.rint(refined[covered]), 0, 255).astype("uint8")
    return result


def regenerate_face_layer(
    source: Path, upscaler: ColorUpscaler | None, *, detail_sharpening: bool = False
) -> Image.Image:
    """Execute the repeatable file-aware variant selected by texture policy."""
    if upscaler is None:
        msg = f"{source.name}: face-layer restoration requires SeedVR2"
        raise ValueError(msg)
    return restore_face_layer(
        prepare_face_context(source), upscaler, detail_sharpening=detail_sharpening
    )
