from __future__ import annotations

import json
import struct
from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.analyze.manifest import analyze_directory
from gk3hd.textures.analyze.usage import (
    TextureUsage,
    action_button_textures,
    analyze_usage,
    bsp_tiled_textures,
    cursor_opacity_textures,
    discover_data_directory,
    font_textures,
    mod_tiled_textures,
    scene_data_textures,
    toolbar_button_textures,
)
from gk3hd.textures.model import TEXTURE_MANIFEST_SCHEMA_VERSION, TextureKind
from tests.unit.textures.test_extraction import _write_barn_fixture

if TYPE_CHECKING:
    from pathlib import Path


def _bsp(u: float, *, index: int = 0) -> bytes:
    return (
        struct.pack("<4s12I", b"NECS", 256, 0, 0, 0, 0, 1, 1, 0, 1, 0, 0, 1)
        + bytes(4)
        + b"stone".ljust(32, b"\0")
        + bytes(24)
        + struct.pack("<4H", 0, 0, 1, 0)
        + struct.pack("<ffH", u, 0.5, index)
    )


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        (b"Alpha Channel=mask", ("C_TEST.BMP", "MASK.BMP")),
        (
            b'Sprite Name="other.bmp"\r\nAlpha Channel=mask.bmp // active',
            ("OTHER.BMP", "MASK.BMP"),
        ),
        (b";Alpha Channel=mask\r\nFrame Count=6", None),
        (b"// Alpha Channel=mask\nAlpha Channel=", None),
        (b"Alpha Channel=missing", None),
    ],
)
def test_cursor_opacity_requires_an_active_resolved_binding(
    definition: bytes, expected: tuple[str, str] | None
) -> None:
    assert (
        cursor_opacity_textures(definition, "C_TEST.CUR", {"C_TEST.BMP", "OTHER.BMP", "MASK.BMP"})
        == expected
    )


def _mod(u: float, *, minor: int = 8) -> bytes:
    return (
        b"LDOM"
        + bytes((minor, 1, 0, 0))
        + struct.pack("<I", 1)
        + bytes(12)
        + (bytes(24) if minor == 9 else b"")
        + b"HSEM"
        + bytes(48)
        + struct.pack("<I", 1)
        + bytes(24)
        + b"PRGM"
        + b"stone".ljust(32, b"\0")
        + bytes(8)
        + struct.pack("<III", 1, 0, 1)
        + bytes(4 + 24)
        + struct.pack("<ff", u, 0.5)
        + b"KDOL"
        + struct.pack("<III", 1, 1, 1)
        + bytes(8 + 4 + 2)
    )


@pytest.mark.parametrize("u", [-2.0, 1.5])
def test_geometry_identifies_repeating_uvs(u: float) -> None:
    assert bsp_tiled_textures(_bsp(u)) == {"STONE.BMP"}
    assert mod_tiled_textures(_mod(u)) == {"STONE.BMP"}
    assert mod_tiled_textures(_mod(u, minor=9)) == {"STONE.BMP"}


@pytest.mark.parametrize("u", [0.0, 1.0, -0.00001, 1.00001, float("nan"), float("inf")])
def test_geometry_does_not_invent_repetition(u: float) -> None:
    assert not bsp_tiled_textures(_bsp(u))
    assert not mod_tiled_textures(_mod(u))


def test_bsp_only_considers_referenced_uvs() -> None:
    assert not bsp_tiled_textures(_bsp(3.0, index=1))


def test_truncated_geometry_is_rejected() -> None:
    with pytest.raises(ValueError, match="truncated"):
        bsp_tiled_textures(_bsp(2.0)[:-1])
    with pytest.raises(ValueError, match="truncated"):
        mod_tiled_textures(_mod(2.0)[:-1])


def test_fonts_resolve_color_and_opacity_not_comments() -> None:
    available = {"ATLAS.BMP", "MASK.BMP", "UNUSED.BMP", "FONT.BMP"}
    definition = (
        b"; Bitmap Name = unused\nBitmap Name = atlas.bmp // unused\nALPHA CHANNEL = Mask\n"
    )
    assert font_textures(definition, "FONT.FON", available) == {"ATLAS.BMP", "MASK.BMP"}
    assert font_textures(b"Height=12", "FONT.FON", available) == {"FONT.BMP"}
    assert not font_textures(b"Bitmap Name=missing", "FONT.FON", available)


def test_action_buttons_resolve_only_real_sprite_state_fields() -> None:
    available = {"EGG_STD.BMP", "EGG_DWN.BMP", "EGG_HOV.BMP", "IGNORED.BMP"}
    definition = (
        b"; EGG,up=ignored\n// TEST,down=ignored\n"
        b'EGG, Up=egg_std, DOWN="EGG_DWN.BMP", hover=egg_hov, type=Normal // up=ignored\n'
        b"UNUSED, cursor=ignored, sound=ignored, up=missing\n"
    )
    assert action_button_textures(definition, available) == available - {"IGNORED.BMP"}


