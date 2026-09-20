"""Standard-library logger used by the vendored VAE."""

from __future__ import annotations

import logging


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a library logger without installing global handlers."""
    return logging.getLogger(name)
