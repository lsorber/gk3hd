"""Read Steam libraries without depending on a client API or a fixed username."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

GK3_APP_ID = "497360"
type VdfValue = str | dict[str, VdfValue]
_TOKENS = re.compile(r'//[^\n]*|"((?:\\.|[^"\\])*)"|([{}])|([^\s{}"]+)')


def read_vdf(path: Path) -> dict[str, VdfValue]:
    """Read Steam's text KeyValues format, preserving nested objects."""
    tokens = []
    for match in _TOKENS.finditer(path.read_text(encoding="utf-8-sig")):
        if match.group().startswith("//"):
            continue
        quoted, brace, bare = match.groups()
        value = re.sub(r'\\([\\"])', r"\1", quoted) if quoted is not None else brace or bare
        tokens.append(value)
    root: dict[str, VdfValue] = {}
    stack = [root]
    index = 0
    while index < len(tokens):
        key = tokens[index]
        index += 1
        if key == "}":
            if len(stack) == 1:
                msg = f"unbalanced Steam configuration: {path.name}"
                raise ValueError(msg)
            stack.pop()
            continue
        if index == len(tokens) or key == "{":
            msg = f"incomplete Steam configuration: {path.name}"
            raise ValueError(msg)
        value = tokens[index]
        index += 1
        if value == "{":
            child: dict[str, VdfValue] = {}
            stack[-1][key] = child
            stack.append(child)
        elif value == "}":
            msg = f"missing Steam configuration value: {path.name}"
            raise ValueError(msg)
        else:
            stack[-1][key] = value
    if len(stack) != 1:
        msg = f"unclosed Steam configuration: {path.name}"
        raise ValueError(msg)
    return root


def vdf_value(value: VdfValue, *keys: str) -> VdfValue:
    """Look up metadata keys case-insensitively, preserving strings and paths."""
    for key in keys:
        if not isinstance(value, dict):
            return {}
        value = next(
            (item for name, item in value.items() if name.casefold() == key.casefold()), {}
        )
    return value


def steam_roots() -> tuple[Path, ...]:
    """Locate normal, Flatpak, and explicitly configured Steam clients."""
    roots = []
    if explicit := os.environ.get("STEAM_DIR"):
        roots.append(Path(explicit).expanduser())
    if os.name == "nt":
        roots.extend(
            Path(value) / "Steam"
            for name in ("PROGRAMFILES(X86)", "PROGRAMFILES")
            if (value := os.environ.get(name))
        )
    else:
        user = Path.home()
        data = Path(os.environ.get("XDG_DATA_HOME", str(user / ".local/share")))
        roots.extend(
            (
                data / "Steam",
                user / ".steam/steam",
                user / ".steam/root",
                user / ".var/app/com.valvesoftware.Steam/data/Steam",
            )
        )
    return tuple(dict.fromkeys(path.resolve() for path in roots if path.is_dir()))


def steam_libraries(root: Path) -> tuple[Path, ...]:
    """Include external/SD-card libraries from the client's library catalog."""
    paths = [root.resolve()]
    catalog = root / "steamapps/libraryfolders.vdf"
    if catalog.is_file():
        values = read_vdf(catalog).get("libraryfolders", {})
        if isinstance(values, dict):
            for key, value in values.items():
                if not key.isdigit():
                    continue
                location = value.get("path") if isinstance(value, dict) else value
                if isinstance(location, str):
                    paths.append(Path(location).expanduser().resolve())
    return tuple(dict.fromkeys(paths))


@dataclass(frozen=True, slots=True)
class SteamGame:
    """The Steam client, content library, and app-specific compatibility state."""

    root: Path
    library: Path
    directory: Path

    @property
    def compatdata(self) -> Path:
        """Reuse an existing prefix, including one left behind after a game move."""
        candidates = tuple(
            library / "steamapps/compatdata" / GK3_APP_ID
            for library in steam_libraries(self.root)
            if (library / "steamapps/compatdata" / GK3_APP_ID / "pfx/system.reg").is_file()
        )
        if len(candidates) > 1:
            msg = "multiple GK3 Proton prefixes exist; resolve the duplicate Steam prefixes first"
            raise ValueError(msg)
        return candidates[0] if candidates else self.library / "steamapps/compatdata" / GK3_APP_ID


def installed_app(library: Path, app_id: str) -> Path | None:
    """Resolve installed content by app ID without guessing localized names."""
    if not app_id.isascii() or not app_id.isdecimal():
        msg = "invalid Steam app ID"
        raise ValueError(msg)
    manifest = library / "steamapps" / f"appmanifest_{app_id}.acf"
    if not manifest.is_file():
        return None
    name = vdf_value(read_vdf(manifest), "appstate", "installdir")
    if not isinstance(name, str) or name in {"", ".", ".."} or re.search(r"[\\/:]", name):
        msg = f"invalid Steam installation directory in {manifest.name}"
        raise ValueError(msg)
    return library / "steamapps/common" / name


def steam_games() -> tuple[SteamGame, ...]:
    """Find GK3 by its app manifest, not a localized display name."""
    games = []
    for root in steam_roots():
        games.extend(
            SteamGame(root, library, directory)
            for library in steam_libraries(root)
            if (directory := installed_app(library, GK3_APP_ID)) is not None
        )
    return tuple(games)
