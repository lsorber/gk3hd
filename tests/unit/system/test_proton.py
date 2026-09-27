"""Steam-selected Proton, exact runtime dependencies and quiet prefix commands."""

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from gk3hd.system import proton
from gk3hd.system.proton import ProtonContext, ProtonError, discover_proton
from gk3hd.system.steam import SteamGame, VdfValue
from tests.unit.system.appinfo_fixture import cache_bytes


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SteamGame:
    root = tmp_path / "Steam"
    library = tmp_path / "SD Card"
    (root / "config").mkdir(parents=True)
    (root / "appcache").mkdir()
    (root / "steamapps").mkdir()
    (library / "steamapps/common/GK3").mkdir(parents=True)
    (root / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders" { "1" { "path" "' + library.as_posix() + '" } }'
    )
    result = SteamGame(root, library, library / "steamapps/common/GK3")
    monkeypatch.setattr(proton, "steam_games", lambda: (result,))
    monkeypatch.setattr(proton, "_is_steam_deck", lambda: False)
    monkeypatch.delenv("GK3HD_PROTON", raising=False)
    return result


def install_app(library: Path, app_id: str, name: str, executable: str = "proton") -> Path:
    directory = library / "steamapps/common" / name
    directory.mkdir(parents=True)
    (directory / executable).touch()
    (library / "steamapps" / f"appmanifest_{app_id}.acf").write_text(
        '"AppState" { "installdir" "' + name + '" }'
    )
    return directory / executable


def metadata(game: SteamGame, *, recommended: str = "", mapping: str = "") -> None:
    play: dict[str, VdfValue] = {
        "compat_tools": {
            "proton_10": {"appid": "100", "aliases": "proton-stable"},
            "proton-experimental": {"appid": "200"},
        },
        "app_mappings": {"497360": {"tool": mapping}},
    }
    game_info: dict[str, VdfValue] = {
        "common": {
            "steam_deck_compatibility": {"configuration": {"recommended_runtime": recommended}}
        }
    }
    (game.root / "appcache/appinfo.vdf").write_bytes(
        cache_bytes({891390: {"appinfo": {"extended": play}}, 497360: {"appinfo": game_info}})
    )


def settings(game: SteamGame, *, explicit: str = "", global_name: str = "") -> None:
    (game.root / "config/config.vdf").write_text(
        '"installconfigstore" { "software" { "valve" { "steam" { "CompatToolMapping" {'
        '"497360" { "name" "' + explicit + '" } "0" { "name" "' + global_name + '" } } } } } }'
    )


def test_official_selection_and_exact_runtime_across_libraries(game: SteamGame) -> None:
    executable = install_app(game.library, "100", "A localized Proton folder")
    runtime = install_app(game.root, "1628350", "A localized runtime", "_v2-entry-point")
    (executable.parent / "toolmanifest.vdf").write_text(
        '"manifest" { "require_tool_appid" "1628350" }'
    )
    metadata(game)
    settings(game, explicit="proton-stable")
    context = discover_proton(game.directory / "GK3.exe")
    assert context.executable == executable
    assert context.runtime == runtime
    assert not game.compatdata.exists()  # Discovery does not initialize Wine.


@pytest.mark.parametrize(
    ("explicit", "recommended", "mapping", "global_name", "expected"),
    [
        ("proton-experimental", "proton-stable", "proton-stable", "proton-stable", "200"),
        ("", "proton-stable", "proton-experimental", "proton-experimental", "100"),
        ("", "", "proton-stable", "proton-experimental", "100"),
        ("", "", "", "proton-stable", "100"),
        ("", "", "", "", "200"),
    ],
)
def test_selection_precedence(  # noqa: PLR0913, PLR0917 - selection matrix columns.
    game: SteamGame,
    monkeypatch: pytest.MonkeyPatch,
    explicit: str,
    recommended: str,
    mapping: str,
    global_name: str,
    expected: str,
) -> None:
    installed = {app_id: install_app(game.library, app_id, app_id) for app_id in ("100", "200")}
    monkeypatch.setattr(proton, "_is_steam_deck", lambda: True)
    metadata(game, recommended=recommended, mapping=mapping)
    settings(game, explicit=explicit, global_name=global_name)
    assert discover_proton(game.directory / "GK3.exe").executable == installed[expected]


