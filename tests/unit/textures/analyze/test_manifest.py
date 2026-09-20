from __future__ import annotations

import json
import struct
from typing import TYPE_CHECKING

import pytest

import gk3hd.textures.analyze.manifest as texture_analyze
from gk3hd.textures.analyze.manifest import analyze_directory, load_feature_manifest, write_manifest
from gk3hd.textures.analyze.usage import TextureUsage
from gk3hd.textures.model import TEXTURE_MANIFEST_SCHEMA_VERSION, TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.cursor_art import CURSOR_OPACITY_PAIRS
from gk3hd.textures.upscale.ui_art import FINGERPRINT_TOOL_SIZES, UI_ART_SIZES, regenerate_ui_art

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.textures.analyze.manifest import AnalysisReport


@pytest.mark.parametrize("name", FINGERPRINT_TOOL_SIZES)
def test_fingerprint_tools_are_verified_ui_not_ordinary_cursors(tmp_path: Path, name: str) -> None:
    size = FINGERPRINT_TOOL_SIZES[name]
    _write_bmp24(tmp_path / name, size=size, top_left=(255, 0, 255))
    _write_bmp24(tmp_path / "C_OTHER.BMP", size=(24, 114))
    features = {item.name: item for item in analyze_directory(tmp_path).manifest.textures}
    assert not features[name].exact_raster
    assert features[name].alphatest
    assert plan_texture(features[name]).kind is PipelineKind.UI_SOURCE_4X
    assert features["C_OTHER.BMP"].exact_raster
    _write_bmp24(tmp_path / name, size=(size[0], size[1] - 1))
    features = {item.name: item for item in analyze_directory(tmp_path).manifest.textures}
    assert not features[name].exact_raster
    with pytest.raises(ValueError, match=r"expected a .* source"):
        regenerate_ui_art(tmp_path / name)


def test_workstation_rgb_opacity_is_not_color_artwork(tmp_path: Path) -> None:
    name = "FP_BLOMAN_P1A.BMP"
    _write_bmp24(tmp_path / name, size=(30, 47))
    _write_bmp24(tmp_path / "UNRELATED_P1A.BMP", size=(30, 47))
    features = {item.name: item for item in analyze_directory(tmp_path).manifest.textures}
    assert features[name].kind is TextureKind.ALPHA
    assert features["UNRELATED_P1A.BMP"].kind is TextureKind.COLOR
    _write_bmp24(tmp_path / name, size=(31, 47))
    features = {item.name: item for item in analyze_directory(tmp_path).manifest.textures}
    assert features[name].kind is TextureKind.ALPHA


