"""Texture routing migrations and safe resume behavior with lightweight backends."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import load_feature_manifest, write_manifest
from gk3hd.textures.install.service import (
    install_texture_pack,
    uninstall_texture_pack,
    verify_texture_pack,
)
from gk3hd.textures.model import (
    TEXTURE_MANIFEST_SCHEMA_VERSION,
    TextureFeatures,
    TextureKind,
    TextureManifest,
)
from gk3hd.textures.pack.build import build_texture_pack
from gk3hd.textures.pack.source import TexturePackSource
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.fingerprint import (
    COMPARISON_FINGERPRINT_NAMES,
    EVIDENCE_FINGERPRINT_NAMES,
    WORKSTATION_MASK_SIZES,
    WORKSTATION_PRINT_SIZES,
    regenerate_fingerprint,
)
from gk3hd.textures.upscale.fonts.atlas import (
    FONT_ATLAS_COLOR_SIZES,
    font_atlas_recipe,
    regenerate_font_atlas,
)
from gk3hd.textures.upscale.generation import GENERATION_STAMP, generation_stamp
from gk3hd.textures.upscale.pipeline import KEY_COLOR, alpha_test_mask, upscale_key_mask
from gk3hd.textures.upscale.service import UpscaleOptions
from gk3hd.textures.upscale.ui_art import FINGERPRINT_TOOL_SIZES, UI_ART_SIZES, regenerate_ui_art
from gk3hd.textures.workspace import ANALYSIS_FILENAME, analysis_file
from tests.unit.textures.test_extraction import _write_barn_fixture

if TYPE_CHECKING:
    from pathlib import Path


class _NearestBackend:
    scale = 4

    def upscale(self, image: Image.Image) -> Image.Image:
        return image.resize((image.width * self.scale, image.height * self.scale))


def test_workstation_print_and_mask_resume_and_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    names = ("FP_LHOMIR_P1.BMP", "FP_LHOMIR_P1A.BMP")
    for name in names:
        mask = name in WORKSTATION_MASK_SIZES
        image = Image.new("L" if mask else "RGB", (25, 44), 0)
        image.paste(120 if mask else (100, 120, 140), (5, 7, 20, 38))
        image.save(source / name)
    write_manifest(
        TextureManifest(
            tuple(
                TextureFeatures(
                    n, kind=TextureKind.ALPHA if n in WORKSTATION_MASK_SIZES else TextureKind.COLOR
                )
                for n in names
            )
        ),
        analysis_file(source),
    )

    def forbid_ai(*_args: object, **_kwargs: object) -> None:
        pytest.fail("workstation evidence must not use AI")

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", forbid_ai)
    assert texture_upscale.upscale(source, output).created == 2
    assert texture_upscale.upscale(source, output).skipped == 2
    # Older palette-mode alpha and AI RGB outputs regenerate automatically.
    Image.new("P", (100, 176)).save(output / "FP_LHOMIR_P1A.PNG")
    Image.new("RGB", (100, 176), (240, 0, 0)).save(output / "FP_LHOMIR_P1.PNG")
    assert texture_upscale.upscale(source, output).created == 2
    pack = build_texture_pack(output, tmp_path / "gk3hd-texture-pack-v1.0.zip", version="1.0")
    game = tmp_path / "game"
    game.mkdir()
    ini = game / "GK3.ini"
    ini.write_bytes(b"[Resource]\r\nCustom Paths=\r\n")
    assert install_texture_pack(game, TexturePackSource.local(pack.archives[0])).textures == 2
    assert verify_texture_pack(game).textures == 2
    for name in names:
        data = (game / "gk3hd/textures/installed" / name).read_bytes()
        assert data.startswith(b"61nM" if name in WORKSTATION_PRINT_SIZES else b"BM")
    uninstall_texture_pack(game)


def test_fingerprint_tools_refresh_retention_and_roundtrip_without_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    names = tuple(FINGERPRINT_TOOL_SIZES)
    for index, name in enumerate(names):
        width, height = FINGERPRINT_TOOL_SIZES[name]
        image = Image.new("RGB", (width, height), (255, 0, 255))
        image.paste((100, 60 + index * 20, 20), (8, 5, width - 8, height - 5))
        image.save(source / name)
    originals = {name: (source / name).read_bytes() for name in names}
    write_manifest(
        TextureManifest(
            tuple(TextureFeatures(name, exact_raster=True, alphatest=True) for name in names),
            schema_version=TEXTURE_MANIFEST_SCHEMA_VERSION - 1,
        ),
        analysis_file(source),
    )

    def forbid_ai(*_args: object, **_kwargs: object) -> None:
        pytest.fail("source-preserving fingerprint tools must not load AI")

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", forbid_ai)
    generated = texture_upscale.upscale(source, output)
    assert (generated.created, generated.excluded) == (len(names), 0)
    assert texture_upscale.upscale(source, output).skipped == len(names)
    assert all(
        not item.exact_raster for item in load_feature_manifest(analysis_file(source)).values()
    )
    pack = build_texture_pack(output, tmp_path / "gk3hd-texture-pack-v1.0.zip", version="1.0")
    game = tmp_path / "game"
    game.mkdir()
    ini = game / "GK3.ini"
    original_ini = b"[Resource]\r\nCustom Paths=\r\n"
    ini.write_bytes(original_ini)
    assert install_texture_pack(game, TexturePackSource.local(pack.archives[0])).textures == len(
        names
    )
    assert verify_texture_pack(game).textures == len(names)
    for name in names:
        payload = (game / "gk3hd/textures/installed" / name).read_bytes()
        assert payload[:4] == b"61nM"
        assert (source / name).read_bytes() == originals[name]
    uninstall_texture_pack(game)
    assert ini.read_bytes() == original_ini


def test_schema_refresh_keeps_retained_cursor_opacity_aligned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    color, opacity = "C_TEST.BMP", "C_TEST_ALPHA.BMP"
    image = Image.new("RGB", (6, 4), (255, 0, 255))
    image.paste((120, 40, 20), (1, 1, 5, 3))
    image.save(source / color)
    Image.fromarray(np.arange(24, dtype=np.uint8).reshape(4, 6)).save(source / opacity)
    originals = {name: (source / name).read_bytes() for name in (color, opacity)}
    _write_barn_fixture(
        tmp_path / "Data",
        core_assets=[
            (color, originals[color], 0),
            (opacity, originals[opacity], 0),
            ("C_TEST.CUR", b"Alpha Channel=c_test_alpha\r\nHotspot=1,1", 0),
        ],
    )
    write_manifest(
        TextureManifest(
            (
                TextureFeatures(color, exact_raster=True, alphatest=True),
                TextureFeatures(opacity, kind=TextureKind.ALPHA),
            ),
            schema_version=TEXTURE_MANIFEST_SCHEMA_VERSION - 1,
        ),
        analysis_file(source),
    )
    stale = output / "C_TEST_ALPHA.PNG"
    Image.new("L", (24, 16), 128).save(stale)

    def forbid_ai(*_args: object, **_kwargs: object) -> None:
        pytest.fail("retained cursor pairs must not create an AI backend")

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", forbid_ai)
    report = texture_upscale.upscale(source, output)
    assert report.created == 0
    assert report.excluded == 2
    assert not stale.exists()
    assert load_feature_manifest(analysis_file(source))[opacity].native_size
    assert all((source / name).read_bytes() == original for name, original in originals.items())


def test_thumbnail_pair_reuses_large_original_without_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    large = source / "SNOTE6_ALPHA.BMP"
    Image.new("RGB", (601, 399), (180, 160, 140)).save(large)
    for name, size in (("SNOTE3", (32, 30)), ("SNOTE9", (94, 94))):
        Image.new("RGB", size, (60, 50, 40)).save(source / f"{name}.BMP")
        Image.new("RGB", (size[0] * 4, size[1] * 4)).save(output / f"{name}.PNG")
    Image.new("L", (94, 94), 255).save(source / "SNOTE9_OP.BMP")
    manifest = tmp_path / "analysis.json"
    write_manifest(
        TextureManifest(
            (
                TextureFeatures(name=large.name, native_size=True),
                TextureFeatures(name="SNOTE3.BMP"),
                TextureFeatures(name="SNOTE9.BMP"),
                TextureFeatures(name="SNOTE9_OP.BMP", kind=TextureKind.ALPHA),
            )
        ),
        manifest,
    )
    monkeypatch.setattr(
        texture_upscale,
        "_create_seedvr2_upscaler",
        lambda *_args, **_kwargs: pytest.fail("thumbnail reconstruction must not load AI"),
    )
    options = UpscaleOptions(features=manifest)
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped, report.excluded) == (3, 0, 1)
    for name in ("SNOTE9", "SNOTE9_OP"):
        with Image.open(output / f"{name}.PNG") as image:
            assert image.size == (376, 376)
    assert texture_upscale.upscale(source, output, options=options).skipped == 3
    Image.new("RGB", (601, 399), (100, 90, 80)).save(large)
    refreshed = texture_upscale.upscale(source, output, options=options)
    assert (refreshed.created, refreshed.skipped) == (2, 1)


@pytest.mark.parametrize(
    "name",
    [
        "COFFEECUP1",
        "COFFEECUP2",
        "BETSLCHRWOOD",
        "BROWNPLASTIC",
        "CLOPINEWHT",
        "CLORED",
        "CS2STRFRNT",
        "CHUFENCEGR",
        "CANDLE",
    ],
)
def test_smooth_material_replaces_ai_and_tracks_source_and_periodicity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    image = Image.new("RGB", (16, 16), (150, 0, 0))
    image.putpixel((0, 0), (50, 0, 0))
    original = source / f"{name}.BMP"
    image.save(original)
    destination = output / f"{name}.PNG"
    Image.new("RGB", (64, 64), (111, 111, 111)).save(destination)
    monkeypatch.setattr(
        texture_upscale,
        "_create_seedvr2_upscaler",
        lambda *_args, **_kwargs: pytest.fail("smooth materials must not load AI"),
    )
    first = texture_upscale.upscale(source, output)
    assert (first.created, first.skipped, first.excluded) == (1, 0, 0)
    manifest_path = analysis_file(source)
    feature = load_feature_manifest(manifest_path)[original.name]
    assert feature.pipeline_override is not None
    assert not feature.native_size
    assert plan_texture(feature).kind is PipelineKind.COLOR_SMOOTH
    assert texture_upscale.upscale(source, output).skipped == 1
    # Rebuild even a same-sized valid PNG when the source or sampling changes.
    image.putpixel((15, 15), (240, 0, 0))
    image.save(original)
    assert texture_upscale.upscale(source, output).created == 1
    payload = json.loads(manifest_path.read_text())
    payload["textures"][0]["tiled"] = True
    manifest_path.write_text(json.dumps(payload))
    assert texture_upscale.upscale(source, output).created == 1
    with Image.open(destination) as generated:
        assert generated.size == (64, 64)
        assert generated.mode == "RGB"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("name", "old_schema"),
    [
        ("COFFEECUP1", 113),
        ("COFFEECUP2", 113),
        ("BETSLCHRWOOD", 114),
        ("BROWNPLASTIC", 114),
        ("CLOPINEWHT", 114),
        ("CLORED", 114),
        ("CS2STRFRNT", 115),
        ("CHUFENCEGR", 115),
    ],
)
def test_smooth_families_migrate_old_ai_routes_without_affecting_other_materials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, old_schema: int
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    original = _color_art((64, 64), (120, 100, 65))
    original.save(source / f"{name}.BMP")
    analysis_file(source).write_text(
        json.dumps(
            {
                "schema_version": old_schema,
                "textures": [TextureFeatures(f"{name}.BMP").to_dict()],
            }
        )
    )
    Image.new("RGB", (256, 256), (111, 111, 111)).save(output / f"{name}.PNG")
    monkeypatch.setattr(
        texture_upscale,
        "_create_seedvr2_upscaler",
        lambda *_args, **_kwargs: pytest.fail("reviewed smooth shading must not load AI"),
    )
    first = texture_upscale.upscale(source, output)
    assert (first.created, first.skipped, first.excluded) == (1, 0, 0)
    assert texture_upscale.upscale(source, output).skipped == 1
    manifest = load_feature_manifest(analysis_file(source))
    assert plan_texture(manifest[f"{name}.BMP"]).kind is PipelineKind.COLOR_SMOOTH
    unrelated_name = f"UNREVIEWED_{name}.BMP"
    original.save(source / unrelated_name)
    report = texture_analyze.analyze(source)
    unrelated = next(t for t in report.manifest.textures if t.name == unrelated_name)
    assert plan_texture(unrelated).kind is PipelineKind.COLOR_AI


def _color_art(size: tuple[int, int], color: tuple[int, int, int]) -> Image.Image:
    """Give color-inference fixtures detail rather than a constant fill."""
    image = Image.new("RGB", size, color)
    image.putpixel((size[0] - 1, size[1] - 1), (color[0] ^ 1, color[1], color[2]))
    return image


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "21PILLOW",
        "27PILLOW",
        "BROWNPILLOW",
        "CHUFOUSHELT",
        "CLOBLEACHGREEN",
        "HALLMPPSTBS",
        "GRANOTEBK",
        "GRANOTEBK6_ALPHA",
        "BLUEAPPLE6_ALPHA",
    ],
)
def test_reviewed_color_choices_replace_old_bicubic_outputs_and_resume_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    original = source / f"{name}.BMP"
    _color_art((64, 64), (120, 100, 65)).save(original)
    analysis_file(source).write_text(
        json.dumps(
            {
                "schema_version": 163,
                "textures": [{**TextureFeatures(original.name).to_dict(), "smooth_color": True}],
            }
        )
    )
    destination = output / f"{name}.PNG"
    Image.new("RGB", (256, 256), (111, 111, 111)).save(destination)
    calls = []

    def backend(*_args: object) -> _NearestBackend:
        calls.append(True)
        return _NearestBackend()

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", backend)
    assert texture_upscale.upscale(source, output).created == 1
    feature = load_feature_manifest(analysis_file(source))[original.name]
    assert feature.kind is TextureKind.COLOR
    assert feature.pipeline_override is None
    assert plan_texture(feature).kind is PipelineKind.COLOR_AI
    with Image.open(destination) as generated:
        assert generated.size == (256, 256)
        assert generated.info[GENERATION_STAMP] == generation_stamp(original, plan_texture(feature))
    assert texture_upscale.upscale(source, output).skipped == 1
    assert len(calls) == 1


@pytest.mark.integration
def test_sign_refreshes_old_smooth_analysis_and_output_with_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    image = Image.new("RGB", (16, 16), (255, 0, 255))
    image.paste((70, 100, 40), (4, 4, 12, 12))
    original = source / "RC1HOTLSIGN.BMP"
    image.save(original)
    destination = output / "RC1HOTLSIGN.PNG"
    Image.new("RGB", (64, 64), (111, 111, 111)).save(destination)
    manifest_path = analysis_file(source)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 163,
                "textures": [{"name": original.name, "alphatest": True, "smooth_color": True}],
            }
        )
    )
    monkeypatch.setattr(
        texture_upscale,
        "_create_seedvr2_upscaler",
        lambda *_args: _NearestBackend(),
    )
    first = texture_upscale.upscale(source, output)
    assert (first.created, first.skipped, first.excluded) == (1, 0, 0)
    features = load_feature_manifest(manifest_path)[original.name]
    assert features.alphatest
    assert features.pipeline_override is None
    assert not features.native_size
    assert plan_texture(features).kind is PipelineKind.ALPHA_TEST_AI
    with Image.open(destination) as generated:
        assert generated.size == (64, 64)
        mask = upscale_key_mask(alpha_test_mask(np.asarray(image)), 4)
        assert np.array_equal(np.all(np.asarray(generated) == KEY_COLOR, axis=2), mask)
    assert texture_upscale.upscale(source, output).skipped == 1
    # Resume validates both the RGB shading and the contour, not merely size.
    image.putpixel((6, 6), (130, 140, 150))
    image.save(original)
    assert texture_upscale.upscale(source, output).created == 1
    with Image.open(destination) as generated:
        broken = generated.copy()
    broken.putpixel((0, 0), (0, 0, 0))
    broken.save(destination)
    assert texture_upscale.upscale(source, output).created == 1
    assert texture_upscale.upscale(source, output).skipped == 1


@pytest.mark.integration
@pytest.mark.parametrize(("name", "old_schema"), [("FINISHED", 46), ("DEATHSCREEN", 47)])
def test_screen_art_refreshes_old_guard_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, old_schema: int
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    _color_art((640, 480), (70, 80, 90)).save(source / f"{name}.BMP")
    manifest = analysis_file(source)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": old_schema,
                "textures": [{"name": f"{name}.BMP", "native_size": True}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        texture_upscale, "_create_seedvr2_upscaler", lambda *_args: _NearestBackend()
    )
    report = texture_upscale.upscale(source, output)
    assert (report.created, report.skipped, report.excluded) == (1, 0, 0)
    feature = load_feature_manifest(manifest)[f"{name}.BMP"]
    assert plan_texture(feature).kind is PipelineKind.COLOR_AI
    with Image.open(output / f"{name}.PNG") as image:
        assert image.size == (2560, 1920)
    assert texture_upscale.upscale(source, output).skipped == 1


def test_constant_colors_reanalyze_and_remove_stale_ai_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    for name, color in (("BLACK", (0, 0, 0)), ("HIDDEN", (255, 0, 255))):
        Image.new("RGB", (4, 4), color).save(source / f"{name}.BMP")
        Image.new("RGB", (16, 16), (111, 111, 111)).save(output / f"{name}.PNG")
    originals = {p.name: p.read_bytes() for p in source.iterdir()}
    analysis_file(source).write_text(json.dumps({"schema_version": 41, "textures": []}))
    monkeypatch.setattr(
        texture_upscale,
        "_create_seedvr2_upscaler",
        lambda *_args, **_kwargs: pytest.fail("constant colors must not load AI"),
    )
    report = texture_upscale.upscale(source, output)
    assert (report.created, report.skipped, report.excluded) == (0, 0, 2)
    assert not list(output.iterdir())
    assert {p.name: p.read_bytes() for p in source.iterdir()} == originals
    features = load_feature_manifest(analysis_file(source))
    assert all(f.constant_color and not f.native_size for f in features.values())


@pytest.mark.integration
def test_geometric_ui_replaces_ai_output_and_resumes_without_loading_a_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    samples = {
        name: UI_ART_SIZES[name]
        for name in ("INV_HIGHLIGHT.BMP", "S_BOX_SIDE.BMP", "C_WAIT.BMP", "C_WAIT_ALPHA.BMP")
    }
    for name, size in samples.items():
        if name.endswith("_ALPHA.BMP"):
            Image.new("L", size, 192).save(source / name)
        else:
            Image.new("RGB", size, (110, 80, 20)).save(source / name)
        Image.new("RGB", (size[0] * 4, size[1] * 4), (255, 255, 255)).save(
            output / name.replace(".BMP", ".PNG")
        )
    manifest = analysis_file(source)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 18,
                "textures": [{"name": name, "native_size": True} for name in samples],
            }
        ),
        encoding="utf-8",
    )

    def fail_model(*_args: object, **_kwargs: object) -> None:
        pytest.fail("geometric controls must not load an AI model")

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", fail_model)
    options = UpscaleOptions()
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped, report.excluded) == (len(samples), 0, 0)
    features = load_feature_manifest(manifest)
    assert all(not features[name].native_size for name in samples)
    assert all(plan_texture(features[name]).kind is PipelineKind.UI_SOURCE_4X for name in samples)
    for name in samples:
        with Image.open(output / name.replace(".BMP", ".PNG")) as result:
            assert result.tobytes() == regenerate_ui_art(source / name).tobytes()
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped, report.excluded) == (0, len(samples), 0)


@pytest.mark.integration
def test_paintings_refresh_previous_native_guards_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    names = ("POUSSIN.BMP", "TENIERS.BMP")
    for name in names:
        _color_art((8, 8), (70, 80, 90)).save(source / name)
    analysis_file(source).write_text(
        json.dumps(
            {
                "schema_version": 13,
                "textures": [{"name": name, "native_size": True} for name in names],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        texture_upscale, "_create_seedvr2_upscaler", lambda *_a, **_kw: _NearestBackend()
    )
    report = texture_upscale.upscale(source, output)
    manifest = load_feature_manifest(analysis_file(source))
    assert (report.created, report.excluded) == (2, 0)
    assert all(plan_texture(manifest[name]).kind is PipelineKind.COLOR_AI for name in names)
    for name in names:
        with Image.open(output / name.replace(".BMP", ".PNG")) as generated:
            assert generated.size == (32, 32)
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped, resumed.excluded) == (0, 2, 0)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("S_ABE_FPRINT.BMP", (41, 51)),
        ("MOSELYPRINT_3.BMP", (32, 30)),
        ("MOSELYPRINT_6_ALPHA.BMP", (307, 400)),
        ("MOSELYPRINT_9.BMP", (94, 94)),
        *((name, (41, 51)) for name in sorted(EVIDENCE_FINGERPRINT_NAMES)),
    ],
)
def test_fingerprints_refresh_old_guards_and_ai_outputs_without_model_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, size: tuple[int, int]
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    original = Image.new("RGB", size, (100, 100, 100))
    original.putpixel((5, 9), (0, 0, 0))
    if name in COMPARISON_FINGERPRINT_NAMES:
        original.paste((255, 0, 255), (10, 10, 30, 40))
    path = source / name
    original.save(path)
    analysis_file(source).write_text(
        json.dumps(
            {
                "schema_version": 12,
                "textures": [{"name": path.name, "native_size": True}],
            }
        ),
        encoding="utf-8",
    )
    destination = output / path.with_suffix(".PNG").name
    target_size = (size[0] * 4, size[1] * 4)
    Image.new("RGB", target_size, (255, 255, 255)).save(destination)

    def fail_model(*_args: object, **_kwargs: object) -> None:
        pytest.fail("fingerprint resampling must not construct an AI backend")

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", fail_model)
    report = texture_upscale.upscale(source, output)
    manifest = load_feature_manifest(analysis_file(source))
    assert not manifest[path.name].native_size
    assert plan_texture(manifest[path.name]).kind is PipelineKind.FINGERPRINT_SOURCE_4X
    assert (report.created, report.skipped, report.excluded) == (1, 0, 0)
    with Image.open(destination) as generated:
        assert generated.tobytes() == regenerate_fingerprint(path).tobytes()
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped) == (0, 1)
    original.putpixel((6, 9), (0, 0, 0))
    original.save(path)
    assert texture_upscale.upscale(source, output).created == 1


@pytest.mark.integration
def test_obsolete_inventory_size_guards_are_reanalyzed_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Previously excluded icons and close-ups enter their proper 4x routes."""
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    names = ("BLAZER_9.BMP", "BLAZER_9_OP.BMP", "SYRUP6_ALPHA.BMP")
    for name in (names[0], names[2]):
        _color_art((8, 8), (20, 30, 40)).save(source / name)
    Image.new("L", (8, 8), 128).save(source / names[1])
    analysis_file(source).write_text(
        json.dumps(
            {
                "schema_version": 5,
                "textures": [{"name": name, "native_size": True} for name in names],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        texture_upscale, "_create_seedvr2_upscaler", lambda *_a, **_kw: _NearestBackend()
    )
    report = texture_upscale.upscale(source, output)
    manifest = load_feature_manifest(analysis_file(source))
    assert (report.created, report.excluded) == (3, 0)
    assert all(not manifest[name].native_size for name in names)
    assert plan_texture(manifest[names[0]]).kind is PipelineKind.COLOR_AI
    assert plan_texture(manifest[names[1]]).kind is PipelineKind.ALPHA_SMOOTH
    assert plan_texture(manifest[names[2]]).kind is PipelineKind.COLOR_AI
    for path in output.glob("*.PNG"):
        with Image.open(path) as image:
            assert image.size == (32, 32)
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped, resumed.excluded) == (0, 3, 0)


@pytest.mark.integration
def test_email_crest_reanalyzes_old_size_guard_and_resumes_dense_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    name = "S_SCHAT_LOGO.BMP"
    _color_art((77, 76), (120, 70, 15)).save(source / name)
    analysis_file(source).write_text(
        json.dumps({"schema_version": 11, "textures": [{"name": name, "native_size": True}]}),
        encoding="utf-8",
    )
    calls = []

    def backend(*_args: object) -> _NearestBackend:
        calls.append(True)
        return _NearestBackend()

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", backend)
    report = texture_upscale.upscale(source, output)
    feature = load_feature_manifest(analysis_file(source))[name]
    assert not feature.native_size
    assert plan_texture(feature).kind is PipelineKind.COLOR_AI
    assert (report.created, report.excluded) == (1, 0)
    with Image.open(output / "S_SCHAT_LOGO.PNG") as image:
        assert image.size == (308, 304)
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped, len(calls)) == (0, 1, 1)


