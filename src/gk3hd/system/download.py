"""Hash-bound standard-library downloads with resumable partial files."""

from __future__ import annotations

import shutil
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Protocol, Self

from gk3hd.system.files import sha256_file

if TYPE_CHECKING:
    from pathlib import Path

ProgressCallback = Callable[[int, int | None], None]
_CHUNK_SIZE = 1024 * 1024
_PARTIAL_CONTENT = 206
_LOCAL_HTTP_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class DownloadError(RuntimeError):
    """Report a failed or unverifiable external asset download."""


class _Response(Protocol):
    """Small response surface used by the streaming downloader."""

    status: int | None
    headers: Mapping[str, str]

    def read(self, size: int = -1) -> bytes:
        """Read response bytes."""
        ...

    def __enter__(self) -> Self:
        """Enter the response context."""
        ...

    def __exit__(self, *exc_info: object) -> None:
        """Close the response context."""
        ...


def download_verified(
    url: str,
    destination: Path,
    *,
    sha256: str,
    size: int | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    """Download one immutable asset, resume when possible, and verify it."""
    _validate_url(url)
    target = destination.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and _matches(target, sha256=sha256, size=size):
        if progress is not None:
            progress(target.stat().st_size, size or target.stat().st_size)
        return target

    partial = target.with_name(f"{target.name}.part")
    completed = partial.stat().st_size if partial.is_file() else 0
    request = urllib.request.Request(url)  # noqa: S310 - URL passed _validate_url.
    if completed:
        request.add_header("Range", f"bytes={completed}-")
    response = _open(request, url=url)

    with response:
        status = getattr(response, "status", None)
        if completed and status != _PARTIAL_CONTENT:
            completed = 0
        mode = "ab" if completed else "wb"
        header_length = response.headers.get("Content-Length")
        announced = int(header_length) + completed if header_length is not None else size
        with partial.open(mode) as stream:
            if progress is not None:
                progress(completed, announced)
            while chunk := response.read(_CHUNK_SIZE):
                stream.write(chunk)
                completed += len(chunk)
                if progress is not None:
                    progress(completed, announced)

    if not _matches(partial, sha256=sha256, size=size):
        actual = sha256_file(partial)
        msg = f"download verification failed for {url}: expected {sha256}, got {actual}"
        raise DownloadError(msg)
    partial.replace(target)
    return target


def _validate_url(url: str) -> None:
    """Permit public HTTPS and loopback HTTP used by deterministic tests."""
    parsed = urllib.parse.urlsplit(url)
    local_http = parsed.scheme == "http" and parsed.hostname in _LOCAL_HTTP_HOSTS
    if parsed.scheme != "https" and not local_http:
        msg = f"download URL must use HTTPS: {url}"
        raise DownloadError(msg)


def _open(request: urllib.request.Request, *, url: str) -> _Response:
    """Open a request only after its URL has passed the scheme policy."""
    try:
        opener = urllib.request.build_opener()
        return opener.open(request, timeout=60)
    except (OSError, urllib.error.URLError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            exc.close()  # HTTPError also owns a response body/socket.
        msg = f"could not download {url}: {exc}"
        raise DownloadError(msg) from exc


def copy_verified(
    source: Path,
    destination: Path,
    *,
    sha256: str,
    size: int | None = None,
) -> Path:
    """Copy one local release asset through the same identity contract."""
    if not _matches(source, sha256=sha256, size=size):
        msg = f"local asset does not match its manifest: {source}"
        raise DownloadError(msg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination


def _matches(path: Path, *, sha256: str, size: int | None) -> bool:
    return (
        path.is_file()
        and (size is None or path.stat().st_size == size)
        and sha256_file(path) == sha256.casefold()
    )
