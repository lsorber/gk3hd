"""Public Typer command-surface and local texture workflow tests."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import TYPE_CHECKING
from unittest.mock import Mock

from PIL import Image
from typer.testing import CliRunner

import gk3hd.install as installation
from gk3hd import __version__
from gk3hd.cli import app
from gk3hd.install import CompositeReport
from gk3hd.renderer.service import RendererService
from gk3hd.textures.install.service import TextureInstallReport
from gk3hd.textures.model import TEXTURE_MANIFEST_SCHEMA_VERSION
from gk3hd.textures.pack.build import build_texture_pack
from gk3hd.textures.workspace import (
    ANALYSIS_FILENAME,
    SOURCE_DIRECTORY,
    UPSCALE_DIRECTORY,
    texture_pack_filename,
    texture_workspace_directory,
)
from tests.unit.textures.test_extraction import _write_barn_fixture

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_every_command_group_renders_help() -> None:
    """The installed console tree exposes all intended entry points."""
    runner = CliRunner()
    for arguments in (
        ["--help"],
        ["install", "--help"],
        ["uninstall", "--help"],
        ["status", "--help"],
        ["doctor", "--help"],
        ["patch", "--help"],
        ["textures", "--help"],
        ["patch", "list", "--help"],
        ["patch", "install", "--help"],
        ["patch", "verify", "--help"],
        ["patch", "uninstall", "--help"],
        ["textures", "extract", "--help"],
        ["textures", "analyze", "--help"],
        ["textures", "upscale", "--help"],
        ["textures", "pack", "--help"],
        ["textures", "install", "--help"],
        ["textures", "verify", "--help"],
        ["textures", "uninstall", "--help"],
    ):
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0, result.output


def test_analyze_summary_counts_reconstructed_ui_and_retained_constants(tmp_path: Path) -> None:
    source = tmp_path / "original"
    source.mkdir()
    Image.new("RGB", (16, 16), (0, 0, 0)).save(source / "BLACK.BMP")
    Image.new("RGB", (8, 8), (0, 0, 0)).save(source / "ROOMWLKBNDS.BMP")
    Image.new("RGB", (8, 1), (0, 0, 0)).save(source / "HELP_BOX_TOP.BMP")
    art = Image.new("RGB", (8, 8), (100, 120, 140))
    art.putpixel((4, 4), (90, 110, 130))
    art.save(source / "SCENE.BMP")
    result = CliRunner().invoke(app, ["textures", "analyze", str(source)])
    assert result.exit_code == 0, result.output
    assert "1 ai, 1 reconstruct, 2 retain" in result.output


def test_patch_list_shows_complete_ids_and_compact_benefits() -> None:
    """The narrow default console keeps every selectable identity readable."""
    result = CliRunner().invoke(app, ["patch", "list"])

    assert result.exit_code == 0, result.output
    expected = (
        "enable_modern_resolutions",
        "fix_keyboard_camera_speed",
        "maximize_graphics_quality",
        "prevent_save_warning_dialogs",
        "prevent_transition_flicker",
        "remove_disc_requirement",
        "scale_fixed_interfaces",
        "skip_all_movies",
        "speed_up_surface_checks",
        "stabilize_mouse_input",
    )
    for patch_id in expected:
        assert patch_id in result.output
    assert "Benefit" in result.output
    assert "CD/DVD drive" in result.output
    assert "recommended + skip_all_movies" in result.output
    assert "modern-display" not in result.output
    assert "Stability fixes" not in result.output
    assert "Enable modern resolutions" not in result.output


def test_texture_pack_install_verify_and_uninstall_commands(tmp_path: Path) -> None:
    """The public CLI can perform the complete local pack lifecycle."""
    pngs = tmp_path / "pngs"
    pngs.mkdir()
    Image.new("RGB", (2, 2), (1, 2, 3)).save(pngs / "ROOM.PNG")
    (tmp_path / ANALYSIS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "ROOM.BMP",
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
    release = tmp_path / "release"
    archive = release / texture_pack_filename(__version__)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "textures",
            "pack",
            str(pngs),
            str(archive),
        ],
    )
    assert result.exit_code == 0, result.output
    assert f"create/push v{__version__}" in result.output

    game = tmp_path / "game"
    game.mkdir()
    (game / "GK3.exe").write_bytes(b"fixture")
    (game / "GK3.ini").write_bytes(b"CUSTOM PATHS = mods\n")
    common = ["--game-dir", str(game)]
    install = runner.invoke(
        app,
        [
            "textures",
            "install",
            *common,
            "--pack",
            str(archive),
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
    )
    assert install.exit_code == 0, install.output
    assert "Finalizing installation" in install.output
    assert "2/2" in install.output
    assert "under gk3hd/textures/installed/" in install.output
    verify = runner.invoke(app, ["textures", "verify", *common])
    assert verify.exit_code == 0, verify.output
    uninstall = runner.invoke(app, ["textures", "uninstall", *common])
    assert uninstall.exit_code == 0, uninstall.output
    assert (game / "GK3.ini").read_bytes() == b"CUSTOM PATHS = mods\n"


def test_texture_install_discovers_a_local_workspace_pack_when_unpinned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local development fallback must not depend on the real release lock."""
    resources = tmp_path / "resources"
    (resources / "assets").mkdir(parents=True)
    (resources / "assets/texture-pack-lock.json").write_text('{"archives": [], "tag": null}')
    (resources / "assets/FACES.TXT").write_bytes(
        files("gk3hd").joinpath("assets/FACES.TXT").read_bytes()
    )
    monkeypatch.setattr("gk3hd.textures.install.service.files", lambda _package: resources)
    game = tmp_path / "game"
    game.mkdir()
    (game / "GK3.exe").write_bytes(b"fixture")
    (game / "GK3.ini").write_bytes(b"CUSTOM PATHS = mods\n")
    workspace = texture_workspace_directory(game)
    pngs = tmp_path / "pngs"
    pngs.mkdir()
    Image.new("RGB", (2, 2), (1, 2, 3)).save(pngs / "ROOM.PNG")
    build_texture_pack(
        pngs,
        workspace / texture_pack_filename("1.0"),
        version="1.0",
    )
    runner = CliRunner()
    common = ["--game-dir", str(game)]

    local = runner.invoke(app, ["textures", "install", *common, "--local"])
    assert local.exit_code == 0, local.output
    assert "Installed 1 texture" in local.output
    assert runner.invoke(app, ["textures", "uninstall", *common]).exit_code == 0

    automatic = runner.invoke(app, ["textures", "install", *common])
    assert automatic.exit_code == 0, automatic.output
    assert "Installed 1 texture" in automatic.output
    assert runner.invoke(app, ["textures", "uninstall", *common]).exit_code == 0

    named = runner.invoke(
        app,
        ["textures", "install", *common, "--pack", texture_pack_filename("1.0")],
    )
    assert named.exit_code == 0, named.output
    assert "Installed 1 texture" in named.output


