"""Enlarge scanned fingerprint evidence without inventing ridge or label detail."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

FINGERPRINT_NAMES = frozenset(
    f"S_{identifier}_FPRINT.BMP"
    for identifier in (
        "ABE",
        "EST",
        "HE2",
        "LAR",
        "LHO",
        "MAD",
        "MON",
        "MOS",
        "VIT",
        "WIL",  # codespell:ignore wil
    )
)
# Workstation print colors and their separately sampled opacity companions.
# Their ridge identities are evidence; AI must not invent or erase them.
WORKSTATION_PRINT_SIZES = {
    "FP_BLOMAN_LARPRNT.BMP": (35, 41),
    **{
        f"FP_BLOMAN_P{i}.BMP": size
        for i, size in enumerate(((30, 47), (31, 48), (32, 49), (35, 50), (31, 50), (29, 38)), 1)
    },
    "FP_BOOKIMMORTALS_P1.BMP": (37, 52),
    "FP_BUCHGLASS_P1.BMP": (54, 77),
    "FP_CIGS_P1.BMP": (56, 49),
    "FP_COLT45_P1.BMP": (22, 23),
    "FP_LHOMIR_P1.BMP": (25, 44),
    "FP_LSRENV_P1.BMP": (30, 44),
    "FP_OCTSHOT_P1.BMP": (47, 55),
    "FP_OCTSHOT_P2.BMP": (49, 61),
    "FP_SODA_P1.BMP": (33, 58),
    "FP_SQRSHOT_P1.BMP": (36, 73),
    "FP_SUITCA_P1.BMP": (32, 26),
    "FP_WATBTL_P1.BMP": (27, 38),
}
WORKSTATION_MASK_SIZES = {
    name.removesuffix(".BMP") + "A.BMP": size for name, size in WORKSTATION_PRINT_SIZES.items()
}
# InventorySprites maps these cards to fingerprint evidence nouns. Their
# handwritten labels and ridge patterns must not be reinterpreted by AI.
# The middle inventory view is always 94x94; previews and close-ups vary.
_INVENTORY_CARD_SIZES = {
    "ABBEPRNT": ((32, 30), (305, 400)),
    "BUCHPRNT": ((30, 32), (283, 392)),
    "VITPRNTWILKESNAME": ((32, 30), (282, 386)),
    "MADPRNT": ((32, 30), (284, 392)),
    "ESTPRNT": ((32, 30), (291, 400)),
    "ESTPRINTGRA": ((32, 30), (304, 400)),
    "LSRPRINTESTELLE_": ((32, 30), (288, 400)),
    "LHOPRNT": ((32, 30), (320, 400)),
    "LARPRNT": ((32, 30), (317, 400)),
    "MONTPRNT": ((32, 30), (320, 399)),
    "MANU1PRINT_": ((30, 32), (283, 400)),
    "MANU2PRINT_": ((30, 32), (288, 400)),
    "MANU3PRINT_": ((30, 32), (304, 400)),
    "MANU4PRINT": ((30, 32), (304, 400)),
    "MANU5PRINT": ((30, 32), (287, 392)),
    "MANU6PRINT": ((30, 32), (301, 400)),
    "LSRPRINTGRACE_": ((32, 30), (293, 400)),
    "WILKESPRNT": ((32, 30), (304, 400)),
    "WILKWBUCHPRNT": ((30, 32), (304, 399)),
}
INVENTORY_FINGERPRINT_SIZES = {
    f"{prefix}{suffix}.BMP": size
    for prefix, (preview, closeup) in _INVENTORY_CARD_SIZES.items()
    for suffix, size in (("3", preview), ("9", (94, 94)), ("6_ALPHA", closeup))
} | {
    "MOSELYPRINT_3.BMP": (32, 30),
    "MOSELYPRINT_6_ALPHA.BMP": (307, 400),
    "MOSELYPRINT_9.BMP": (94, 94),
}
EVIDENCE_FINGERPRINT_FAMILIES = ("BUCH_BLD", "BUTH_BLD", "EST_LSR", "MOS_BLD")
COMPARISON_FINGERPRINT_NAMES = frozenset(
    f"{prefix}_COMPARE.BMP" for prefix in EVIDENCE_FINGERPRINT_FAMILIES
)
EVIDENCE_FINGERPRINT_NAMES = frozenset(
    name
    for prefix in EVIDENCE_FINGERPRINT_FAMILIES
    for name in (
        f"{prefix}_PRINT.BMP",
        f"{prefix}_COMPARE.BMP",
        f"{prefix.replace('_', '_RED_', 1)}_PRINT.BMP",
    )
)
FINGERPRINT_SIZES = {
    **WORKSTATION_PRINT_SIZES,
    **WORKSTATION_MASK_SIZES,
    **dict.fromkeys(FINGERPRINT_NAMES, (41, 51)),
    **dict.fromkeys(EVIDENCE_FINGERPRINT_NAMES, (41, 51)),
    **INVENTORY_FINGERPRINT_SIZES,
}


def is_fingerprint(name: str) -> bool:
    """Recognize suspect scans, evidence fragments and the inventory card."""
    return Path(name).name.upper() in FINGERPRINT_SIZES


def regenerate_fingerprint(source: Path) -> Image:
    """Resample the complete source at 4x with deterministic bicubic reconstruction.

    These tiny photographic scans contain ridge identities, not freely inferred
    surface detail. AI can replace their noisy source with a different pattern.
    Bicubic interpolation keeps the source structure, including its uncertainty;
    no sharpening, thresholding, ridge synthesis, or geometric warp is applied.
    """
    from PIL import Image as PillowImage  # noqa: PLC0415

    if not is_fingerprint(source.name):
        msg = f"not a recognized fingerprint: {source.name}"
        raise ValueError(msg)
    with PillowImage.open(source) as original:
        width, height = FINGERPRINT_SIZES[source.name.upper()]
        if original.size != (width, height):
            msg = (
                f"{source.name}: expected a {width}x{height} source fingerprint, "
                f"got {original.size}"
            )
            raise ValueError(msg)
        size = (width * 4, height * 4)
        if source.name.upper() in WORKSTATION_PRINT_SIZES:
            from gk3hd.textures.upscale.pipeline import resample_keyed_art  # noqa: PLC0415

            # The workstation's native blend treats pure black as a key.
            # Interpolating that hidden black into the ridge contour creates
            # a dark outline at high resolution; bleed RGB separately.
            return resample_keyed_art(original, scale=4, key_color=(0, 0, 0), sample_aligned=True)
        if source.name.upper() in WORKSTATION_MASK_SIZES:
            return original.convert("L").transform(
                size,
                PillowImage.Transform.AFFINE,
                (0.25, 0, -0.125, 0, 0.25, -0.125),
                PillowImage.Resampling.BICUBIC,
            )
        rgb = original.convert("RGB")
        if source.name.upper() in COMPARISON_FINGERPRINT_NAMES:
            return _resample_comparison(rgb, size)
        return rgb.resize(size, PillowImage.Resampling.BICUBIC)


def _resample_comparison(original: Image, size: tuple[int, int]) -> Image:
    """Resample clipped evidence without mixing its magenta holes into ridges.

    Pillow resizes RGBA with premultiplied alpha, excluding transparent colors
    from the interpolation. Restore the exact rectangular comparison windows
    with nearest-neighbor coverage: their edges select evidence, not a soft
    material contour. The engine still receives an RGB color-keyed bitmap.
    """
    from PIL import Image as PillowImage  # noqa: PLC0415
    from PIL import ImageChops  # noqa: PLC0415

    key_color = (255, 0, 255)
    difference = ImageChops.difference(original, PillowImage.new("RGB", original.size, key_color))
    red, green, blue = difference.split()
    opaque = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(
        lambda value: 255 if value else 0
    )
    rgba = original.convert("RGBA")
    rgba.putalpha(opaque)
    result = rgba.resize(size, PillowImage.Resampling.BICUBIC).convert("RGB")
    transparent = ImageChops.invert(opaque).resize(size, PillowImage.Resampling.NEAREST)
    result.paste(key_color, mask=transparent)
    return result


def is_current_fingerprint(source: Path, destination: Path) -> bool:
    """Reject older AI results and refresh output when the source changes."""
    from PIL import Image as PillowImage  # noqa: PLC0415

    expected = regenerate_fingerprint(source)
    with PillowImage.open(destination) as candidate:
        return (
            candidate.mode == expected.mode
            and candidate.size == expected.size
            and candidate.tobytes() == expected.tobytes()
        )
