"""Standalone server assets must preserve the qualified protocol and exact payload."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from gk3hd.vr.android import wine_assets

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "package"
    root.mkdir()
    image = bytearray(64)
    image[:6] = b"\x7fELF\x02\x01"
    image[16:20] = b"\x03\x00\x3e\x00"
    payload = {"wineserver": bytes(image), "COPYING.LIB": b"fixture license"}
    for name in ("registry-save.patch", "private-temp.patch", "upstream.json"):
        payload[name] = (wine_assets.RECIPE / name).read_bytes().replace(b"\r\n", b"\n")
    for name, data in payload.items():
        (root / name).write_bytes(data)
    pin = json.loads(payload["upstream.json"])
    record = {
        "schema": 1,
        "kind": "standalone-wine-registry-server",
        "upstream": pin,
        "protocol_sha256": pin["protocol_sha256"],
        "default_async_registry": True,
        "default_versioned_dirty_tracking": True,
        "patches": {
            name: hashlib.sha256(payload[name]).hexdigest()
            for name in ("registry-save.patch", "private-temp.patch")
        },
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()},
    }
    (root / "server-build.json").write_text(json.dumps(record))
    return root


def test_packages_exact_server_and_source_provenance(source: Path, tmp_path: Path) -> None:
    app = tmp_path / "app"
    first = wine_assets.build_asset(source, app)
    assert wine_assets.build_asset(source, app) == first
    assets = app / "src/main/assets/gk3hd"
    assert (assets / "wine-server.elf").read_bytes() == (source / "wineserver").read_bytes()
    assert (assets / "wine-server.sha256").read_text().strip() == first["server_sha256"]
    assert (assets / "wine/COPYING.LIB").read_bytes() == (source / "COPYING.LIB").read_bytes()
    assert (assets / "wine/server-build.json").read_bytes() == (
        source / "server-build.json"
    ).read_bytes()


@pytest.mark.parametrize("change", ["binary", "protocol", "defaults"])
def test_rejects_unqualified_input_before_publishing(
    source: Path, tmp_path: Path, change: str
) -> None:
    if change == "binary":
        (source / "wineserver").write_bytes(b"different executable")
    else:
        path = source / "server-build.json"
        record = json.loads(path.read_bytes())
        record["protocol_sha256" if change == "protocol" else "default_async_registry"] = (
            "0" * 64 if change == "protocol" else False
        )
        path.write_text(json.dumps(record))
    app = tmp_path / "app"
    with pytest.raises(ValueError, match=r"verification|compatible source recipe"):
        wine_assets.build_asset(source, app)
    assert not app.exists()


def test_preserves_an_existing_different_build(source: Path, tmp_path: Path) -> None:
    app = tmp_path / "app"
    existing = app / "src/main/assets/gk3hd/wine-server.elf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"another build")
    with pytest.raises(FileExistsError, match="Existing Wine server assets differ"):
        wine_assets.build_asset(source, app)
    assert existing.read_bytes() == b"another build"
    assert not existing.with_name("wine-server.sha256").exists()
