"""Exact, case-aware GK3 INI ownership tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from gk3hd.system.ini import (
    IniError,
    install_custom_path,
    installed_ini_matches,
    prepare_custom_path,
    restore_custom_path,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_custom_path_is_canonical_and_leftmost_then_restores_exactly(tmp_path: Path) -> None:
    """An existing case variant moves left without changing the INI filename."""
    ini = tmp_path / "gk3.ini"
    original = b"[Paths]\r\nCUSTOM PATHS = mods; GK3HD; other\r\n"
    ini.write_bytes(original)

    change = install_custom_path(tmp_path)

    assert change.filename == "gk3.ini"
    assert ini.read_bytes() == b"[Paths]\r\nCUSTOM PATHS = gk3hd; mods; other\r\n"
    restore_custom_path(tmp_path, change)
    assert ini.read_bytes() == original


def test_missing_ini_uses_canonical_name_and_uninstall_removes_it(tmp_path: Path) -> None:
    """Creation state is distinct from an existing empty file."""
    change = install_custom_path(tmp_path)

    ini = tmp_path / "GK3.ini"
    assert ini.read_bytes() == b"CUSTOM PATHS = gk3hd\n"
    restore_custom_path(tmp_path, change)
    assert not ini.exists()


def test_restore_refuses_later_user_edit(tmp_path: Path) -> None:
    """Uninstall never overwrites an unrecognized post-install INI."""
    ini = tmp_path / "GK3.ini"
    ini.write_bytes(b"CUSTOM PATHS = mods\n")
    change = install_custom_path(tmp_path)
    ini.write_bytes(ini.read_bytes() + b"USER = edit\n")

    with pytest.raises(IniError, match="changed after installation"):
        restore_custom_path(tmp_path, change)


def test_game_newline_rewrite_remains_a_verified_reversible_install(tmp_path: Path) -> None:
    """GK3 may rewrite LF as CRLF without changing the managed INI value."""
    change = install_custom_path(tmp_path)
    ini = tmp_path / "GK3.ini"
    ini.write_bytes(ini.read_bytes().replace(b"\n", b"\r\n"))

    assert installed_ini_matches(ini, change)
    restore_custom_path(tmp_path, change)
    assert not ini.exists()


def test_nested_custom_path_is_normalized_case_insensitively(tmp_path: Path) -> None:
    """A safe game-relative subdirectory is accepted and deduplicated as one entry."""
    ini = tmp_path / "GK3.ini"
    ini.write_bytes(b"CUSTOM PATHS = mods; GK3HD/TEXTURES/INSTALLED\n")

    _change, installed = prepare_custom_path(tmp_path, "gk3hd/textures/installed")

    assert installed == b"CUSTOM PATHS = gk3hd/textures/installed; mods\n"


@pytest.mark.parametrize(
    "value",
    ["/absolute", "../escape", "gk3hd//upscale", "gk3hd\\upscale", "gk3hd;other"],
)
def test_nested_custom_path_rejects_unsafe_forms(tmp_path: Path, value: str) -> None:
    """Only canonical forward-slash relative paths may enter the INI."""
    with pytest.raises(IniError, match="invalid custom path"):
        prepare_custom_path(tmp_path, value)
