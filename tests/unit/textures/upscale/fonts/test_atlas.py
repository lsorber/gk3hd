from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.upscale.fonts import atlas as font_atlas
from gk3hd.textures.upscale.fonts.atlas import (
    FontAtlasRecipe,
    _render_exact_raster_atlas,
    font_atlas_recipe,
    parse_glyph_cells,
    regenerable_font_atlas_names,
    regenerate_font_atlas,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def paired_atlas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    primary = Image.new("RGB", (8, 5), (255, 0, 255))
    for x in (1, 3, 7):
        primary.putpixel((x, 0), (0, 0, 255))
    primary.putpixel((2, 3), (97, 101, 103))
    primary.save(tmp_path / "TEST.BMP")
    alpha = Image.new("L", primary.size, 0)
    alpha.putpixel((2, 3), 96)
    alpha.save(tmp_path / "TEST_ALPHA.BMP")
    for name, is_alpha in (("TEST.BMP", False), ("TEST_ALPHA.BMP", True)):
        monkeypatch.setitem(
            font_atlas._RECIPES,
            name,
            FontAtlasRecipe("TEST.BMP", b"AB", 1, alpha=is_alpha, alpha_companion="TEST_ALPHA.BMP"),
        )
    return tmp_path


@pytest.mark.parametrize("name", ["TEST.BMP", "TEST_ALPHA.BMP"])
@pytest.mark.slow
def test_regeneration_rejects_missing_alpha_from_either_member(
    paired_atlas: Path, name: str
) -> None:
    (paired_atlas / "TEST_ALPHA.BMP").unlink()
    with pytest.raises(ValueError, match=r"font atlas companion is missing: TEST_ALPHA\.BMP"):
        regenerate_font_atlas(paired_atlas / name)


@pytest.mark.parametrize("name", ["TEST.BMP", "TEST_ALPHA.BMP"])
@pytest.mark.slow
def test_regeneration_rejects_misaligned_alpha_from_either_member(
    paired_atlas: Path, name: str
) -> None:
    Image.new("L", (9, 5), 0).save(paired_atlas / "TEST_ALPHA.BMP")
    with pytest.raises(ValueError, match=r"alpha atlas dimensions do not match TEST\.BMP"):
        regenerate_font_atlas(paired_atlas / name)


@pytest.mark.slow
def test_regeneration_keeps_color_and_coverage_registered(paired_atlas: Path) -> None:
    color = regenerate_font_atlas(paired_atlas / "TEST.BMP")
    alpha = regenerate_font_atlas(paired_atlas / "TEST_ALPHA.BMP")
    assert color.size == alpha.size == (32, 20)
    assert color.crop((8, 12, 12, 16)).getextrema() == ((97, 97), (101, 101), (103, 103))
    assert alpha.crop((8, 12, 12, 16)).getextrema() == (96, 96)
    assert alpha.getpixel((4, 0)) == 0  # Color markers are never coverage.


@pytest.mark.slow
def test_paired_font_preserves_independent_key_and_opacity(paired_atlas: Path) -> None:
    primary_path = paired_atlas / "TEST.BMP"
    alpha_path = paired_atlas / "TEST_ALPHA.BMP"
    with primary_path.open("rb") as stream, Image.open(stream) as opened:
        original_color = opened.convert("RGB")
    with alpha_path.open("rb") as stream, Image.open(stream) as opened:
        original_alpha = opened.convert("L")
    # Shipped fonts can carry nonzero coverage behind keyed color. Conversely,
    # a visible color value with zero opacity must not acquire inferred coverage.
    original_alpha.putpixel((1, 2), 255)
    original_color.putpixel((4, 2), (97, 101, 103))
    original_color.save(primary_path)
    original_alpha.save(alpha_path)
    source_bytes = (primary_path.read_bytes(), alpha_path.read_bytes())

    color = regenerate_font_atlas(primary_path)
    alpha = regenerate_font_atlas(alpha_path)

    assert color.crop((4, 8, 8, 12)).getextrema() == ((255, 255), (0, 0), (255, 255))
    assert alpha.crop((4, 8, 8, 12)).getextrema() == (255, 255)
    assert color.crop((16, 8, 20, 12)).getextrema() == ((97, 97), (101, 101), (103, 103))
    assert alpha.crop((16, 8, 20, 12)).getextrema() == (0, 0)
    assert (primary_path.read_bytes(), alpha_path.read_bytes()) == source_bytes


def test_recipe_catalog_is_explicit_and_pairs_alpha_atlases() -> None:
    names = regenerable_font_atlas_names()
    arial = font_atlas_recipe("f_arial_t8.bmp")
    times_alpha = font_atlas_recipe("TIMES_R_12A.BMP")
    goudy_alpha = font_atlas_recipe("F_CAPTION_GOUDY14AA_ALPHA.BMP")

    assert len(names) == 72
    assert arial is not None
    assert (arial.primary, arial.line_count) == ("F_ARIAL_T8.BMP", 1)
    assert arial.implicit_right_edge
    assert times_alpha is not None
    assert times_alpha.alpha
    assert not times_alpha.implicit_right_edge
    # Unidentified atlases remain native; recognized atlases preserve their
    # shipped glyph rasters instead of substituting a modern outline face.
    assert font_atlas_recipe("F_STATUS_DEFAULT.BMP") is None
    assert goudy_alpha is not None
    assert goudy_alpha.alpha
    assert goudy_alpha.alpha_companion == "F_CAPTION_GOUDY14AA_ALPHA.BMP"
    assert font_atlas_recipe("F_CAPTION_GOUDY14DS.BMP") is not None
    assert font_atlas_recipe("RC_GOUDY12.BMP") is not None


def test_pulldown_recipe_preserves_its_verified_byte_map() -> None:
    # SpriteButton's paired cache now retains the reconstructed detail. This
    # recipe still keeps ambiguous S shapes and the fallback as source artwork.
    recipe = font_atlas_recipe("SID_PDN_10.BMP")
    assert recipe is not None
    assert (recipe.line_count, len(recipe.characters)) == (3, 181)


def test_tooltip_preserves_its_distinct_extended_character_order() -> None:
    recipe = font_atlas_recipe("F_TOOLTIP.BMP")
    assert recipe is not None
    assert len(recipe.characters) == 180
    assert b"\xac" not in recipe.characters
    assert b"\xab\xad\xae" in recipe.characters
    assert recipe.characters.endswith(b"\xfe\xff")
    assert recipe.implicit_right_edge
    assert recipe.line_count == 1


def test_pulldown12_artwork_map_is_not_a_descriptor_rewrite() -> None:
    smaller = font_atlas_recipe("SID_PDN_10.BMP")
    recipe = font_atlas_recipe("SID_PDN_12.BMP")
    assert smaller is not None
    assert recipe is not None
    assert recipe.characters == smaller.characters.replace(b"\xcf", b"")
    assert len(recipe.characters) == 180
    assert recipe.characters[132] == 0xD0
    assert recipe.characters[-1] == 0xFF


def test_times_repaired_underline_keeps_the_complete_character_table() -> None:
    regular = font_atlas_recipe("TIMES_R_12.BMP")
    assert regular is not None
    for name in ("TIMES_B_U_12.BMP", "TIMES_B_U_12A.BMP"):
        recipe = font_atlas_recipe(name)
        assert recipe is not None
        assert recipe.characters == regular.characters
        assert recipe.characters[-1] == 0xFF
        assert recipe.coverage_baseline == 11


def test_pulldown16_labels_authored_last_cell_without_inventing_missing_glyphs() -> None:
    complete = font_atlas_recipe("SID_PDN_10.BMP")
    recipe = font_atlas_recipe("SID_PDN_16.BMP")
    assert complete is not None
    assert recipe is not None
    assert recipe.characters == complete.characters[:148] + b"\xff"
    assert len(recipe.characters) == 149
    assert recipe.characters[-2:] == b"\xde\xff"
    assert set(range(0xDF, 0xFF)).isdisjoint(recipe.characters)


def test_tempus_color_pair_has_its_own_opacity_recipe() -> None:
    recipe = font_atlas_recipe("F_TEMPUS_A10.BMP")
    arial = font_atlas_recipe("F_ARIAL_T10.BMP")
    assert recipe is not None
    assert arial is not None
    assert recipe.characters == arial.characters
    assert recipe.line_count == 4
    color = font_atlas_recipe("F_TEMPUS_10.BMP")
    alpha = font_atlas_recipe("F_TEMPUS_10_ALPHA.BMP")
    assert color is not None
    assert alpha is not None
    assert color.characters == alpha.characters == recipe.characters
    assert color.line_count == alpha.line_count == 4
    assert not color.alpha
    assert alpha.alpha
    assert color.alpha_companion == alpha.alpha_companion == "F_TEMPUS_10_ALPHA.BMP"


def test_marker_parser_does_not_create_a_cell_across_atlas_rows() -> None:
    image = Image.new("RGB", (8, 6), (255, 0, 255))
    pixels = image.load()
    assert pixels is not None
    for x in (1, 3, 7):
        pixels[x, 0] = (0, 0, 255)
    for x in (1, 4, 7):
        pixels[x, 3] = (0, 0, 255)
    recipe = FontAtlasRecipe("TEST.BMP", b"ABCD", 2)

    cells = parse_glyph_cells(image, recipe)

    assert [cell.character for cell in cells] == list(b"ABCD")
    assert [cell.rect for cell in cells] == [
        (1, 1, 3, 3),
        (3, 1, 7, 3),
        (1, 4, 4, 6),
        (4, 4, 7, 6),
    ]
    with pytest.raises(ValueError, match="at least 5 are required"):
        parse_glyph_cells(image, FontAtlasRecipe("TEST.BMP", b"ABCD\xff", 2))


@pytest.mark.parametrize("key", [(255, 0, 255), (248, 0, 248)])
def test_documented_end_marker_excludes_trailing_artwork(key: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (12, 5), key)
    image.putpixel((0, 1), (100, 120, 155))
    image.putpixel((0, 3), (0, 255, 0))  # Baseline, separate from replacement color.
    for x in (1, 4, 8):
        image.putpixel((x, 0), (0, 0, 255))
    image.putpixel((10, 2), (255, 255, 255))  # Ignored after the ending marker.
    recipe = FontAtlasRecipe("DOCUMENTED.BMP", b"AB", 1)

    cells = parse_glyph_cells(image, recipe)
    output = _render_exact_raster_atlas(image, cells, recipe)

    assert [cell.rect for cell in cells] == [(1, 1, 4, 5), (4, 1, 8, 5)]
    assert output.getpixel((40, 8)) == key
    assert output.getpixel((0, 1)) == (100, 120, 155)
    assert output.getpixel((0, 12)) == (0, 255, 0)
    assert output.getpixel((0, 13)) == key


def test_missing_end_marker_requires_explicit_verified_recipe_exception() -> None:
    image = Image.new("RGB", (8, 5), (255, 0, 255))
    for x in (1, 4):
        image.putpixel((x, 0), (0, 0, 255))
    with pytest.raises(ValueError, match="marker table has 1 glyph cells"):
        parse_glyph_cells(image, FontAtlasRecipe("DOCUMENTED.BMP", b"AB", 1))
    cells = parse_glyph_cells(
        image, FontAtlasRecipe("LEGACY.BMP", b"AB", 1, implicit_right_edge=True)
    )
    assert cells[-1].rect == (4, 1, 8, 5)


@pytest.mark.parametrize("line_count", [0, -1])
def test_marker_parser_rejects_nonpositive_line_count(line_count: int) -> None:
    image = Image.new("RGB", (8, 6), (255, 0, 255))
    with pytest.raises(ValueError, match="line count must be positive"):
        parse_glyph_cells(image, FontAtlasRecipe("INVALID.BMP", b"A", line_count))


def test_marker_parser_rejects_rows_without_glyph_pixels() -> None:
    image = Image.new("RGB", (8, 3), (255, 0, 255))
    with pytest.raises(ValueError, match="each line needs a marker row and glyph pixels"):
        parse_glyph_cells(image, FontAtlasRecipe("INVALID.BMP", b"ABC", 3))


def test_marker_parser_rejects_height_not_divisible_by_line_count() -> None:
    image = Image.new("RGB", (8, 7), (255, 0, 255))
    with pytest.raises(ValueError, match="height does not divide into 3 lines"):
        parse_glyph_cells(image, FontAtlasRecipe("INVALID.BMP", b"ABC", 3))


@pytest.mark.parametrize("characters", [b"AB", b"ABC"])
def test_marker_parser_rejects_every_unmapped_cell(characters: bytes) -> None:
    image = Image.new("RGB", (16, 5), (255, 0, 255))
    for x in (1, 4, 7, 10, 13):
        image.putpixel((x, 0), (0, 0, 255))
    recipe = FontAtlasRecipe("INVALID.BMP", characters, 1)
    with pytest.raises(ValueError, match="marker table has 4 glyph cells; at most"):
        parse_glyph_cells(image, recipe)


def test_marker_parser_keeps_every_declared_cell() -> None:
    image = Image.new("RGB", (12, 5), (255, 0, 255))
    for x in (1, 4, 7, 10):
        image.putpixel((x, 0), (0, 0, 255))
    recipe = FontAtlasRecipe("VERIFIED.BMP", b"AB\xff", 1)
    cells = parse_glyph_cells(image, recipe)
    assert [(cell.character, cell.rect) for cell in cells] == [
        (ord("A"), (1, 1, 4, 5)),
        (ord("B"), (4, 1, 7, 5)),
        (0xFF, (7, 1, 10, 5)),
    ]


@pytest.mark.parametrize("name", ["F_SSERIF_T8.BMP", "F_SSERIF_T8B.BMP"])
def test_menu_font_preserves_nontext_symbol_slots(name: str) -> None:
    recipe = font_atlas_recipe(name)
    assert recipe is not None
    assert recipe.characters[-3:] == b"\xd8\xda\x9d"
    assert len(recipe.characters) == 96
    # Include the whole table: omitting/reordering either arrow would shift the
    # default glyph, even if ordinary letters still appeared to render correctly.
    image = Image.new("RGB", (1 + len(recipe.characters) * 2, 5), (255, 0, 255))
    for index in range(len(recipe.characters)):
        image.putpixel((1 + index * 2, 0), (24, 255, 255))
    cells = parse_glyph_cells(image, recipe)
    assert [cell.character for cell in cells] == list(recipe.characters)
    for index, cell in enumerate(cells[-3:], start=1):
        image.putpixel((cell.rect[0], index), (255, 255, 255))
    output = _render_exact_raster_atlas(image, cells, recipe)
    for cell in cells[-3:]:
        expected = image.crop(cell.rect).resize((8, 16), Image.Resampling.NEAREST)
        left, top, right, bottom = cell.rect
        actual = output.crop((left * 4, top * 4, right * 4, bottom * 4))
        assert actual.tobytes() == expected.tobytes()


def test_exact_atlas_preserves_every_cell_position_size_and_pixel() -> None:
    source = Image.new("RGB", (10, 5), (255, 0, 255))
    source.putpixel((0, 1), (213, 178, 246))
    # Deliberately uneven cells catch horizontal fitting, uniform-width
    # assumptions, and off-by-one marker placement.
    for x in (1, 3, 7):
        source.putpixel((x, 0), (213, 178, 246))
    source.putpixel((1, 1), (255, 255, 255))
    source.putpixel((3, 4), (19, 37, 53))
    source.putpixel((5, 2), (97, 101, 103))
    source.putpixel((9, 3), (107, 109, 113))
    recipe = FontAtlasRecipe("PIXEL.BMP", b"ABC", 1, implicit_right_edge=True)
    cells = parse_glyph_cells(source, recipe)

    output = _render_exact_raster_atlas(source, cells, recipe)

    assert output.size == (40, 20)
    assert [cell.rect for cell in cells] == [
        (1, 1, 3, 5),
        (3, 1, 7, 5),
        (7, 1, 10, 5),
    ]
    for cell in cells:
        left, top, right, bottom = cell.rect
        expected = source.crop(cell.rect).resize(
            ((right - left) * 4, (bottom - top) * 4),
            Image.Resampling.NEAREST,
        )
        actual = output.crop((left * 4, top * 4, right * 4, bottom * 4))
        assert np.array_equal(np.asarray(actual), np.asarray(expected))

    # Each marker keeps its exact x*4 coordinate and one-pixel width, so the
    # native parser cannot invent narrower, wider, or shifted glyph cells.
    marker = (213, 178, 246)
    assert [x for x in range(output.width) if output.getpixel((x, 0)) == marker] == [4, 12, 28]
    assert output.getpixel((0, 1)) == marker
    assert output.getpixel((0, 4)) == (255, 0, 255)


def test_exact_alpha_atlas_preserves_each_source_coverage_pixel() -> None:
    primary = Image.new("RGB", (4, 3), (255, 0, 255))
    primary.putpixel((1, 0), (255, 255, 255))
    recipe = FontAtlasRecipe("FONT.BMP", b"A", 1, alpha=True, implicit_right_edge=True)
    cells = parse_glyph_cells(primary, recipe)
    source = Image.new("L", (4, 3), 0)
    source.putpixel((1, 1), 96)

    output = _render_exact_raster_atlas(source, cells, recipe)

    assert output.mode == "L"
    assert output.crop((4, 4, 8, 8)).getextrema() == (96, 96)
    assert output.getpixel((4, 0)) == 0


@pytest.mark.parametrize("line_count", [1, 3])
@pytest.mark.parametrize("parser_background", [(255, 0, 255), (255, 255, 255)])
def test_marker_geometry_survives_distinct_parser_background(
    line_count: int,
    parser_background: tuple[int, int, int],
) -> None:
    """The native parser must recover sparse boundaries, not the color key."""
    key = (255, 0, 255)
    marker = (19, 37, 53)
    source = Image.new("RGB", (12, 6 * line_count), key)
    for y in range(2, source.height):
        source.putpixel((0, y), parser_background)
    source.putpixel((0, 1), (97, 101, 103))
    source.putpixel((0, 4), marker)  # Native vertical metric sentinel.
    boundaries = (1, 3, 8, 11)
    for row in range(line_count):
        for x in range(1, source.width):
            source.putpixel((x, row * 6), parser_background)
        for x in boundaries:
            source.putpixel((x, row * 6), marker)
            source.putpixel((x, row * 6 + 3), (109, 113, 127))
    characters = bytes(range(65, 65 + (4 if line_count == 1 else 3 * line_count)))
    recipe = FontAtlasRecipe(
        "FONT.BMP", characters, line_count, implicit_right_edge=line_count == 1
    )
    cells = parse_glyph_cells(source, recipe)

    output = _render_exact_raster_atlas(source, cells, recipe)

    assert output.getpixel((0, 0)) == key
    assert output.getpixel((0, 1)) == source.getpixel((0, 1))
    assert output.getpixel((0, 2)) == parser_background
    for row in range(line_count):
        assert [
            x
            for x in range(1, output.width)
            if output.getpixel((x, row * 6 * 4)) != output.getpixel((0, 2))
        ] == [x * 4 for x in boundaries]
    assert (
        next(y for y in range(2, output.height) if output.getpixel((0, y)) != parser_background)
        == 4 * 4
    )
    for cell in cells:
        left, top, right, bottom = cell.rect
        expected = source.crop(cell.rect).resize(
            ((right - left) * 4, (bottom - top) * 4), Image.Resampling.NEAREST
        )
        actual = output.crop((left * 4, top * 4, right * 4, bottom * 4))
        assert np.array_equal(np.asarray(actual), np.asarray(expected))