def test_load_feature_manifest(tmp_path: Path) -> None:
    path = tmp_path / "features.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "textures": [
                    {
                        "name": "thing.bmp",
                        "kind": "color",
                        "tiled": True,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_feature_manifest(path)
    assert loaded["THING.BMP"].tiled


def _write_bmp24(
    path: Path,
    *,
    top_left: tuple[int, int, int] = (0, 0, 0),
    size: tuple[int, int] = (2, 2),
) -> None:
    red, green, blue = top_left
    width, height = size
    row_size = ((24 * width + 31) // 32) * 4
    row = bytes((blue, green, red)) * width + bytes(row_size - width * 3)
    # Ordinary-art fixtures need actual detail: a flat fill now intentionally
    # selects the constant-color route instead of AI inference.
    pixels = bytearray(row * height)
    if width * height > 1:
        offset = (width - 1) * 3
        pixels[offset : offset + 3] = bytes((blue ^ 1, green, red))
    header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 0, 0, 0, 0)
    path.write_bytes(header + dib + pixels)


def _write_bmp8(path: Path, indexes: bytes, palette: list[tuple[int, int, int]]) -> None:
    width = len(indexes)
    row_size = ((width + 3) // 4) * 4
    pixels = indexes + b"\0" * (row_size - width)
    palette_bytes = b"".join(
        struct.pack("<BBBB", blue, green, red, 0) for red, green, blue in palette
    )
    offset = 54 + len(palette_bytes)
    header = struct.pack("<2sIHHI", b"BM", offset + len(pixels), 0, 0, offset)
    dib = struct.pack("<IiiHHIIiiII", 40, width, 1, 1, 8, 0, len(pixels), 0, 0, len(palette), 0)
    path.write_bytes(header + dib + palette_bytes + pixels)


def _by_name(report: AnalysisReport) -> dict[str, TextureFeatures]:
    return {texture.name: texture for texture in report.manifest.textures}


def _feature_policy(names: list[str], **values: object) -> str:
    return json.dumps(
        {
            "schema_version": 9,
            "feature_overrides": [
                {"textures": names, "set": values, "reason": "Explicit test correction."}
            ],
        }
    )


@pytest.mark.parametrize("retained", [True, False])
def test_cursor_opacity_follows_the_final_color_route(tmp_path: Path, *, retained: bool) -> None:
    _write_bmp24(tmp_path / "C_TEST.BMP", size=(2, 1), top_left=(255, 0, 255))
    _write_bmp8(tmp_path / "C_TEST_ALPHA.BMP", b"\0\1", [(0, 0, 0), (255, 255, 255)])
    overrides = tmp_path / "override.json"
    overrides.write_text(
        _feature_policy(["C_TEST.BMP"], exact_raster=retained),
        encoding="utf-8",
    )
    usage = TextureUsage(cursor_opacity_pairs=frozenset({("C_TEST.BMP", "C_TEST_ALPHA.BMP")}))
    textures = _by_name(analyze_directory(tmp_path, overrides=overrides, usage=usage))
    alpha = textures["C_TEST_ALPHA.BMP"]
    assert alpha.kind is TextureKind.ALPHA
    assert alpha.native_size is retained
    assert plan_texture(alpha).kind is (
        PipelineKind.NATIVE_SIZE_UNCHANGED if retained else PipelineKind.ALPHA_SMOOTH
    )


def test_cursor_opacity_rejects_mismatched_original_dimensions(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "C_TEST.BMP", size=(3, 1))
    _write_bmp8(tmp_path / "C_TEST_ALPHA.BMP", b"\0\1", [(0, 0, 0), (255, 255, 255)])
    usage = TextureUsage(cursor_opacity_pairs=frozenset({("C_TEST.BMP", "C_TEST_ALPHA.BMP")}))
    with pytest.raises(ValueError, match="different source dimensions"):
        analyze_directory(tmp_path, usage=usage)


def test_absent_cursor_color_does_not_freeze_a_standalone_opacity(tmp_path: Path) -> None:
    _write_bmp8(tmp_path / "C_TEST_ALPHA.BMP", b"\0\1", [(0, 0, 0), (255, 255, 255)])
    usage = TextureUsage(cursor_opacity_pairs=frozenset({("C_TEST.BMP", "C_TEST_ALPHA.BMP")}))
    alpha = _by_name(analyze_directory(tmp_path, usage=usage))["C_TEST_ALPHA.BMP"]
    assert not alpha.native_size


def test_classifies_actual_gk3_naming_conventions(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "TITLE.BMP")
    _write_bmp24(tmp_path / "TREE.BMP", top_left=(255, 0, 255))
    _write_bmp24(tmp_path / "C_CONSTRUCT.BMP", top_left=(255, 0, 255))
    _write_bmp24(tmp_path / "I_LOOK_STD.BMP", size=(32, 32))
    _write_bmp24(tmp_path / "RC_OPTIONS_STD.BMP", size=(32, 32))
    _write_bmp24(tmp_path / "RC_PANEL.BMP", size=(252, 75))
    _write_bmp8(tmp_path / "ITEM9_OP.BMP", bytes((0, 1)), [(0, 0, 0), (255, 255, 255)])
    _write_bmp8(tmp_path / "ROOMWLKBNDS.BMP", bytes((0, 1)), [(255, 255, 255), (0, 0, 255)])
    _write_bmp8(tmp_path / "ROOM_A_512FT_MASK.BMP", bytes((0, 1)), [(255, 255, 255), (0, 0, 255)])
    _write_bmp24(tmp_path / "BNDRY1.BMP", size=(256, 256))
    _write_bmp8(tmp_path / "SHOVELGREY9.BMP", bytes((0, 1)), [(0, 0, 0), (255, 255, 255)])

    textures = _by_name(analyze_directory(tmp_path))

    assert textures["TITLE.BMP"].kind is TextureKind.COLOR
    assert textures["TREE.BMP"].alphatest
    assert textures["C_CONSTRUCT.BMP"].exact_raster
    assert textures["I_LOOK_STD.BMP"].exact_raster
    assert not textures["RC_OPTIONS_STD.BMP"].exact_raster
    assert plan_texture(textures["RC_OPTIONS_STD.BMP"]).kind is PipelineKind.UI_SOURCE_4X
    assert not textures["RC_PANEL.BMP"].exact_raster
    assert textures["ITEM9_OP.BMP"].kind is TextureKind.ALPHA
    assert textures["ROOMWLKBNDS.BMP"].kind is TextureKind.DATA
    assert textures["ROOM_A_512FT_MASK.BMP"].kind is TextureKind.DATA
    assert textures["BNDRY1.BMP"].kind is TextureKind.DATA
    assert textures["SHOVELGREY9.BMP"].kind is TextureKind.COLOR


def test_recognizes_same_size_a_suffix_alpha_companion(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "FONT.BMP", size=(1, 1))
    _write_bmp8(tmp_path / "FONTA.BMP", bytes((0,)), [(127, 127, 127)])

    textures = _by_name(analyze_directory(tmp_path))

    assert textures["FONTA.BMP"].kind is TextureKind.ALPHA


def test_applies_explicit_feature_corrections(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "STONE.BMP")
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        _feature_policy(["stone.bmp"], tiled=True),
        encoding="utf-8",
    )

    texture = analyze_directory(tmp_path, overrides=overrides).manifest.textures[0]

    assert texture.tiled
    assert texture.kind is TextureKind.COLOR


def test_applies_grouped_font_atlas_corrections(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "F_CAPTION_GOUDY14.BMP", top_left=(255, 0, 255))
    _write_bmp8(
        tmp_path / "F_CAPTION_GOUDY14AA_ALPHA.BMP",
        bytes((0, 1)),
        [(0, 0, 0), (255, 255, 255)],
    )
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        _feature_policy(
            ["F_CAPTION_GOUDY14.BMP", "F_CAPTION_GOUDY14AA_ALPHA.BMP"], font_atlas=True
        ),
        encoding="utf-8",
    )

    report = analyze_directory(tmp_path, overrides=overrides)
    textures = _by_name(report)

    assert textures["F_CAPTION_GOUDY14.BMP"].font_atlas
    assert textures["F_CAPTION_GOUDY14.BMP"].alphatest
    assert not textures["F_CAPTION_GOUDY14.BMP"].exact_raster
    assert textures["F_CAPTION_GOUDY14AA_ALPHA.BMP"].font_atlas
    assert textures["F_CAPTION_GOUDY14AA_ALPHA.BMP"].kind is TextureKind.ALPHA
    assert report.routes == {PipelineKind.FONT_ATLAS_SOURCE_4X: 2}


