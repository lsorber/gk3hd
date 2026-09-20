"""Portable target discovery for supported Gabriel Knight 3 installations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gk3hd.system.steam import steam_games


class DiscoveryError(RuntimeError):
    """Report a missing or ambiguous GK3 installation surface."""


@dataclass(frozen=True, slots=True)
class GameTarget:
    """Resolved executable, game directory, data directory, and optional INI."""

    game_dir: Path
    exe: Path
    data_dir: Path
    ini: Path | None


def discover_game(*, game_dir: Path | None = None, exe: Path | None = None) -> GameTarget:
    """Resolve an explicit target or discover GK3 in conventional locations."""
    if exe is not None:
        executable = exe.expanduser().resolve()
        if not executable.is_file():
            msg = f"GK3 executable does not exist: {executable}"
            raise DiscoveryError(msg)
        return _target_from_exe(executable)
    if game_dir is not None:
        root = game_dir.expanduser().resolve()
        executable = _find_executable(root)
        if executable is None:
            msg = f"could not find GK3.exe under game directory: {root}"
            raise DiscoveryError(msg)
        return _target_from_exe(executable)

    for root in _conventional_roots():
        executable = _find_executable(root)
        if executable is not None:
            return _target_from_exe(executable)
    msg = "could not locate Gabriel Knight 3; pass --game-dir or --exe"
    raise DiscoveryError(msg)


def find_ini(game_dir: Path) -> Path | None:
    """Find the GK3 INI case-insensitively and reject case-only duplicates."""
    matches = sorted(
        (
            path
            for path in game_dir.iterdir()
            if path.is_file() and path.name.casefold() == "gk3.ini"
        ),
        key=lambda path: path.name,
    )
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        msg = f"ambiguous GK3 INI files: {names}"
        raise DiscoveryError(msg)
    return matches[0] if matches else None


def _target_from_exe(executable: Path) -> GameTarget:
    game_root = executable.parent
    data = _case_insensitive_directory(game_root, "data") or game_root
    return GameTarget(game_dir=game_root, exe=executable, data_dir=data, ini=find_ini(game_root))


def _find_executable(root: Path) -> Path | None:
    nested = _case_insensitive_directory(root, "GK3")
    for candidate_root in (root,) if nested is None else (root, nested):
        if not candidate_root.is_dir():
            continue
        for candidate in candidate_root.iterdir():
            if candidate.is_file() and candidate.name.casefold() == "gk3.exe":
                return candidate.resolve()
    return None


def _case_insensitive_directory(root: Path, name: str) -> Path | None:
    if not root.is_dir():
        return None
    for candidate in root.iterdir():
        if candidate.is_dir() and candidate.name.casefold() == name.casefold():
            return candidate.resolve()
    return None


def _conventional_roots() -> tuple[Path, ...]:
    roots = [game.directory for game in steam_games()]
    if os.name != "nt":
        return tuple(roots)
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    program_files = os.environ.get("PROGRAMFILES")
    if program_files_x86:
        base = Path(program_files_x86)
        roots.extend(
            (
                base / "Steam" / "steamapps" / "common" / "Gabriel Knight 3",
                base / "GOG Galaxy" / "Games" / "Gabriel Knight 3",
            )
        )
    if program_files:
        base = Path(program_files)
        roots.extend(
            (
                base / "Steam" / "steamapps" / "common" / "Gabriel Knight 3",
                base / "GOG Galaxy" / "Games" / "Gabriel Knight 3",
            )
        )
    system_drive = os.environ.get("SYSTEMDRIVE", "C:")
    roots.append(Path(system_drive + "\\") / "GOG Games" / "Gabriel Knight 3")
    return tuple(roots)
