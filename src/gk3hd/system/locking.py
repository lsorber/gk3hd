"""Cross-process exclusion shared by executable and texture transactions."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING, BinaryIO, Self

from gk3hd.system.files import cache_directory

if os.name == "nt":
    import msvcrt
else:
    import fcntl

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType


class LockError(RuntimeError):
    """Report an already-owned or invalid gk3hd transaction lock."""


def executable_lock_path(exe: Path) -> Path:
    """Return the one lock shared by installer and validation transactions."""
    target = exe.resolve()
    identity = hashlib.sha256(os.path.normcase(str(target)).encode()).hexdigest()
    return cache_directory() / "locks" / f"{identity}.lock"


class ExclusiveFileLock:
    """Own the first byte of a stable lock file until context exit.

    The file itself is intentionally persistent: deleting a lock path after
    release introduces a race where another process still holds the old inode
    while a third process locks a newly created file. Windows releases the byte
    range automatically if the owner is killed or rebooted.
    """

    def __init__(self, path: Path) -> None:
        """Bind a reusable lock object to an absolute stable file path."""
        self.path = path.resolve()
        self._handle: BinaryIO | None = None

    def __enter__(self) -> Self:
        """Acquire the file's first byte without waiting for another owner."""
        if self._handle is not None:
            message = f"transaction lock is already active: {self.path}"
            raise LockError(message)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0)
        try:
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            message = f"another gk3hd transaction already owns {self.path}"
            raise LockError(message) from exc
        # Windows permits locking the first byte of an empty file. Initialize
        # the persistent sentinel only after acquiring that range, avoiding a
        # race between two processes opening a newly created lock file.
        try:
            if self.path.stat().st_size == 0:
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
        except BaseException:
            # Closing also releases the acquired byte range. A failed sentinel
            # write must not strand a lock that __exit__ will never see.
            handle.close()
            raise
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release ownership and close the handle while retaining the file."""
        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        try:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
