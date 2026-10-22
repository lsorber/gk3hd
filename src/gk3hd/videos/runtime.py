"""Build and verify the private, registration-free AV1 playback resources."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from gk3hd.system.download import download_verified
from gk3hd.system.files import atomic_write, cache_directory, json_bytes, sha256_file
from gk3hd.videos.catalog import movie_workspace

RECIPE = Path(__file__).with_name("player")
PLAYER_DLL = "gk3hd-videos.dll"

if TYPE_CHECKING:
    from gk3hd.system.download import ProgressCallback


class _PlayerPin(TypedDict):
    version: str
    url: str
    sha256: str
    size: int
    files: list[str]


def _pin() -> _PlayerPin:
    return cast("_PlayerPin", json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8")))


def recipe_digest() -> str:
    """Identify source, pinned codecs and the native compiler recipe together."""
    digest = hashlib.sha256()
    for path in sorted(RECIPE.iterdir()):
        if path.is_file():
            digest.update(path.name.encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n"))
    toolchain = RECIPE.parents[1] / "renderer"
    digest.update((toolchain / "toolchain.ps1").read_bytes().replace(b"\r\n", b"\n"))
    compiler = json.loads((toolchain / "upstream.json").read_text(encoding="utf-8"))
    digest.update(json_bytes({key: compiler[key] for key in ("msvc", "windows_sdk")}))
    return digest.hexdigest()


def inspect_player(directory: Path) -> tuple[tuple[str, str, int], ...]:
    """Require every codec, license and wrapper to match the successful build."""
    pin = _pin()
    names = {*pin["files"], PLAYER_DLL}
    record = json.loads((directory / "player.json").read_text(encoding="utf-8"))
    if (
        not isinstance(record, dict)
        or record.get("recipe_sha256") != recipe_digest()
        or not isinstance(record.get("files"), dict)
        or set(record["files"]) != names
    ):
        msg = "movie player build is incomplete or outdated; run gk3hd videos build"
        raise ValueError(msg)
    entries = []
    for name in sorted(names):
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha256_file(path) != record["files"][name]:
            msg = f"movie player resource changed: {name}; run gk3hd videos build"
            raise ValueError(msg)
        entries.append((name, record["files"][name], path.stat().st_size))
    return tuple(entries)


def local_player(game_dir: Path) -> Path:
    """Resolve only the current recipe's verified build, not an arbitrary DLL."""
    directory = movie_workspace(game_dir) / "player" / recipe_digest()[:16] / "runtime"
    if not directory.is_dir():
        msg = "AV1 playback needs its player build; run gk3hd videos build first"
        raise ValueError(msg)
    inspect_player(directory)
    return directory


def codec_cache(cache: Path | None = None) -> Path:
    """Keep the upstream archive separate from our own release assets."""
    pin = _pin()
    return (cache or cache_directory()) / "video-player" / pin["sha256"] / "lav-x86.zip"


def download_codecs(cache: Path | None = None, *, progress: ProgressCallback | None = None) -> Path:
    """Obtain the immutable, unmodified x86 codecs directly from upstream."""
    pin = _pin()
    return download_verified(
        pin["url"], codec_cache(cache), sha256=pin["sha256"], size=pin["size"], progress=progress
    )


def extract_codecs(archive: Path, output: Path) -> None:
    """Install only pinned codec and notice names, never register system filters."""
    pin = _pin()
    if archive.stat().st_size != pin["size"] or sha256_file(archive) != pin["sha256"]:
        msg = "cached video codecs failed verification"
        raise ValueError(msg)
    with zipfile.ZipFile(archive) as package:
        for name in pin["files"]:
            atomic_write(output / name, package.read(name))


def build_player(game_dir: Path) -> Path:
    """Download pinned codecs and compile the small adapter without registering them."""
    if sys.platform != "win32":
        msg = "building the movie player requires Windows with Visual Studio C++ Build Tools"
        raise ValueError(msg)
    shell = shutil.which("pwsh")
    if shell is None:
        msg = "PowerShell 7 (pwsh) is required for movie player builds"
        raise ValueError(msg)
    root = movie_workspace(game_dir) / "player" / recipe_digest()[:16]
    output = root / "runtime"
    if (output / "player.json").is_file():
        inspect_player(output)
        return output
    root.mkdir(parents=True, exist_ok=True)
    pin = _pin()
    archive = download_codecs()
    output.mkdir(exist_ok=True)
    extract_codecs(archive, output)
    headers = root / "include"
    headers.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for name in ("LAVVideoSettings.h", "LAVAudioSettings.h", "LAVSplitterSettings.h"):
            atomic_write(headers / name, package.read("include/" + name))
    result = subprocess.run(  # noqa: S603 - fixed script and separate path arguments.
        [
            shell,
            "-NoProfile",
            "-File",
            str(RECIPE / "build.ps1"),
            "-Output",
            str(output),
            "-Include",
            str(headers),
        ],
        check=False,
    )
    if result.returncode:
        msg = f"movie player build failed (exit {result.returncode})"
        raise RuntimeError(msg)
    atomic_write(
        output / "player.json",
        json_bytes(
            {
                "recipe_sha256": recipe_digest(),
                "files": {name: sha256_file(output / name) for name in (*pin["files"], PLAYER_DLL)},
            }
        ),
    )
    inspect_player(output)
    return output
