"""Separate dense frame sampling from the native tiled-panel coordinate system."""

from __future__ import annotations

import struct

from gk3hd.patch.binary.x86 import Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.map_overview import emit_overview_source
from gk3hd.textures.native_bmp import PAIRED_UI_COLOR_SIZES
from gk3hd.textures.upscale.fingerprint import INVENTORY_FINGERPRINT_SIZES
from gk3hd.textures.upscale.fonts.button import FONT_BUTTON_SIZES
from gk3hd.textures.upscale.menu_art import CONSERVATIVE_MENU_SIZES
from gk3hd.textures.upscale.thumbnail_recipes import FRAMED_THUMBNAIL_SIZES
from gk3hd.textures.upscale.ui_art import (
    LEGACY_DOCUMENT_SIZES,
    LEGACY_TOOLBAR_ART_SIZES,
    QUIT_BUTTON_SIZES,
)

BORDER_IMAGES = (
    (b"help_box_corner_bl", 2, 2),
    (b"help_box_corner_br", 2, 2),
    (b"help_box_corner_tl", 2, 2),
    (b"help_box_corner_tr", 2, 2),
    (b"help_box_side", 1, 4),
    (b"help_box_top", 8, 1),
    (b"msg_box_corner_ll", 5, 5),
    (b"msg_box_corner_lr", 5, 5),
    (b"msg_box_corner_ul", 5, 5),
    (b"msg_box_corner_ur", 5, 5),
    (b"msg_box_horiz", 1, 5),
    (b"msg_box_vert", 5, 1),
    (b"rc_box_side", 1, 4),
    (b"rc_box_top", 8, 1),
    (b"rc_box_corner_bl", 2, 2),
    (b"rc_box_corner_br", 2, 2),
    (b"rc_box_corner_tl", 2, 2),
    (b"rc_box_corner_tr", 2, 2),
)
OPTIONS_IMAGES = (
    (b"rc_arw_dwn", 17, 15),
    (b"rc_arw_hi", 17, 15),
    (b"rc_arw_r", 17, 15),
    (b"rc_but_chk", 17, 15),
    (b"rc_but_dis", 17, 15),
    (b"rc_but_r", 17, 15),
    (b"rc_dropdown", 252, 132),
    (b"rc_dropdown_link", 14, 4),
    (b"rc_so_dropdown", 252, 52),
    (b"rc_so_slider", 4, 8),
)
TUTORIAL_IMAGES = (
    (b"bothkeys", 131, 140),
    (b"mousemvt", 160, 154),
    (b"lcmouse", 38, 51),
    (b"rcmouse", 38, 51),
)
OPTIONS_PANEL_IMAGES = tuple(
    (name, 252, height)
    for name, height in (
        (b"rc_panel", 75),
        (b"gamesc", 102),
        (b"graphsc", 124),
        (b"advoptsc", 134),
        (b"soundsc", 212),
    )
)
FONT_BUTTON_IMAGES = tuple(
    (name.removesuffix(".BMP").lower().encode("ascii"), *size)
    for name, size in FONT_BUTTON_SIZES.items()
)
DIALOG_IMAGES = ((b"quitgame", 595, 218), (b"paused", 140, 37))
# Archived DebugMgr binds this color image to CAIN_ALPHA through UIImage.
# Its software-opacity path needs the same logical extents as ordinary UI.
OPACITY_IMAGE_PAIRS = tuple(
    (name.removesuffix(".BMP").lower().encode("ascii"), *size)
    for name, size in PAIRED_UI_COLOR_SIZES.items()
)
QUIT_BUTTON_IMAGES = tuple(
    (name.removesuffix(".BMP").lower().encode("ascii"), *size)
    for name, size in QUIT_BUTTON_SIZES.items()
)
HELP_BUTTON_IMAGES = tuple(
    (label + b"_" + state, 49, 28)
    for label in (b"prev", b"next", b"exit")
    for state in (b"u", b"h", b"d")
)
MESSAGE_BUTTON_IMAGES = tuple(
    (b"msg_" + label + b"_" + state, 46, 26)
    for label in (b"yes", b"no", b"ok")
    for state in (b"u", b"h", b"d")
)
LOAD_SAVE_BUTTON_IMAGES = tuple(
    (label + state, width, 38 if label != b"exit" and state == b"d" else height)
    for label, width, height in ((b"exit", 58, 26), (b"restore", 145, 39), (b"save", 145, 39))
    for state in (b"d", b"dis", b"hov", b"n")
)
OPTIONS_TAB_IMAGES = tuple(
    (b"op_" + label + b"_" + state, width, 29)
    for label, width in ((b"gamopt", 73), (b"gropt", 72), (b"sopt", 73))
    for state in (b"r", b"hi", b"dwn")
)
OPTIONS_ACTION_IMAGES = tuple(
    (label + b"_" + state, width, 17)
    for label, width in ((b"gamop_cms", 150), (b"gropt_agopt", 165))
    for state in (b"r", b"hi", b"dwn")
)
OPTIONS_LABEL_IMAGES = (
    (b"advop_ani_dis", 164, 16),
    (b"advop_ani_r", 164, 16),
    (b"advop_lod_dis", 36, 12),
    (b"advop_lod_r", 36, 12),
    (b"advop_mipmap_dis", 96, 16),
    (b"advop_mipmap_r", 95, 16),
    (b"advop_tri_dis", 139, 19),
    (b"advop_tri_r", 139, 19),
    (b"gropt_gam_dis", 204, 17),
    (b"gropt_inrend_dis", 158, 21),
    (b"gropt_inrend_r", 158, 21),
)
SIDNEY_TAB_IMAGES = tuple(
    (b"b_" + label + b"_" + state, 76, 13)
    for label in (
        b"addata",
        b"analyze",
        b"email",
        b"files",
        b"makeid",
        b"search",
        b"suspt",
        b"transl",
    )
    for state in (b"u", b"h", b"d", b"x")
)
# These share logical bitmap geometry, not a texture-generation algorithm.
EVIDENCE_FINGERPRINT_IMAGES = tuple(
    (name, 41, 51)
    for prefix in (b"buch_bld", b"buth_bld", b"est_lsr", b"mos_bld")
    for name in (
        prefix + b"_print",
        prefix + b"_compare",
        prefix.replace(b"_", b"_red_", 1) + b"_print",
    )
)
SIDNEY_NAVIGATION_IMAGES = (
    (b"s_bar_stretch", 2, 13),
    (b"s_bar_topangle_lr", 12, 10),
    (b"s_bar_topstrip_lr", 1, 10),
    (b"s_dwnarw", 7, 6),
    (b"s_dwnarw_noemb", 7, 6),
    (b"s_slider_dwnarrow", 6, 6),
    (b"s_slider_uparrow", 6, 6),
    (b"s_id_bracket", 45, 11),
)
SIDNEY_SHAPE_IMAGES = tuple(
    (name, 64, 64) for name in (b"triangle", b"circle", b"rectangle", b"hexagram")
)
GPS_CONTROL_IMAGES = tuple(
    (b"gps" + part + b"_" + suffix, width, height)
    for suffix, length, thickness, target_width, target_height, button_width, button_height in (
        (b"l", 205, 3, 20, 21, 37, 35),
        (b"m", 193, 3, 20, 21, 34, 33),
        (b"s", 128, 2, 12, 13, 23, 22),
    )
    for part, width, height in (
        (b"hline", length, thickness),
        (b"vline", thickness, length),
        (b"target", target_width, target_height),
        (b"power_off_up", button_width, button_height),
        (b"power_on_down", button_width, button_height),
        (b"power_on_up", button_width, button_height),
    )
)
SIDNEY_FRAME_IMAGES = tuple(
    (name + suffix, width, height)
    for name, width, height in (
        (b"s_box_corner", 2, 1),
        (b"s_box_corner_bl", 2, 2),
        (b"s_box_corner_br", 2, 2),
        (b"s_box_corner_tl", 2, 2),
        (b"s_box_corner_tr", 2, 2),
        (b"s_box_side", 1, 4),
        (b"s_box_top", 8, 1),
        (b"s_but_side", 1, 13),
        (b"s_but_stretch", 1, 13),
        (b"s_but14_side", 1, 13),
        (b"s_but14_stretch", 1, 13),
        (b"s_but18_side", 1, 18),
        (b"s_but18_stretch", 1, 18),
    )
    for suffix in (b"", b"_l")
)
# History's menu owner sizes generated separator caches from these resources.
# Their heights are layout units, not the fourfold source raster's texel count.
SIDNEY_SEPARATOR_IMAGES = ((b"s_bit_space1", 2, 1),)
SIDNEY_BACKGROUND_IMAGES = ((b"s_bkgnd", 640, 480), (b"s_main_scn", 640, 480))
GPS_MAP_IMAGES = tuple(
    (b"gps" + location + b"_" + variant + opacity, width, height)
    for location in (b"bec", b"ler", b"mcf")
    for variant, width, height in ((b"l", 222, 332), (b"m", 208, 311), (b"s", 139, 208))
    for opacity in (b"", b"_alpha")
)
SIDNEY_MAP_IMAGES = ((b"sidneybigmap", 1368, 1368), (b"sidneylittlemap", 342, 342))
SIDNEY_MAP_OVERLAY_IMAGES = (
    (b"serpent", 177, 208),
    (b"serplitmap", 47, 52),
    (b"maplg_the", 40, 31),
    (b"maplg_site", 46, 32),
    (b"mapsm_the", 18, 16),
    (b"mapsm_site", 20, 13),
)
PARCHMENT_IMAGES = (
    (b"parchment1_base", 432, 384),
    (b"parchment2_base", 390, 424),
)
SIDNEY_GEOMETRY_IMAGES = (
    *((f"sid_symb_{index}".encode(), 94, 94) for index in range(1, 5)),
    (b"geomparch1final", 432, 384),
    (b"geomparch2final", 390, 424),
    (b"geompoussinfinal", 431, 350),
    (b"geomtenniersfinal", 464, 350),
    (b"teniergeoa", 464, 350),
    (b"teniergeob", 464, 350),
    (b"teniergeoc", 464, 350),
)
SIDNEY_CLUE_IMAGES = (
    (b"poussin_zoom", 215, 209),
    (b"teniers_zoom", 214, 217),
    (b"zion_rot", 115, 115),
    (b"sion", 67, 46),
    (b"pythagoras", 289, 289),
)
SIDNEY_SHARED_CONTROL_IMAGES = (
    (b"closewin_up", 16, 16),
    (b"closewin_hover", 16, 16),
    (b"closewin_down", 16, 16),
    (b"sidneybullet", 15, 15),
    (b"s_from_to", 38, 61),
    (b"horizontalrule", 640, 15),
)
CONSOLE_IMAGES = ((b"minisnaky", 30, 30), (b"snaky", 100, 100))
TIMEBLOCK_BUTTON_IMAGES = tuple(
    (b"tb_" + label + b"_" + state, 81, 26)
    for label in (b"cont", b"save")
    for state in (b"u", b"h", b"d", b"x")
)
TITLE_BUTTON_IMAGES = tuple(
    (b"title_" + label + b"_" + state, 81, 26)
    for label in (b"intro", b"play", b"restore", b"quit")
    for state in (b"u", b"h", b"d", b"x")
)
DEATH_BUTTON_IMAGES = tuple(
    (b"ds_" + label + b"_" + state, 81, 26)
    for label in (b"rtry", b"rest", b"quit")
    for state in (b"n", b"h", b"d", b"x")
)
ZODIAC_IMAGES = tuple(
    (f"lsr_pg{page}_{sign}_{state}".encode(), width, height)
    for page, sign, width, height in (
        (1, "aqu", 305, 142),
        (1, "pis", 307, 178),
        (2, "ari", 294, 172),
        (2, "tau", 308, 183),
        (3, "gem", 299, 232),
        (3, "can", 299, 97),
        (3, "leo", 311, 149),
        (4, "vir", 292, 176),
        (4, "lib", 309, 209),
        (5, "sco", 294, 191),
        (5, "oph", 312, 190),
        (6, "sag", 323, 166),
        (6, "cap", 340, 221),
    )
    for state in ("fin", "lit")
) + tuple((f"lsr_pg{page}_base".encode(), 640, 400) for page in range(1, 7))

