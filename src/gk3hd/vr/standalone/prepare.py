"""Prepare a compiler-free standalone install and reuse verified private bundles."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write, is_sha256, json_bytes, sha256_file
from gk3hd.system.locking import ExclusiveFileLock
from gk3hd.textures.install import service as textures
from gk3hd.videos.manifest import STATE_FILENAME as VIDEO_STATE_FILENAME
from gk3hd.videos.pack import PackRequest, check_standalone_pack, install_pack
from gk3hd.vr import distribution
from gk3hd.vr.artifact import inspect_vr_dll
from gk3hd.vr.game import original_source
from gk3hd.vr.standalone import device as devices
from gk3hd.vr.standalone import pack as packer
from gk3hd.vr.standalone.build import inspect_components
from gk3hd.vr.standalone.install import InstallProgress, require_player_closed
from gk3hd.vr.standalone.paths import APK_FILENAME, BUNDLE_FILENAME, workspace

if TYPE_CHECKING:
    from collections.abc import Callable

    from gk3hd.system.discovery import GameTarget
    from gk3hd.textures.progress import TextureInstallProgress


_MAX_RECORD = 4096


def _record(path: Path) -> dict[str, str]:
    if not path.is_file() or path.stat().st_size > _MAX_RECORD:
        msg = "Missing or oversized private bundle preparation record"
        raise ValueError(msg)
    record = json.loads(path.read_bytes())
    if not isinstance(record, dict) or not all(
        isinstance(record.get(key), str) and is_sha256(record[key]) for key in ("inputs", "sha256")
    ):
        msg = "Invalid private bundle preparation record; existing files preserved"
        raise ValueError(msg)
    return record


def _recover(directory: Path) -> None:
    journal = directory / "pending.json"
    if not journal.exists():
        return
    record = _record(journal)
    before = record.get("before")
    if before is not None and (not isinstance(before, str) or not is_sha256(before)):
        msg = "Invalid private bundle recovery baseline; existing files preserved"
        raise ValueError(msg)
    target = directory / BUNDLE_FILENAME
    actual = sha256_file(target) if target.is_file() else None
    if actual == record["sha256"]:
        atomic_write(
            directory / "prepared.json",
            json_bytes({"inputs": record["inputs"], "sha256": actual}),
        )
    elif actual != before:
        msg = "Private bundle changed during recovery; existing files preserved"
        raise ValueError(msg)
    journal.unlink()


def prepare(
    *,
    game_dir: Path | None = None,
    adb: Path | None = None,
    device: str | None = None,
    on_progress: Callable[[InstallProgress], None] | None = None,
    build_dir: Path | None = None,
) -> tuple[Path, Path, str]:
    """Prepare a private bundle from published assets or a verified local build."""
    notify = on_progress or (lambda _event: None)
    notify(InstallProgress("preflight", "Checking the headset and purchased game"))
    selected = devices.probe(adb=adb, device=device)
    devices.require_install_platform(selected)
    require_player_closed(adb=adb, device=selected.device)
    game = discover_game(game_dir=game_dir)
    original_source(game.exe)
    if build_dir is None:
        components = _install_published_assets(game.game_dir, notify)
    else:
        components = build_dir.resolve()
        inspect_components(components)
        inspect_vr_dll(distribution.renderer_path(components))
        for name, state in (
            ("textures", textures.STATE_FILENAME),
            ("videos", VIDEO_STATE_FILENAME),
        ):
            if not (game.game_dir / state).is_file():
                msg = f"HD {name} are not installed. Run gk3hd {name} install first."
                raise ValueError(msg)
    bundle = _prepare_bundle(game, components, notify)
    return components / APK_FILENAME, bundle, selected.device


def _install_published_assets(game_dir: Path, notify: Callable[[InstallProgress], None]) -> Path:
    check_standalone_pack()
    notify(InstallProgress("download", "Finding compatible prebuilt VR components"))
    components = distribution.components(
        progress=lambda done, total: notify(
            InstallProgress("download", "Downloading VR components", done, total)
        )
    )

    def texture_progress(event: TextureInstallProgress) -> None:
        notify(
            InstallProgress("textures", event.description, event.completed, event.total, event.unit)
        )

    textures.install(textures.TextureInstallRequest(game_dir=game_dir), progress=texture_progress)

    def video_progress(message: str, done: int, total: int) -> None:
        notify(InstallProgress("videos", message, done, total))

    notify(InstallProgress("videos", "Installing the released HD videos and private player"))
    install_pack(game_dir, PackRequest(), progress=video_progress)
    return components


def _prepare_bundle(
    game: GameTarget,
    components: Path,
    notify: Callable[[InstallProgress], None],
) -> Path:
    directory = workspace(game.game_dir) / "ready"
    with ExclusiveFileLock(directory / ".prepare.lock"):
        _recover(directory)
        notify(InstallProgress("prepare", "Checking private game files"))
        target = directory / BUNDLE_FILENAME
        state = directory / "prepared.json"
        record = _record(state) if state.is_file() else None
        before = None
        if target.exists():
            if record is None:
                msg = "Unrecognized private bundle preserved; move it before automatic preparation"
                raise ValueError(msg)
            before = sha256_file(target)
            if record["sha256"] != before:
                msg = "Private bundle changed outside GK3HD; existing files preserved"
                raise ValueError(msg)
        payload = packer.prepare_payload(game, components, packer.PreparationOptions())
        signature = payload.identity
        if record is not None and before is not None and record["inputs"] == signature:
            payload.verify_unchanged()
            notify(InstallProgress("prepare", "Reusing the verified game bundle"))
            return target
        with TemporaryDirectory(prefix=".prepare-", dir=directory) as temporary:
            receipt = payload.write(
                Path(temporary) / BUNDLE_FILENAME,
                progress=lambda done, total: notify(
                    InstallProgress("prepare", "Packaging private game data", done, total, "items")
                ),
            )
            current = sha256_file(target) if target.exists() else None
            if current != before:
                msg = "Private bundle changed during preparation; existing files preserved"
                raise ValueError(msg)
            journal = directory / "pending.json"
            atomic_write(
                journal,
                json_bytes(
                    {
                        "inputs": signature,
                        "sha256": receipt.sha256,
                        "before": before,
                    }
                ),
            )
            receipt.path.replace(target)
            atomic_write(state, json_bytes({"inputs": signature, "sha256": receipt.sha256}))
            journal.unlink()
        return target
