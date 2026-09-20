"""Source-faithful enlargement of UI artwork and navigation controls."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd.textures.upscale.cursor_art import (
    CURSOR_ART_SIZES,
    CURSOR_OPACITY_SIZES,
    regenerate_cursor_art,
)
from gk3hd.textures.upscale.menu_art import CONSERVATIVE_MENU_SIZES

if TYPE_CHECKING:
    from PIL.Image import Image

# Shaded legacy button artwork, unlike the seven pixel-defined toolbar glyphs.
# Exact dimensions are shared with the native UI density matcher. These assets
# have renderer-fixture coverage; their older layout has no verified retail entry.
LEGACY_TOOLBAR_ART_SIZES = {
    "TBBTBAKPAKCU.BMP": (22, 22),
    "TBBTBAKPAKOU.BMP": (22, 27),
    "TBBTCAMERA_D.BMP": (22, 24),
    "TBBTCAMERA_G.BMP": (22, 22),
    "TBBTCAMERA_U.BMP": (22, 24),
    "TBBTEXIT___U.BMP": (22, 22),
}

BINOCULAR_CONTROL_SIZES = {
    "BINOCBTNAREA.BMP": (112, 116),
    **{
        f"BINOCBTN{direction}{state}.BMP": size
        for direction, size in (
            ("UP", (25, 45)),
            ("DOWN", (25, 45)),
            ("LEFT", (45, 25)),
            ("RIGHT", (45, 25)),
        )
        for state in ("D", "U")
    },
}
BINOCULAR_MASK_NAME = "BINOCMASK.BMP"
# The fingerprint workstation owns these as moving UI images, not ordinary
# cursors. Keep complete state families and exact source extents: this catalog
# drives analysis, reconstruction and the matching engine contract tests.
FINGERPRINT_TOOL_SIZES = {
    "C_FPBRUSH.BMP": (24, 114),
    "C_FPBRUSH_WDUST.BMP": (24, 114),
    "C_FPTAPE_FP.BMP": (33, 54),
    "C_FPTAPE_NOFP.BMP": (33, 54),
}
SIDNEY_SHAPE_SIZES = {
    f"{name}.BMP": (64, 64) for name in ("TRIANGLE", "CIRCLE", "RECTANGLE", "HEXAGRAM")
}
GPS_CONTROL_SIZES = {
    **{
        f"GPS{part}_{suffix}.BMP": size
        for suffix, line, target in (
            ("L", (205, 3), (20, 21)),
            ("M", (193, 3), (20, 21)),
            ("S", (128, 2), (12, 13)),
        )
        for part, size in (("HLINE", line), ("VLINE", line[::-1]), ("TARGET", target))
    },
    **{
        f"GPSPOWER_{state}_{suffix}.BMP": size
        for suffix, size in (("L", (37, 35)), ("M", (34, 33)), ("S", (23, 22)))
        for state in ("OFF_UP", "ON_DOWN", "ON_UP")
    },
}
GPS_MAP_SIZES = {
    f"GPS{location}_{variant}{opacity}.BMP": size
    for location in ("BEC", "LER", "MCF")
    for variant, size in (("L", (222, 332)), ("M", (208, 311)), ("S", (139, 208)))
    for opacity in ("", "_ALPHA")
}
SIDNEY_MAP_SIZES = {"SIDNEYBIGMAP.BMP": (1368, 1368), "SIDNEYLITTLEMAP.BMP": (342, 342)}
SIDNEY_SHARED_CONTROL_SIZES = {
    **{f"CLOSEWIN_{state}.BMP": (16, 16) for state in ("UP", "HOVER", "DOWN")},
    "SIDNEYBULLET.BMP": (15, 15),
    "S_FROM_TO.BMP": (38, 61),
    "HORIZONTALRULE.BMP": (640, 15),
}
SIDNEY_MAP_OVERLAY_SIZES = {
    "SERPENT.BMP": (177, 208),
    "SERPLITMAP.BMP": (47, 52),
    "MAPLG_THE.BMP": (40, 31),
    "MAPLG_SITE.BMP": (46, 32),
    "MAPSM_THE.BMP": (18, 16),
    "MAPSM_SITE.BMP": (20, 13),
}
PARCHMENT_SIZES = {"PARCHMENT1_BASE.BMP": (432, 384), "PARCHMENT2_BASE.BMP": (390, 424)}
# Complete LSR pages contain literal handwritten puzzle prose, not scenery
# for AI to reinterpret. Their FIN/LIT overlays preserve the same lettering.
ZODIAC_PAGE_SIZES = {f"LSR_PG{page}_BASE.BMP": (640, 400) for page in range(1, 7)}
ZODIAC_OVERLAY_SIZES = {
    f"LSR_PG{page}_{sign}_{state}.BMP": size
    for page, sign, size in (
        (1, "AQU", (305, 142)),
        (1, "PIS", (307, 178)),
        (2, "ARI", (294, 172)),
        (2, "TAU", (308, 183)),
        (3, "GEM", (299, 232)),
        (3, "CAN", (299, 97)),
        (3, "LEO", (311, 149)),
        (4, "VIR", (292, 176)),
        (4, "LIB", (309, 209)),
        (5, "SCO", (294, 191)),
        (5, "OPH", (312, 190)),
        (6, "SAG", (323, 166)),
        (6, "CAP", (340, 221)),
    )
    for state in ("FIN", "LIT")
}
SIDNEY_CLUE_SIZES = {
    "POUSSIN_ZOOM.BMP": (215, 209),
    "TENIERS_ZOOM.BMP": (214, 217),
    "ZION_ROT.BMP": (115, 115),
    "SION.BMP": (67, 46),
    "PYTHAGORAS.BMP": (289, 289),
}
SIDNEY_ID_SIZES = {
    f"{character}_{profession}.BMP": (254, 164)
    for character in ("GAB", "GRA")
    for profession in (
        "AUTO",
        "BLOOD",
        "CORONER",
        "DIAPER",
        "DOC",
        "ELEC",
        "EMONTHLY",
        "ENCY",
        "FREELANCE",
        "NOPD",
        "NYTIMES",
        "PLUMB",
        "SECURITY",
        "SHOES",
        "SPORTSI",
    )
}
SIDNEY_GEOMETRY_SIZES = {
    **{f"SID_SYMB_{index}.BMP": (94, 94) for index in range(1, 5)},
    "GEOMPARCH1FINAL.BMP": (432, 384),
    "GEOMPARCH2FINAL.BMP": (390, 424),
    "GEOMPOUSSINFINAL.BMP": (431, 350),
    "GEOMTENNIERSFINAL.BMP": (464, 350),
    "TENIERGEOA.BMP": (464, 350),
    "TENIERGEOB.BMP": (464, 350),
    "TENIERGEOC.BMP": (464, 350),
}
SIDNEY_GEOMETRY_KEYS = {
    name: (0, 255, 0) if name.startswith("TENIERGEO") else (255, 0, 255)
    for name in SIDNEY_GEOMETRY_SIZES
}

SIDNEY_NAVIGATION_SIZES = {
    "S_BAR_STRETCH.BMP": (2, 13),
    "S_BAR_TOPANGLE_LR.BMP": (12, 10),
    "S_BAR_TOPSTRIP_LR.BMP": (1, 10),
    "S_DWNARW.BMP": (7, 6),
    "S_DWNARW_NOEMB.BMP": (7, 6),
    "S_SLIDER_DWNARROW.BMP": (6, 6),
    "S_SLIDER_UPARROW.BMP": (6, 6),
    "S_ID_BRACKET.BMP": (45, 11),
}

SIDNEY_SEPARATOR_SIZES = {"S_BIT_SPACE1.BMP": (2, 1)}
# S_BIT_SPACE2 is a constant fill: its native 1x12 raster already expresses
# the intended blank separator, so it does not need a generated replacement.
SIDNEY_FRAME_SIZES = {
    f"{name}{suffix}.BMP": size
    for name, size in (
        ("S_BOX_CORNER", (2, 1)),
        ("S_BOX_CORNER_BL", (2, 2)),
        ("S_BOX_CORNER_BR", (2, 2)),
        ("S_BOX_CORNER_TL", (2, 2)),
        ("S_BOX_CORNER_TR", (2, 2)),
        ("S_BOX_SIDE", (1, 4)),
        ("S_BOX_TOP", (8, 1)),
        ("S_BUT_SIDE", (1, 13)),
        ("S_BUT_STRETCH", (1, 13)),
        ("S_BUT14_SIDE", (1, 13)),
        ("S_BUT14_STRETCH", (1, 13)),
        ("S_BUT18_SIDE", (1, 18)),
        ("S_BUT18_STRETCH", (1, 18)),
    )
    for suffix in ("", "_L")
}
# Unlike the gold variants and button strips, these six BRN originals are
# standard 24-bit BMPs. Preserve their loader path: native565 encoding changes
# the gray frame by one green-channel step relative to the unmodified game.
STANDARD_BMP_UI_NAMES = (
    frozenset(
        f"S_BOX_{part}.BMP"
        for part in ("CORNER_BL", "CORNER_BR", "CORNER_TL", "CORNER_TR", "SIDE", "TOP")
    )
    # Color GPS maps were native RGB565 in the BRNs, despite extraction's
    # portable 24-bit BMPs. Only their paired 8-bit opacity was standard BMP.
    | {name for name in GPS_MAP_SIZES if name.endswith("_ALPHA.BMP")}
    | CURSOR_OPACITY_SIZES.keys()
)
CONSOLE_PATTERN_SIZES = {
    "MINISNAKY.BMP": (30, 30),
    "SNAKY.BMP": (100, 100),
}
OPTIONS_PANEL_SIZES = {
    f"{name}.BMP": (252, height)
    for name, height in (
        ("RC_PANEL", 75),
        ("GAMESC", 102),
        ("GRAPHSC", 124),
        ("ADVOPTSC", 134),
        ("SOUNDSC", 212),
    )
}
DIALOG_ART_SIZES = {"QUITGAME.BMP": (595, 218), "PAUSED.BMP": (140, 37)}
# The legacy riddle's handwriting and page perspective differ from its newer
# close-up. Preserve those source samples; AI or another page would change text.
LEGACY_DOCUMENT_SIZES = {"BLUEAPPLE.BMP": (640, 480)}
TIMEBLOCK_BUTTON_SIZES = {
    f"TB_{label}_{state}.BMP": (81, 26)
    for label in ("CONT", "SAVE")
    for state in ("U", "H", "D", "X")
}
TITLE_BUTTON_SIZES = {
    f"TITLE_{label}_{state}.BMP": (81, 26)
    for label in ("INTRO", "PLAY", "RESTORE", "QUIT")
    for state in ("U", "H", "D", "X")
}
DEATH_BUTTON_SIZES = {
    f"DS_{group}_{state}.BMP": (81, 26)
    for group in ("RTRY", "REST", "QUIT")
    for state in ("N", "H", "D", "X")
}
QUIT_BUTTON_SIZES = {
    f"QG_{label}_{state}.BMP": (width, 26)
    for label, width in (("YES", 81), ("NO", 81), ("TS", 117))
    for state in ("U", "H", "D")
}
HELP_BUTTON_SIZES = {
    f"{label}_{state}.BMP": (49, 28)
    for label in ("PREV", "NEXT", "EXIT")
    for state in ("U", "H", "D")
}
MESSAGE_BUTTON_SIZES = {
    f"MSG_{label}_{state}.BMP": (46, 26)
    for label in ("YES", "NO", "OK")
    for state in ("U", "H", "D")
}
LOAD_SAVE_BUTTON_SIZES = {
    f"{label}{state}.BMP": (width, 38 if label != "EXIT" and state == "D" else height)
    for label, width, height in (("EXIT", 58, 26), ("RESTORE", 145, 39), ("SAVE", 145, 39))
    for state in ("D", "DIS", "HOV", "N")
}
OPTIONS_TAB_SIZES = {
    f"OP_{label}_{state}.BMP": (width, 29)
    for label, width in (("GAMOPT", 73), ("GROPT", 72), ("SOPT", 73))
    for state in ("R", "HI", "DWN")
}
OPTIONS_ACTION_SIZES = {
    f"{label}_{state}.BMP": (width, 17)
    for label, width in (("GAMOP_CMS", 150), ("GROPT_AGOPT", 165))
    for state in ("R", "HI", "DWN")
}
SIDNEY_TAB_SIZES = {
    f"B_{label}_{state}.BMP": (76, 13)
    for label in ("ADDATA", "ANALYZE", "EMAIL", "FILES", "MAKEID", "SEARCH", "SUSPT", "TRANSL")
    for state in ("U", "H", "D", "X")
}
BINOCULAR_LABEL_SIZES = {
    "BINOCBTNEXITD.BMP": (134, 31),
    "BINOCBTNEXITDIS.BMP": (135, 30),
    "BINOCBTNEXITHOV.BMP": (135, 30),
    "BINOCBTNEXITU.BMP": (135, 30),
    "BINOCBTNZOOMIND.BMP": (134, 30),
    "BINOCBTNZOOMINDIS.BMP": (135, 30),
    "BINOCBTNZOOMINHOV.BMP": (135, 29),
    "BINOCBTNZOOMINU.BMP": (134, 30),
    "BINOCBTNZOOMOUTD.BMP": (134, 30),
    "BINOCBTNZOOMOUTDIS.BMP": (135, 30),
    "BINOCBTNZOOMOUTHOV.BMP": (134, 30),
    "BINOCBTNZOOMOUTU.BMP": (134, 30),
}
MONOTONE_BUTTON_SIZES = (
    DEATH_BUTTON_SIZES
    | TITLE_BUTTON_SIZES
    | TIMEBLOCK_BUTTON_SIZES
    | QUIT_BUTTON_SIZES
    | HELP_BUTTON_SIZES
    | MESSAGE_BUTTON_SIZES
    | LOAD_SAVE_BUTTON_SIZES
    | OPTIONS_TAB_SIZES
    | OPTIONS_ACTION_SIZES
    | SIDNEY_TAB_SIZES
    | BINOCULAR_LABEL_SIZES
)
OPTIONS_LABEL_SIZES = {
    "ADVOP_ANI_DIS.BMP": (164, 16),
    "ADVOP_ANI_R.BMP": (164, 16),
    "ADVOP_LOD_DIS.BMP": (36, 12),
    "ADVOP_LOD_R.BMP": (36, 12),
    "ADVOP_MIPMAP_DIS.BMP": (96, 16),
    "ADVOP_MIPMAP_R.BMP": (95, 16),
    "ADVOP_TRI_DIS.BMP": (139, 19),
    "ADVOP_TRI_R.BMP": (139, 19),
    "GROPT_GAM_DIS.BMP": (204, 17),
    "GROPT_INREND_DIS.BMP": (158, 21),
    "GROPT_INREND_R.BMP": (158, 21),
}
UI_ART_SIZES = {
    **LEGACY_DOCUMENT_SIZES,
    **LEGACY_TOOLBAR_ART_SIZES,
    **CURSOR_ART_SIZES,
    **CURSOR_OPACITY_SIZES,
    **FINGERPRINT_TOOL_SIZES,
    **CONSERVATIVE_MENU_SIZES,
    **CONSOLE_PATTERN_SIZES,
    **OPTIONS_PANEL_SIZES,
    **DIALOG_ART_SIZES,
    **MONOTONE_BUTTON_SIZES,
    **OPTIONS_LABEL_SIZES,
    **SIDNEY_SHARED_CONTROL_SIZES,
    **PARCHMENT_SIZES,
    **ZODIAC_PAGE_SIZES,
    **ZODIAC_OVERLAY_SIZES,
    **SIDNEY_CLUE_SIZES,
    **SIDNEY_ID_SIZES,
    **SIDNEY_GEOMETRY_SIZES,
    **SIDNEY_MAP_SIZES,
    **SIDNEY_MAP_OVERLAY_SIZES,
    **GPS_MAP_SIZES,
    **GPS_CONTROL_SIZES,
    **SIDNEY_SHAPE_SIZES,
    **BINOCULAR_CONTROL_SIZES,
    BINOCULAR_MASK_NAME: (640, 480),
    **SIDNEY_NAVIGATION_SIZES,
    **SIDNEY_FRAME_SIZES,
    **SIDNEY_SEPARATOR_SIZES,
    "RC_ARW_DWN.BMP": (17, 15),
    "RC_ARW_HI.BMP": (17, 15),
    "RC_ARW_R.BMP": (17, 15),
    "RC_BUT_CHK.BMP": (17, 15),
    "RC_BUT_DIS.BMP": (17, 15),
    "RC_BUT_R.BMP": (17, 15),
    "RC_DROPDOWN.BMP": (252, 132),
    "RC_DROPDOWN_LINK.BMP": (14, 4),
    "RC_SO_DROPDOWN.BMP": (252, 52),
    "RC_SO_SLIDER.BMP": (4, 8),
    "HELP_BOX_CORNER_BL.BMP": (2, 2),
    "HELP_BOX_CORNER_BR.BMP": (2, 2),
    "HELP_BOX_CORNER_TL.BMP": (2, 2),
    "HELP_BOX_CORNER_TR.BMP": (2, 2),
    "HELP_BOX_SIDE.BMP": (1, 4),
    "HELP_BOX_TOP.BMP": (8, 1),
    "MSG_BOX_CORNER_LL.BMP": (5, 5),
    "MSG_BOX_CORNER_LR.BMP": (5, 5),
    "MSG_BOX_CORNER_UL.BMP": (5, 5),
    "MSG_BOX_CORNER_UR.BMP": (5, 5),
    "MSG_BOX_HORIZ.BMP": (1, 5),
    "MSG_BOX_VERT.BMP": (5, 1),
    "RC_BOX_CORNER_BL.BMP": (2, 2),
    "RC_BOX_CORNER_BR.BMP": (2, 2),
    "RC_BOX_CORNER_TL.BMP": (2, 2),
    "RC_BOX_CORNER_TR.BMP": (2, 2),
    "RC_BOX_SIDE.BMP": (1, 4),
    "RC_BOX_TOP.BMP": (8, 1),
    "INV_HIGHLIGHT.BMP": (99, 98),
    "INV_SCROLLBACK.BMP": (22, 22),
    "INV_SCROLLDN_DIS.BMP": (22, 20),
    "INV_SCROLLDN_DWN.BMP": (22, 20),
    "INV_SCROLLDN_HOV.BMP": (22, 20),
    "INV_SCROLLDN_STD.BMP": (22, 20),
    "INV_SCROLLUP_DIS.BMP": (22, 20),
    "INV_SCROLLUP_DWN.BMP": (22, 20),
    "INV_SCROLLUP_HOV.BMP": (22, 20),
    "INV_SCROLLUP_STD.BMP": (22, 20),
    "SAVELOAD_SCROLLBACK.BMP": (22, 22),
    "SAVELOAD_SCROLLDN_DIS.BMP": (22, 20),
    "SAVELOAD_SCROLLDN_DWN.BMP": (22, 20),
    "SAVELOAD_SCROLLDN_HOV.BMP": (22, 20),
    "SAVELOAD_SCROLLDN_STD.BMP": (22, 20),
    "SAVELOAD_SCROLLUP_DIS.BMP": (22, 20),
    "SAVELOAD_SCROLLUP_DWN.BMP": (22, 20),
    "SAVELOAD_SCROLLUP_HOV.BMP": (22, 20),
    "SAVELOAD_SCROLLUP_STD.BMP": (22, 20),
}
_PIXEL_ALIGNED = frozenset(
    {
        name
        for name in UI_ART_SIZES
        if name.startswith(("HELP_BOX_", "MSG_BOX_", "RC_")) and name not in OPTIONS_PANEL_SIZES
    }
    | {
        "INV_HIGHLIGHT.BMP",
        "INV_SCROLLBACK.BMP",
        "SAVELOAD_SCROLLBACK.BMP",
        "S_FROM_TO.BMP",
        "HORIZONTALRULE.BMP",
    }
    | SIDNEY_FRAME_SIZES.keys()
    | SIDNEY_SEPARATOR_SIZES.keys()
    | SIDNEY_NAVIGATION_SIZES.keys()
    | BINOCULAR_CONTROL_SIZES.keys()
    | {name for name in GPS_CONTROL_SIZES if not name.startswith("GPSPOWER_")}
)
_SAMPLE_ALIGNED = (
    frozenset(SIDNEY_SHAPE_SIZES)
    | (SIDNEY_SHARED_CONTROL_SIZES.keys() - _PIXEL_ALIGNED)
    | GPS_MAP_SIZES.keys()
    | SIDNEY_MAP_SIZES.keys()
    | PARCHMENT_SIZES.keys()
    | ZODIAC_PAGE_SIZES.keys()
    | SIDNEY_CLUE_SIZES.keys()
    | SIDNEY_ID_SIZES.keys()
    | OPTIONS_PANEL_SIZES.keys()
    | DIALOG_ART_SIZES.keys()
    | {name for name in GPS_CONTROL_SIZES if name.startswith("GPSPOWER_")}
)


def is_geometric_ui(name: str) -> bool:
    """Recognize tested controls, not arbitrary small or low-palette images."""
    return Path(name).name.upper() in UI_ART_SIZES


def ui_art_output_mode(name: str, source_mode: str) -> str:
    """Keep sampled grayscale opacity separate from opaque RGB reconstruction."""
    if name.upper() in CURSOR_OPACITY_SIZES:
        return "L"
    return "L" if name.upper() in _SAMPLE_ALIGNED and source_mode == "L" else "RGB"


def regenerate_ui_art(source: Path) -> Image:
    """Enlarge crisp frames exactly and interpolate shaded arrow buttons at 4x.

    The axis-aligned highlight and repeating track have no missing diagonal
    detail: exact pixel replication preserves their border thickness, palette
    and binary magenta key. The arrow buttons already encode shaded contours;
    bicubic interpolation preserves those without AI changing bevels or corners.
    Options controls retain their exact pixel-aligned bevels, checkbox symbols
    and thin slider graduations through replication, including their arrows.
    No sharpening, invented geometry or font reconstruction is performed.
    Binocular directional overlays and their base share exact replication to
    preserve their alignment. The separate aperture reconstructs its binary
    contour without submitting the dark surround to AI.
    The two moving fingerprint brushes preserve their shaded tool artwork with
    aligned color-key contours; their UI-image ownership differs from cursors.
    SIDNEY's four shape-selector illustrations interpolate their original
    line coverage; they do not reconstruct or alter the map's puzzle geometry.
    GPS crosshairs retain exact line thickness and binary keys; power buttons
    interpolate the existing shading without shifting reference-size samples.
    GPS map contours, labels and paired opacity use that same sample alignment;
    grayscale opacity remains grayscale, with no invented contour geometry.
    SIDNEY's overview and detailed map preserve their authored labels and
    coordinates through the same interpolation. The engine selects between
    these real cartographic detail levels according to presentation scale.
    The serpent trail and map-site lettering preserve authored placement with
    aligned, unbiased color-key contours; AI must not redraw these puzzle marks.
    Parchment lettering is scanned artwork, not a replaceable font atlas.
    Le Serpent Rouge's six complete pages retain that same source lettering
    and native sample alignment rather than generating replacement handwriting.
    Its completed/active section overlays use identical sample alignment, with
    unbiased key contours where holes reveal the underlying page (Gemini).
    Its geometric clue overlays use aligned, unbiased binary contours so
    reconstruction neither invents letters nor shifts the indicated characters.
    The four hermetic e-mail diagrams use the same source-aligned contours:
    their red strokes are authored illustrations, not font-atlas glyphs.
    Zoomed inscriptions and illustrated search clues preserve their embedded
    lettering and linework; these are authored clues, not AI-restored scenery.
    Shared close buttons and search bullets interpolate their authored shading
    at the same reference sample phase; translation dividers retain exact lines.
    Printed ID cards preserve their baked logos, signatures, fine rules and
    portraits together. Interpolation adds samples without inventing letters
    or substituting faces; these complete illustrations are not font atlases.
    Options panels likewise preserve their baked labels, recessed fields and
    slider graduations together at the reference sample phase.
    Pause and quit illustrations preserve their gold lettering, medallion and
    beveled frames together, without AI inventing replacement ornamentation.
    Baked dialog, Help and Options buttons use sample-aligned monotone reconstruction of their
    complete artwork, avoiding ringing around the narrow baked letter strokes.
    Reviewed opaque menu illustrations instead preserve RGB565 cell averages,
    matching the opaque menu renderer's area-filtering contract rather than the
    point-sample alignment of the other reconstructed interfaces.
    """
    from PIL import Image as PillowImage  # noqa: PLC0415

    name = source.name.upper()
    expected = UI_ART_SIZES.get(name)
    if expected is None:
        msg = f"not a verified geometric UI texture: {source.name}"
        raise ValueError(msg)
    with PillowImage.open(source) as original:
        if original.size != expected:
            msg = f"{source.name}: expected a {expected} source, got {original.size}"
            raise ValueError(msg)
        if name in (
            CURSOR_ART_SIZES.keys()
            | LEGACY_TOOLBAR_ART_SIZES.keys()
            | LEGACY_DOCUMENT_SIZES.keys()
            | CURSOR_OPACITY_SIZES.keys()
            | CONSERVATIVE_MENU_SIZES.keys()
            | MONOTONE_BUTTON_SIZES.keys()
            | OPTIONS_LABEL_SIZES.keys()
        ):
            return _resample_detailed_art(original, name)
        if name in CONSOLE_PATTERN_SIZES:
            # Reconstruct the authored repeating diagonal pattern, not new AI
            # linework. Neighbouring tiles supply periodic interpolation at
            # every edge, with the same exact native sample phase as controls.
            tile = original.convert("RGB")
            padded = PillowImage.new("RGB", (expected[0] * 3, expected[1] * 3))
            for y in range(3):
                for x in range(3):
                    padded.paste(tile, (x * expected[0], y * expected[1]))
            return padded.transform(
                (expected[0] * 4, expected[1] * 4),
                PillowImage.Transform.AFFINE,
                (0.25, 0, expected[0] - 0.125, 0, 0.25, expected[1] - 0.125),
                PillowImage.Resampling.BICUBIC,
            )
        if name in _SAMPLE_ALIGNED:
            # GK3 samples a 4x control at (4*x+2, 4*y+2) when presenting the
            # reference-size icon. Anchor those samples on the original pixel
            # centers, while interpolating the additional high-resolution
            # samples. Ordinary resize introduces a 1/8-source-pixel phase
            # shift and changes the thin circle/hexagram's reference coverage.
            return original.convert(ui_art_output_mode(name, original.mode)).transform(
                (expected[0] * 4, expected[1] * 4),
                PillowImage.Transform.AFFINE,
                (0.25, 0, -0.125, 0, 0.25, -0.125),
                PillowImage.Resampling.BICUBIC,
            )
        if (
            name == BINOCULAR_MASK_NAME
            or name in SIDNEY_GEOMETRY_SIZES
            or name in SIDNEY_MAP_OVERLAY_SIZES
            or name in ZODIAC_OVERLAY_SIZES
            or name in FINGERPRINT_TOOL_SIZES
        ):
            from gk3hd.textures.upscale.pipeline import resample_keyed_art  # noqa: PLC0415

            return resample_keyed_art(
                original,
                scale=4,
                key_color=SIDNEY_GEOMETRY_KEYS.get(name, (255, 0, 255)),
                sample_aligned=(
                    name in SIDNEY_GEOMETRY_SIZES
                    or name in SIDNEY_MAP_OVERLAY_SIZES
                    or name in ZODIAC_OVERLAY_SIZES
                    or name in FINGERPRINT_TOOL_SIZES
                ),
            )
        method = (
            PillowImage.Resampling.NEAREST
            if name in _PIXEL_ALIGNED
            else PillowImage.Resampling.BICUBIC
        )
        return original.convert("RGB").resize((expected[0] * 4, expected[1] * 4), method)


def _resample_detailed_art(original: Image, name: str) -> Image:
    """Select the measured sampling contract for cursor, menu and lettered art."""
    from gk3hd.textures.upscale.menu_art import resample_menu_art  # noqa: PLC0415
    from gk3hd.textures.upscale.pipeline import (  # noqa: PLC0415
        resample_keyed_art,
        resample_monotone_art,
    )

    if name in CURSOR_ART_SIZES or name in CURSOR_OPACITY_SIZES:
        return regenerate_cursor_art(original, name)
    if name in LEGACY_TOOLBAR_ART_SIZES:
        return resample_keyed_art(original, scale=4, sample_aligned=True)
    if name in CONSERVATIVE_MENU_SIZES:
        return resample_menu_art(original)
    return resample_monotone_art(original)


def is_current_ui_art(source: Path, destination: Path) -> bool:
    """Replace earlier AI output and invalidate resampling when the source changes."""
    from PIL import Image as PillowImage  # noqa: PLC0415

    expected = regenerate_ui_art(source)
    with PillowImage.open(destination) as candidate:
        return (
            candidate.mode == expected.mode
            and candidate.size == expected.size
            and candidate.tobytes() == expected.tobytes()
        )
