"""Carry third-party notices with the standalone APK."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd.system.download import download_verified

if TYPE_CHECKING:
    from zipfile import ZipFile

_RECIPE = Path(__file__).resolve().parent
_LIBADRENOTOOLS = "app/src/main/cpp/libadrenotools"
_BSD2_SHA256 = "7ea796e199e46093c2f5c391697bce5abeacd02b7216aa0a84e5839afb5584f3"
_LGPL21_SHA256 = "20c17d8b8c48a600800dfd14f95d5cb9ff47066a9641ddeab48dc54aec96e331"
COMPONENT_LICENSES = {
    "OpenXR-WXR-LICENSE.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    "Winlator-LICENSE.txt": _LGPL21_SHA256,
    "Vortek-LICENSE.txt": _LGPL21_SHA256,
}
_LOCAL = {
    "Adrenotools-LICENSE.txt": (f"{_LIBADRENOTOOLS}/LICENSE", _BSD2_SHA256),
    "Linker-namespace-bypass-LICENSE.txt": (
        f"{_LIBADRENOTOOLS}/lib/linkernsbypass/LICENSE",
        _BSD2_SHA256,
    ),
    "Winlator-LICENSE.txt": ("LICENSE", _LGPL21_SHA256),
}
_ZSTD = json.loads((_RECIPE / "upstream.json").read_bytes())["zstd_jni"]
_ASSETS = "assets/gk3hd"
_OPENXR_LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
_PACKAGED = {
    # Commons Compress 1.20 contributes both resources.
    "META-INF/NOTICE.txt": "964f986652d38e0e250cff9ba0e63e933f48dd6fdb3afecade167ab9f7cde9af",
    "META-INF/LICENSE.txt": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    f"{_ASSETS}/OpenXR-Loader-LICENSE.txt": _OPENXR_LICENSE_SHA256,
}


def verify_component_licenses(directory: Path) -> None:
    """Require the exact upstream license texts beside the release binaries."""
    for name, digest in COMPONENT_LICENSES.items():
        path = directory / name
        if (
            not path.is_file()
            or path.stat().st_size > 64 * 1024
            or hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != digest
        ):
            msg = f"Missing or changed standalone component license: {name}"
            raise ValueError(msg)


def embed(winlator: Path) -> None:
    """Copy notices from the exact source checkout and the pinned zstd-jni tag."""
    assets = winlator / "app/src/main" / _ASSETS
    assets.mkdir(parents=True, exist_ok=True)
    for name, (source, digest) in _LOCAL.items():
        path = winlator / source
        payload = path.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(payload).hexdigest() != digest:
            msg = f"Winlator notice differs from its source pin: {name}"
            raise ValueError(msg)
        (assets / name).write_bytes(payload)
    base = f"https://raw.githubusercontent.com/luben/zstd-jni/{_ZSTD['commit']}"
    for name, entry in _ZSTD["notices"].items():
        download_verified(
            f"{base}/{entry['path']}", assets / name, sha256=entry["sha256"], size=entry["size"]
        )


def verify(archive: ZipFile) -> None:
    """Reject APKs with a missing or changed third-party notice."""
    digests = _PACKAGED | {f"{_ASSETS}/{name}": digest for name, (_, digest) in _LOCAL.items()}
    digests.update(
        {f"{_ASSETS}/{name}": entry["sha256"] for name, entry in _ZSTD["notices"].items()}
    )
    for name, digest in digests.items():
        try:
            info = archive.getinfo(name)
        except KeyError as error:
            msg = f"The release APK is missing a third-party notice: {name}"
            raise ValueError(msg) from error
        if info.file_size > 64 * 1024 or hashlib.sha256(archive.read(info)).hexdigest() != digest:
            msg = f"The release APK has a changed third-party notice: {name}"
            raise ValueError(msg)
