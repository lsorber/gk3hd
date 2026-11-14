"""Read verified installed HD resources without importing desktop preferences."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.system.files import is_portable_filename, sha256_file
from gk3hd.textures.install.service import STATE_FILENAME, TEXTURE_DIRECTORY, verify_texture_pack
from gk3hd.videos.catalog import MOVIE_INSTALL_PATH
from gk3hd.videos.install import MovieInstaller
from gk3hd.videos.manifest import STATE_FILENAME as VIDEO_STATE_FILENAME
from gk3hd.videos.manifest import MovieState

if TYPE_CHECKING:
    from pathlib import Path

_MAX_STATE = 2 * 1024**2


@dataclass(frozen=True, slots=True)
class InstalledAssets:
    """Explicit resource paths and installed identities, not a copied desktop tree."""

    files: dict[str, Path]
    hashes: dict[str, str]
    metadata: bytes
    ini: bytes
    state: Path | None = None
    state_sha256: str | None = None

    def verify_unchanged(self) -> None:
        """Reject a concurrent pack replacement before publishing its private copy."""
        if self.state is not None and sha256_file(self.state) != self.state_sha256:
            msg = "Installed asset ownership changed during standalone preparation"
            raise ValueError(msg)


def texture_inputs(game_dir: Path, *, enabled: bool) -> InstalledAssets:
    """Require verified HD assets unless an original-texture control is explicit.

    The desktop state and INI may contain private/custom paths. Only portable
    pack identity is recorded; original preferences and state bytes stay local.
    """
    state = game_dir / STATE_FILENAME
    if not enabled:
        return InstalledAssets({}, {}, b'{"mode":"original","texture_count":0}\n', b"")
    if not state.exists():
        msg = "HD textures are not installed; run gk3hd textures install before packing"
        raise ValueError(msg)
    if not state.is_file() or state.is_symlink() or state.stat().st_size > _MAX_STATE:
        msg = "Missing or oversized installed texture ownership record"
        raise ValueError(msg)
    frozen = state.read_bytes()
    report = verify_texture_pack(game_dir)
    if state.read_bytes() != frozen:
        msg = "Installed texture ownership changed during verification"
        raise ValueError(msg)
    directory = report.directory.resolve()
    if not directory.is_relative_to(game_dir.resolve()):
        msg = "Installed texture directory escapes the game folder"
        raise ValueError(msg)
    record = json.loads(frozen)
    files: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    for entry in record["files"]:
        name = entry["filename"]
        if not is_portable_filename(name):
            msg = "Unsafe installed texture filename"
            raise ValueError(msg)
        relative = f"{TEXTURE_DIRECTORY}/{name}"
        files[relative] = directory / name
        hashes[relative] = entry["sha256"]
    identity = hashlib.sha256(frozen).hexdigest()
    metadata = json.dumps(
        {
            "mode": "installed-hd",
            "pack_version": report.pack_version,
            "texture_count": report.textures,
            "installed_state_sha256": identity,
        },
        sort_keys=True,
    ).encode()
    return InstalledAssets(
        files,
        hashes,
        metadata,
        f"CUSTOM PATHS = {TEXTURE_DIRECTORY}\n".encode("ascii"),
        state,
        identity,
    )


def video_inputs(game_dir: Path, *, enabled: bool) -> InstalledAssets:
    """Freeze verified replacements and all private player/codec resources.

    Native playback uses its fixed private installation path, without copying
    desktop preferences or registering codecs. Normal preparation installs the
    release pack first; an explicit diagnostic control may retain originals.
    """
    if not enabled:
        return InstalledAssets({}, {}, b'{"mode":"original","video_count":0}\n', b"")
    state = game_dir / VIDEO_STATE_FILENAME
    if not state.is_file() or state.is_symlink() or state.stat().st_size > _MAX_STATE:
        msg = "HD videos are not installed; run gk3hd videos install before packing"
        raise ValueError(msg)
    frozen = state.read_bytes()
    report = MovieInstaller.verify(game_dir)
    if state.read_bytes() != frozen:
        msg = "Installed video ownership changed during verification"
        raise ValueError(msg)
    record = MovieState.from_dict(json.loads(frozen))
    directory = report.directory.resolve()
    if not directory.is_relative_to(game_dir.resolve()):
        msg = "Installed video directory escapes the game folder"
        raise ValueError(msg)
    files = {
        f"{MOVIE_INSTALL_PATH}/{item.filename}": directory / item.filename
        for item in record.inventory
    }
    hashes = {f"{MOVIE_INSTALL_PATH}/{item.filename}": item.sha256 for item in record.inventory}
    identity = hashlib.sha256(frozen).hexdigest()
    metadata = json.dumps(
        {
            "mode": "installed-hd",
            "video_count": report.videos,
            "player_resources": len(record.resources),
            "pack_identity": record.pack_identity,
            "installed_state_sha256": identity,
        },
        sort_keys=True,
    ).encode()
    return InstalledAssets(files, hashes, metadata, b"", state, identity)
