"""Collect native capture-driver tests only on their supported platform."""

import sys
from pathlib import Path

import pytest

pytest_plugins = ("pytester",)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Live game automation is always explicit, never part of ordinary CI."""
    group = parser.getgroup("gk3hd visual")
    parser.addoption(
        "--slow", action="store_true", help="Include reconstruction and native-emulation tests."
    )
    group.addoption(
        "--visual", action="store_true", help="Enable live-game visual tests (Windows)."
    )
    group.addoption(
        "--suite",
        choices=("small", "medium", "large"),
        default="small",
        help="Visual scene suite: small (12), medium (25), or large (100); default: small.",
    )
    group.addoption("--game-dir", default=None, help="Override automatic GK3 discovery.")
    group.addoption("--visual-resolution", default="3840x2160")
    group.addoption("--resume", default=None, help="Resume an existing build/visual run.")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep marked captures inert unless requested, including on Windows CI."""
    enabled = config.getoption("--visual")
    if enabled and (sys.platform != "win32" or hasattr(config, "workerinput")):
        message = "visual tests require Windows and serial execution (no xdist)"
        raise pytest.UsageError(message)
    selected, deselected = [], []
    windows = Path(__file__).parent / "windows"
    for item in items:
        if item.path.is_relative_to(windows):
            item.add_marker(pytest.mark.windows)
        if item.get_closest_marker("windows") and sys.platform != "win32":
            item.add_marker(pytest.mark.skip(reason="requires Windows APIs"))
        if item.get_closest_marker("slow") and not config.getoption("--slow"):
            deselected.append(item)
            continue
        selected.append(item)
        if item.get_closest_marker("visual") and not enabled:
            item.add_marker(pytest.mark.skip(reason="live game tests require --visual"))
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


# Avoid importing Win32-only dependencies at all on portable CI workers.
collect_ignore = ["windows"] if sys.platform != "win32" else []