SIDNEY_ID_IMAGES = tuple(
    (character + b"_" + profession, 254, 164)
    for character in (b"gab", b"gra")
    for profession in (
        b"auto",
        b"blood",
        b"coroner",
        b"diaper",
        b"doc",
        b"elec",
        b"emonthly",
        b"ency",
        b"freelance",
        b"nopd",
        b"nytimes",
        b"plumb",
        b"security",
        b"shoes",
        b"sportsi",
    )
)

DETAILED_ACTION_IMAGES = tuple(
    (name.removesuffix(".BMP").lower().encode("ascii"), size[0], size[1])
    for name, size in (FRAMED_THUMBNAIL_SIZES | CONSERVATIVE_MENU_SIZES).items()
)
OPAQUE_INVENTORY_IMAGES = ((b"undefined9", 94, 94),)
# These inventory cards and previews also appear as BitmapObjects in SIDNEY.
# Normalize only the high blitter: Inventory's software-alpha drawable keeps
# its own dense metrics, mask and temporary 94x94 model conversion.
BLIT_ONLY_IMAGES = (
    *(
        (name.removesuffix(".BMP").lower().encode("ascii"), *size)
        for name, size in INVENTORY_FINGERPRINT_SIZES.items()
        if not name.endswith("6_ALPHA.BMP")
    ),
    (b"abbetape3", 32, 30),
    (b"map3", 32, 30),
    (b"tempstant9", 94, 94),
)

