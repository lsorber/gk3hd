"""Exercise deterministic native-client packaging without compiling or running code."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from typing import TYPE_CHECKING

import pytest

from gk3hd.vr.android import native_client

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def client(tmp_path: Path) -> Path:
    if native_client.zstd is None:
        pytest.skip("Standalone source builds require Python 3.14")
    path = tmp_path / "native-client.so"
    data = bytearray(128)
    data[:6] = b"\x7fELF\x02\x01"
    data[16:20] = b"\x03\x00\xb7\x00"
    path.write_bytes(data)
    return path


@pytest.fixture
def allocation(client: Path, tmp_path: Path) -> Path:
    path = tmp_path / "allocation.so"
    path.write_bytes(client.read_bytes() + b"allocation")
    return path


def test_archive_is_deterministic_and_contains_only_the_client(
    client: Path, allocation: Path, tmp_path: Path
) -> None:
    app = tmp_path / "app"
    record = native_client.build_asset(client, app, allocation=allocation)
    packed = app / "src/main/assets/graphics_driver/gk3hd-vortek.tzst"
    before = packed.read_bytes(), packed.stat().st_mtime_ns
    assert native_client.build_asset(client, app, allocation=allocation) == record
    assert (packed.read_bytes(), packed.stat().st_mtime_ns) == before
    assert record["client_sha256"] == hashlib.sha256(client.read_bytes()).hexdigest()
    assert record["archive_sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert str(tmp_path) not in (app / "gk3hd-vortek.json").read_text()
    assert json.loads((app / "gk3hd-vortek.json").read_text()) == record
    assert record["allocation_sha256"] == hashlib.sha256(allocation.read_bytes()).hexdigest()
    assert record["allocation_bytes"] == allocation.stat().st_size
    assert (
        app / "src/main/assets/graphics_driver/libgk3hd_kgsl.so"
    ).read_bytes() == allocation.read_bytes()
    if native_client.zstd is None:
        pytest.skip("Standalone source builds require Python 3.14")
    with tarfile.open(fileobj=io.BytesIO(native_client.zstd.decompress(before[0]))) as archive:
        assert archive.getnames() == ["./usr/lib/libvulkan_vortek.so"]
        member = archive.extractfile(archive.getnames()[0])
        assert member is not None
        assert member.read() == client.read_bytes()


@pytest.mark.parametrize(
    "data",
    [b"not ELF", b"\x7fELF\x01\x01" + bytes(128), bytes(1024 * 1024 + 1)],
    ids=["not-elf", "wrong-architecture", "oversized"],
)
def test_invalid_client_is_rejected_before_output(
    client: Path, allocation: Path, tmp_path: Path, data: bytes
) -> None:
    client.write_bytes(data)
    app = tmp_path / "app"
    with pytest.raises(ValueError, match="client"):
        native_client.build_asset(client, app, allocation=allocation)
    assert not app.exists()


def test_changed_record_is_preserved_without_creating_an_archive(
    client: Path, allocation: Path, tmp_path: Path
) -> None:
    app = tmp_path / "app"
    app.mkdir()
    record = app / "gk3hd-vortek.json"
    record.write_text("unreviewed contents")
    with pytest.raises(FileExistsError, match="Existing"):
        native_client.build_asset(client, app, allocation=allocation)
    assert record.read_text() == "unreviewed contents"
    assert not (app / "src").exists()


@pytest.mark.parametrize("data", [b"not ELF", bytes(1024 * 1024 + 1)], ids=["not-elf", "oversized"])
def test_invalid_allocation_library_is_rejected_before_output(
    client: Path, allocation: Path, tmp_path: Path, data: bytes
) -> None:
    allocation.write_bytes(data)
    app = tmp_path / "app"
    with pytest.raises(ValueError, match="allocation"):
        native_client.build_asset(client, app, allocation=allocation)
    assert not app.exists()


def test_unsupported_python_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(native_client, "zstd", None)
    with pytest.raises(RuntimeError, match=r"Python 3\.14"):
        native_client.build_asset(
            tmp_path / "missing.so", tmp_path / "app", allocation=tmp_path / "missing-allocation.so"
        )
    assert not (tmp_path / "app").exists()
