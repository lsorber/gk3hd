"""Direct DLL releases retain source provenance, notices and identity checks."""

from __future__ import annotations

import hashlib
import json
import struct
from typing import TYPE_CHECKING

import pytest

from gk3hd.renderer import artifact

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def renderer_dll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    pin = {
        "version": "2.2-gk3hd.3",
        "commit": "a" * 40,
        "msvc": "1",
        "windows_sdk": "2",
        "meson": "3",
        "ninja": "4",
    }
    patch = b"synthetic source patch\n"
    dll = bytearray(256)
    dll[:2] = b"MZ"
    struct.pack_into("<I", dll, 0x3C, 64)
    dll[64:68] = b"PE\0\0"
    for offset, value in ((68, 0x14C), (86, 0x2000), (88, 0x10B)):
        struct.pack_into("<H", dll, offset, value)
    path = tmp_path / f"d7vk-{pin['version']}.dll"
    path.write_bytes(dll)
    notices = "\n".join(f"=== {name} ===\nTest notice" for name in artifact._LICENSES).encode()
    path.with_suffix(".txt").write_bytes(notices)
    build = {
        "version": pin["version"],
        "upstream_commit": pin["commit"],
        **{key: pin[key] for key in ("msvc", "windows_sdk", "meson", "ninja")},
        "source_path_mapping": "gk3hd-build",
        "dll_sha256": hashlib.sha256(dll).hexdigest(),
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "notices_sha256": hashlib.sha256(notices).hexdigest(),
        "surface_tests": "passed",
        "helper_tests": "passed",
    }
    path.with_suffix(".json").write_text(json.dumps(build))
    (recipe / "upstream.json").write_text(json.dumps(pin))
    (recipe / "renderer.patch").write_bytes(patch)
    monkeypatch.setattr(artifact, "_TOOLS", recipe)
    return path


def test_direct_dll_lock_and_all_uploads(renderer_dll: Path) -> None:
    asset = artifact.inspect_dll(renderer_dll)
    lock = asset.lock("v1.0")
    assert lock["asset_url"].endswith("/v1.0/d7vk-2.2-gk3hd.3.dll")
    assert lock["dll_sha256"] == hashlib.sha256(renderer_dll.read_bytes()).hexdigest()
    assert int(lock["dll_size"]) == renderer_dll.stat().st_size
    assert artifact.release_target(lock) == ("lsorber/gk3hd", "v1.0", renderer_dll.name)
    assert asset.uploads == (
        renderer_dll,
        renderer_dll.with_suffix(".json"),
        renderer_dll.with_suffix(".txt"),
    )
    asset.verify_unchanged()
    with pytest.raises(ValueError, match=r"invalid.*tag"):
        asset.lock("../latest")


@pytest.mark.parametrize(
    "field",
    [
        "surface_tests",
        "helper_tests",
        "patch_sha256",
        "dll_sha256",
        "notices_sha256",
        "msvc",
        "upstream_commit",
    ],
)
def test_renderer_rejects_mismatched_provenance(renderer_dll: Path, field: str) -> None:
    path = renderer_dll.with_suffix(".json")
    build = json.loads(path.read_text())
    build[field] = "wrong"
    path.write_text(json.dumps(build))
    with pytest.raises(ValueError, match="provenance"):
        artifact.inspect_dll(renderer_dll)


@pytest.mark.parametrize("suffix", [".json", ".txt"])
def test_renderer_requires_companions(renderer_dll: Path, suffix: str) -> None:
    renderer_dll.with_suffix(suffix).unlink()
    with pytest.raises(FileNotFoundError):
        artifact.inspect_dll(renderer_dll)


@pytest.mark.parametrize("payload", [b"", b"MZ", b"MZ" + bytes(80)])
def test_renderer_rejects_malformed_dll(payload: bytes) -> None:
    with pytest.raises(ValueError, match="x86 PE32 DLL"):
        artifact._verify_dll(payload)


@pytest.mark.parametrize(("offset", "value"), [(68, 0x8664), (86, 0), (88, 0x20B)])
def test_renderer_rejects_exe_or_x64(renderer_dll: Path, offset: int, value: int) -> None:
    payload = bytearray(renderer_dll.read_bytes())
    struct.pack_into("<H", payload, offset, value)
    renderer_dll.write_bytes(payload)
    with pytest.raises(ValueError, match="x86 PE32 DLL"):
        artifact.inspect_dll(renderer_dll)


def _remote(asset: artifact.RendererAsset) -> dict[str, object]:
    return {
        "tag_name": "v1.0",
        "assets": [
            {
                "name": p.name,
                "state": "uploaded",
                "size": p.stat().st_size,
                "digest": "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in asset.uploads
        ],
    }


def test_renderer_remote_gate(renderer_dll: Path) -> None:
    asset = artifact.inspect_dll(renderer_dll)
    lock = asset.lock("v1.0")
    artifact.validate_release_assets(lock, _remote(asset))
    with pytest.raises(ValueError, match="pinned tag"):
        artifact.validate_release_assets(lock, {**_remote(asset), "tag_name": "v1.1"})
    with pytest.raises(ValueError, match="missing unique"):
        artifact.validate_release_assets(lock, {"tag_name": "v1.0", "assets": []})


@pytest.mark.parametrize(("field", "value"), [("digest", None), ("size", 1), ("state", "starter")])
def test_renderer_rejects_bad_remote_upload(renderer_dll: Path, field: str, value: object) -> None:
    asset = artifact.inspect_dll(renderer_dll)
    remote = _remote(asset)
    assets = remote["assets"]
    assert isinstance(assets, list)
    assets[0][field] = value
    with pytest.raises(ValueError, match="incomplete or differs"):
        artifact.validate_release_assets(asset.lock("v1.0"), remote)


@pytest.mark.parametrize("suffix", [".dll", ".json", ".txt"])
def test_renderer_replacement_before_tag_is_detected(renderer_dll: Path, suffix: str) -> None:
    asset = artifact.inspect_dll(renderer_dll)
    path = renderer_dll.with_suffix(suffix)
    path.write_bytes(b"x" * path.stat().st_size)
    with pytest.raises(ValueError, match="changed after verification"):
        asset.verify_unchanged()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a.dll",
        "file:///tmp/a.dll",
        "https://github.com/lsorber/gk3hd/releases/download/latest/a.dll",
    ],
)
def test_renderer_refuses_mutable_or_foreign_url(url: str) -> None:
    with pytest.raises(ValueError, match="immutable"):
        artifact.release_target({"asset_url": url, "dll_sha256": "a" * 64})
