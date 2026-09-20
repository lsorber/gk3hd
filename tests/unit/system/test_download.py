"""Failed downloads close their response bodies as reliably as successful ones."""

import io
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import Mock

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
