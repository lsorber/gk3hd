"""Unified Gabriel Knight 3 modernization package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gk3hd")
except PackageNotFoundError:
    __version__ = "1.0"

__all__ = ["__version__"]