def test_action_button_usage_requires_32px_color_art_and_respects_fonts(tmp_path: Path) -> None:
    for name, size in (
        ("MENU", (32, 32)),
        ("PANEL", (96, 32)),
        ("OTHER", (32, 32)),
        ("ATLAS", (32, 32)),
        ("BOUNDARY", (32, 32)),
    ):
        Image.new("RGB", size, (40, 50, 60)).save(tmp_path / f"{name}.BMP")
    usage = TextureUsage(
        action_buttons=frozenset({"MENU.BMP", "PANEL.BMP", "ATLAS.BMP", "BOUNDARY.BMP"}),
        fonts=frozenset({"ATLAS.BMP"}),
    )
    features = {f.name: f for f in analyze_directory(tmp_path, usage=usage).manifest.textures}
    assert features["MENU.BMP"].exact_raster
    assert all(
        not features[name].exact_raster
        for name in ("PANEL.BMP", "OTHER.BMP", "ATLAS.BMP", "BOUNDARY.BMP")
    )
    assert features["ATLAS.BMP"].font_atlas


def test_toolbar_buttons_resolve_states_not_backgrounds_or_comments() -> None:
    available = {"UP.BMP", "DOWN.BMP", "DISABLED.BMP", "HOVER.BMP", "IGNORED.BMP"}
    definition = (
        b'; camSpriteUp=ignored\n// camSpriteDown=ignored\ncamSpriteUp="up.bmp"\n'
        b"cameraSpriteDown=down // camSpriteDis=ignored\nCameraSpriteDis=disabled\n"
        b"exitSpriteHover=hover\ncamSpriteUp=missing\nbackground=ignored\n"
        b"currInvSprite=ignored\ntimeSprite=ignored\ncameraPos=ignored\n"
    )
    assert toolbar_button_textures(definition, available) == available - {"IGNORED.BMP"}


def test_toolbar_usage_preserves_small_icons_without_a_size_only_heuristic(tmp_path: Path) -> None:
    names = {"ICON", "PANEL", "PREVIEW", "OTHER", "ATLAS", "BOUNDARY", "ICON_ALPHA"}
    for name in names:
        size = {"PANEL": (100, 24), "PREVIEW": (33, 32)}.get(name, (22, 24))
        image = Image.new("P" if name == "ICON_ALPHA" else "RGB", size)
        if name == "ICON_ALPHA":
            image.putpalette([channel for channel in range(256) for _ in range(3)])
        if name == "ICON":
            image.putpixel((0, 0), (255, 0, 255))
        image.save(tmp_path / f"{name}.BMP")
    usage = TextureUsage(
        toolbar_buttons=frozenset(f"{name}.BMP" for name in names - {"OTHER"}),
        fonts=frozenset({"ATLAS.BMP"}),
    )
    features = {f.name: f for f in analyze_directory(tmp_path, usage=usage).manifest.textures}
    assert features["ICON.BMP"].exact_raster
    assert features["ICON.BMP"].alphatest
    assert all(not features[f"{name}.BMP"].exact_raster for name in names - {"ICON"})
    assert features["ATLAS.BMP"].font_atlas


def test_archive_usage_and_default_discovery(tmp_path: Path) -> None:
    data = tmp_path / "dAtA"
    _write_barn_fixture(
        data,
        core_assets=[
            ("STONE.BMP", b"pixels not needed", 0),
            ("ATLAS.BMP", b"pixels not needed", 0),
            ("F_UNREFERENCED.BMP", b"pixels not needed", 0),
            ("ROOM.BSP", _bsp(2.0), 1),
            ("FONT.FON", b"Bitmap Name=atlas", 1),
            ("EGG_STD.BMP", b"pixels not needed", 0),
            ("VERBS.TXT", b"EGG,up=egg_std,down=missing,hover=missing", 1),
            ("CAMERA.BMP", b"pixels not needed", 0),
            ("DISABLED.BMP", b"pixels not needed", 0),
            ("TBLAYOUT.TXT", b"camSpriteUp=camera", 1),
            ("OBLAYOUT.TXT", b"cameraSpriteDis=disabled", 1),
            ("C_WAIT.BMP", b"pixels not needed", 0),
            ("C_WAIT_ALPHA.BMP", b"pixels not needed", 0),
            ("C_WAIT.CUR", b"Alpha Channel=c_wait_alpha", 1),
        ],
        child_assets=[("OBJECT.MOD", _mod(2.0), 0)],
    )
    source = tmp_path / "gk3hd" / "textures" / "original"
    source.mkdir(parents=True)
    for name in ("STONE.BMP", "ATLAS.BMP", "F_UNREFERENCED.BMP"):
        Image.new("RGB", (2, 2)).save(source / name)
    assert discover_data_directory(source) == data
    assert discover_data_directory(tmp_path / "missing") is None
    progress: list[tuple[int, int]] = []
    usage = analyze_usage(data, progress=lambda done, total: progress.append((done, total)))
    assert usage == TextureUsage(
        tiled=frozenset({"STONE.BMP"}),
        fonts=frozenset({"ATLAS.BMP", "F_UNREFERENCED.BMP"}),
        action_buttons=frozenset({"EGG_STD.BMP"}),
        toolbar_buttons=frozenset({"CAMERA.BMP", "DISABLED.BMP"}),
        cursor_opacity_pairs=frozenset({("C_WAIT.BMP", "C_WAIT_ALPHA.BMP")}),
    )
    assert progress == [(index, 7) for index in range(1, 8)]
    report = texture_analyze.analyze(source)
    textures = {texture.name: texture for texture in report.manifest.textures}
    assert textures["STONE.BMP"].tiled
    assert textures["ATLAS.BMP"].font_atlas
    assert textures["F_UNREFERENCED.BMP"].font_atlas


