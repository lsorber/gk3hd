"""Conservative enlargement of reviewed opaque menu artwork."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray
    from PIL.Image import Image

CONSERVATIVE_MENU_SIZES: dict[str, tuple[int, int]] = {
    f"{family}_{state}.BMP": (32, 32)
    for family in (
        # Shaded character portraits, with no verified larger matching render.
        "I_ABBE",
        "I_BUTHANE",
        "I_EML",
        "I_GABE",
        "I_GABE_GRACE",
        "I_GRACE",
        "I_HENCHMEN",
        "I_LHO",
        "I_MONTREAUX",
        "I_MOSELY",
        "I_VIT",
        "I_WILKES",
        # Keep the original printed artwork where larger inventory views differ.
        "I_PRESSCARD",
        "I_COORDPAPER",
        "I_SUMNOTE",
        "I_SYMBOLSNOTE",
        "I_PASSPORT",
        # Processed skull renders and shaded gesture illustrations, not the
        # flat, deliberately pixel-drawn I_VAMPIRES family.
        "I_DEADGUYS",
        "I_VAMPIRE",
        "I_HANDSHAKEA",
        "I_HANDSHAKEB",
        "I_HANDSHAKEC",
        "I_HANDSHAKED",
        "I_HANDSHAKEE",
        # The original handshake and petting illustrations also have shaded
        # skin/fur interiors. Preserve their shapes and native area samples.
        "I_HANDSHAKE",
        "I_PET",
        # Shaded navigation arrows and conceptual illustrations; keep these
        # separate from flat pixel-defined arrows and dithered pictograms.
        "I_ARROWDOWN",
        "I_ARROWFORWARD",
        "I_ARROWLEFT",
        "I_ARROWRIGHT",
        "I_ARROWUP",
        "I_BURNING",
        "I_BURYING",
        "I_ERASE",
        "I_FREEMASONTREASURE",
        "I_FREEMAS",
        "I_HOTELSTAFF",
        "I_PRIORYTREASURE",
        "I_SCALE",
        "I_SEARCH",
        "I_SELLING",
        "I_THINK",
        "I_TURN_LOCK",
        "I_DONTNO",
        # Shaded original artwork whose larger inventory views differ in
        # lighting, composition or markings. AI also changes their contours.
        "I_BLKFIBER",
        "I_GAUNTLET",
        "I_GRANOTEBOOK",
        "I_MON",
        "I_POEMNOTE",
        "I_SIDNEY",
        "I_STONE",
        # The room-key illustrations have different ring/shaft artwork from
        # the larger inventory view. Preserve their complete authored states.
        "I_GRARM",
        "I_ROOMKEY",
    )
    for state in ("STD", "HOV", "DWN")
} | dict.fromkeys(
    # Older authored states, not inferred complete STD/HOV/DWN families.
    # The shaded hose coils benefit from the same conservative reconstruction;
    # retain their original loop shapes, highlights and button bevels.
    (
        "I_MACHINE.BMP",
        "I_MOSE_ROOM_KEY.BMP",
        "I_HOSE_STD.BMP",
        "I_HOSE_DWN.BMP",
        "I_UNCOIL.BMP",
        "I_UNCOILD.BMP",
    ),
    (32, 32),
)

# The current right-click toolbar shares opaque source storage, but its renderer
# owns a separate layout affine. Include disabled originals, not grayscale
# versions synthesized from another state, and retain the older exit spellings.
TOOLBAR_ART_SIZES: dict[str, tuple[int, int]] = {
    f"RC_{family}_{state}.BMP": (32, 32)
    for family in (
        "CAMERAS",
        "CINEMATICOFF",
        "CINEMATIC",
        "DIAL_CAMERAS",
        "EXIT",
        "HELP",
        "HINTS",
        "INVENTORY_CLOSE",
        "INVENTORY_OPEN",
        "OPTIONS",
        "RADIO",
        "TAPE",
    )
    for state in ("STD", "HOV", "DWN", "DIS")
} | dict.fromkeys(
    ("RC_INVENTORY_EXIT.BMP", "RC_INVENTORY_EXIT_HOV.BMP", "RC_INVENTORY_EXITD.BMP"), (32, 32)
)
# Opaque control artwork with baked markings. Preserve each authored state,
# including disabled variants and nonstandard names, without redrawing letters.
MENU_CONTROL_ART_SIZES: dict[str, tuple[int, int]] = (
    {
        f"{family}_{state}.BMP": (32, 32)
        for family in ("I_CANCEL", "I_CASE", "I_OPERATE", "I_RLC", "I_SION", "I_WAKEUPCALL")
        for state in ("STD", "HOV", "DWN")
    }
    | {
        f"{family}_{state}.BMP": (32, 32)
        for family in ("I_INSPECT", "I_ZOOMOUT")
        for state in ("STD", "HOV", "DWN", "DIS")
    }
    | dict.fromkeys(
        (
            "I_EXIT_STD.BMP",
            "I_EXIT_HOV.BMP",
            "I_EXIT_DOWN.BMP",
            "I_BLANKBTN_U.BMP",
            "I_BLANKBTN_D.BMP",
            "I_TURN_PAGE_BACK.BMP",
            "I_TURN_PAGE_FWD.BMP",
        ),
        (32, 32),
    )
)
CONSERVATIVE_MENU_SIZES |= TOOLBAR_ART_SIZES | MENU_CONTROL_ART_SIZES


def resample_menu_art(image: Image) -> Image:
    """Add shaded samples while preserving native RGB565 area-filtered pixels.

    Treat each source pixel as a cell average, not a point sample. Symmetric
    subdivisions preserve those averages, and limited slopes avoid ringing at
    printed marks, faces and bevels. Work in the actual 5/6/5-bit channel
    space so the game's quantization cannot shift the native reference colors.
    This recovers no missing detail and never substitutes faces or lettering.
    It is not a resampler for font atlases, keyed coverage, opacity or data textures.
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image as PillowImage  # noqa: PLC0415

    if image.mode != "RGB":
        msg = "menu reconstruction requires opaque RGB artwork"
        raise ValueError(msg)
    native = np.asarray(image, dtype=np.uint8) >> np.array([3, 2, 3], dtype=np.uint8)
    dense = np.rint(_subdivide_axis(_subdivide_axis(native.astype(np.float64), 1), 0))
    # Floor-scaled PNG channels round-trip exactly through encode_rgb565.
    rgb = dense.astype(np.uint16) * 255 // np.array([31, 63, 31], dtype=np.uint16)
    return PillowImage.fromarray(rgb.astype(np.uint8))


def _subdivide_axis(data: NDArray[np.float64], axis: int) -> NDArray[np.float64]:
    """Split each cell into four samples with a bounded, mean-preserving slope."""
    import numpy as np  # noqa: PLC0415

    values = np.moveaxis(data, axis, 0)
    padded = np.concatenate((values[:1], values, values[-1:]), axis=0)
    left, right = values - padded[:-2], padded[2:] - values
    centered = (left + right) / 2
    slope = np.where(
        left * right > 0,
        np.sign(centered)
        * np.minimum(np.abs(centered), np.minimum(2 * np.abs(left), 2 * np.abs(right))),
        0,
    )
    offsets = np.array([-0.375, -0.125, 0.125, 0.375]).reshape((1, 4) + (1,) * (values.ndim - 1))
    result = values[:, None] + slope[:, None] * offsets
    result = result.reshape((values.shape[0] * 4, *values.shape[1:]))
    return np.moveaxis(result, 0, axis)