def test_pinned_texture_install_uses_release_even_with_ambient_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "GK3.exe").touch()
    resources = tmp_path / "resources"
    (resources / "assets").mkdir(parents=True)
    (resources / "assets/texture-pack-lock.json").write_text(
        json.dumps(
            {
                "tag": "v1.0",
                "archives": [
                    {"filename": texture_pack_filename("1.0"), "sha256": "0" * 64, "size": 100}
                ],
            }
        )
    )
    monkeypatch.setattr("gk3hd.textures.install.service.files", lambda _package: resources)
    discover = Mock(side_effect=AssertionError("pinned installs must not inspect ambient packs"))
    monkeypatch.setattr("gk3hd.textures.install.service.discover_local_texture_pack", discover)
    install = Mock(return_value=TextureInstallReport("1.0", 1, tmp_path / "installed"))
    monkeypatch.setattr("gk3hd.textures.install.service.install_texture_pack", install)
    result = CliRunner().invoke(app, ["textures", "install", "--game-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    source = install.call_args.args[1]
    assert source.assets[0].archive_path is None
    assert source.assets[0].archive_url == (
        "https://github.com/lsorber/gk3hd/releases/download/v1.0/gk3hd-texture-pack-v1.0.zip"
    )
    discover.assert_not_called()


def test_root_install_renders_composed_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shortcut calls the Python coordinator and reports both components."""

    def install_fixture(
        *args: object,
        **kwargs: object,
    ) -> CompositeReport:
        del args, kwargs
        return CompositeReport(patches=8, textures=6658, changed=True)

    monkeypatch.setattr(installation, "install", install_fixture)

    result = CliRunner().invoke(app, ["install"])

    assert result.exit_code == 0, result.output
    assert "8 patches, 6658 textures" in result.output


def test_read_only_and_empty_uninstall_commands_accept_explicit_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Status, doctor, and uninstall use explicit targets without machine paths."""
    game = tmp_path / "game"
    game.mkdir()
    (game / "GK3.exe").write_bytes(b"unsupported fixture")
    # An unrelated real game may be running while this temporary, unsupported
    # fixture is tested. The renderer's live-process guard has its own tests.
    monkeypatch.setattr(
        "gk3hd.cli.RendererService", lambda: RendererService(process_probe=lambda: False)
    )
    runner = CliRunner()

    status = runner.invoke(app, ["status", "--game-dir", str(game)])
    doctor = runner.invoke(app, ["doctor", "--game-dir", str(game)])
    uninstall = runner.invoke(app, ["uninstall", "--game-dir", str(game)])

    assert status.exit_code == 0, status.output
    assert "not installed" in status.output
    assert doctor.exit_code == 0, doctor.output
    assert "patched or unsupported" in doctor.output
    assert uninstall.exit_code == 0, uninstall.output


def test_patch_error_is_concise_without_traceback(tmp_path: Path) -> None:
    """Unsupported binaries produce one actionable Rich error boundary."""
    game = tmp_path / "game"
    game.mkdir()
    (game / "GK3.exe").write_bytes(b"unsupported fixture")

    result = CliRunner().invoke(
        app,
        ["patch", "install", "--game-dir", str(game), "--dry-run"],
    )

    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_analysis_and_upscale_use_colocated_workspace_defaults(tmp_path: Path) -> None:
    """Analysis is visible beside texture stages and upscale recreates it when absent."""
    game = tmp_path / "game"
    game.mkdir()
    (game / "GK3.exe").write_bytes(b"fixture")
    _write_barn_fixture(game / "Data", core_assets=[("C_ICON.BMP", b"fixture", 0)])
    texture_workspace = texture_workspace_directory(game)
    source = texture_workspace / SOURCE_DIRECTORY
    source.mkdir(parents=True)
    Image.new("RGB", (2, 3), (10, 20, 30)).save(source / "C_ICON.BMP")
    analysis = texture_workspace / ANALYSIS_FILENAME
    runner = CliRunner()

    analyzed = runner.invoke(app, ["textures", "analyze", "--game-dir", str(game)])

    assert analyzed.exit_code == 0, analyzed.output
    assert analysis.is_file()
    assert str(analysis) in analyzed.output.replace("\n", "")
    assert analysis.parent == source.parent
    normalized_output = " ".join(analyzed.output.split())
    assert "Analyzed 1 texture: 1 retain" in normalized_output

    analysis.unlink()
    upscaled = runner.invoke(app, ["textures", "upscale", "--game-dir", str(game)])

    assert upscaled.exit_code == 0, upscaled.output
    assert analysis.is_file()
    assert "Created analysis:" in upscaled.output
    assert not (texture_workspace / UPSCALE_DIRECTORY / "C_ICON.PNG").exists()


def test_upscale_import_error_preserves_extra_and_missing_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional-backend failures name their cause without Rich consuming brackets."""
    source = tmp_path / "textures"
    source.mkdir()

    def fail_upscale(_source: Path, _output: Path, **_options: object) -> None:
        message = "No module named 'einops'"
        raise ModuleNotFoundError(message, name="einops")

    monkeypatch.setattr("gk3hd.cli.textures.texture_upscale.upscale", fail_upscale)

    result = CliRunner().invoke(app, ["textures", "upscale", str(source)])

    assert result.exit_code == 1
    assert "einops" in result.output
    assert "gk3hd[upscale]" in result.output


def test_pack_uses_workspace_release_and_version_defaults(tmp_path: Path) -> None:
    """The ordinary pack command needs no paths, version, or future release URL."""
    game = tmp_path / "game"
    game.mkdir()
    (game / "GK3.exe").write_bytes(b"fixture")
    texture_workspace = texture_workspace_directory(game)
    upscaled = texture_workspace / UPSCALE_DIRECTORY
    upscaled.mkdir(parents=True)
    Image.new("RGB", (2, 2), (1, 2, 3)).save(upscaled / "ROOM.PNG")
    (texture_workspace / "texture-analysis.json").write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 1,
                "textures": [
                    {
                        "name": "ROOM.BMP",
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

    result = CliRunner().invoke(
        app,
        ["textures", "pack", "--game-dir", str(game)],
    )

    archive = texture_workspace / texture_pack_filename(__version__)
    lock = texture_workspace / "texture-pack-lock.json"
    assert result.exit_code == 0, result.output
    assert archive.is_file()
    assert json.loads(lock.read_text(encoding="utf-8"))["tag"] == f"v{__version__}"
    assert "https://" not in lock.read_text(encoding="utf-8")
