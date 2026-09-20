"""Rebuild representative deterministic families without private artifacts or caches."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.pack.build as texture_pack
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd.textures.install.service import (
    install_texture_pack,
    uninstall_texture_pack,
    verify_texture_pack,
)
from gk3hd.textures.pack.source import TexturePackSource
from gk3hd.textures.routing import PipelineKind
from gk3hd.textures.upscale import service as texture_service
from gk3hd.textures.upscale.cursor_art import CURSOR_ART_SIZES, CURSOR_OPACITY_SIZES
from gk3hd.textures.upscale.fonts.button import FONT_BUTTON_SIZES
from gk3hd.textures.upscale.ui_art import (
    FINGERPRINT_TOOL_SIZES,
    LEGACY_DOCUMENT_SIZES,
    LEGACY_TOOLBAR_ART_SIZES,
    QUIT_BUTTON_SIZES,
)
from gk3hd.textures.workspace import analysis_file

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.slow


# One small member per transform; catalog membership is tested separately.
def _representative(sizes: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    name = min(sizes, key=lambda name: sizes[name][0] * sizes[name][1])
    return {name: sizes[name]}


_BUTTONS = _representative(FONT_BUTTON_SIZES)
_CURSORS = {"C_WAIT.BMP": CURSOR_ART_SIZES["C_WAIT.BMP"]}
_OPACITY = _representative(CURSOR_OPACITY_SIZES)
_TOOLS = _representative(FINGERPRINT_TOOL_SIZES)
_TOOLBAR = _representative(LEGACY_TOOLBAR_ART_SIZES)
_DOCUMENTS = _representative(LEGACY_DOCUMENT_SIZES)
_QUIT = _representative(QUIT_BUTTON_SIZES)


def _write_originals(directory: Path, *, reverse: bool) -> dict[str, bytes]:
    sizes = {
        **_BUTTONS,
        **_CURSORS,
        **_OPACITY,
        **_TOOLS,
        **_TOOLBAR,
        **_DOCUMENTS,
        **_QUIT,
        "SNOTE.BMP": (32, 32),
        "SNOTE_HOV.BMP": (32, 32),
        "SNOTED.BMP": (32, 32),
        "SNOTE6_ALPHA.BMP": (601, 399),
        "CAIN.BMP": (148, 160),
        "CAIN_ALPHA.BMP": (148, 160),
        **{
            f"{family}_{state}.BMP": (32, 32)
            for family in ("I_ROOMKEY", "I_GRARM")
            for state in ("STD", "HOV", "DWN")
        },
        "C_POINT.BMP": (19, 19),
        "ROOM_WLKBNDS.BMP": (16, 16),
    }
    directory.mkdir(parents=True)
    for name in sorted(sizes, reverse=reverse):
        width, height = sizes[name]
        background = (255, 0, 255) if name.startswith("C_") else (40, 16, 8)
        image = Image.new("RGB", (width, height), background)
        image.paste((160, 96, 40), (5, 5, width - 5, height - 5))
        image.paste((96, 48, 24), (7, 6, width - 6, height - 6))
        if name == "SNOTE6_ALPHA.BMP":
            # The companion has its own ordinary color route, but the three
            # thumbnails must reconstruct from this original, not AI output.
            image.paste((0, 0, 0), (0, 0, width, height))
            image.paste((160, 96, 40), (150, 100, 450, 300))
        if name in CURSOR_OPACITY_SIZES or name == "CAIN_ALPHA.BMP":
            image = image.convert("L")
        image.save(directory / name)
    return {name: (directory / name).read_bytes() for name in sizes}


def _rebuild(directory: Path, *, implicit_analysis: bool) -> dict[str, bytes]:
    source, output = directory / "original", directory / "upscaled"
    enlarged_count = (
        len(_CURSORS)
        + len(_OPACITY)
        + len(_TOOLS)
        + len(_TOOLBAR)
        + len(_DOCUMENTS)
        + len(_QUIT)
        + 6
    )
    if not implicit_analysis:
        report = texture_analyze.analyze(source)
        assert report.routes == {
            PipelineKind.UI_SOURCE_4X: enlarged_count,
            PipelineKind.EXACT_RASTER_UNCHANGED: 1,
            PipelineKind.DATA_UNCHANGED: 1,
            PipelineKind.THUMBNAIL_SOURCE_4X: 3,
            PipelineKind.COLOR_AI: 2,
            PipelineKind.ALPHA_SMOOTH: 1,
            PipelineKind.FONT_BUTTON_SOURCE_4X: len(_BUTTONS),
        }
    enlarged_count += 6 + len(_BUTTONS)
    report = texture_upscale.upscale(source, output)
    assert (report.created, report.excluded, report.skipped) == (enlarged_count, 2, 0)
    assert texture_upscale.upscale(source, output).skipped == enlarged_count
    pack = texture_pack.pack(output, directory / "gk3hd-texture-pack-v1.0.zip", version="1.0")
    game = directory / "game"
    game.mkdir()
    ini = game / "GK3.ini"
    original_ini = b"[Resource]\r\nCustom Paths=existing-mod\r\n"
    ini.write_bytes(original_ini)
    assert (
        install_texture_pack(game, TexturePackSource.local(pack.archives[0])).textures
        == enlarged_count
    )
    assert verify_texture_pack(game).textures == enlarged_count
    installed = game / "gk3hd/textures/installed"
    artifacts = {
        "analysis": analysis_file(source).read_bytes(),
        "pack": pack.archives[0].read_bytes(),
        **{f"png/{path.name}": path.read_bytes() for path in output.glob("*.PNG")},
        **{f"bmp/{path.name}": path.read_bytes() for path in installed.glob("*.BMP")},
    }
    assert len(artifacts) == enlarged_count * 2 + 2
    for names in (_CURSORS, _TOOLBAR, _DOCUMENTS, _QUIT, _BUTTONS):
        assert all(artifacts[f"bmp/{name}"].startswith(b"61nM") for name in names)
    assert all(
        artifacts[f"bmp/{name}"].startswith(b"61nM")
        for name in ("SNOTE.BMP", "SNOTE_HOV.BMP", "SNOTED.BMP")
    )
    assert all(artifacts[f"bmp/{name}"].startswith(b"BM") for name in _OPACITY)
    assert artifacts["bmp/CAIN.BMP"].startswith(b"61nM")
    assert artifacts["bmp/CAIN_ALPHA.BMP"].startswith(b"BM")
    uninstall_texture_pack(game)
    assert ini.read_bytes() == original_ini
    return artifacts


@pytest.mark.integration
def test_clean_rebuild_is_independent_of_location_order_and_cached_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inference_sizes: list[tuple[int, int]] = []

    class CompanionBackend:
        scale = 4

        @staticmethod
        def upscale(image: Image.Image) -> Image.Image:
            inference_sizes.append(image.size)
            return image.resize((image.width * 4, image.height * 4))

    monkeypatch.setattr(
        texture_service, "_create_seedvr2_upscaler", lambda *_args: CompanionBackend()
    )
    first, second = tmp_path / "first", tmp_path / "unrelated path" / "second"
    originals = _write_originals(first / "original", reverse=False)
    assert _write_originals(second / "original", reverse=True) == originals
    monkeypatch.chdir(first)
    explicit = _rebuild(first, implicit_analysis=False)
    monkeypatch.chdir(second)
    implicit = _rebuild(second, implicit_analysis=True)
    assert explicit == implicit
    # The larger note companion and CAIN color invoke inference in each folder.
    # CAIN opacity, menu reconstruction and resumed outputs never invoke it.
    assert len(inference_sizes) == 4
    assert inference_sizes[:2] == inference_sizes[2:]
    for directory in (first, second):
        for name, payload in originals.items():
            assert (directory / "original" / name).read_bytes() == payload