def test_applies_native_size_correction(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "TITLE_PLAY_U.BMP")
    overrides = tmp_path / "overrides.json"
    overrides.write_text(_feature_policy(["TITLE_PLAY_U.BMP"], native_size=True), encoding="utf-8")

    report = analyze_directory(tmp_path, overrides=overrides)
    texture = report.manifest.textures[0]

    assert texture.native_size
    assert report.routes == {PipelineKind.NATIVE_SIZE_UNCHANGED: 1}


@pytest.mark.parametrize(
    ("name", "size"),
    [(name, UI_ART_SIZES[name]) for name in ("INV_HIGHLIGHT.BMP", "S_BOX_SIDE.BMP", "C_WAIT.BMP")],
)
def test_packaged_catalog_enlarges_verified_controls_as_geometry(
    tmp_path: Path, name: str, size: tuple[int, int]
) -> None:
    _write_bmp24(tmp_path / name, size=size)

    for color, opacity in CURSOR_OPACITY_PAIRS.items():
        if name in (color, opacity):
            _write_bmp24(tmp_path / color, size=size)
            _write_bmp24(tmp_path / opacity, size=size)

    report = texture_analyze.analyze(tmp_path, tmp_path / "texture-analysis.json")

    texture = report.manifest.textures[0]
    assert not texture.native_size
    assert report.routes == {PipelineKind.UI_SOURCE_4X: len(report.manifest.textures)}