@pytest.mark.integration
def test_gps_and_lsr_inventory_pairs_refresh_old_guards_and_keep_opacity_non_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    names = []
    for base in ("GPS_9", "LSRPRINTGRACE_9", "LSRPRINTESTELLE_9"):
        color, opacity = f"{base}.BMP", f"{base}_OP.BMP"
        _color_art((94, 94), (20, 30, 40)).save(source / color)
        Image.new("L", (94, 94), 128).save(source / opacity)
        names.extend((color, opacity))
    analysis_file(source).write_text(
        json.dumps(
            {
                "schema_version": 10,
                "textures": [{"name": name, "native_size": True} for name in names],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    class Backend(_NearestBackend):
        def upscale(self, image: Image.Image) -> Image.Image:
            calls.append(image.mode)
            return super().upscale(image)

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", lambda *_args: Backend())
    report = texture_upscale.upscale(source, output)
    assert (report.created, report.excluded) == (6, 0)
    manifest = load_feature_manifest(analysis_file(source))
    for name in names:
        assert not manifest[name].native_size
        expected = (
            PipelineKind.ALPHA_SMOOTH
            if "_OP" in name
            else PipelineKind.COLOR_AI
            if name == "GPS_9.BMP"
            else PipelineKind.FINGERPRINT_SOURCE_4X
        )
        assert plan_texture(manifest[name]).kind is expected
        with Image.open(output / f"{name[:-4]}.PNG") as image:
            assert image.size == (376, 376)
            assert image.mode == ("P" if "_OP" in name else "RGB")
    assert calls == ["RGB"]
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped, len(calls)) == (0, 6, 1)


@pytest.mark.integration
def test_fingerprint_card_replaces_old_ai_outputs_without_loading_ai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    sizes = {
        "ABBEPRNT3": (32, 30),
        "ABBEPRNT9": (94, 94),
        "ABBEPRNT6_ALPHA": (305, 400),
    }
    originals = {}
    for name, size in sizes.items():
        image = _color_art(size, (230, 231, 233))
        image.save(source / f"{name}.BMP")
        originals[name] = image
        # Old AI output has the right dimensions but wrong evidence pixels.
        Image.new("RGB", (size[0] * 4, size[1] * 4), (17, 20, 23)).save(output / f"{name}.PNG")
    Image.new("L", (94, 94), 128).save(source / "ABBEPRNT9_OP.BMP")
    monkeypatch.setattr(
        texture_upscale,
        "_create_seedvr2_upscaler",
        lambda *_args: pytest.fail("fingerprint evidence must not load an AI model"),
    )
    report = texture_upscale.upscale(source, output)
    assert (report.created, report.excluded) == (4, 0)
    for name, original in originals.items():
        expected = original.resize(
            (original.width * 4, original.height * 4), Image.Resampling.BICUBIC
        )
        with Image.open(output / f"{name}.PNG") as actual:
            assert actual.convert("RGB").tobytes() == expected.tobytes()
    manifest = load_feature_manifest(analysis_file(source))
    assert manifest["ABBEPRNT6_ALPHA.BMP"].kind is TextureKind.COLOR
    assert manifest["ABBEPRNT9_OP.BMP"].kind is TextureKind.ALPHA
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped) == (0, 4)


@pytest.mark.integration
def test_interior_key_reinfers_contaminated_rgb_then_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    original = Image.new("RGB", (8, 8), (20, 30, 40))
    original.paste((255, 0, 255), (2, 2, 6, 6))
    original.save(source / "APERTURE.BMP")
    analysis_file(source).write_text(
        json.dumps(
            {
                "schema_version": 4,
                "textures": [{"name": "APERTURE.BMP", "alphatest": False}],
            }
        ),
        encoding="utf-8",
    )
    # Correct dimensions do not make RGB inferred with visible magenta valid.
    Image.new("RGB", (32, 32), (200, 10, 190)).save(output / "APERTURE.PNG")
    calls = []

    def backend(*_args: object, **_kwargs: object) -> _NearestBackend:
        calls.append(True)
        return _NearestBackend()

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", backend)
    report = texture_upscale.upscale(source, output)
    assert load_feature_manifest(analysis_file(source))["APERTURE.BMP"].alphatest
    assert (report.created, report.skipped) == (1, 0)
    assert len(calls) == 1
    with Image.open(output / "APERTURE.PNG") as result:
        assert result.getpixel((0, 0)) == (20, 30, 40)
        assert result.getpixel((16, 16)) == (255, 0, 255)
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped) == (0, 1)
    assert len(calls) == 1


