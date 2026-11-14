"""Automatically provision ADB without trusting partial or altered downloads."""

from __future__ import annotations

import json
import os
from base64 import b64encode
from hashlib import sha256
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.system.download import DownloadError
from gk3hd.vr.standalone import adb

if TYPE_CHECKING:
    from pathlib import Path


def test_adb_retries_an_incomplete_install_and_reuses_verified_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = "adb.exe" if os.name == "nt" else "adb"
    payloads = {executable: b"adb contents", "NOTICE.txt": b"notice"}
    pins = {}
    for name, data in payloads.items():
        encoded = b64encode(data)
        pins[name] = {
            "size": len(encoded),
            "sha256": sha256(encoded).hexdigest(),
            "decoded_sha256": sha256(data).hexdigest(),
        }
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps({"commit": "revision", "hosts": {"windows": pins, "linux": pins}}))
    monkeypatch.setattr(adb, "_PIN", pin)
    monkeypatch.setattr(adb, "cache_directory", lambda: tmp_path / "cache")
    monkeypatch.setattr(adb.sys, "platform", "win32" if os.name == "nt" else "linux")
    monkeypatch.setattr(adb.platform, "machine", lambda: "x86_64")

    def fetch(_url: str, destination: Path, *, sha256: str, size: int) -> Path:
        name = destination.stem
        assert sha256 == pins[name]["sha256"]
        assert size == pins[name]["size"]
        destination.write_bytes(b64encode(payloads[name]))
        return destination

    interrupted = Mock(side_effect=[DownloadError("connection lost")])
    monkeypatch.setattr(adb, "download_verified", interrupted)
    with pytest.raises(DownloadError, match="connection lost"):
        adb.download_adb()

    download = Mock(side_effect=fetch)
    monkeypatch.setattr(adb, "download_verified", download)
    path = adb.download_adb()
    assert path.read_bytes() == payloads[executable]
    assert path.with_name("NOTICE.txt").read_bytes() == payloads["NOTICE.txt"]
    assert os.access(path, os.X_OK)
    assert download.call_count == len(payloads)

    download.reset_mock()
    assert adb.download_adb() == path
    download.assert_not_called()

    path.write_bytes(b"altered executable")
    assert adb.download_adb().read_bytes() == payloads[executable]
    download.assert_called_once()