def test_explicit_policy_overrides_archive_facts(tmp_path: Path) -> None:
    Image.new("RGB", (2, 2)).save(tmp_path / "STONE.BMP")
    policy = tmp_path / "policy.json"
    policy.write_text(
        '{"schema_version":9,"feature_overrides":[{"textures":["STONE.BMP"],'
        '"set":{"tiled":false},"reason":"Test correction."}]}',
        encoding="utf-8",
    )
    usage = TextureUsage(tiled=frozenset({"STONE.BMP"}))
    report = analyze_directory(tmp_path, overrides=policy, usage=usage)
    assert not report.manifest.textures[0].tiled


def test_archive_error_names_the_broken_resource(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    _write_barn_fixture(data, core_assets=[("BROKEN.MOD", b"LDOM", 0)])
    with pytest.raises(ValueError, match=r"BROKEN\.MOD: truncated"):
        analyze_usage(data)


def test_scene_data_uses_sections_bindings_and_existing_companions() -> None:
    available = {"REGIONS.BMP", "NIGHT.BMP", "SKY.BMP", "SKY_MASK.BMP", "OTHER_MASK.BMP"}
    sif = (
        b'[GENERAL]\nboundary="regions.bmp",size={100,200}\n'
        b'// boundary=unused\n[GENERAL={IsCurrentTime("202p")}]\nboundary=night\n'
        b"[MODELS]\nboundary=sky\n"
    )
    scn = (
        b'[Skybox]\nLeft="sky.bmp"\nRight=other\n;Up=night\nAzimuth=night\n'
        b"// Front=night\nDown=missing\n[Models]\nLeft=night\n"
    )
    assert scene_data_textures(sif, ".sif", available) == {"REGIONS.BMP", "NIGHT.BMP"}
    assert scene_data_textures(scn, ".SCN", available) == {"SKY_MASK.BMP"}
    assert not scene_data_textures(sif, ".SCN", available)
    assert not scene_data_textures(b"[GENERAL]\nboundary=../regions", ".SIF", available)


def test_data_usage_takes_precedence_over_artwork_and_font_heuristics(tmp_path: Path) -> None:
    name = "F_REGIONS.BMP"
    Image.new("RGB", (32, 32), (255, 0, 255)).save(tmp_path / name)
    usage = TextureUsage(data=frozenset({name}), fonts=frozenset({name}))
    feature = analyze_directory(tmp_path, usage=usage).manifest.textures[0]
    assert feature.kind is TextureKind.DATA
    assert not feature.font_atlas
    assert not feature.alphatest
    assert not feature.exact_raster


def test_archive_usage_discovers_arbitrarily_named_data_maps(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    _write_barn_fixture(
        data,
        core_assets=[
            ("REGIONS.BMP", b"pixels not needed", 0),
            ("SKY.BMP", b"pixels not needed", 0),
            ("SKY_MASK.BMP", b"pixels not needed", 0),
            ("ROOM.SIF", b"[GENERAL]\nboundary=regions", 1),
            ("ROOM.SCN", b"[Skybox]\nFront=sky", 1),
        ],
    )
    assert analyze_usage(data).data == {"REGIONS.BMP", "SKY_MASK.BMP"}
    source = tmp_path / "gk3hd" / "textures" / "original"
    source.mkdir(parents=True)
    for name in ("REGIONS.BMP", "SKY_MASK.BMP"):
        image = Image.new("RGB", (8, 8), (255, 0, 255))
        image.putpixel((4, 4), (255, 0, 0))
        image.save(source / name)
    originals = {path.name: path.read_bytes() for path in source.iterdir()}
    analysis = source.parent / "texture-analysis.json"
    analysis.write_text(
        json.dumps(
            {
                "schema_version": 124,
                "textures": [{"name": name, "kind": "color"} for name in originals],
            }
        ),
        encoding="utf-8",
    )
    # Automatic analysis must retain even RGB/keyed data with unfamiliar names.
    output = tmp_path / "upscaled"
    report = texture_upscale.upscale(source, output)
    assert (report.textures, report.created, report.excluded) == (2, 0, 2)
    assert json.loads(analysis.read_text(encoding="utf-8"))["schema_version"] == (
        TEXTURE_MANIFEST_SCHEMA_VERSION
    )
    assert not list(output.glob("*.PNG"))
    assert {path.name: path.read_bytes() for path in source.iterdir()} == originals