@pytest.mark.integration
def test_binocular_mask_replaces_stale_ai_with_geometric_resampling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The packaged catalog, not a manual repair script, owns binocular-mask policy."""
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    mask = Image.new("RGB", (640, 480), (0, 0, 0))
    mask.paste((255, 0, 255), (200, 100, 440, 380))
    original = source / "BINOCMASK.BMP"
    mask.save(original)
    pristine = original.read_bytes()
    Image.new("RGB", (2560, 1920), (180, 0, 180)).save(output / "BINOCMASK.PNG")

    def no_ai(*_args: object, **_kwargs: object) -> None:
        pytest.fail("A geometric binocular mask must never initialize AI")

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", no_ai)
    report = texture_upscale.upscale(source, output)
    manifest = load_feature_manifest(analysis_file(source))
    assert not manifest[original.name].native_size
    assert plan_texture(manifest[original.name]).kind is PipelineKind.UI_SOURCE_4X
    assert report.created == 1
    assert report.excluded == 0
    with Image.open(output / "BINOCMASK.PNG") as result:
        assert result.size == (2560, 1920)
        assert result.getpixel((0, 0)) == (0, 0, 0)
        assert {color for _, color in result.getcolors() or []} == {(0, 0, 0), (255, 0, 255)}
    assert texture_upscale.upscale(source, output).skipped == 1
    assert original.read_bytes() == pristine


@pytest.mark.integration
def test_pixel_drawn_grab_animation_is_retained_by_default(tmp_path: Path) -> None:
    """The complete seven-frame pixel-art strip requires no manifest override."""
    source = tmp_path / "original"
    source.mkdir()
    original = source / "C_GRAB.BMP"
    strip = Image.new("RGB", (238, 35), (255, 0, 255))
    for frame in range(7):
        strip.paste((0, 0, 0), (34 * frame + 5, 6, 34 * frame + 20, 29))
        strip.paste((255, 220, 180), (34 * frame + 6, 7, 34 * frame + 19, 28))
    strip.save(original)
    pristine = original.read_bytes()
    output = tmp_path / "upscaled"
    output.mkdir()
    obsolete = output / "C_GRAB.PNG"
    strip.resize((952, 140)).save(obsolete)

    report = texture_upscale.upscale(source, output)
    manifest = load_feature_manifest(analysis_file(source))

    assert plan_texture(manifest[original.name]).kind is PipelineKind.EXACT_RASTER_UNCHANGED
    assert (report.created, report.skipped, report.excluded) == (0, 0, 1)
    assert not obsolete.exists()
    assert original.read_bytes() == pristine
    assert texture_upscale.upscale(source, output).excluded == 1


@pytest.mark.integration
def test_exact_raster_is_excluded_from_the_replacement_pack(tmp_path: Path) -> None:
    """Fixed-layout pixel art remains in the BRNs instead of changing UI geometry."""
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("RGB", (3, 2), (4, 5, 6)).save(source / "C_ICON.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "C_ICON.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": True,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "png"
    output.mkdir()
    Image.new("RGB", (12, 8), (4, 5, 6)).save(output / "C_ICON.PNG")

    options = UpscaleOptions(features=features)
    report = texture_upscale.upscale(source, output, options=options)

    assert (report.created, report.skipped, report.excluded) == (0, 0, 1)
    assert not (output / "C_ICON.PNG").exists()


@pytest.mark.integration
def test_resume_distinguishes_a_literal_texture_from_an_ntfs_8dot3_alias(
    tmp_path: Path,
) -> None:
    """A long-name PNG cannot impersonate GK3's separate explicit DOS name."""
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("L", (2, 2), 1).save(source / "FLOORT~1.BMP")
    Image.new("L", (2, 2), 10).save(source / "FLOORTILE.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 2,
                "textures": [
                    {
                        "name": name,
                        "kind": "alpha",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                    for name in ("FLOORT~1.BMP", "FLOORTILE.BMP")
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "png"
    output.mkdir()
    existing = Image.new("P", (8, 8), 10)
    existing.putpalette([value for value in range(256) for _channel in range(3)])
    existing.info[GENERATION_STAMP] = generation_stamp(
        source / "FLOORTILE.BMP",
        plan_texture(TextureFeatures(name="FLOORTILE.BMP", kind=TextureKind.ALPHA)),
    )
    texture_upscale._write_png_atomic(existing, output / "FLOORTILE.PNG")
    alias = output / "FLOORT~1.PNG"
    if not alias.exists() or alias.name.casefold() in {
        path.name.casefold() for path in output.iterdir()
    }:
        pytest.skip("filesystem does not generate NTFS 8.3 aliases")

    report = texture_upscale.upscale(
        source,
        output,
        options=UpscaleOptions(features=features),
    )

    assert (report.created, report.skipped) == (1, 1)
    assert {path.name.casefold() for path in output.iterdir()} == {
        "floort~1.png",
        "floortile.png",
    }
    with Image.open(output / "FLOORT~1.PNG") as image:
        assert image.convert("L").getpixel((0, 0)) == 1
    with Image.open(output / "FLOORTILE.PNG") as image:
        assert image.convert("L").getpixel((0, 0)) == 10


@pytest.mark.integration
def test_resume_replaces_an_output_mode_from_the_wrong_deterministic_route(
    tmp_path: Path,
) -> None:
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("L", (2, 2), 127).save(source / "FADE_OP.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "FADE_OP.BMP",
                        "kind": "alpha",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "png"
    output.mkdir()
    Image.new("RGB", (8, 8), (127, 127, 127)).save(output / "FADE_OP.PNG")

    report = texture_upscale.upscale(
        source,
        output,
        options=UpscaleOptions(features=features),
    )

    assert (report.created, report.skipped) == (1, 0)
    with Image.open(output / "FADE_OP.PNG") as image:
        assert image.mode == "P"


@pytest.mark.integration
def test_upscale_generates_default_colocated_analysis_once(tmp_path: Path) -> None:
    """The implicit feature manifest is created beside, then reused by, the BMP folder."""
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("RGB", (2, 2), (4, 5, 6)).save(source / "C_ICON.BMP")
    output = tmp_path / "png"

    texture_upscale.upscale(source, output)
    analysis = source.parent / ANALYSIS_FILENAME
    original = analysis.read_bytes()
    texture_upscale.upscale(source, output)

    assert analysis.read_bytes() == original
    assert not (output / "C_ICON.PNG").exists()


@pytest.mark.integration
def test_upscale_refreshes_an_implicit_manifest_from_the_previous_schema(
    tmp_path: Path,
) -> None:
    source = tmp_path / "textures" / "original"
    source.mkdir(parents=True)
    Image.new("RGB", (2, 2), (4, 5, 6)).save(source / "C_ICON.BMP")
    analysis = source.parent / ANALYSIS_FILENAME
    analysis.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "textures": [
                    {
                        "name": "C_ICON.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    texture_upscale.upscale(source, tmp_path / "png")

    migrated = json.loads(analysis.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == TEXTURE_MANIFEST_SCHEMA_VERSION
    assert migrated["textures"][0]["exact_raster"] is True


@pytest.mark.integration
def test_schema_refresh_excludes_an_unresolved_font_alpha_companion(tmp_path: Path) -> None:
    """Old analysis must not route an unresolved font mask through generic alpha."""
    source = tmp_path / "textures" / "original"
    source.mkdir(parents=True)
    name = "F_TIMES_B_I_12A.BMP"
    Image.new("L", (2, 2), 127).save(source / name)
    analysis = source.parent / ANALYSIS_FILENAME
    analysis.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "texture_count": 1,
                "textures": [
                    {
                        "name": name,
                        "kind": "alpha",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = texture_upscale.upscale(source, tmp_path / "png")

    migrated = json.loads(analysis.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == TEXTURE_MANIFEST_SCHEMA_VERSION
    assert migrated["textures"][0]["font_atlas"] is True
    assert report.excluded == 1
    assert not (tmp_path / "png" / name.replace(".BMP", ".PNG")).exists()


@pytest.mark.integration
def test_upscale_excludes_font_color_and_alpha_atlases(tmp_path: Path) -> None:
    """Font pixels encode metrics and remain supplied by the original BRNs."""
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("RGB", (4, 2), (255, 0, 255)).save(source / "FONT.BMP")
    Image.new("L", (4, 2), 127).save(source / "FONTA.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 2,
                "textures": [
                    {
                        "name": "FONT.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": True,
                        "exact_raster": False,
                        "font_atlas": True,
                    },
                    {
                        "name": "FONTA.BMP",
                        "kind": "alpha",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "png"

    report = texture_upscale.upscale(
        source,
        output,
        options=UpscaleOptions(features=features),
    )

    assert (report.textures, report.created, report.skipped, report.excluded) == (2, 0, 0, 2)
    assert not list(output.glob("*.PNG"))


@pytest.mark.integration
def test_upscale_regenerates_only_a_vetted_font_atlas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("RGB", (4, 2), (255, 0, 255)).save(source / "F_ARIAL_T8.BMP")
    output = tmp_path / "png"
    output.mkdir()
    Image.new("RGB", (16, 8), (0, 0, 0)).save(output / "F_ARIAL_T8.PNG")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "F_ARIAL_T8.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": True,
                        "exact_raster": False,
                        "font_atlas": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "gk3hd.textures.upscale.fonts.atlas.regenerate_font_atlas",
        lambda _source: Image.new("RGB", (16, 8), (1, 2, 3)),
    )

    report = texture_upscale.upscale(
        source,
        output,
        options=UpscaleOptions(features=features),
    )

    assert (report.textures, report.created, report.skipped, report.excluded) == (1, 1, 0, 0)
    with Image.open(output / "F_ARIAL_T8.PNG") as image:
        assert image.size == (16, 8)
        assert image.getpixel((0, 0)) == (1, 2, 3)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("glyph_size", "glyph_position"),
    [((20, 120), (5, 4))],
    ids=["squashed-stretched-and-shifted"],
)
@pytest.mark.slow
def test_upscale_repairs_distorted_glyphs_without_overwrite(
    tmp_path: Path,
    glyph_size: tuple[int, int],
    glyph_position: tuple[int, int],
) -> None:
    """Correct atlas dimensions and markers cannot excuse distorted glyph pixels."""
    recipe = font_atlas_recipe("RC_GOUDY12.BMP")
    assert recipe is not None
    widths = [10, *([7] * (len(recipe.characters) - 1))]
    widths[-1] += FONT_ATLAS_COLOR_SIZES[recipe.primary][0] - 1 - sum(widths)
    key = (0, 0, 0)
    original = Image.new("RGB", (1 + sum(widths), 16), key)
    original.putpixel((0, 12), (255, 0, 0))
    left = 1
    for width in widths:
        original.putpixel((left, 0), (255, 255, 255))
        left += width
    # Uneven side bearings, an internal gap, and empty baseline padding must
    # survive together; fitting only the ink bounds changes these metrics.
    original.paste((193, 197, 199), (3, 3, 8, 12))
    original.paste(key, (5, 5, 7, 9))
    source = tmp_path / "original"
    source.mkdir()
    source_path = source / recipe.primary
    original.save(source_path)
    expected = regenerate_font_atlas(source_path)
    stale = expected.copy()
    glyph = expected.crop((4, 4, 44, 64)).resize(glyph_size, Image.Resampling.NEAREST)
    stale.paste(key, (4, 4, 44, 64))
    stale.paste(glyph, glyph_position)
    assert not np.array_equal(np.asarray(stale), np.asarray(expected))
    output = tmp_path / "upscaled"
    output.mkdir()
    destination = output / "RC_GOUDY12.PNG"
    stale.save(destination)

    report = texture_upscale.upscale(source, output)

    assert (report.created, report.skipped) == (1, 0)
    with Image.open(destination) as fixed:
        assert np.array_equal(np.asarray(fixed), np.asarray(expected))
        source_cell = np.asarray(original)[1:16, 1:11]
        assert np.array_equal(
            np.asarray(fixed)[4:64, 4:44], source_cell.repeat(4, axis=0).repeat(4, axis=1)
        )
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped) == (0, 1)


@pytest.mark.integration
def test_upscale_repairs_caption_markers_without_overwrite(tmp_path: Path) -> None:
    """Valid-sized legacy PNGs with collapsed marker rows must not be resumed."""
    source = tmp_path / "original"
    source.mkdir()
    original = Image.new("RGB", (363, 6), (255, 0, 255))
    for x in range(1, original.width):
        original.putpixel((x, 0), (255, 255, 255))
    for x in range(1, original.width, 2):
        original.putpixel((x, 0), (255, 0, 255))
    original.putpixel((0, 1), (255, 255, 255))
    original.putpixel((0, 2), (255, 255, 255))
    original.putpixel((7, 3), (19, 37, 53))
    original.save(source / "F_CAPTION_GOUDY14.BMP")
    output = tmp_path / "upscaled"
    output.mkdir()
    # This is the previous generator's failure: correct dimensions and glyph
    # pixels, but transparency color in place of the white parser background.
    stale = original.resize((1452, 24), Image.Resampling.NEAREST)
    stale.paste((255, 0, 255), (0, 0, stale.width, 4))
    stale.paste((255, 0, 255), (0, 0, 4, stale.height))
    stale.putpixel((0, 1), (255, 255, 255))
    destination = output / "F_CAPTION_GOUDY14.PNG"
    stale.save(destination)

    report = texture_upscale.upscale(source, output)

    assert (report.created, report.skipped) == (1, 0)
    with Image.open(destination) as fixed:
        assert fixed.getpixel((0, 2)) == (255, 255, 255)
        assert [
            x for x in range(1, fixed.width) if fixed.getpixel((x, 0)) != fixed.getpixel((0, 2))
        ] == [x * 4 for x in range(1, original.width, 2)]
        assert fixed.getpixel((7 * 4, 3 * 4)) == (19, 37, 53)
    resumed = texture_upscale.upscale(source, output)
    assert (resumed.created, resumed.skipped) == (0, 1)


@pytest.mark.integration
def test_upscale_excludes_exact_raster_and_data_from_outputs(tmp_path: Path) -> None:
    """Native-size art and data remain in the BRNs instead of entering the pack."""
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("RGB", (2, 2), (4, 5, 6)).save(source / "ROOM.BMP")
    Image.new("L", (2, 2), 7).save(source / "ROOMWLKBNDS.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 2,
                "textures": [
                    {
                        "name": "ROOM.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": True,
                        "font_atlas": False,
                    },
                    {
                        "name": "ROOMWLKBNDS.BMP",
                        "kind": "data",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = texture_upscale.upscale(
        source,
        tmp_path / "png",
        options=UpscaleOptions(features=features),
    )

    assert (report.textures, report.created, report.skipped, report.excluded) == (2, 0, 0, 2)
    assert not (tmp_path / "png" / "ROOM.PNG").exists()
    assert not (tmp_path / "png" / "ROOMWLKBNDS.PNG").exists()


@pytest.mark.integration
def test_resume_regenerates_an_obsolete_key_mask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An obsolete alpha stamp regenerates through the current full pipeline."""
    source = tmp_path / "bmp"
    source.mkdir()
    pixels = np.array(
        [
            [(255, 0, 255), (255, 0, 255), (10, 20, 30)],
            [(255, 0, 255), (10, 20, 30), (10, 20, 30)],
            [(10, 20, 30), (10, 20, 30), (10, 20, 30)],
        ],
        dtype=np.uint8,
    )
    Image.fromarray(pixels, mode="RGB").save(source / "KEYED.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "KEYED.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": True,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "png"
    output.mkdir()
    nearest = Image.fromarray(pixels, mode="RGB").resize((12, 12), Image.Resampling.NEAREST)
    nearest.info[GENERATION_STAMP] = generation_stamp(
        source / "KEYED.BMP", plan_texture(TextureFeatures(name="KEYED.BMP", alphatest=True))
    )
    texture_upscale._write_png_atomic(nearest, output / "KEYED.PNG")

    calls: list[str] = []

    def backend(*_args: object) -> _NearestBackend:
        calls.append("loaded")
        return _NearestBackend()

    monkeypatch.setattr(texture_upscale, "_create_seedvr2_upscaler", backend)
    options = UpscaleOptions(features=features)
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped) == (1, 0)
    assert calls == ["loaded"]
    with Image.open(output / "KEYED.PNG") as image:
        actual = np.all(np.asarray(image) == KEY_COLOR, axis=2)
    expected = upscale_key_mask(alpha_test_mask(pixels), 4)
    np.testing.assert_array_equal(actual, expected)
    resumed = texture_upscale.upscale(source, output, options=options)
    assert (resumed.created, resumed.skipped) == (0, 1)
    assert calls == ["loaded"]


@pytest.mark.integration
@pytest.mark.parametrize("periodic", [False, True])
def test_stale_ai_output_regenerates_with_current_source_contour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, periodic: bool
) -> None:
    source, output = tmp_path / "original", tmp_path / "upscaled"
    source.mkdir()
    output.mkdir()
    pixels = np.full((16, 32, 3), KEY_COLOR, dtype=np.uint8)
    pixels[0, 1] = (82, 56, 57)
    pixels[6:14, 10:28] = (110, 80, 30)
    Image.fromarray(pixels).save(source / "SIGN.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "SIGN.BMP",
                        "kind": "color",
                        "tiled": periodic,
                        "alphatest": True,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    legacy_mask = upscale_key_mask(np.all(pixels == KEY_COLOR, axis=2), 4, periodic=periodic)
    legacy = np.full((64, 128, 3), (100, 70, 20), dtype=np.uint8)
    legacy[legacy_mask] = KEY_COLOR
    generated = Image.fromarray(legacy)
    generated.info[GENERATION_STAMP] = generation_stamp(
        source / "SIGN.BMP",
        plan_texture(TextureFeatures(name="SIGN.BMP", alphatest=True, tiled=periodic)),
    )
    texture_upscale._write_png_atomic(generated, output / "SIGN.PNG")

    monkeypatch.setattr(
        texture_upscale, "_create_seedvr2_upscaler", lambda *_a, **_kw: _NearestBackend()
    )
    options = UpscaleOptions(features=features)
    report = texture_upscale.upscale(source, output, options=options)
    assert (report.created, report.skipped) == (1, 0)
    with Image.open(output / "SIGN.PNG") as image:
        repaired = np.asarray(image)
    expected = upscale_key_mask(alpha_test_mask(pixels), 4, periodic=periodic)
    np.testing.assert_array_equal(np.all(repaired == KEY_COLOR, axis=2), expected)
    assert np.count_nonzero(expected & ~legacy_mask) > 0
    resumed = texture_upscale.upscale(source, output, options=options)
    assert (resumed.created, resumed.skipped) == (0, 1)


@pytest.mark.integration
def test_upscale_wraps_backend_defects_with_texture_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An optional-backend defect reaches the CLI as a concise domain error."""
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("RGB", (2, 2), (4, 5, 6)).save(source / "PHOTO.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "PHOTO.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class BrokenBackend:
        scale = 4

        def upscale(self, _image: Image.Image) -> Image.Image:
            msg = "backend implementation defect"
            raise AttributeError(msg)

    monkeypatch.setattr(
        texture_upscale,
        "_create_seedvr2_upscaler",
        lambda *_args: BrokenBackend(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"could not upscale PHOTO\.BMP: backend implementation defect",
    ):
        texture_upscale.upscale(
            source,
            tmp_path / "png",
            options=UpscaleOptions(features=features),
        )


@pytest.mark.integration
def test_upscale_keeps_a_complete_destination_when_png_encoding_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "bmp"
    source.mkdir()
    Image.new("L", (2, 2), 127).save(source / "FADE_OP.BMP")
    features = tmp_path / "features.json"
    features.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "FADE_OP.BMP",
                        "kind": "alpha",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "png"
    texture_upscale.upscale(source, output, options=UpscaleOptions(features=features))
    destination = output / "FADE_OP.PNG"
    original = destination.read_bytes()

    def fail_save(
        _self: Image.Image,
        _fp: object,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        msg = "simulated encoder failure"
        raise OSError(msg)

    monkeypatch.setattr(Image.Image, "save", fail_save)
    with pytest.raises(RuntimeError, match="simulated encoder failure"):
        texture_upscale.upscale(
            source,
            output,
            options=UpscaleOptions(features=features, overwrite=True),
        )

    assert destination.read_bytes() == original
    assert not list(output.glob(".*.tmp"))
