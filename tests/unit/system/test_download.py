"""Verify download cleanup and resumption from existing partial files."""

import hashlib
import io
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from gk3hd.system import download


def test_http_errors_close_response_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://example.com/missing.zip"
    body = io.BytesIO(b"not found")
    error = urllib.error.HTTPError(url, 404, "Not Found", Message(), body)
    opener = Mock()
    opener.open.side_effect = error
    monkeypatch.setattr(download.urllib.request, "build_opener", lambda: opener)
    with pytest.raises(download.DownloadError, match="404"):
        download.download_verified(url, tmp_path / "pack.zip", sha256="0" * 64)
    assert body.closed
    assert not (tmp_path / "pack.zip").exists()


def test_completed_partial_is_verified_without_another_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "pack.zip"
    partial = target.with_suffix(".zip.part")
    payload = b"download interrupted after writing the last byte"
    partial.write_bytes(payload)
    opener = Mock()
    progress = Mock()
    monkeypatch.setattr(download.urllib.request, "build_opener", opener)

    assert (
        download.download_verified(
            "https://example.com/pack.zip",
            target,
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
            progress=progress,
        )
        == target
    )
    assert target.read_bytes() == payload
    assert not partial.exists()
    opener.assert_not_called()
    progress.assert_called_once_with(len(payload), len(payload))


def test_invalid_complete_partial_is_downloaded_from_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "pack.zip"
    partial = target.with_suffix(".zip.part")
    partial.write_bytes(b"bad")
    payload = b"new"
    response = MagicMock(status=200, headers={"Content-Length": str(len(payload))})
    response.__enter__.return_value = response
    response.read.side_effect = [payload, b""]
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(download.urllib.request, "build_opener", lambda: opener)

    download.download_verified(
        "https://example.com/pack.zip",
        target,
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
    )

    assert opener.open.call_args.args[0].get_header("Range") is None
    assert target.read_bytes() == payload
    assert not partial.exists()
