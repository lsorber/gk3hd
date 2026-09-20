"""Contracts for cross-process executable transaction serialization."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.system import locking
from gk3hd.system.files import cache_directory
from gk3hd.system.locking import ExclusiveFileLock, LockError, executable_lock_path

if TYPE_CHECKING:
    from pathlib import Path


def test_executable_lock_path_is_shared_and_stable(tmp_path: Path) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")

    path = executable_lock_path(exe)
    assert path.parent == cache_directory() / "locks"
    assert path.suffix == ".lock"
    assert path == executable_lock_path(exe)


def test_second_transaction_cannot_own_the_same_lock(tmp_path: Path) -> None:
    path = tmp_path / ".GK3.exe.gk3hd.lock"

    with (
        ExclusiveFileLock(path),
        pytest.raises(LockError, match="another gk3hd transaction"),
        ExclusiveFileLock(path),
    ):
        pytest.fail("the second owner must never enter")

    # The stable file is reusable after release and is deliberately not
    # deleted, avoiding an inode/path replacement race between processes.
    with ExclusiveFileLock(path):
        assert path.exists()
    assert path.read_bytes() == b"0"


def test_failed_sentinel_initialization_releases_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error after acquiring the range must not leave an unreachable owner."""
    path = tmp_path / "sentinel.lock"
    lock = ExclusiveFileLock(path)
    handle = path.open("a+b")
    with monkeypatch.context() as patch:
        patch.setattr(type(path), "open", Mock(return_value=handle))
        patch.setattr(handle, "flush", Mock(side_effect=OSError("sentinel unavailable")))
        with pytest.raises(OSError, match="sentinel unavailable"):
            lock.__enter__()
    assert handle.closed
    with ExclusiveFileLock(path):
        assert path.exists()


def test_failed_explicit_unlock_still_closes_the_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the descriptor is the final release even if explicit unlocking fails."""
    path = tmp_path / "unlock.lock"
    lock = ExclusiveFileLock(path)
    lock.__enter__()
    handle = lock._handle
    assert handle is not None
    with monkeypatch.context() as patch:
        if os.name == "nt":
            patch.setattr(locking.msvcrt, "locking", Mock(side_effect=OSError("unlock failed")))
        else:
            patch.setattr(locking.fcntl, "flock", Mock(side_effect=OSError("unlock failed")))
        with pytest.raises(OSError, match="unlock failed"):
            lock.__exit__(None, None, None)
    assert handle.closed
    with ExclusiveFileLock(path):
        assert path.exists()
