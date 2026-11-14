"""Reject incompatible native consumers and guest producers before touching a headset."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from gk3hd.vr.standalone import install as installer
from gk3hd.vr.standalone.apk import (
    COMPONENT_ASSET,
    COMPONENT_FILES,
    COMPONENT_UPDATE_ASSET,
    player_components,
    require_player_components,
    supports_component_update,
)
from gk3hd.vr.standalone.bundle import REQUIRED_FILES, build_bundle
from tests.unit.vr.standalone.test_apk import binary_manifest

if TYPE_CHECKING:
    from pathlib import Path


def _apk(path: Path, contents: bytes) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", binary_manifest())
        archive.writestr(COMPONENT_ASSET, contents)
    return path


def _pair(tmp_path: Path, *, mismatch: str | None = None) -> tuple[Path, Path]:
    files = {}
    for index, name in enumerate([*sorted(REQUIRED_FILES), "Data/core.brn"]):
        source = tmp_path / f"input-{index}"
        source.write_bytes(name.encode())
        files[name] = source
    identities = {
        name: hashlib.sha256(files[name].read_bytes()).hexdigest() for name in COMPONENT_FILES
    }
    if mismatch:
        identities[mismatch] = "a" * 64
    contents = "".join(f"{digest}  {name}\n" for name, digest in sorted(identities.items()))
    apk = _apk(tmp_path / "player.apk", contents.encode())
    return apk, build_bundle(files, tmp_path / "game.zip").path


def test_matching_player_and_bundle_are_accepted(tmp_path: Path) -> None:
    apk, bundle = _pair(tmp_path)
    require_player_components(apk, bundle)
    assert set(player_components(apk)) == COMPONENT_FILES


@pytest.mark.parametrize(
    ("marker", "supported", "verification", "additions"),
    [
        (None, False, False, False),
        (b"1", False, False, False),
        (b"2", True, False, False),
        (b"3", True, True, False),
        (b"4", True, True, True),
    ],
)
def test_component_archive_support_requires_the_matching_apk_marker(
    tmp_path: Path, marker: bytes | None, *, supported: bool, verification: bool, additions: bool
) -> None:
    apk = tmp_path / "player.apk"
    with ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", binary_manifest())
        if marker is not None:
            archive.writestr(COMPONENT_UPDATE_ASSET, marker)
    assert supports_component_update(apk) is supported
    assert supports_component_update(apk, verification_only=True) is verification
    assert supports_component_update(apk, additions=True) is additions


@pytest.mark.parametrize("name", sorted(COMPONENT_FILES))
def test_mismatched_components_are_rejected_before_device_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    apk, bundle = _pair(tmp_path, mismatch=name)
    probe = Mock(side_effect=AssertionError("No headset access before component matching"))
    monkeypatch.setattr(installer, "probe", probe)
    with pytest.raises(ValueError, match=f"do not match: {name}"):
        installer.install(apk=apk, bundle=bundle, adb=tmp_path / "adb")
    probe.assert_not_called()


@pytest.mark.parametrize(
    "contents",
    [
        b"",
        b"x" * 513,
        b"\xff",
        b"a" * 64 + b"  openxr_wxr32.dll\n",
        (b"a" * 64 + b"  openxr_wxr32.dll\n") * 2,
        b"invalid  openxr_wxr32.dll\n",
        b"a" * 64 + b"  ../openxr_wxr32.dll\n",
    ],
)
def test_missing_or_malformed_pairing_is_not_guessed(tmp_path: Path, contents: bytes) -> None:
    apk = _apk(tmp_path / "player.apk", contents)
    with pytest.raises(ValueError, match="component pairing"):
        player_components(apk)


def test_missing_asset_requires_a_rebuild(tmp_path: Path) -> None:
    apk = tmp_path / "old.apk"
    with ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", binary_manifest())
    with pytest.raises(ValueError, match="rebuild"):
        player_components(apk)
