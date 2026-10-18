"""An opt-in player never replaces flat files or adopts unmanaged content."""

from __future__ import annotations

import hashlib
import struct
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.patch.builds import SUPPORTED_BUILDS
from gk3hd.patch.manifest import ManifestIdentity, PatchManifest
from gk3hd.patch.model import ProfileId
from gk3hd.system import locking
from gk3hd.system.discovery import GameTarget
from gk3hd.vr import service, transaction
from gk3hd.vr.service import VRService
from gk3hd.vr.state import OWNED_FILES, VRState
from gk3hd.vr.transaction import FILES, PLAYER, STATE
from tests.unit.renderer.test_artifact import renderer_dll, vr_dll

__all__ = ["renderer_dll", "vr_dll"]

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    for name in ("GK3.exe", "ddraw.dll", "dxvk.conf", "GK3.ini", "save0001.gk3"):
        (root / name).write_bytes(b"original" if name == "GK3.exe" else f"flat {name}".encode())
    target = GameTarget(root, root / "GK3.exe", root, root / "GK3.ini")
    monkeypatch.setattr(service, "discover_game", Mock(return_value=target))
    cache = tmp_path / "cache"
    monkeypatch.setattr(transaction, "cache_directory", lambda: cache)
    monkeypatch.setattr(locking, "cache_directory", lambda: cache)
    profile = next(iter(SUPPORTED_BUILDS.values()))

    def recognized(digest: str) -> object:
        if digest != hashlib.sha256(b"original").hexdigest():
            msg = "unsupported source"
            raise ValueError(msg)
        return profile

    monkeypatch.setattr(service, "profile_for_sha256", recognized)
    monkeypatch.setattr(service, "_flat", Mock(return_value=(b"flat dependencies", profile)))

    def compile_player(_flat: object, *, units_per_meter: float, **_options: object) -> Mock:
        data = b"VR player" + struct.pack("<f", units_per_meter)
        return Mock(image=Mock(to_bytes=Mock(return_value=data)))

    def verify_player(
        _flat: object, image: Mock, *, units_per_meter: float, **options: object
    ) -> Mock:
        expected = compile_player(_flat, units_per_meter=units_per_meter, **options)
        if image.to_bytes() != expected.image.to_bytes():
            msg = "player differs from independent rebuild"
            raise ValueError(msg)
        return expected

    monkeypatch.setattr(service, "compile_vr", compile_player)
    monkeypatch.setattr(service, "verify_vr", verify_player)
    monkeypatch.setattr(service.PEFile, "from_path", lambda path: Mock(to_bytes=path.read_bytes))
    return root


def flat_files(game: Path) -> dict[str, bytes]:
    return {
        name: (game / name).read_bytes()
        for name in ("GK3.exe", "ddraw.dll", "dxvk.conf", "GK3.ini", "save0001.gk3")
    }


def test_default_scale_preserves_documented_model_inches(game: Path, vr_dll: Path) -> None:
    owner = VRService(process_probe=lambda: False)
    owner.install(game_dir=game, dll=vr_dll)
    state = VRState.read(game / STATE)
    # Original FACES.TXT gives eye separation as 2.5 model inches. The scale
    # must preserve that physical length, independently of the wearer's IPD.
    assert 2.5 / state.units_per_meter == pytest.approx(0.0635)
    serialized_scale = struct.unpack("<f", (game / "GK3-VR.exe").read_bytes()[-4:])[0]
    assert 2.5 / serialized_scale == pytest.approx(0.0635)
    owner.verify(game_dir=game)
    owner.uninstall(game_dir=game)


def test_preparation_install_verification_update_and_removal_preserve_flat_play(
    game: Path, vr_dll: Path
) -> None:
    baseline = flat_files(game)
    owner = VRService(process_probe=lambda: False)
    prepared = owner.prepare(game_dir=game, dll=vr_dll)
    assert not any((game / name).exists() for name in FILES)
    owner.apply(prepared)
    owner.verify(game_dir=game)
    assert (game / f"{PLAYER}/original.exe").read_bytes() == b"original"
    assert (game / f"{PLAYER}/ddraw.dll").read_bytes() == vr_dll.read_bytes()
    assert flat_files(game) == baseline
    owner.install(game_dir=game, dll=vr_dll, units_per_meter=80)
    assert VRState.read(game / STATE).units_per_meter == 80
    owner.verify(game_dir=game)
    assert owner.uninstall(game_dir=game) == game
    assert not any((game / name).exists() for name in FILES)
    assert flat_files(game) == baseline
    assert owner.uninstall(game_dir=game) == game


@pytest.mark.parametrize("name", FILES)
def test_unmanaged_collisions_are_never_adopted(game: Path, vr_dll: Path, name: str) -> None:
    path = game / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"unmanaged")
    with pytest.raises(ValueError, match=r"unmanaged|Expecting value"):
        VRService(process_probe=lambda: False).prepare(game_dir=game, dll=vr_dll)
    assert path.read_bytes() == b"unmanaged"


