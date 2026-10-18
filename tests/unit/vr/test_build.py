"""Prototype builds cannot overwrite normal renderer records or publish failed output."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.renderer import build as native_build
from gk3hd.vr import build

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    monkeypatch.setattr(build, "discover_game", Mock(return_value=Mock(game_dir=root)))
    return root


@pytest.mark.parametrize("custom_output", [False, True])
def test_prototype_build_is_separate_and_reusable(
    game: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, custom_output: bool
) -> None:
    flat = game / "gk3hd/renderer/latest.json"
    flat.parent.mkdir(parents=True)
    flat.write_bytes(b"existing flat record")
    output = tmp_path / "prototype" if custom_output else None
    digest = "a" * 64
    target = output or build.workspace(game) / digest[:16]
    pin = json.loads((build.RECIPE / "upstream.json").read_text(encoding="utf-8"))
    candidate = Mock(
        path=target / f"dxvk-sarek-{pin['version']}-xr-prototype.dll", dll_sha256="b" * 64
    )
    compiler = Mock()
    monkeypatch.setattr(build, "compile_recipe", compiler)
    monkeypatch.setattr(build, "recipe_digest", lambda: digest)
    monkeypatch.setattr(build, "inspect_vr_dll", Mock(return_value=candidate))
    assert build.build(game_dir=game, output=output) is candidate
    compiler.assert_called_once_with(target.resolve(), jobs=12, variant="openxr")
    assert flat.read_bytes() == b"existing flat record"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert build.local_build(game_dir=game) is candidate


@pytest.mark.parametrize("failure", ["compile", "inspect", "recipe-changed"])
def test_failed_build_does_not_replace_last_successful_record(
    game: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    record = build.workspace(game) / "latest.json"
    record.parent.mkdir(parents=True)
    record.write_bytes(b"previous successful record")
    compiler = Mock(side_effect=RuntimeError("compiler failed") if failure == "compile" else None)
    inspector = Mock(side_effect=ValueError("invalid candidate") if failure == "inspect" else None)
    digest = Mock(side_effect=["a" * 64, "b" * 64] if failure == "recipe-changed" else None)
    digest.return_value = "a" * 64
    monkeypatch.setattr(build, "compile_recipe", compiler)
    monkeypatch.setattr(build, "inspect_vr_dll", inspector)
    monkeypatch.setattr(build, "recipe_digest", digest)
    with pytest.raises((RuntimeError, ValueError)):
        build.build(game_dir=game)
    assert record.read_bytes() == b"previous successful record"


@pytest.mark.parametrize("field", ["sha256", "recipe_sha256"])
def test_local_lookup_rejects_changed_candidate_or_recipe(
    game: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    record = build.workspace(game) / "latest.json"
    record.parent.mkdir(parents=True)
    data = {"dll": "candidate.dll", "sha256": "b" * 64, "recipe_sha256": "a" * 64}
    data[field] = "c" * 64
    record.write_text(json.dumps(data))
    monkeypatch.setattr(build, "inspect_vr_dll", Mock(return_value=Mock(dll_sha256="b" * 64)))
    monkeypatch.setattr(build, "recipe_digest", lambda: "a" * 64)
    with pytest.raises(ValueError, match="changed"):
        build.local_build(game_dir=game)


@pytest.mark.parametrize("data", [[], {}, {"dll": 1}])
def test_local_lookup_requires_a_valid_record(
    game: Path, monkeypatch: pytest.MonkeyPatch, data: object
) -> None:
    record = build.workspace(game) / "latest.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps(data))
    inspector = Mock()
    monkeypatch.setattr(build, "inspect_vr_dll", inspector)
    with pytest.raises(TypeError, match="invalid"):
        build.local_build(game_dir=game)
    inspector.assert_not_called()


def test_local_lookup_requires_a_successful_build(game: Path) -> None:
    with pytest.raises(ValueError, match="no verified"):
        build.local_build(game_dir=game)


@pytest.mark.parametrize("variant", ["flat", "openxr"])
def test_native_recipe_only_enables_xr_for_the_explicit_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    runner = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(native_build.sys, "platform", "win32")
    monkeypatch.setattr(native_build.shutil, "which", Mock(return_value="pwsh"))
    monkeypatch.setattr(native_build.subprocess, "run", runner)
    if variant == "openxr":
        native_build.compile_recipe(tmp_path, jobs=4, variant="openxr")
    else:
        native_build.compile_recipe(tmp_path, jobs=4)
    args = runner.call_args.args[0]
    assert ("-OpenXR" in args) == (variant == "openxr")
    assert args[args.index("-OutputRoot") + 1] == str(tmp_path)


def test_native_recipe_reports_failure_without_claiming_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(native_build.sys, "platform", "win32")
    monkeypatch.setattr(native_build.shutil, "which", Mock(return_value="pwsh"))
    monkeypatch.setattr(native_build.subprocess, "run", Mock(return_value=Mock(returncode=7)))
    with pytest.raises(RuntimeError, match="exit 7"):
        native_build.compile_recipe(tmp_path, jobs=4, variant="openxr")
