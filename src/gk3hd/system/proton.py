"""Target-specific Proton discovery and quiet Windows-command execution."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gk3hd.system.appinfo import read_appinfo
from gk3hd.system.steam import (
    GK3_APP_ID,
    SteamGame,
    VdfValue,
    installed_app,
    read_vdf,
    steam_games,
    steam_libraries,
    vdf_value,
)

_PROC_COMM_LIMIT = 15
_STEAM_PLAY_APP_ID = 891390


class ProtonError(RuntimeError):
    """Report missing or ambiguous Steam compatibility state."""


@dataclass(frozen=True, slots=True)
class ProtonContext:
    """Run commands with the same client, library, prefix, and Proton as GK3."""

    game: SteamGame
    executable: Path
    runtime: Path | None = None

    def run(self, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Run a Windows utility without leaking Wine diagnostics into the CLI."""
        environment = dict(os.environ)
        prefix = self.game.compatdata
        environment.update(
            {
                "STEAM_COMPAT_DATA_PATH": str(prefix),
                "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(self.game.root),
                "STEAM_COMPAT_INSTALL_PATH": str(self.game.directory),
                "STEAM_COMPAT_APP_ID": GK3_APP_ID,
                "STEAM_COMPAT_LIBRARY_PATHS": ":".join(
                    str(path) for path in steam_libraries(self.game.root)
                ),
                "SteamAppId": GK3_APP_ID,
                "SteamGameId": GK3_APP_ID,
                "WINEDEBUG": "-all",
                # PROTON_LOG would redirect reg.exe's result away from our pipe.
                "PROTON_LOG": "0",
                "LC_ALL": "C.UTF-8",
            }
        )
        # Proton's 'run' initializes a new prefix; 'runinprefix' preserves an
        # existing one. Never invoke a system Wine binary against Steam state.
        verb = "runinprefix" if (prefix / "pfx/system.reg").is_file() else "run"
        command = [str(self.executable), verb, *arguments]
        tool_paths = [self.executable.parent]
        if self.runtime is not None:
            command = [str(self.runtime), "--verb=run", "--", *command]
            tool_paths.append(self.runtime.parent)
        environment["STEAM_COMPAT_TOOL_PATHS"] = ":".join(str(path) for path in tool_paths)
        prefix.mkdir(parents=True, exist_ok=True)
        try:
            return subprocess.run(  # noqa: S603 - resolved installed Proton, argument vector only.
                command,
                env=environment,
                cwd=self.game.directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            msg = f"could not run GK3's Proton configuration utility: {exc}"
            raise ProtonError(msg) from exc


def discover_proton(exe: Path) -> ProtonContext:
    """Resolve one app's selected tool; never guess a prefix from a username."""
    target = exe.resolve()
    games = [game for game in steam_games() if target.is_relative_to(game.directory.resolve())]
    if len(games) != 1:
        msg = "could not identify a unique Steam library/prefix for this GK3 installation"
        raise ProtonError(msg)
    game = games[0]
    if override := os.environ.get("GK3HD_PROTON"):
        tool = Path(override).expanduser().resolve()
        executable = tool / "proton" if tool.is_dir() else tool
    else:
        executable = _selected_proton(game)
    if not executable.is_file():
        msg = "GK3's selected Proton is not installed; install its compatibility tool in Steam"
        raise ProtonError(msg)
    return ProtonContext(game, executable, _required_runtime(game, executable))


def _selected_proton(game: SteamGame) -> Path:
    config = game.root / "config/config.vdf"
    settings = vdf_value(
        read_vdf(config) if config.is_file() else {},
        "InstallConfigStore",
        "Software",
        "Valve",
        "Steam",
    )
    custom = _compatibility_tools(game)
    explicit = vdf_value(settings, "CompatToolMapping", GK3_APP_ID, "name")
    # Custom tools do not need Steam's binary cache (which may be missing offline).
    if isinstance(explicit, str) and explicit in custom:
        return _unique_tool(explicit, custom[explicit])
    cache = game.root / "appcache/appinfo.vdf"
    metadata = (
        read_appinfo(cache, frozenset({int(GK3_APP_ID), _STEAM_PLAY_APP_ID}))
        if cache.is_file()
        else {}
    )
    catalog = vdf_value(metadata.get(_STEAM_PLAY_APP_ID, {}), "appinfo", "extended")
    recommended = (
        vdf_value(
            metadata.get(int(GK3_APP_ID), {}),
            "appinfo",
            "common",
            "steam_deck_compatibility",
            "configuration",
            "recommended_runtime",
        )
        if _is_steam_deck()
        else {}
    )
    names = (
        explicit,
        recommended,
        vdf_value(catalog, "app_mappings", GK3_APP_ID, "tool"),
        vdf_value(settings, "CompatToolMapping", "0", "name"),
        vdf_value(settings, "ToolMapping", GK3_APP_ID, "name"),
        vdf_value(settings, "ToolMapping", "0", "name"),
    )
    for name in names:
        if isinstance(name, str) and name:
            matches = custom[name] if name in custom else _official_tools(game, catalog, name)
            return _unique_tool(name, matches)
    if previous := _prefix_tool(game):
        return previous
    # Steam's aliases identify current official defaults without embedding a
    # Proton version. Never fall back when an explicit selection is unavailable.
    for name in ("proton-experimental", "proton-stable"):
        if matches := _official_tools(game, catalog, name):
            return _unique_tool(name, matches)
    msg = "no installed Proton was found for GK3; install/select its compatibility tool in Steam"
    raise ProtonError(msg)


def _prefix_tool(game: SteamGame) -> Path | None:
    # Existing prefix metadata records the actual runtime even when Steam's
    # automatic per-game tool mapping is not in the user configuration.
    info = game.compatdata / "config_info"
    if info.is_file():
        for line in info.read_text(encoding="utf-8").splitlines()[1:4]:
            path = Path(line)
            if not path.is_absolute():
                continue
            for candidate in (path, *path.parents):
                if (candidate / "proton").is_file():
                    return candidate / "proton"
    return None


def _is_steam_deck() -> bool:
    if os.environ.get("SteamDeck") == "1":  # noqa: SIM112 - Steam's case-sensitive variable.
        return True
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return False
    return release.get("ID") == "steamos" and release.get("VARIANT_ID") == "steamdeck"


def _unique_tool(name: str, matches: list[Path]) -> Path:
    if len(matches) == 1:
        return matches[0]
    msg = f"Steam selected {name!r}, but its installed Proton tool could not be uniquely resolved"
    raise ProtonError(msg)


def _official_tools(game: SteamGame, catalog: VdfValue, name: str) -> list[Path]:
    tools = vdf_value(catalog, "compat_tools")
    matches = []
    if isinstance(tools, dict):
        for identity, entry in tools.items():
            aliases = vdf_value(entry, "aliases")
            names = [identity, *aliases.split(",")] if isinstance(aliases, str) else [identity]
            app_id = vdf_value(entry, "appid")
            if name in names and isinstance(app_id, str):
                for library in steam_libraries(game.root):
                    directory = installed_app(library, app_id)
                    if directory is not None and (directory / "proton").is_file():
                        matches.append((directory / "proton").resolve())
    return list(dict.fromkeys(matches))


def _required_runtime(game: SteamGame, executable: Path) -> Path | None:
    manifest = executable.parent / "toolmanifest.vdf"
    if not manifest.is_file():
        return None  # Older/self-contained custom Proton tools have no container.
    required = vdf_value(read_vdf(manifest), "manifest", "require_tool_appid")
    if not required or required == "0":
        return None
    if not isinstance(required, str):
        msg = "invalid required Steam runtime app ID in Proton's toolmanifest.vdf"
        raise ProtonError(msg)
    matches = []
    for library in steam_libraries(game.root):
        directory = installed_app(library, required)
        if directory is not None and (directory / "_v2-entry-point").is_file():
            matches.append((directory / "_v2-entry-point").resolve())
    if len(matches) != 1:
        msg = (
            f"Proton requires Steam Linux Runtime app {required}; "
            "install it in Steam (a unique installed runtime is required)"
        )
        raise ProtonError(msg)
    return matches[0]


def _compatibility_tools(game: SteamGame) -> dict[str, list[Path]]:
    tools: dict[str, list[Path]] = {}
    parents = [game.root / "compatibilitytools.d"]
    parents.extend(library / "steamapps/common" for library in steam_libraries(game.root))
    for parent in parents:
        if not parent.is_dir():
            continue
        for directory in sorted(parent.iterdir()):
            manifest = directory / "compatibilitytool.vdf"
            if not manifest.is_file() or not (directory / "proton").is_file():
                continue
            entries = vdf_value(read_vdf(manifest), "compatibilitytools", "compat_tools")
            if isinstance(entries, dict):
                for name in entries:
                    executable = (directory / "proton").resolve()
                    if executable not in tools.setdefault(name, []):
                        tools[name].append(executable)
    return tools


def is_gk3_running(proc: Path = Path("/proc")) -> bool:
    """Detect Wine-hosted GK3 processes without depending on pgrep or ps."""
    if not proc.is_dir():
        msg = "cannot inspect running games: procfs is unavailable"
        raise ProtonError(msg)
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            name = (directory / "comm").read_text().strip().casefold()
        except FileNotFoundError:
            continue
        except PermissionError:
            # Other users' processes are outside this per-user Steam prefix.
            continue
        if name.startswith("gk3") and (name.endswith(".exe") or len(name) == _PROC_COMM_LIMIT):
            return True
    return False
