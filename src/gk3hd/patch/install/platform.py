"""Select a registry/configuration adapter for the resolved installation."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from gk3hd.patch.install.proton import proton_configuration
from gk3hd.patch.install.windows import WindowsInstallConfiguration

if TYPE_CHECKING:
    from pathlib import Path


def default_configuration(exe: Path) -> WindowsInstallConfiguration:
    """Use Windows settings or the game's own isolated Proton prefix."""
    return WindowsInstallConfiguration() if os.name == "nt" else proton_configuration(exe)
