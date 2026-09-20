"""Discover and verify published 32-bit D7VK DLLs without archive extraction."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import urllib.request
from importlib.resources import files
from typing import TYPE_CHECKING

from gk3hd.system.download import DownloadError, ProgressCallback, download_verified
from gk3hd.system.files import atomic_write, cache_directory, sha256_file

if TYPE_CHECKING:
    from pathlib import Path


def release_lock() -> dict[str, str]:
    """Read the bundled immutable renderer identity."""
    payload = json.loads(files("gk3hd").joinpath("assets/d7vk-lock.json").read_text())
    if not isinstance(payload, dict) or not all(isinstance(v, str) for v in payload.values()):
        msg = "invalid packaged D7VK lock"
        raise RuntimeError(msg)
    return payload


DLL_NAME = "ddraw.dll"
CONFIG_NAME = "dxvk.conf"
DLL_SHA256 = release_lock()["dll_sha256"]
VERSION = release_lock()["version"]
_FIRST_PRINTABLE_ASCII = 32
REPOSITORY = "lsorber/gk3hd"
ASSET_NAME = re.compile(r"d7vk-([0-9]+(?:\.[0-9]+){1,2}-gk3hd\.[0-9]+)\.dll")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_PAGE_SIZE = 100
_MAX_PAGES = 100
MAX_DLL_BYTES = 32 * 1024 * 1024
_MIN_DOS_HEADER = 64
_MIN_NT_HEADER = 26
_PE32_MACHINE = 0x14C
_PE32_MAGIC = 0x10B
_DLL_FLAG = 0x2000


def validate_dll(payload: bytes) -> None:
    """Reject an EXE, x64 image, archive, or malformed header before installation."""
    if len(payload) < _MIN_DOS_HEADER or payload[:2] != b"MZ":
        msg = "renderer is not an x86 PE32 DLL"
        raise ValueError(msg)
    offset = struct.unpack_from("<I", payload, 0x3C)[0]
    if (
        offset + _MIN_NT_HEADER > len(payload)
        or payload[offset : offset + 4] != b"PE\0\0"
        or struct.unpack_from("<H", payload, offset + 4)[0] != _PE32_MACHINE
        or struct.unpack_from("<H", payload, offset + 24)[0] != _PE32_MAGIC
        or not struct.unpack_from("<H", payload, offset + 22)[0] & _DLL_FLAG
    ):
        msg = "renderer is not an x86 PE32 DLL"
        raise ValueError(msg)


def _release_page(page: int) -> list[dict[str, object]]:
    url = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page={_PAGE_SIZE}&page={page}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "gk3hd"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS API.
            payload = json.load(response)
    except (OSError, ValueError) as exc:
        msg = f"could not discover the latest gk3hd renderer: {exc}"
        raise DownloadError(msg) from exc
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        msg = "invalid GitHub release inventory"
        raise DownloadError(msg)
    return payload


def latest_renderer() -> dict[str, str]:
    """Find the most recently published stable release carrying our renderer.

    GitHub orders by creation, not publication, so inspect every page before
    choosing. Never silently fall back to an older DLL on invalid metadata.
    """
    candidates: list[tuple[str, dict[str, object], list[dict[str, object]]]] = []
    for page in range(1, _MAX_PAGES + 1):
        releases = _release_page(page)
        for release in releases:
            if release.get("draft") is not False or release.get("prerelease") is not False:
                continue
            assets = release.get("assets")
            published = release.get("published_at")
            if not isinstance(assets, list) or not isinstance(published, str):
                msg = "published GitHub release has no valid asset inventory or date"
                raise DownloadError(msg)
            matches = [
                asset
                for asset in assets
                if isinstance(asset, dict)
                and isinstance(asset.get("name"), str)
                and ASSET_NAME.fullmatch(asset["name"])
            ]
            if matches:
                candidates.append((published, release, matches))
        if len(releases) < _PAGE_SIZE:
            break
    else:
        msg = "too many GitHub release pages to determine the latest renderer safely"
        raise DownloadError(msg)
    if not candidates:
        msg = "no published gk3hd renderer DLL found on GitHub Releases"
        raise DownloadError(msg)
    _, release, matches = max(candidates, key=lambda item: item[0])
    if len(matches) != 1:
        msg = "latest renderer release must contain exactly one gk3hd DLL"
        raise DownloadError(msg)
    return _renderer_identity(release, matches[0])


def _renderer_identity(release: dict[str, object], asset: dict[str, object]) -> dict[str, str]:
    """Accept only the official immutable URL and an upload-computed identity."""
    tag, name, digest, size = (
        release.get("tag_name"),
        asset["name"],
        asset.get("digest"),
        asset.get("size"),
    )
    if (
        not isinstance(tag, str)
        or re.fullmatch(r"v[0-9]+(?:\.[0-9]+){1,2}", tag) is None
        or not isinstance(name, str)
        or not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or _DIGEST.fullmatch(digest[7:]) is None
        or type(size) is not int
        or size <= 0
        or size > MAX_DLL_BYTES
        or asset.get("state") != "uploaded"
    ):
        msg = "latest renderer DLL has invalid tag, upload state, size or SHA-256"
        raise DownloadError(msg)
    url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
    if asset.get("browser_download_url") != url:
        msg = "renderer download URL does not belong to the expected release"
        raise DownloadError(msg)
    return {"asset_url": url, "dll_sha256": digest[7:], "dll_size": str(size)}


def cached_path(digest: str) -> Path:
    """Locate a content-addressed DLL without permitting path traversal."""
    if _DIGEST.fullmatch(digest) is None:
        msg = "invalid renderer SHA-256"
        raise ValueError(msg)
    return cache_directory() / "d7vk" / digest / DLL_NAME


def cached_dll_matches(digest: str) -> bool:
    """Recognize verified cached identities, never just a DLL filename."""
    path = cached_path(digest)
    return path.is_file() and sha256_file(path) == digest


def retain_dll(path: Path) -> None:
    """Keep an already admitted local renderer available for exact rollback."""
    if path.is_file():
        payload = path.read_bytes()
        atomic_write(cached_path(hashlib.sha256(payload).hexdigest()), payload)


def config_bytes(*, executable_name: str, previous: bytes = b"") -> bytes:
    """Append GK3-only presentation policy, retaining unrelated config verbatim.

    D7VK's parser assigns the last active value and matches section names to
    the executable basename exactly. An explicit final section avoids inheriting
    another application's section or changing its settings. The transaction
    retains the complete original bytes for uninstall and conflict detection.
    """
    if (
        not executable_name
        or any(char in executable_name for char in "[]/\\")
        or any(ord(char) < _FIRST_PRINTABLE_ASCII for char in executable_name)
        or b"\x00" in previous
    ):
        msg = "invalid D7VK executable name or non-text configuration"
        raise ValueError(msg)
    newline = b"\r\n" if b"\r\n" in previous else b"\n"
    block = newline.join(
        (
            b"# gk3hd: required presentation settings (restored on uninstall)",
            b"[" + executable_name.encode("utf-8") + b"]",
            b"ddraw.forceLegacyPresent = True",
            b"ddraw.legacyPresentGuard = Strict",
            b"ddraw.cpuRenderTargetBacking = True",
            b"d3d9.presentInterval = 0",
            b"",
        )
    )
    if previous.endswith(block):
        return previous
    separator = newline if previous and not previous.endswith(b"\n") else b""
    return previous + separator + block


def dll_bytes(*, sha256: str | None = None, progress: ProgressCallback | None = None) -> bytes:
    """Fetch latest on a new install; replay the exact cached digest on recovery."""
    if sha256 is not None:
        payload = cached_path(sha256).read_bytes()
        if hashlib.sha256(payload).hexdigest() != sha256:
            msg = "cached renderer DLL differs from its transaction SHA-256"
            raise DownloadError(msg)
        return payload
    lock = latest_renderer()
    dll = download_verified(
        lock["asset_url"],
        cached_path(lock["dll_sha256"]),
        sha256=lock["dll_sha256"],
        size=int(lock["dll_size"]),
        progress=progress,
    )
    payload = dll.read_bytes()
    validate_dll(payload)
    return payload
