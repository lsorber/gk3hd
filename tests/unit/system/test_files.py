"""Tests for shared durable-file helpers."""

from __future__ import annotations

import hashlib
import stat
from typing import TYPE_CHECKING

import pytest

from gk3hd.system.files import atomic_write, sha256_file

if TYPE_CHECKING:
    from pathlib import Path


def test_sha256_file_reports_streaming_byte_progress(tmp_path: Path) -> None:
    payload = b"progress"
    source = tmp_path / "asset.bin"
    source.write_bytes(payload)
    updates: list[tuple[int, int]] = []

    digest = sha256_file(source, chunk_size=3, progress=lambda *values: updates.append(values))

    assert digest == hashlib.sha256(payload).hexdigest()
    assert updates == [(0, 8), (3, 8), (6, 8), (8, 8)]


def test_atomic_write_replaces_exact_bytes_and_preserves_existing_mode(tmp_path: Path) -> None:
    target = tmp_path / "GK3.exe"
    target.write_bytes(b"original")
    target.chmod(0o640)
    original_mode = stat.S_IMODE(target.stat().st_mode)

    atomic_write(target, b"complete replacement")

    assert target.read_bytes() == b"complete replacement"
    assert stat.S_IMODE(target.stat().st_mode) == original_mode
    assert list(tmp_path.glob(".GK3.exe.*.tmp")) == []


def test_atomic_write_never_truncates_target_when_replacement_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "GK3.exe"
    target.write_bytes(b"original remains intact")

    def deny_replace(source: Path, destination: Path) -> None:
        del source, destination
        message = "injected replacement denial"
        raise PermissionError(message)

    monkeypatch.setattr(type(target), "replace", deny_replace)

    with pytest.raises(PermissionError, match="replacement denial"):
        atomic_write(target, b"must never be written in place")

    assert target.read_bytes() == b"original remains intact"
    assert list(tmp_path.glob(".GK3.exe.*.tmp")) == []