FINGERPRINT_TOOL_IMAGES = (
    (b"c_fpbrush", 24, 114),
    (b"c_fpbrush_wdust", 24, 114),
    (b"c_fptape_fp", 33, 54),
    (b"c_fptape_nofp", 33, 54),
)

LEGACY_TOOLBAR_IMAGES = tuple(
    (name.removesuffix(".BMP").lower().encode("ascii"), *size)
    for name, size in LEGACY_TOOLBAR_ART_SIZES.items()
)
LEGACY_DOCUMENT_IMAGES = tuple(
    (name.removesuffix(".BMP").lower().encode("ascii"), *size)
    for name, size in LEGACY_DOCUMENT_SIZES.items()
)

UI_IMAGES = (
    ZODIAC_IMAGES
    + SIDNEY_ID_IMAGES
    + CONSOLE_IMAGES
    + DEATH_BUTTON_IMAGES
    + TITLE_BUTTON_IMAGES
    + TIMEBLOCK_BUTTON_IMAGES
    + BORDER_IMAGES
    + OPTIONS_IMAGES
    + OPTIONS_PANEL_IMAGES
    + FONT_BUTTON_IMAGES
    + DIALOG_IMAGES
    + QUIT_BUTTON_IMAGES
    + HELP_BUTTON_IMAGES
    + MESSAGE_BUTTON_IMAGES
    + LOAD_SAVE_BUTTON_IMAGES
    + OPTIONS_TAB_IMAGES
    + OPTIONS_ACTION_IMAGES
    + OPTIONS_LABEL_IMAGES
    + SIDNEY_TAB_IMAGES
    + TUTORIAL_IMAGES
    + EVIDENCE_FINGERPRINT_IMAGES
    + SIDNEY_FRAME_IMAGES
    + SIDNEY_NAVIGATION_IMAGES
    + SIDNEY_SHAPE_IMAGES
    + GPS_CONTROL_IMAGES
    + GPS_MAP_IMAGES
    + SIDNEY_MAP_IMAGES
    + SIDNEY_MAP_OVERLAY_IMAGES
    + PARCHMENT_IMAGES
    + SIDNEY_GEOMETRY_IMAGES
    + SIDNEY_CLUE_IMAGES
    + SIDNEY_SHARED_CONTROL_IMAGES
    + DETAILED_ACTION_IMAGES
    + OPAQUE_INVENTORY_IMAGES
    + SIDNEY_SEPARATOR_IMAGES
    + SIDNEY_BACKGROUND_IMAGES
    + FINGERPRINT_TOOL_IMAGES
    + LEGACY_TOOLBAR_IMAGES
    + LEGACY_DOCUMENT_IMAGES
    + OPACITY_IMAGE_PAIRS
)
# A one-byte record length skips a variable-length terminated name in O(1),
# including on dimension mismatches, without padding every short resource name
# to 20 bytes. The catalog occupies a separately bounded two-page region.
_NAME_BYTES = 32
_MAX_DENSE_EXTENT = (1 << 16) - 1


