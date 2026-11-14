"""Release APKs identify the Winlator archives and the installer fetches them upstream."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest

from gk3hd.vr.android import runtime_assets

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    payloads = {
        "rootfs.tzst": b"root",
        "container_pattern.tzst": b"prefix",
        "box64/box64-1.0.tzst": b"emulator",
    }
    (tmp_path / "winlator-runtime.json").write_text(
        json.dumps(
            {
                name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in payloads.items()
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "upstream.json").write_text(
        json.dumps({"winlator": {"commit": "a" * 40}}), encoding="utf-8"
    )
    monkeypatch.setattr(runtime_assets, "_RECIPE", tmp_path)
    monkeypatch.setattr(runtime_assets, "cache_directory", lambda: tmp_path / "cache")
    return payloads


def test_release_leaves_stock_runtime_out_of_apk(tmp_path: Path, runtime: dict[str, bytes]) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    for name, data in runtime.items():
        (assets / name).parent.mkdir(parents=True, exist_ok=True)
        (assets / name).write_bytes(data)
    runtime_assets.omit_from_release(assets)
    apk = tmp_path / "player.apk"
    with ZipFile(apk, "w") as archive:
        for path in assets.rglob("*"):
            if path.is_file():
                archive.write(path, f"assets/{path.relative_to(assets).as_posix()}")
    assert (
        runtime_assets.apk_runtime(apk, required=True)
        == hashlib.sha256((tmp_path / "winlator-runtime.json").read_bytes()).hexdigest()
    )

    with ZipFile(apk, "a") as archive:
        archive.writestr("assets/rootfs.tzst", runtime["rootfs.tzst"])
    with pytest.raises(ValueError, match="must be downloaded from Winlator"):
        runtime_assets.apk_runtime(apk, required=True)


def test_transfer_uses_exact_upstream_paths_and_bytes(
    tmp_path: Path, runtime: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    urls = []

    def download(url: str, path: Path, **options: object) -> Path:
        data = runtime[url.split("/app/src/main/assets/", maxsplit=1)[1]]
        assert options["sha256"] == hashlib.sha256(data).hexdigest()
        assert options["size"] == len(data)
        urls.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    monkeypatch.setattr(runtime_assets, "download_verified", download)
    result = runtime_assets.prepare_transfer(tmp_path / "runtime.zip", progress=lambda *_: None)
    with ZipFile(result) as transfer:
        assert {name: transfer.read(name) for name in transfer.namelist()} == runtime
    upstream = f"https://raw.githubusercontent.com/brunodev85/winlator-app/{'a' * 40}"
    assert urls == [f"{upstream}/app/src/main/assets/{name}" for name in runtime]
