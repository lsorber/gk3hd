"""Local defaults connect build, packing and installation without device access."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock
from uuid import uuid4

import pytest

from gk3hd.vr.standalone import paths

if TYPE_CHECKING:
    from pathlib import Path


def _build(root: Path, *, release: bool = False) -> Path:
    candidate = root / "build" / uuid4().hex
    candidate.mkdir(parents=True)
    record = candidate / paths.BUILD_RECORD
    record.write_text("{}")
    paths.record_build(root, record, release=release)
    return candidate


def test_defaults_use_the_discovered_games_build_and_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        paths, "discover_game", Mock(return_value=SimpleNamespace(game_dir=tmp_path))
    )
    root = tmp_path / "gk3hd/vr/standalone"
    development = _build(root)
    apk, bundle = paths.install_inputs()
    assert apk == development / paths.APK_FILENAME
    assert bundle == root / "gk3hd-standalone.zip"


def test_a_new_development_build_does_not_replace_the_signed_selection(tmp_path: Path) -> None:
    release = _build(tmp_path, release=True)
    development = _build(tmp_path)
    (tmp_path / "build" / uuid4().hex).mkdir()

    assert paths.recorded_build(tmp_path, release=True) == release
    assert paths.recorded_build(tmp_path) == development


def test_changed_release_build_record_requires_rebuild(tmp_path: Path) -> None:
    release = _build(tmp_path, release=True)
    (release / paths.BUILD_RECORD).write_text('{"modified":true}')

    with pytest.raises(ValueError, match=r"changed.*build --release"):
        paths.recorded_build(tmp_path, release=True)


def test_selected_game_and_build_directory_can_be_combined(tmp_path: Path) -> None:
    apk, bundle = paths.install_inputs(game_dir=tmp_path, build_dir=tmp_path / "candidate")
    assert apk == tmp_path / "candidate/gk3hd-standalone.apk"
    assert bundle == tmp_path / "gk3hd/vr/standalone/gk3hd-standalone.zip"


@pytest.mark.parametrize("explicit_apk", [False, True])
def test_explicit_inputs_do_not_require_a_locally_installed_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, explicit_apk: bool
) -> None:
    discovery = Mock(side_effect=RuntimeError("No local game"))
    monkeypatch.setattr(paths, "discover_game", discovery)
    apk, bundle = paths.install_inputs(
        apk=tmp_path / "player.apk" if explicit_apk else None,
        build_dir=tmp_path / "candidate",
        bundle=tmp_path / "private.zip",
    )
    assert apk == (
        tmp_path / "player.apk" if explicit_apk else tmp_path / "candidate/gk3hd-standalone.apk"
    )
    assert bundle == tmp_path / "private.zip"
    discovery.assert_not_called()