def test_packaged_policy_upscales_ordinary_model_materials(tmp_path: Path) -> None:
    for name, size in (("CANDY", (128, 128)), ("GOAT", (128, 128)), ("DAGGER", (128, 512))):
        _write_bmp24(tmp_path / f"{name}.BMP", size=size)

    report = texture_analyze.analyze(tmp_path, tmp_path / "analysis.json")

    assert all(not texture.native_size for texture in report.manifest.textures)
    assert report.routes == {PipelineKind.COLOR_AI: 3}


@pytest.mark.parametrize(
    ("name", "size", "route"),
    [
        ("ARMWLKBNDS.BMP", (256, 256), PipelineKind.DATA_UNCHANGED),
        ("C_CONSTRUCT.BMP", (16, 16), PipelineKind.EXACT_RASTER_UNCHANGED),
        ("I_LOOK_STD.BMP", (32, 32), PipelineKind.EXACT_RASTER_UNCHANGED),
        ("RC_OPTIONS_STD.BMP", (32, 32), PipelineKind.UI_SOURCE_4X),
        ("OPTSC.BMP", (252, 36), PipelineKind.EXACT_RASTER_UNCHANGED),
        ("CHECKERTRANS.BMP", (8, 8), PipelineKind.EXACT_RASTER_UNCHANGED),
        ("DISCOBALLSPECKS.BMP", (64, 64), PipelineKind.EXACT_RASTER_UNCHANGED),
        ("F_ARIAL_T8.BMP", (256, 16), PipelineKind.FONT_ATLAS_SOURCE_4X),
        ("COURIER_B_14.BMP", (256, 64), PipelineKind.FONT_ATLAS_SOURCE_4X),
        ("SID_CAP_16.BMP", (256, 64), PipelineKind.FONT_ATLAS_SOURCE_4X),
        ("RC_SO_SAVE_STD.BMP", (60, 17), PipelineKind.FONT_BUTTON_SOURCE_4X),
    ],
)
def test_intrinsic_routes_do_not_depend_on_redundant_native_guards(
    tmp_path: Path, name: str, size: tuple[int, int], route: PipelineKind
) -> None:
    # Deliberately no Data directory: dynamic archive evidence is unavailable.
    _write_bmp24(tmp_path / name, size=size)
    report = texture_analyze.analyze(tmp_path, tmp_path / "analysis.json")
    assert not report.manifest.textures[0].native_size
    assert report.routes == {route: 1}


def test_plain_options_panel_correction_is_by_name_not_size(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "OPTSC.BMP", size=(252, 75))
    _write_bmp24(tmp_path / "OTHER_PANEL.BMP", size=(252, 36))
    textures = analyze_directory(tmp_path).manifest.textures
    assert {texture.name for texture in textures if texture.exact_raster} == {"OPTSC.BMP"}


def test_stipple_identity_does_not_exclude_arbitrary_small_cutouts(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "CHECKERTRANS.BMP", size=(16, 16))
    _write_bmp24(tmp_path / "OTHER_CUTOUT.BMP", size=(8, 8))
    _write_bmp24(tmp_path / "DISCOBALLSPECKS.BMP", size=(128, 128))
    _write_bmp24(tmp_path / "OTHER_LIGHTS.BMP", size=(64, 64))
    textures = analyze_directory(tmp_path).manifest.textures
    assert {texture.name for texture in textures if texture.exact_raster} == {
        "CHECKERTRANS.BMP",
        "DISCOBALLSPECKS.BMP",
    }


@pytest.mark.parametrize("name", ["FINISHED.BMP", "DEATHSCREEN.BMP"])
def test_screen_illustration_is_color_art_not_a_native_font_atlas(
    tmp_path: Path, name: str
) -> None:
    _write_bmp24(tmp_path / name, size=(640, 480))
    report = texture_analyze.analyze(tmp_path, tmp_path / "analysis.json")
    feature = report.manifest.textures[0]
    assert not feature.native_size
    assert not feature.font_atlas
    assert not feature.tiled
    assert report.routes == {PipelineKind.COLOR_AI: 1}


