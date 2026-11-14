"""Move standalone game saves over the authorized USB connection."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from gk3hd.system.files import sha256_file
from gk3hd.vr.standalone.apk import APPLICATION_ID
from gk3hd.vr.standalone.device import USB_RETRY, resolve_adb, select_device, usb_problem
from gk3hd.vr.standalone.install import _Adb

_PROVIDER = f"content://{APPLICATION_ID}.setup"
_SAVE_NAME = re.compile(r"(?:save[0-9]{4}|fastsave)\.gk3", re.ASCII | re.IGNORECASE)
_MAX_TOTAL = 64 * 1024**2
_MAX_FILE = 16 * 1024**2
_MAX_ARCHIVE = 66 * 1024**2
_TIMEOUT = 60


def _check_archive(path: Path) -> int:
    if not path.is_file() or path.stat().st_size > _MAX_ARCHIVE:
        msg = "The save backup is missing or exceeds the supported size"
        raise ValueError(msg)
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if (
                any(
                    not _SAVE_NAME.fullmatch(entry.filename)
                    or not 0 < entry.file_size <= _MAX_FILE
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                    or entry.flag_bits & 1
                    for entry in entries
                )
                or len({entry.filename.lower() for entry in entries}) != len(entries)
                or sum(entry.file_size for entry in entries) > _MAX_TOTAL
            ):
                msg = "The backup contains unexpected, duplicate or oversized save entries"
                raise ValueError(msg)
            if archive.testzip() is not None:
                msg = "The save backup failed verification"
                raise ValueError(msg)
    except (BadZipFile, NotImplementedError, RuntimeError) as error:
        msg = "The save backup could not be read as a valid ZIP"
        raise ValueError(msg) from error
    return len(entries)


def _connect(adb: Path | None, device: str | None) -> _Adb:
    executable = resolve_adb(adb)
    return _Adb(executable, select_device(executable, device))


def backup(
    destination: Path | None = None, *, adb: Path | None = None, device: str | None = None
) -> tuple[Path, int]:
    """Read a verified save snapshot without touching the game's files."""
    name = f"GK3HD-saves-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"
    target = (destination or Path(name)).expanduser().resolve()
    if target.exists():
        msg = f"Backup already exists. Choose a different filename.\n{target}"
        raise FileExistsError(msg)
    link = _connect(adb, device)
    with TemporaryDirectory(prefix=".gk3hd-saves-", dir=target.parent) as temporary:
        staged = Path(temporary) / "saves.zip"
        with staged.open("wb") as output:
            try:
                result = subprocess.run(  # noqa: S603 - explicit ADB command and fixed URI.
                    link.command("exec-out", "content", "read", "--uri", f"{_PROVIDER}/saves"),
                    stdout=output,
                    stderr=subprocess.PIPE,
                    timeout=_TIMEOUT,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                msg = f"The headset stopped responding over USB. {USB_RETRY}"
                raise RuntimeError(msg) from error
        if result.returncode or not staged.stat().st_size:
            detail = result.stderr.decode("utf-8", errors="replace")
            msg = usb_problem(detail) or (
                "Could not read the headset's saves. Close GK3HD VR and retry. "
                "If it still fails, check that the installed build supports USB save backup."
            )
            raise RuntimeError(msg)
        count = _check_archive(staged)
        os.link(staged, target)
    return target, count


def restore(source: Path, *, adb: Path | None = None, device: str | None = None) -> int:
    """Restore missing saves. The headset keeps different existing saves."""
    archive = source.expanduser().resolve()
    _check_archive(archive)
    link = _connect(adb, device)
    token = uuid4().hex
    identity = sha256_file(archive)
    remote = f"/sdcard/Download/gk3hd-restore-{token}.zip"
    try:
        link.run("push", "-q", str(archive), remote, timeout=_TIMEOUT)
        response = link.run(
            "shell",
            "content",
            "call",
            "--uri",
            _PROVIDER,
            "--method",
            "restore-saves",
            "--arg",
            f"{token}:{identity}",
            timeout=_TIMEOUT,
        )
        if match := re.fullmatch(r"Result: Bundle\[\{restored=([0-9]+)\}\]", response):
            return int(match[1])
        error = re.fullmatch(r"Result: Bundle\[\{error=([^\r\n]{1,300})\}\]", response)
        msg = (
            error[1]
            if error
            else "Could not restore saves. Check that the app supports USB restore."
        )
        raise RuntimeError(msg)
    finally:
        # Do not mask a disconnected USB cable or the restore result.
        with suppress(OSError, RuntimeError):
            link.run("shell", "rm", "-f", remote, checked=False)
