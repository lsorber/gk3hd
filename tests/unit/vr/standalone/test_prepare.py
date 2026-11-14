"""One-command preparation updates data without resetting the purchased game."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.system.files import sha256_file
from gk3hd.vr.standalone import prepare as service
from gk3hd.vr.standalone.bundle import BundleReceipt
from gk3hd.vr.standalone.device import DeviceProbe

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    game, components = tmp_path / "game", tmp_path / "components"
    game.mkdir()
    components.mkdir()
    (game / "Data").mkdir()
    for name in (
        "GK3.exe",
        "binkw32.dll",
        "save0001.gk3",
        "GK3.ini",
        service.textures.STATE_FILENAME,
        service.VIDEO_STATE_FILENAME,
    ):
        (game / name).write_bytes(name.encode())
    (game / "Data/common.brn").write_bytes(b"purchased data")
    (components / "standalone-components.json").write_bytes(b"build one")
    service.distribution.renderer_path(components).with_suffix(".json").write_bytes(b"renderer one")
    download = Mock(return_value=components)
    headset = DeviceProbe("quest", {"api": "32", "abis": "arm64-v8a"}, None, (), ())
    probe = Mock(return_value=headset)
    closed = Mock()
    video_pin = Mock()
    textures = Mock()
    videos = Mock()
    monkeypatch.setattr(service.distribution, "components", download)
    monkeypatch.setattr(service.devices, "probe", probe)
    monkeypatch.setattr(service, "require_player_closed", closed)
    monkeypatch.setattr(service, "check_standalone_pack", video_pin)
    monkeypatch.setattr(
        service,
        "discover_game",
        lambda **_kwargs: SimpleNamespace(
            game_dir=game, exe=game / "GK3.exe", data_dir=game / "Data"
        ),
    )
    original = Mock(return_value=game / "GK3.exe")
    monkeypatch.setattr(service, "original_source", original)
    monkeypatch.setattr(service.textures, "install", textures)
    monkeypatch.setattr(service, "install_pack", videos)

    def pack(output: Path, **_kwargs: object) -> BundleReceipt:
        output.write_bytes((components / "standalone-components.json").read_bytes())
        return BundleReceipt(output, sha256_file(output), 1, output.stat().st_size)

    builder = Mock(side_effect=pack)

    def prepare_payload(*_args: object) -> SimpleNamespace:
        payload = service.packer.PlayerPayload(
            generated={
                "standalone-components.json": (
                    components / "standalone-components.json"
                ).read_bytes(),
            },
            files={},
            hashes={"videos": sha256_file(game / service.VIDEO_STATE_FILENAME)},
            verify_unchanged=lambda: None,
        )
        return SimpleNamespace(
            identity=payload.identity, write=builder, verify_unchanged=payload.verify_unchanged
        )

    monkeypatch.setattr(service.packer, "prepare_payload", prepare_payload)
    return SimpleNamespace(
        game=game,
        components=components,
        pack=builder,
        download=download,
        probe=probe,
        closed=closed,
        original=original,
        video_pin=video_pin,
        textures=textures,
        videos=videos,
    )


def test_running_game_stops_before_downloading_or_preparing_assets(
    environment: SimpleNamespace,
) -> None:
    environment.closed.side_effect = RuntimeError("Close the standalone game before installing")
    with pytest.raises(RuntimeError, match="Close the standalone game"):
        service.prepare(game_dir=environment.game)
    environment.closed.assert_called_once_with(adb=None, device="quest")
    environment.download.assert_not_called()
    environment.textures.assert_not_called()
    environment.videos.assert_not_called()
    environment.pack.assert_not_called()


@pytest.mark.parametrize(("api", "abis"), [("25", "arm64-v8a"), ("32", "armeabi-v7a")])
def test_unsupported_device_stops_before_downloading_assets(
    environment: SimpleNamespace, api: str, abis: str
) -> None:
    environment.probe.return_value.properties.update(api=api, abis=abis)
    with pytest.raises(RuntimeError, match="requires Android API 26"):
        service.prepare(game_dir=environment.game)
    environment.download.assert_not_called()
    environment.textures.assert_not_called()
    environment.videos.assert_not_called()
    environment.pack.assert_not_called()


def test_unsupported_game_stops_before_downloading_assets(environment: SimpleNamespace) -> None:
    environment.original.side_effect = ValueError("Unrecognized original executable")
    with pytest.raises(ValueError, match="Unrecognized original executable"):
        service.prepare(game_dir=environment.game)
    environment.download.assert_not_called()
    environment.textures.assert_not_called()
    environment.videos.assert_not_called()
    environment.pack.assert_not_called()


def test_incompatible_movies_stop_before_preparing_other_standalone_assets(
    environment: SimpleNamespace,
) -> None:
    environment.video_pin.side_effect = ValueError("video pack uses a different playback build")
    with pytest.raises(ValueError, match="different playback build"):
        service.prepare(game_dir=environment.game)
    environment.download.assert_not_called()
    environment.textures.assert_not_called()
    environment.videos.assert_not_called()
    environment.pack.assert_not_called()


def test_repeated_install_reuses_verified_bundle_and_keeps_game_preferences(
    environment: SimpleNamespace,
) -> None:
    game = environment.game
    before = {name: (game / name).read_bytes() for name in ("GK3.exe", "save0001.gk3", "GK3.ini")}
    first = service.prepare(game_dir=game)
    assert first[2] == "quest"
    assert service.prepare(game_dir=game) == first
    assert environment.pack.call_count == 1
    assert all((game / name).read_bytes() == data for name, data in before.items())


def test_local_prepare_reuses_bundle_without_downloading_or_reinstalling_assets(
    environment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    game, components = environment.game, environment.components
    monkeypatch.setattr(service, "inspect_components", Mock())
    monkeypatch.setattr(service, "inspect_vr_dll", Mock())
    result = service.prepare(game_dir=game, build_dir=components)
    assert service.prepare(game_dir=game, build_dir=components) == result

    assert result[0].parent == components
    assert environment.pack.call_count == 1
    environment.download.assert_not_called()
    environment.video_pin.assert_not_called()
    environment.textures.assert_not_called()
    environment.videos.assert_not_called()


def test_new_components_replace_only_the_owned_private_bundle(environment: SimpleNamespace) -> None:
    _, bundle, _ = service.prepare(game_dir=environment.game)
    (environment.components / "standalone-components.json").write_bytes(b"build two")
    _, updated, _ = service.prepare(game_dir=environment.game)
    assert updated == bundle
    assert updated.read_bytes() == b"build two"
    assert environment.pack.call_count == 2


def test_updated_video_pack_invalidates_the_cached_bundle(environment: SimpleNamespace) -> None:
    game = environment.game
    before = (game / "GK3.ini").read_bytes()
    service.prepare(game_dir=game)
    (game / service.VIDEO_STATE_FILENAME).write_bytes(b"new released video inventory")
    service.prepare(game_dir=game)
    assert environment.pack.call_count == 2
    assert (game / "GK3.ini").read_bytes() == before


def test_video_download_and_install_progress_is_owned_by_the_standalone_cli(
    environment: SimpleNamespace,
) -> None:
    events = []

    def videos(*_args: object, **kwargs: object) -> None:
        progress = kwargs["progress"]
        assert callable(progress)
        progress("Downloading videos", 12, 24)

    environment.videos.side_effect = videos
    service.prepare(game_dir=environment.game, on_progress=events.append)
    assert any(
        event.stage == "videos"
        and event.completed == 12
        and event.total == 24
        and event.message == "Downloading videos"
        and event.unit == "bytes"
        for event in events
    )


def test_failed_repack_leaves_the_previous_private_bundle_usable(
    environment: SimpleNamespace,
) -> None:
    _, bundle, _ = service.prepare(game_dir=environment.game)
    before = bundle.read_bytes()
    (environment.components / "standalone-components.json").write_bytes(b"build two")
    environment.pack.side_effect = ValueError("compilation failed")
    with pytest.raises(ValueError, match="compilation failed"):
        service.prepare(game_dir=environment.game)
    assert bundle.read_bytes() == before


def test_interrupted_metadata_publication_is_completed_on_retry(
    environment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    service.prepare(game_dir=environment.game)
    (environment.components / "standalone-components.json").write_bytes(b"build two")
    original = service.atomic_write

    def interrupt(path: Path, payload: bytes) -> None:
        if path.name == "prepared.json":
            message = "interrupted after bundle publication"
            raise OSError(message)
        original(path, payload)

    monkeypatch.setattr(service, "atomic_write", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        service.prepare(game_dir=environment.game)
    monkeypatch.setattr(service, "atomic_write", original)
    _, bundle, _ = service.prepare(game_dir=environment.game)
    assert bundle.read_bytes() == b"build two"
    assert environment.pack.call_count == 2
    assert not (bundle.parent / "pending.json").exists()


def test_unrecognized_changes_are_preserved(environment: SimpleNamespace) -> None:
    _, bundle, _ = service.prepare(game_dir=environment.game)
    bundle.write_bytes(b"external change")
    with pytest.raises(ValueError, match="changed outside"):
        service.prepare(game_dir=environment.game)
    assert bundle.read_bytes() == b"external change"
    assert environment.pack.call_count == 1


def test_repack_preserves_a_bundle_edited_during_preparation(environment: SimpleNamespace) -> None:
    _, bundle, _ = service.prepare(game_dir=environment.game)
    state = bundle.with_name("prepared.json")
    original_state = state.read_bytes()
    (environment.components / "standalone-components.json").write_bytes(b"build two")
    pack = environment.pack.side_effect

    def edit_existing(output: Path, **kwargs: object) -> BundleReceipt:
        receipt = pack(output, **kwargs)
        bundle.write_bytes(b"external change during pack")
        return receipt

    environment.pack.side_effect = edit_existing
    with pytest.raises(ValueError, match="Private bundle changed during preparation"):
        service.prepare(game_dir=environment.game)
    assert bundle.read_bytes() == b"external change during pack"
    assert state.read_bytes() == original_state
    assert not bundle.with_name("pending.json").exists()


def test_device_error_happens_before_downloads_or_game_changes(
    environment: SimpleNamespace,
) -> None:
    environment.probe.side_effect = RuntimeError("authorize the headset")
    with pytest.raises(RuntimeError, match="authorize"):
        service.prepare(game_dir=environment.game)
    environment.download.assert_not_called()
    environment.textures.assert_not_called()