def test_missing_explicit_tool_never_falls_back(game: SteamGame) -> None:
    install_app(game.library, "200", "Experimental")
    metadata(game)
    settings(game, explicit="proton-stable")
    with pytest.raises(ProtonError, match="proton-stable"):
        discover_proton(game.directory / "GK3.exe")


def test_steam_selection_can_be_inspected_despite_cli_override(
    game: SteamGame, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = install_app(game.library, "200", "Proton Experimental")
    override = game.root / "compatibilitytools.d/Private Test/proton"
    override.parent.mkdir(parents=True)
    override.touch()
    metadata(game)
    settings(game, explicit="proton-experimental")
    monkeypatch.setenv("GK3HD_PROTON", str(override))

    assert discover_proton(game.directory / "GK3.exe").executable == override
    assert discover_proton(game.directory / "GK3.exe", use_override=False).executable == selected


def test_missing_required_runtime_is_actionable_before_mutation(game: SteamGame) -> None:
    executable = install_app(game.library, "100", "Proton")
    (executable.parent / "toolmanifest.vdf").write_text(
        '"manifest" { "require_tool_appid" "4183110" }'
    )
    metadata(game)
    with pytest.raises(ProtonError, match="4183110"):
        discover_proton(game.directory / "GK3.exe")
    assert not game.compatdata.exists()


def test_custom_selection_works_without_official_cache(game: SteamGame) -> None:
    executable = game.root / "compatibilitytools.d/GE Custom/proton"
    executable.parent.mkdir(parents=True)
    executable.touch()
    (executable.parent / "compatibilitytool.vdf").write_text(
        '"CompatibilityTools" { "Compat_Tools" { "ge-custom" { "install_path" "." } } }'
    )
    settings(game, explicit="ge-custom")
    (game.root / "appcache/appinfo.vdf").write_bytes(b"broken cache")
    assert discover_proton(game.directory / "GK3.exe").executable == executable


def test_existing_prefix_runtime_is_reused_without_mapping(game: SteamGame) -> None:
    executable = install_app(game.root, "100", "Proton")
    prefix = game.root / "steamapps/compatdata/497360"
    (prefix / "pfx").mkdir(parents=True)
    (prefix / "pfx/system.reg").touch()
    (prefix / "config_info").write_text(
        "version\n" + (executable.parent / "files/share").as_posix()
    )
    context = discover_proton(game.directory / "GK3.exe")
    assert context.executable == executable
    assert context.game.compatdata == prefix


@pytest.mark.parametrize("existing", [False, True])
def test_run_uses_runtime_and_quiet_target_environment(
    game: SteamGame,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    executable = install_app(game.library, "100", "Proton")
    runtime = install_app(game.root, "300", "Runtime", "_v2-entry-point")
    if existing:
        (game.compatdata / "pfx").mkdir(parents=True)
        (game.compatdata / "pfx/system.reg").touch()
    monkeypatch.setenv("PROTON_LOG", "1")

    def complete(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "getcompatpath" in command:
            (game.compatdata / "pfx").mkdir(parents=True, exist_ok=True)
            (game.compatdata / "pfx/system.reg").touch()
            return subprocess.CompletedProcess(command, 0, "Z:\\game", "")
        return subprocess.CompletedProcess(command, 0, "registry output", "")

    runner = Mock(side_effect=complete)
    monkeypatch.setattr(proton.subprocess, "run", runner)
    result = ProtonContext(game, executable, runtime).run(("reg.exe", "query", r"HKCU\Space Here"))
    assert result.stdout == "registry output"
    assert runner.call_count == 2
    assert runner.call_args_list[0].args[0] == [
        str(runtime),
        "--verb=run",
        "--",
        str(executable),
        "getcompatpath",
        str(game.directory),
    ]
    assert runner.call_args.args[0] == [
        str(runtime),
        "--verb=run",
        "--",
        str(executable),
        "runinprefix",
        "reg.exe",
        "query",
        r"HKCU\Space Here",
    ]
    options = runner.call_args.kwargs
    assert options["capture_output"]
    assert options["timeout"] == 60
    assert options["cwd"] == game.directory
    assert options["env"]["STEAM_COMPAT_DATA_PATH"] == str(game.compatdata)
    assert options["env"]["STEAM_COMPAT_TOOL_PATHS"] == f"{executable.parent}:{runtime.parent}"
    assert options["env"]["PROTON_LOG"] == "0"
    assert options["env"]["WINEDEBUG"] == "-all"
    assert os.environ["PROTON_LOG"] == "1"


def test_existing_prefix_migrates_before_changes_and_only_once(
    game: SteamGame, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older Proton must not erase installed settings on the next game launch."""
    registry = game.compatdata / "pfx/system.reg"
    registry.parent.mkdir(parents=True)
    registry.touch()
    executable = install_app(game.library, "100", "Proton")
    server = executable.parent / "files/bin/wineserver"
    server.parent.mkdir(parents=True)
    server.touch()
    state = {"migrated": False, "override": False}

    def complete(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "getcompatpath" in command:
            state.update(migrated=True, override=False)
        else:
            assert state["migrated"]
            if "add" in command:
                state["override"] = True
            else:
                assert state["override"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(proton.subprocess, "run", complete)
    context = ProtonContext(game, executable)
    context.run(("reg.exe", "add", "HKCU", "/v", "ddraw"))
    context.run(("reg.exe", "query", "HKCU", "/v", "ddraw"))
    assert state["override"]


def test_registry_write_waits_for_persistence_inside_runtime(
    game: SteamGame, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = install_app(game.library, "100", "Proton")
    server = executable.parent / "files/bin/wineserver"
    server.parent.mkdir(parents=True)
    server.touch()
    runtime = install_app(game.root, "300", "Runtime", "_v2-entry-point")

    def complete(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "getcompatpath" in command:
            registry = game.compatdata / "pfx/system.reg"
            registry.parent.mkdir(parents=True)
            registry.touch()
        return subprocess.CompletedProcess(command, 0, "", "")

    runner = Mock(side_effect=complete)
    monkeypatch.setattr(proton.subprocess, "run", runner)
    ProtonContext(game, executable, runtime).run(("reg.exe", "add", "HKCU", "/v", "ddraw"))
    command = runner.call_args.args[0]
    assert command[:5] == [str(runtime), "--verb=run", "--", "sh", "-c"]
    assert '"$GK3HD_WINESERVER" -w' in command[5]
    assert runner.call_args.kwargs["env"]["GK3HD_WINESERVER"] == str(server)


@pytest.mark.parametrize(("exit_code", "prefix_created"), [(1, False), (1, True), (0, False)])
def test_failed_prefix_bootstrap_does_not_run_registry_command(
    game: SteamGame,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    prefix_created: bool,
) -> None:
    def bootstrap(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if prefix_created:
            (game.compatdata / "pfx").mkdir(parents=True)
            (game.compatdata / "pfx/system.reg").touch()
        return subprocess.CompletedProcess(command, exit_code, "", "failed")

    runner = Mock(side_effect=bootstrap)
    monkeypatch.setattr(proton.subprocess, "run", runner)
    with pytest.raises(ProtonError, match="initialize"):
        ProtonContext(game, Path("proton")).run(("reg.exe", "query", "HKCU"))
    assert runner.call_count == 1


@pytest.mark.parametrize("failure", [OSError("missing"), subprocess.TimeoutExpired("proton", 60)])
def test_run_failures_have_context(
    game: SteamGame,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    monkeypatch.setattr(proton.subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(ProtonError, match="configuration utility"):
        ProtonContext(game, Path("proton")).run(("reg.exe",))