def test_packaged_policy_upscales_help_mouse_diagrams_with_color_key(tmp_path: Path) -> None:
    for name, size in (
        ("BOTHKEYS", (131, 140)),
        ("MOUSEMVT", (160, 154)),
        ("LCMOUSE", (38, 51)),
        ("RCMOUSE", (38, 51)),
    ):
        _write_bmp24(tmp_path / f"{name}.BMP", size=size, top_left=(255, 0, 255))

    report = texture_analyze.analyze(tmp_path, tmp_path / "analysis.json")

    assert all(not texture.native_size for texture in report.manifest.textures)
    assert report.routes == {PipelineKind.ALPHA_TEST_AI: 4}


def test_packaged_policy_separates_ai_paintings_from_source_faithful_clues(
    tmp_path: Path,
) -> None:
    names = ("POUSSIN", "TENIERS", "POUSSIN_ZOOM", "TENIERS_ZOOM", "ZION_ROT", "SION", "PYTHAGORAS")
    for name in names:
        _write_bmp24(tmp_path / f"{name}.BMP")
    textures = _by_name(texture_analyze.analyze(tmp_path, tmp_path / "analysis.json"))
    for name in names[:2]:
        assert not textures[f"{name}.BMP"].native_size
        assert plan_texture(textures[f"{name}.BMP"]).kind is PipelineKind.COLOR_AI
    for name in names[2:]:
        assert not textures[f"{name}.BMP"].native_size
        assert plan_texture(textures[f"{name}.BMP"]).kind is PipelineKind.UI_SOURCE_4X


def test_packaged_catalog_upscales_the_driving_map_as_one_family(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "DM_ARM.BMP", size=(55, 39))
    _write_bmp24(tmp_path / "DM_ARM_UL.BMP", size=(55, 39))
    _write_bmp24(tmp_path / "DM_BASE.BMP", size=(640, 480))

    report = texture_analyze.analyze(tmp_path, tmp_path / "texture-analysis.json")
    textures = _by_name(report)

    assert not textures["DM_ARM.BMP"].native_size
    assert not textures["DM_ARM_UL.BMP"].native_size
    assert not textures["DM_BASE.BMP"].native_size
    assert report.routes == {
        PipelineKind.COLOR_AI: 1,
        PipelineKind.DRIVING_MAP_COMPOSITE: 2,
    }


def test_writes_deterministic_explicit_manifest(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "B.BMP")
    _write_bmp24(tmp_path / "A.BMP")
    output = tmp_path / "features.json"

    report = analyze_directory(tmp_path)
    write_manifest(report.manifest, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == TEXTURE_MANIFEST_SCHEMA_VERSION
    assert payload["texture_count"] == 2
    assert [entry["name"] for entry in payload["textures"]] == ["A.BMP", "B.BMP"]
    assert payload["textures"][0] == {
        "name": "A.BMP",
        "kind": "color",
        "tiled": False,
        "alphatest": False,
        "exact_raster": False,
        "font_atlas": False,
        "native_size": False,
        "constant_color": False,
        "alpha_silhouette": False,
        "processing": {"pipeline": "ai", "variant": "color"},
    }


def test_rejects_unknown_override_names(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "A.BMP")
    overrides = tmp_path / "overrides.json"
    overrides.write_text(_feature_policy(["MISSING.BMP"], tiled=True), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown texture"):
        analyze_directory(tmp_path, overrides=overrides)


def test_can_report_unused_overrides_in_partial_corpus(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "A.BMP")
    overrides = tmp_path / "overrides.json"
    overrides.write_text(_feature_policy(["MISSING.BMP"], tiled=True), encoding="utf-8")

    report = analyze_directory(
        tmp_path,
        overrides=overrides,
        allow_unused_overrides=True,
    )

    assert report.unused_overrides == ("MISSING.BMP",)
    assert len(report.manifest.textures) == 1
