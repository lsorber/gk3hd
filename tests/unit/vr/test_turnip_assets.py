"""Source-driver packaging preserves provenance and rejects altered build inputs."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from gk3hd.vr.android import turnip_assets


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path]:
    if turnip_assets.zstd is None:
        pytest.skip("source-driver packaging requires Python 3.14")
    source, app = tmp_path / "driver", tmp_path / "app"
    payload = {
        "usr/lib/" + name: b"\x7fELF\x02\x01" + bytes(10) + b"\x03\x00\xb7\x00"
        for name in turnip_assets.LIBRARIES
    }
    payload["usr/lib/libvulkan_freedreno.so"] += b"MESA_GK3HD_COMPRESSED_X11\0"
    payload.update(dict.fromkeys(turnip_assets.NOTICES, b"fixture notice"))
    for name, content in payload.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    pin = json.loads((turnip_assets.RECIPE / "upstream.json").read_text())
    record = {
        "kind": "standalone-private-source-driver",
        "mesa": pin["mesa"]["version"],
        "archive_sha256": pin["mesa"]["sha256"],
        "minimum_transport": "four-row-padded-stereo",
        "patches": {
            name: hashlib.sha256(
                (turnip_assets.RECIPE / name).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for name in turnip_assets.PATCHES
        },
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in payload.items()},
    }
    (source / "driver-build.json").write_text(json.dumps(record))
    version = app / "src/main/java/com/winlator/core/DefaultVersion.java"
    version.parent.mkdir(parents=True)
    version.write_text('public static final String TURNIP = "26.2.0";\n')
    return source, app


def test_package_is_repeatable_and_selects_its_own_builtin_version(
    inputs: tuple[Path, Path],
) -> None:
    source, app = inputs
    first = turnip_assets.build_asset(source, app)
    before = {p.relative_to(app): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    assert turnip_assets.build_asset(source, app) == first
    assert {p.relative_to(app): p.read_bytes() for p in app.rglob("*") if p.is_file()} == before
    version = (app / "src/main/java/com/winlator/core/DefaultVersion.java").read_text()
    assert str(first["version"]) in version
    descriptor = json.loads((app / "src/main/assets/gk3hd-turnip.json").read_text())
    assert descriptor["compressed_x11"] is True
    assert set(descriptor["files"]) == set(turnip_assets.LIBRARIES)


def test_archive_can_populate_an_empty_runtime(inputs: tuple[Path, Path], tmp_path: Path) -> None:
    source, app = inputs
    record = turnip_assets.build_asset(source, app)
    packed = next((app / "src/main/assets/graphics_driver").glob("*.tzst")).read_bytes()
    assert turnip_assets.zstd is not None
    root = tmp_path / "runtime"
    root.mkdir()
    # The host's extractor creates directory entries explicitly. Exercise that
    # consumer contract instead of tarfile's implicit parent-directory creation.
    with tarfile.open(fileobj=io.BytesIO(turnip_assets.zstd.decompress(packed))) as archive:
        for entry in archive:
            path = root / entry.name
            if entry.isdir():
                path.mkdir()
            else:
                assert entry.isfile()
                assert path.parent.is_dir()
                stream = archive.extractfile(entry)
                assert stream is not None
                path.write_bytes(stream.read())
    for name, identity in record["files"].items():
        assert (
            hashlib.sha256((root / "usr/lib" / name).read_bytes()).hexdigest() == identity["sha256"]
        )
    assert (root / "usr/share/vulkan/icd.d/freedreno_icd.aarch64.json").is_file()


def test_packaging_runs_without_an_installed_gk3hd(inputs: tuple[Path, Path]) -> None:
    source, app = inputs
    assert turnip_assets.__file__ is not None
    result = subprocess.run(  # noqa: S603 - first-party standalone build helper and owned inputs.
        [sys.executable, "-I", turnip_assets.__file__, str(source), str(app)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    descriptor = json.loads((app / "src/main/assets/gk3hd-turnip.json").read_text())
    assert json.loads(result.stdout) == descriptor


def test_corrupt_input_does_not_publish_assets_or_change_default(inputs: tuple[Path, Path]) -> None:
    source, app = inputs
    (source / "usr/lib/libvulkan_freedreno.so").write_bytes(b"corrupt")
    before = {p: p.read_bytes() for p in app.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="verification"):
        turnip_assets.build_asset(source, app)
    assert {p: p.read_bytes() for p in app.rglob("*") if p.is_file()} == before


def test_driver_without_compressed_transport_is_rejected(inputs: tuple[Path, Path]) -> None:
    source, app = inputs
    name = "usr/lib/libvulkan_freedreno.so"
    binary = source / name
    data = binary.read_bytes().removesuffix(b"MESA_GK3HD_COMPRESSED_X11\0")
    binary.write_bytes(data)
    receipt = source / "driver-build.json"
    record = json.loads(receipt.read_text())
    record["files"][name] = hashlib.sha256(data).hexdigest()
    receipt.write_text(json.dumps(record))

    with pytest.raises(ValueError, match="lacks the compressed X11 transport"):
        turnip_assets.build_asset(source, app)
    assert not (app / "src/main/assets").exists()


def test_conflicting_asset_is_preserved(inputs: tuple[Path, Path]) -> None:
    source, app = inputs
    turnip_assets.build_asset(source, app)
    descriptor = app / "src/main/assets/gk3hd-turnip.json"
    descriptor.write_bytes(b"another build")
    before = {p: p.read_bytes() for p in app.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError, match="differ"):
        turnip_assets.build_asset(source, app)
    assert {p: p.read_bytes() for p in app.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("field", ["patches", "minimum_transport", "archive_sha256"])
def test_different_source_or_transport_is_rejected(inputs: tuple[Path, Path], field: str) -> None:
    source, app = inputs
    path = source / "driver-build.json"
    record = json.loads(path.read_text())
    record[field] = "different"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="pinned source"):
        turnip_assets.build_asset(source, app)
    assert not (app / "src/main/assets").exists()


@pytest.mark.parametrize("patch", turnip_assets.PATCHES)
def test_missing_patch_provenance_does_not_publish_assets(
    inputs: tuple[Path, Path], patch: str
) -> None:
    source, app = inputs
    path = source / "driver-build.json"
    record = json.loads(path.read_text())
    del record["patches"][patch]
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="pinned source"):
        turnip_assets.build_asset(source, app)
    assert not (app / "src/main/assets").exists()
