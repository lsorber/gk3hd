"""One local workspace shared by standalone build, pack and install commands."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write, is_sha256, json_bytes, sha256_file

if TYPE_CHECKING:
    from pathlib import Path

APK_FILENAME = "gk3hd-standalone.apk"
BUNDLE_FILENAME = "gk3hd-standalone.zip"
BUILD_RECORD = "standalone-components.json"


def workspace(game_dir: Path | None = None) -> Path:
    """Resolve the normal game workspace without creating directories."""
    directory = game_dir.resolve() if game_dir is not None else discover_game().game_dir
    return directory / "gk3hd" / "vr" / "standalone"


def _receipt(directory: Path, *, release: bool) -> Path:
    return directory / ("latest-release.json" if release else "latest-development.json")


def record_build(directory: Path, record: Path, *, release: bool) -> None:
    """Publish a verified managed build only after its components are complete."""
    atomic_write(
        _receipt(directory, release=release),
        json_bytes({"candidate": record.parent.name, "sha256": sha256_file(record)}),
    )


def recorded_build(directory: Path, *, release: bool = False) -> Path:
    """Select the matching build flavor using its portable, content-bound receipt."""
    receipt = _receipt(directory, release=release)
    command = "gk3hd vr standalone build" + (" --release" if release else "")
    if not receipt.is_file():
        msg = f"No verified standalone build recorded. Run {command} first."
        raise ValueError(msg)
    data = json.loads(receipt.read_text(encoding="utf-8"))
    candidate = data.get("candidate") if isinstance(data, dict) else None
    if (
        not isinstance(candidate, str)
        or re.fullmatch("[0-9a-f]{32}", candidate) is None
        or not is_sha256(data.get("sha256"))
    ):
        msg = f"Invalid standalone build receipt. Run {command} again."
        raise ValueError(msg)
    target = directory / "build" / candidate
    record = target / BUILD_RECORD
    if target.is_symlink() or not record.is_file() or sha256_file(record) != data["sha256"]:
        msg = f"Recorded standalone build is missing or changed. Run {command} again."
        raise ValueError(msg)
    return target


def install_inputs(
    *,
    game_dir: Path | None = None,
    build_dir: Path | None = None,
    apk: Path | None = None,
    bundle: Path | None = None,
) -> tuple[Path, Path]:
    """Use build/pack outputs by default; explicit inputs need no local game."""
    if apk is None:
        apk = (build_dir or recorded_build(workspace(game_dir))) / APK_FILENAME
    if bundle is None:
        bundle = workspace(game_dir) / BUNDLE_FILENAME
    return apk, bundle
