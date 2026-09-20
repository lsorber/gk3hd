"""Latest stable renderer discovery and digest-frozen install/recovery."""

from __future__ import annotations

import hashlib
import struct
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.renderer import distribution as d7vk
from gk3hd.system.download import DownloadError

if TYPE_CHECKING:
    from pathlib import Path


def _release(tag: str = "v1.1", *, published: str = "2026-09-19T10:00:00Z") -> dict[str, object]:
    name = "d7vk-2.2-gk3hd.9.dll"
    return {
        "tag_name": tag,
        "published_at": published,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": 100,
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": f"https://github.com/lsorber/gk3hd/releases/download/{tag}/{name}",
            }
        ],
    }


def test_latest_skips_package_only_drafts_prereleases_and_paginates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    older = _release("v1.0", published="2026-09-01T00:00:00Z")
    newer = _release()
    pages = [
        [{**_release("v1.3"), "assets": []}, {**_release(), "draft": True}, older],
        [{**_release(), "prerelease": True}, newer],
    ]
    fetch = Mock(side_effect=pages)
    monkeypatch.setattr(d7vk, "_PAGE_SIZE", 3)
    monkeypatch.setattr(d7vk, "_release_page", fetch)
    result = d7vk.latest_renderer()
    assert "/v1.1/" in result["asset_url"]
    assert result["dll_sha256"] == "a" * 64
    assert result["dll_size"] == "100"
    assert [c.args for c in fetch.call_args_list] == [(1,), (2,)]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("digest", None),
        ("digest", "sha256:bad"),
        ("size", 0),
        ("size", True),
        ("state", "starter"),
        ("browser_download_url", "https://example.com/evil.dll"),
    ],
)
def test_latest_rejects_bad_identity_without_falling_back(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    newest = _release()
    assets = newest["assets"]
    assert isinstance(assets, list)
    assets[0][field] = value
    monkeypatch.setattr(
        d7vk, "_release_page", Mock(return_value=[_release("v1.0", published="2026-09-01"), newest])
    )
    with pytest.raises(DownloadError):
        d7vk.latest_renderer()


@pytest.mark.parametrize("duplicate", [False, True])
def test_latest_requires_one_matching_dll(
    monkeypatch: pytest.MonkeyPatch, *, duplicate: bool
) -> None:
    release = _release()
    assets = release["assets"]
    assert isinstance(assets, list)
    release["assets"] = assets * 2 if duplicate else []
    monkeypatch.setattr(d7vk, "_release_page", Mock(return_value=[release]))
    with pytest.raises(DownloadError, match=r"exactly one|no published"):
        d7vk.latest_renderer()


def test_discovery_failure_is_not_silently_downgraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d7vk, "_release_page", Mock(side_effect=DownloadError("rate limit")))
    with pytest.raises(DownloadError, match="rate limit"):
        d7vk.latest_renderer()


def test_direct_dll_is_cached_by_digest_and_recovery_never_rediscovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    header = bytearray(256)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 64)
    header[64:68] = b"PE\0\0"
    struct.pack_into("<H", header, 68, 0x14C)
    struct.pack_into("<H", header, 86, 0x2000)
    struct.pack_into("<H", header, 88, 0x10B)
    payload = bytes(header)
    digest = hashlib.sha256(payload).hexdigest()
    identity = {
        "asset_url": "https://github.com/lsorber/gk3hd/releases/download/v1.1/renderer.dll",
        "dll_sha256": digest,
        "dll_size": str(len(payload)),
    }
    discover = Mock(return_value=identity)
    monkeypatch.setattr(d7vk, "cache_directory", lambda: tmp_path)
    monkeypatch.setattr(d7vk, "latest_renderer", discover)

    def download(url: str, destination: Path, **kwargs: object) -> Path:
        assert url == identity["asset_url"]
        assert kwargs["sha256"] == digest
        assert kwargs["size"] == len(payload)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(payload)
        return destination

    monkeypatch.setattr(d7vk, "download_verified", download)
    assert hashlib.sha256(d7vk.dll_bytes()).hexdigest() == digest
    discover.side_effect = AssertionError("recovery must not resolve latest")
    assert d7vk.dll_bytes(sha256=digest) == payload
    assert d7vk.cached_dll_matches(digest)
    d7vk.cached_path(digest).write_bytes(b"tampered")
    assert not d7vk.cached_dll_matches(digest)
    with pytest.raises(DownloadError, match="transaction SHA-256"):
        d7vk.dll_bytes(sha256=digest)


def test_previous_dll_is_retained_for_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(d7vk, "cache_directory", lambda: tmp_path / "cache")
    dll = tmp_path / "ddraw.dll"
    dll.write_bytes(b"older renderer")
    d7vk.retain_dll(dll)
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()
    assert d7vk.dll_bytes(sha256=digest) == dll.read_bytes()
    with pytest.raises(ValueError, match="invalid renderer SHA-256"):
        d7vk.dll_bytes(sha256="../ddraw.dll")
