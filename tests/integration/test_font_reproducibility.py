"""Representative font reconstruction, resume, and installation without private inputs."""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.pack.build as texture_pack
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.install.service import install_texture_pack, uninstall_texture_pack
from gk3hd.textures.native_bmp import encode_rgb565
from gk3hd.textures.pack.source import TexturePackSource
from gk3hd.textures.routing import PipelineKind
from gk3hd.textures.upscale import service
from gk3hd.textures.upscale.fonts.atlas import (
    FONT_ATLAS_COLOR_SIZES,
    FONT_OUTLINE_STAMP,
    font_atlas_recipe,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.service import UpscaleOptions
from gk3hd.textures.workspace import analysis_file
from tests.font_fixtures import make_courier_opacity_pair

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.slow


def _make_originals(directory: Path, *, reverse: bool) -> dict[str, bytes]:
    """Exercise unequal cells, row endings, symbols and paired coverage."""
    directory.mkdir(parents=True)
    # Paired coverage and exact-raster/optional-outline paths are sufficient here.
    # Glyph/layout variants have focused unit tests; don't rebuild the catalog.
    make_courier_opacity_pair(directory, "COURIER_R_12.BMP")
    for name in sorted(("F_ARIAL_T8.BMP", "F_TOOLTIP.BMP"), reverse=reverse):
        recipe = font_atlas_recipe(name)
        assert recipe is not None
        total_cells = len(recipe.characters)
        count = ceil(total_cells / recipe.line_count)
        boundaries = [1]
        for index in range(count):
            boundaries.append(boundaries[-1] + 2 + index % 4)
        width, height = FONT_ATLAS_COLOR_SIZES[name]
        row_height = height // recipe.line_count
        assert boundaries[-1] < width
        color = Image.new("RGB", (width, height), (248, 0, 248))
        alpha = Image.new("L", color.size, 0)
        parser_background = (255, 255, 255)
        color.paste(parser_background, (0, 2, 1, color.height))
        color.putpixel((0, 1), (123, 234, 45))
        color.putpixel((0, 4), (0, 0, 0))
        for row in range(recipe.line_count):
            top = row * row_height
            color.paste(parser_background, (1, top, width, top + 1))
            row_cells = min(count, total_cells - row * count)
            row_boundaries = boundaries[: row_cells + 1]
            markers = row_boundaries[:-1] if recipe.implicit_right_edge else row_boundaries
            for x in markers:
                color.putpixel((x, top), (0, 0, 255))
            for index, left in enumerate(row_boundaries[:-1]):
                position = (left + index % 2, top + 2 + index % 4)
                color.putpixel(position, (40 + index % 100, 96, 180))
                alpha.putpixel(position, 20 + index % 200)
        color.save(directory / name)
        if recipe.alpha_companion is not None:
            alpha.save(directory / recipe.alpha_companion)
    # Identification failure is not permission to infer a typeface or use AI.
    unknown = Image.new("RGB", (8, 5), (248, 0, 248))
    unknown.putpixel((3, 3), (255, 255, 255))
    unknown.save(directory / "F_UNIDENTIFIED.BMP")
    return {path.name: path.read_bytes() for path in directory.glob("*.BMP")}


def _rebuild(root: Path, *, automatic_analysis: bool) -> dict[str, bytes]:
    source, output = root / "original", root / "upscaled"
    names = {path.name for path in source.glob("*.BMP")} - {"F_UNIDENTIFIED.BMP"}
    count = len(names)
    if not automatic_analysis:
        analysis = texture_analyze.analyze(source)
        assert analysis.routes == {
            PipelineKind.FONT_ATLAS_SOURCE_4X: count,
            PipelineKind.FONT_ATLAS_UNCHANGED: 1,
        }
    report = texture_upscale.upscale(source, output)
    assert (report.created, report.skipped, report.excluded) == (count, 0, 1)
    report = texture_upscale.upscale(source, output)
    assert (report.created, report.skipped, report.excluded) == (0, count, 1)
    assert not (output / "F_UNIDENTIFIED.PNG").exists()
    assert (output / "F_TOOLTIP.PNG").exists()
    pack = texture_pack.pack(output, root / "gk3hd-texture-pack-v1.0.zip", version="1.0")
    game = root / "game"
    game.mkdir()
    ini = game / "GK3.ini"
    previous_ini = b"[Resource]\r\nCustom Paths=another-mod\r\n"
    ini.write_bytes(previous_ini)
    assert install_texture_pack(game, TexturePackSource.local(pack.archives[0])).textures == count
    installed = game / "gk3hd/textures/installed"
    artifacts = {
        "analysis": analysis_file(source).read_bytes(),
        "pack": pack.archives[0].read_bytes(),
        **{f"png/{path.name}": path.read_bytes() for path in output.glob("*.PNG")},
        **{f"bmp/{path.name}": path.read_bytes() for path in installed.glob("*.BMP")},
    }
    assert len(artifacts) == count * 2 + 2
    for name in names:
        with Image.open(output / f"{name[:-4]}.PNG") as image:
            if name in FONT_ATLAS_COLOR_SIZES:
                assert artifacts[f"bmp/{name}"] == encode_rgb565(image)
            else:
                assert artifacts[f"bmp/{name}"].startswith(b"BM")
                with (installed / name).open("rb") as stream, Image.open(stream) as decoded:
                    assert decoded.tobytes() == image.tobytes()
    uninstall_texture_pack(game)
    assert ini.read_bytes() == previous_ini
    return artifacts


@pytest.mark.integration
def test_font_routes_rebuild_without_external_fonts_or_private_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_backend(*_args: object) -> None:
        pytest.fail("source-atlas regeneration must not initialize or download an AI backend")

    monkeypatch.setattr(service, "_create_seedvr2_upscaler", unexpected_backend)
    first, second = tmp_path / "first", tmp_path / "different location" / "second"
    originals = _make_originals(first / "original", reverse=False)
    assert _make_originals(second / "original", reverse=True) == originals
    monkeypatch.chdir(first)
    explicit = _rebuild(first, automatic_analysis=False)
    monkeypatch.chdir(second)
    automatic = _rebuild(second, automatic_analysis=True)
    assert explicit == automatic
    for root in (first, second):
        assert {
            path.name: path.read_bytes() for path in (root / "original").glob("*.BMP")
        } == originals


@pytest.mark.integration
@pytest.mark.parametrize("member", ["COURIER_R_12.BMP", "COURIER_R_12A.BMP"])
def test_font_resume_rechecks_original_glyph_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    originals, output = tmp_path / "original", tmp_path / "upscaled"
    originals.mkdir()
    make_courier_opacity_pair(originals, "COURIER_R_12.BMP")
    monkeypatch.chdir(tmp_path)
    count = 2
    assert texture_upscale.upscale(originals, output).created == count
    destination = output / f"{member[:-4]}.PNG"
    previous = destination.read_bytes()
    source = originals / member
    with source.open("rb") as stream, Image.open(stream) as image:
        changed = image.copy()
    color_member = changed.mode == "RGB"
    # Mutate actual ink, not a background pixel in the variable-width fixture.
    position = (4, 3)
    assert changed.getpixel(position) == ((255, 255, 255) if color_member else 46)
    changed.putpixel(position, (255, 0, 255) if color_member else 211)
    changed.save(source)
    if color_member:
        companion = originals / "COURIER_R_12A.BMP"
        with companion.open("rb") as stream, Image.open(stream) as image:
            opacity = image.copy()
        opacity.putpixel(position, 0)
        opacity.save(companion)
    report = texture_upscale.upscale(originals, output)
    refreshed = 2 if color_member else 1
    assert (report.created, report.skipped) == (refreshed, count - refreshed)
    assert destination.read_bytes() != previous


@pytest.mark.integration
def test_explicit_font_variant_replaces_only_supported_atlases_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outline = pytest.importorskip("gk3hd.textures.upscale.fonts.outline", exc_type=ImportError)
    source, output = tmp_path / "original", tmp_path / "upscaled"
    _make_originals(source, reverse=False)
    monkeypatch.chdir(tmp_path)
    count = len(list(source.glob("*.BMP"))) - 1
    assert texture_upscale.upscale(source, output).created == count
    original_outputs = {path.name: path.read_bytes() for path in output.glob("*.PNG")}
    monkeypatch.setattr(
        outline,
        "supplied_font_files",
        lambda _path: {outline._REGULAR: b"regular fixture", outline._BOLD: b"bold fixture"},
    )

    def render(source: Path, _font_bytes: bytes) -> outline.OutlineAtlas:
        image = regenerate_font_atlas(source)
        image.putpixel((10, 10), (16, 32, 64))
        image.info[FONT_OUTLINE_STAMP] = "fixture provenance"
        return outline.OutlineAtlas(
            image,
            (
                outline.OutlineGlyph(65, "verified-outline"),
                outline.OutlineGlyph(66, "native-raster-mismatch"),
            ),
        )

    monkeypatch.setattr(outline, "regenerate_outline_atlas", render)
    options = UpscaleOptions(fonts=tmp_path / "explicit-fonts")
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped, report.excluded) == (2, count - 2, 1)
    assert (report.font_outlined_glyphs, report.font_retained_glyphs) == (2, 2)
    assert texture_upscale.upscale(source, output, options=options).skipped == count
    assert texture_upscale.upscale(source, output).created == 2
    assert {path.name: path.read_bytes() for path in output.glob("*.PNG")} == original_outputs