def build_resource_match(
    *, wrapper_va: int, images: tuple[tuple[bytes, int, int], ...] | None = None, density: int = 4
) -> bytes:
    """Match ESI's exact terminated name and EAX's fourfold physical size.

    A bounded read-only table keeps catalog growth out of the instruction
    budget. Preserve every register; carry alone indicates a match.
    """
    if density not in (1, 4):
        msg = "resource density must be native or fourfold"
        raise ValueError(msg)
    catalog = UI_IMAGES if images is None else images
    if not catalog:
        msg = "UI matcher requires at least one resource"
        raise ValueError(msg)
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\xbb")
    code.absolute_label("table")
    code.raw(b"\xbf" + struct.pack("<I", len(catalog)))
    code.label("entry")
    # The compact table stores positive 16-bit extents, while native surface
    # fields remain full DWORDs. Zero-extend before comparison, never truncate
    # a live surface dimension (which could make an unrelated resource match).
    for offset, surface_offset in ((0, 0x38), (2, 0x3C)):
        code.raw(b"\x0f\xb7\x53" + bytes([offset]) + b"\x3b\x50" + bytes([surface_offset]))
        code.jump_short_if(Condition.NOT_EQUAL, "next")
    code.raw(b"\x31\xc9")
    code.label("name")
    code.raw(b"\x8a\x54\x0e\x08\x80\xfa\x41")
    code.jump_short_if(Condition.BELOW, "compare")
    code.raw(b"\x80\xfa\x5a")
    code.jump_short_if(Condition.ABOVE, "compare")
    code.raw(b"\x80\xca\x20")
    code.label("compare")
    code.raw(b"\x3a\x54\x0b\x05")
    code.jump_short_if(Condition.NOT_EQUAL, "next")
    code.raw(b"\x84\xd2")
    code.jump_short_if(Condition.EQUAL, "match")
    code.raw(b"\x41\x83\xf9" + bytes([_NAME_BYTES]))
    code.jump_short_if(Condition.BELOW, "name")
    code.label("next")
    code.raw(b"\x0f\xb6\x4b\x04\x03\xd9\x4f")
    code.jump_short_if(Condition.NOT_EQUAL, "entry")
    code.raw(b"\x61\xf8\xc3")
    code.label("match")
    code.raw(b"\x61\xf9\xc3")
    code.label("table")
    for name, width, height in catalog:
        if len(name) >= _NAME_BYTES:
            msg = f"UI resource name exceeds matcher record: {name!r}"
            raise ValueError(msg)
        if not (
            0 < width * density <= _MAX_DENSE_EXTENT and 0 < height * density <= _MAX_DENSE_EXTENT
        ):
            msg = f"UI resource extent exceeds matcher record: {name!r} ({width}, {height})"
            raise ValueError(msg)
        code.raw(
            struct.pack("<HHB", width * density, height * density, len(name) + 6) + name + b"\0"
        )
    return code.build()


