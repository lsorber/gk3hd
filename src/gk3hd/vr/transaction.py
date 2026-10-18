"""Crash-recoverable publication of VR-only files, never the flat installation."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from gk3hd.patch.install.windows import is_gk3_running
from gk3hd.system.files import atomic_write, cache_directory, is_sha256, json_bytes, sha256_file
from gk3hd.system.locking import ExclusiveFileLock, executable_lock_path

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PLAYER = "gk3hd/vr/player"
STATE = ".gk3hd-vr.json"
FILES = (
    "GK3-VR.exe",
    f"{PLAYER}/original.exe",
    f"{PLAYER}/ddraw.dll",
    f"{PLAYER}/ddraw.json",
    f"{PLAYER}/ddraw.txt",
    f"{PLAYER}/dxvk.conf",
    STATE,
)
JOURNAL = ".gk3hd-vr-journal.json"
_MAX_BYTES = 64 * 1024 * 1024


class VRTransaction:
    """Own the shared game lock and fixed, explicitly VR-only file targets."""

    def __init__(self, exe: Path, *, process_probe: Callable[[], bool] = is_gk3_running) -> None:
        """Bind recovery to this game, without paths supplied by journal content."""
        self.exe = exe.resolve()
        self._process_probe = process_probe

    def _stopped(self) -> None:
        if self._process_probe():
            msg = "close GK3 and its VR player before changing VR files"
            raise RuntimeError(msg)

    def _path(self, name: str) -> Path:
        if name not in {*FILES, JOURNAL}:
            msg = "VR transaction target is outside its fixed ownership scope"
            raise ValueError(msg)
        path = self.exe.parent / name
        for part in (path, *path.parents):
            if part == self.exe.parent:
                break
            if part.is_symlink() or part.is_junction():
                msg = "VR transaction targets must not traverse links or junctions"
                raise ValueError(msg)
        return path

    def snapshot(self) -> dict[str, str | None]:
        """Capture exact target identities for preflight race detection."""
        return {name: self._identity(name) for name in FILES}

    def _identity(self, name: str) -> str | None:
        path = self._path(name)
        if not path.exists():
            return None
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            msg = "invalid or oversized VR transaction file"
            raise ValueError(msg)
        return sha256_file(path)

    @staticmethod
    def _cache(payload: bytes) -> str:
        if len(payload) > _MAX_BYTES:
            msg = "oversized VR transaction payload"
            raise ValueError(msg)
        digest = hashlib.sha256(payload).hexdigest()
        path = cache_directory() / "vr-transactions" / digest
        # Immutable rollback content only needs one durable publication. Verify
        # the bytes before reuse; a filename alone never establishes identity.
        if path.is_file() and path.stat().st_size == len(payload) and sha256_file(path) == digest:
            return digest
        atomic_write(path, payload)
        return digest

    @staticmethod
    def _load(digest: str) -> bytes:
        path = cache_directory() / "vr-transactions" / digest
        if path.stat().st_size > _MAX_BYTES:
            msg = "oversized VR recovery cache"
            raise ValueError(msg)
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            msg = "VR recovery cache changed; retain the journal"
            raise ValueError(msg)
        return payload

    def commit(
        self,
        files: dict[str, bytes | None],
        *,
        expected: dict[str, str | None],
        validate: Callable[[], None],
        preflight: Callable[[], None] | None = None,
    ) -> None:
        """Publish verified files or restore every captured pre-install value.

        The caller establishes ownership before calling this method. Passing
        None removes only that owned target. Validation must inspect the actual
        published player, not merely the prepared in-memory bytes.
        """
        if set(files) != set(FILES) or set(expected) != set(FILES):
            msg = "VR publication requires its exact fixed target inventory"
            raise ValueError(msg)
        with ExclusiveFileLock(executable_lock_path(self.exe)):
            self._stopped()
            self._recover()
            if self.snapshot() != expected:
                msg = "VR files changed after preparation"
                raise ValueError(msg)
            if preflight is not None:
                preflight()
            rows = {
                name: {
                    "before": self._cache(self._path(name).read_bytes())
                    if expected[name]
                    else None,
                    "after": self._cache(payload) if payload is not None else None,
                }
                for name, payload in files.items()
            }
            if any(row["before"] != expected[name] for name, row in rows.items()):
                msg = "VR files changed while capturing rollback state"
                raise ValueError(msg)
            journal = {"schema": 1, "exe": self.exe.name, "phase": "rollback", "files": rows}
            path = self._path(JOURNAL)
            atomic_write(path, json_bytes(journal))
            try:
                for name in FILES:
                    self._require_allowed(name, rows[name])
                    self._publish(name, files[name])
                validate()
                self._require_final(rows, "after")
                atomic_write(path, json_bytes({**journal, "phase": "committed"}))
                path.unlink()
            except BaseException as error:
                try:
                    self._recover()
                except Exception as recovery_error:  # noqa: BLE001 - retain journal and primary error.
                    error.add_note(f"VR recovery also failed: {recovery_error}")
                raise

    def _publish(self, name: str, payload: bytes | None) -> None:
        path = self._path(name)
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, payload)

    def _require_allowed(self, name: str, row: dict[str, str | None]) -> None:
        if self._identity(name) not in {row["before"], row["after"]}:
            msg = f"VR file {name} changed outside the transaction; retain the journal"
            raise ValueError(msg)

    def _require_final(self, rows: dict[str, dict[str, str | None]], side: str) -> None:
        if any(self._identity(name) != rows[name][side] for name in FILES):
            msg = "VR transaction does not match its verified final state"
            raise ValueError(msg)

    def recover(self) -> bool:
        """Undo interrupted publication or retain a verified committed generation."""
        with ExclusiveFileLock(executable_lock_path(self.exe)):
            self._stopped()
            return self._recover()

    def _recover(self) -> bool:
        path = self._path(JOURNAL)
        if not path.exists():
            return False
        self._identity(JOURNAL)
        journal = json.loads(path.read_bytes())
        rows = self._rows(journal)
        for name in FILES:
            self._require_allowed(name, rows[name])
        if journal["phase"] == "committed":
            self._require_final(rows, "after")
        else:
            # Validate ALL captured payloads before mutating even the first file.
            payloads = {
                name: self._load(row["before"]) if row["before"] is not None else None
                for name, row in rows.items()
            }
            for name in FILES:
                self._require_allowed(name, rows[name])
                self._publish(name, payloads[name])
            self._require_final(rows, "before")
        path.unlink()
        return True

    def _rows(self, journal: object) -> dict[str, dict[str, str | None]]:
        if (
            not isinstance(journal, dict)
            or set(journal) != {"schema", "exe", "phase", "files"}
            or type(journal["schema"]) is not int
            or journal["schema"] != 1
            or journal["exe"] != self.exe.name
            or journal["phase"] not in ("rollback", "committed")
            or not isinstance(journal["files"], dict)
            or set(journal["files"]) != set(FILES)
        ):
            msg = "invalid VR recovery journal"
            raise ValueError(msg)
        for row in journal["files"].values():
            if (
                not isinstance(row, dict)
                or set(row) != {"before", "after"}
                or any(value is not None and not is_sha256(value) for value in row.values())
            ):
                msg = "invalid VR recovery identity"
                raise ValueError(msg)
        return journal["files"]