@pytest.mark.parametrize("name", OWNED_FILES)
def test_user_changes_are_preserved_by_install_and_uninstall(
    game: Path, vr_dll: Path, name: str
) -> None:
    owner = VRService(process_probe=lambda: False)
    owner.install(game_dir=game, dll=vr_dll)
    path = game / name
    path.write_bytes(b"external edit")
    before = {name: (game / name).read_bytes() for name in FILES}
    with pytest.raises(ValueError, match="VR-owned files changed"):
        owner.install(game_dir=game, dll=vr_dll)
    with pytest.raises(ValueError, match="VR-owned files changed"):
        owner.uninstall(game_dir=game)
    assert before == {name: (game / name).read_bytes() for name in FILES}


@pytest.mark.parametrize("changed", ["flat", "renderer", "state"])
def test_changes_after_preparation_are_rejected_before_publication(
    game: Path, vr_dll: Path, changed: str
) -> None:
    owner = VRService(process_probe=lambda: False)
    prepared = owner.prepare(game_dir=game, dll=vr_dll)
    path = {"flat": game / "GK3.exe", "renderer": vr_dll, "state": game / STATE}[changed]
    path.write_bytes(b"changed after preflight")
    with pytest.raises(ValueError, match="changed"):
        owner.apply(prepared)
    assert path.read_bytes() == b"changed after preflight"
    assert not (game / "GK3-VR.exe").exists()


def test_flat_manifest_selects_only_its_verified_supported_backup(game: Path, vr_dll: Path) -> None:
    original = game / "GK3.exe.bak"
    original.write_bytes(b"original")
    (game / "GK3.exe").write_bytes(b"flat patched")
    digest = hashlib.sha256(b"original").hexdigest()
    profile = next(iter(SUPPORTED_BUILDS.values()))
    manifest = PatchManifest.create(
        identity=ManifestIdentity(
            "development",
            None,
            profile.id,
            digest,
            ProfileId("recommended"),
            (),
            1280,
            800,
            "a" * 64,
            original.name,
        ),
        installed_sha256=hashlib.sha256(b"flat patched").hexdigest(),
    )
    (game / ".gk3hd-patch.json").write_text(manifest.to_json())
    baseline = flat_files(game)
    owner = VRService(process_probe=lambda: False)
    owner.install(game_dir=game, dll=vr_dll)
    assert (game / f"{PLAYER}/original.exe").read_bytes() == b"original"
    assert flat_files(game) == baseline
    assert original.read_bytes() == b"original"


def test_an_unmanaged_backup_does_not_authorize_an_unknown_game(game: Path, vr_dll: Path) -> None:
    (game / "GK3.exe.bak").write_bytes(b"original")
    (game / "GK3.exe").write_bytes(b"unknown mod")
    with pytest.raises(ValueError, match="unsupported source"):
        VRService(process_probe=lambda: False).install(game_dir=game, dll=vr_dll)
    assert not (game / STATE).exists()
    assert (game / "GK3.exe").read_bytes() == b"unknown mod"


def test_local_build_is_used_when_no_dll_path_is_supplied(
    game: Path, vr_dll: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = service.inspect_vr_dll(vr_dll)
    lookup = Mock(return_value=asset)
    monkeypatch.setattr(service, "local_build", lookup)
    VRService(process_probe=lambda: False).install(game_dir=game)
    lookup.assert_called_once_with(game_dir=game)


def test_published_validation_failure_restores_absent_vr_installation(
    game: Path, vr_dll: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = VRService(process_probe=lambda: False)
    prepared = owner.prepare(game_dir=game, dll=vr_dll)
    monkeypatch.setattr(owner, "verify", Mock(side_effect=ValueError("bad disk player")))
    baseline = flat_files(game)
    with pytest.raises(ValueError, match="bad disk player"):
        owner.apply(prepared)
    assert not any((game / name).exists() for name in FILES)
    assert flat_files(game) == baseline


def test_a_forged_ownership_hash_cannot_replace_independent_program_verification(
    game: Path, vr_dll: Path
) -> None:
    owner = VRService(process_probe=lambda: False)
    owner.install(game_dir=game, dll=vr_dll)
    state = VRState.read(game / STATE)
    player = game / "GK3-VR.exe"
    player.write_bytes(b"changed program")
    hashes = dict(state.files)
    hashes["GK3-VR.exe"] = hashlib.sha256(player.read_bytes()).hexdigest()
    (game / STATE).write_bytes(VRState(state.units_per_meter, tuple(hashes.items())).to_bytes())
    with pytest.raises(ValueError, match="independent rebuild"):
        owner.verify(game_dir=game)


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf"), 1e308, 1e-300])
def test_invalid_calibration_cannot_publish_a_player(
    game: Path, vr_dll: Path, scale: float
) -> None:
    with pytest.raises(ValueError, match="world scale"):
        VRService(process_probe=lambda: False).prepare(
            game_dir=game, dll=vr_dll, units_per_meter=scale
        )
    assert not any((game / name).exists() for name in FILES)