def build_dimensions(*, wrapper_va: int, match_va: int, logical_va: int) -> bytes:
    """Return transient logical metrics without modifying any source surface."""
    code = X86Emitter(base_va=wrapper_va)
    code.call_absolute(match_va)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
    code.raw(b"\x52")
    for offset, target in ((0x38, logical_va), (0x3C, logical_va + 4)):
        code.raw(b"\x8b\x50" + bytes([offset]) + b"\xc1\xfa\x02")
        code.raw(b"\x89\x15" + struct.pack("<I", target))
    code.raw(b"\x5a\xb8" + struct.pack("<I", logical_va) + b"\xf9\xc3")
    code.label("native")
    code.raw(b"\xf8\xc3")
    return code.build()


def build_surface_match(
    *,
    wrapper_va: int,
    resource_match_va: int,
    manager_va: int,
    images: tuple[tuple[bytes, int, int], ...] | None = None,
    density: int = 4,
) -> bytes:
    """Resolve EAX through the live BitmapManager table, never a stale source cache.

    Border cache construction can precede GetDimensions for a corner placed at
    (0, 0). Consequently the dimension getter cannot reliably register every
    border source. First reject all other physical sizes cheaply; only candidates
    search the manager's current resource table. No resource pointers are retained
    across unloading or reused surface allocations. Preserve all registers.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    catalog = UI_IMAGES if images is None else images
    if not catalog:
        msg = "UI matcher requires at least one resource"
        raise ValueError(msg)
    if density not in (1, 4):
        msg = "surface density must be native or fourfold"
        raise ValueError(msg)
    sizes = sorted({(w * density, h * density) for _, w, h in catalog})
    code.raw(b"\x8b\x50\x38\x8b\x58\x3c\xbf")
    code.absolute_label("sizes")
    code.raw(b"\xbd" + struct.pack("<I", len(sizes)))
    code.label("size")
    code.raw(b"\x3b\x17")
    code.jump_short_if(Condition.NOT_EQUAL, "next_size")
    code.raw(b"\x3b\x5f\x04")
    code.jump_short_if(Condition.EQUAL, "lookup")
    code.label("next_size")
    code.raw(b"\x83\xc7\x08\x4d")
    code.jump_short_if(Condition.NOT_EQUAL, "size")
    code.jump("native")
    code.label("lookup")
    code.raw(b"\x8b\x3d" + struct.pack("<I", manager_va) + b"\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x8f\x24\x01\x00\x00\x8b\xbf\x20\x01\x00\x00\x85\xff")
    code.jump_if(Condition.EQUAL, "native")
    code.label("loop")
    code.raw(b"\x85\xc9")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x37\x83\xc7\x04\x49\x85\xf6")
    code.jump_if(Condition.EQUAL, "loop")
    code.raw(b"\x39\x46\x30")
    code.jump_if(Condition.NOT_EQUAL, "loop")
    code.call_absolute(resource_match_va)
    code.raw(b"\x61\xc3")
    code.label("native")
    code.raw(b"\x61\xf8\xc3")
    code.label("sizes")
    for width, height in sizes:
        code.raw(struct.pack("<II", width, height))
    return code.build()


def build_high_dimensions(
    *, wrapper_va: int, surface_match_va: int, original: bytes, return_va: int
) -> bytes:
    """Clip named borders in logical space before GK3 derives destination extents.

    Entry is the high blitter's dimension-load block, with EBX=source and
    EDI=destination. Replay its loads and locals, then divide only the recognized
    source's width/height registers. The underlying surface remains physical.
    Changing only GetDimensions leaves this path deriving oversized rectangles
    directly from the surface; changing only the final source double-scales it.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x9c" + original + b"\x50\x8b\xc3")
    code.call_absolute(surface_match_va)
    code.raw(b"\x58")
    code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
    code.raw(b"\xc1\xf8\x02\xc1\xf9\x02")
    code.label("done")
    code.raw(b"\x9d")
    code.jump_absolute(return_va)
    return code.build()


def build_bitmap_object_dimensions(
    *, wrapper_va: int, dimensions_va: int, surface_match_va: int, logical_va: int
) -> bytes:
    """Give bitmap layout callers logical extents for shared inventory artwork.

    Inventory's software-alpha constructor must still see physical dimensions.
    Only BitmapObject::SetImage and SIDNEY's preview-centering call get the
    extra catalog; the shared getter is unchanged. Already-logical results
    cannot match a live source surface.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\xff\x74\x24\x04")
    code.call_absolute(dimensions_va)
    code.raw(b"\x50\x83\xe8\x38")
    code.call_absolute(surface_match_va)
    code.raw(b"\x58")
    code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
    code.raw(b"\x52")
    for offset in (0, 4):
        code.raw(b"\x8b\x50" + bytes([offset]) + b"\xc1\xfa\x02\x89\x15")
        code.raw(struct.pack("<I", logical_va + offset))
    code.raw(b"\x5a\xb8" + struct.pack("<I", logical_va))
    code.label("done")
    code.raw(b"\xc2\x04\x00")
    return code.build()


def build_blit_match(*, wrapper_va: int, ui_match_va: int, extra_match_va: int) -> bytes:
    """Extend ordinary blit sampling without changing shared drawable metrics."""
    code = X86Emitter(base_va=wrapper_va)
    code.call_absolute(ui_match_va)
    code.jump_short_if(Condition.BELOW, "done")
    code.jump_absolute(extra_match_va)
    code.label("done")
    code.raw(b"\xc3")
    return code.build()


def build_source(
    *,
    wrapper_va: int,
    surface_match_va: int,
    scratch_va: int,
    callers: tuple[int, ...],
    manager_va: int,
    dimensions_va: int,
) -> bytes:
    """Map high-blitter logical clips to dense pixels exactly once at the sink.

    Other final-blit callers already provide physical rectangles and pass through.
    Preserve the caller's RECT and destination argument; only substitute a private
    source copy. This helper is called before PUSHAD in the shared dispatcher.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8d\x6c\x24\x24")
    for address in callers:
        code.raw(b"\x81\x7d\x00" + struct.pack("<I", address))
        code.jump_if(Condition.EQUAL, "candidate")
    code.jump("done")
    code.label("candidate")
    code.raw(b"\x8b\x45\x04")
    code.call_absolute(surface_match_va)
    code.jump_if(Condition.ABOVE_OR_EQUAL, "done")
    code.raw(b"\x8b\x75\x0c\x85\xf6")
    code.jump_if(Condition.EQUAL, "done")
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\xc1\xe0\x02\xa3")
        code.raw(struct.pack("<I", scratch_va + offset))
    code.raw(b"\xc7\x45\x0c" + struct.pack("<I", scratch_va))
    emit_overview_source(
        code, scratch_va=scratch_va, manager_va=manager_va, dimensions_va=dimensions_va
    )
    code.label("done")
    code.raw(b"\x61\xc3")
    return code.build()
