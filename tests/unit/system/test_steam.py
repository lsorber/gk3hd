"""Portable Steam discovery, including external libraries and nested game paths."""

from pathlib import Path

import pytest

from gk3hd.system import steam
from gk3hd.system.discovery import discover_game
from gk3hd.system.steam import read_vdf


def test_read_vdf_handles_nested_objects_comments_and_windows_paths(tmp_path: Path) -> None:
    source = tmp_path / "config.vdf"
    source.write_text(r"""// comment
    "libraryfolders" { "0" { "path" "D:\\Steam Library" "apps" { "497360" "123" } } }
    """)
    assert read_vdf(source) == {
        "libraryfolders": {"0": {"path": r"D:\Steam Library", "apps": {"497360": "123"}}}
    }


@pytest.mark.parametrize("text", ['"x" { "a"', '"x" { "a" "b"', "}", '"x" }'])
def test_read_vdf_rejects_broken_objects(tmp_path: Path, text: str) -> None:
    source = tmp_path / "config.vdf"
    source.write_text(text)
    with pytest.raises(ValueError, match="Steam configuration"):
        read_vdf(source)


def test_manifest_discovers_sd_library_and_lowercase_game_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = tmp_path / "Steam"
    library = tmp_path / "SD Card"
    (client / "steamapps").mkdir(parents=True)
    (library / "steamapps").mkdir(parents=True)
    (client / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders" { "1" { "path" "' + library.as_posix() + '" } }',
    )
    (library / "steamapps/appmanifest_497360.acf").write_text(
        '"AppState" { "installdir" "Localized Game" }',
    )
    game = library / "steamapps/common/Localized Game/gk3"
    game.mkdir(parents=True)
    (game / "GK3.exe").write_bytes(b"fixture")
    monkeypatch.setattr(steam, "steam_roots", lambda: (client,))
    target = discover_game()
    assert target.game_dir == game
    assert steam.steam_games()[0].compatdata == library / "steamapps/compatdata/497360"


def test_explicit_discovery_does_not_require_a_working_steam_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "GK3.exe").write_bytes(b"fixture")
    monkeypatch.setattr(steam, "steam_roots", lambda: ())
    assert discover_game(game_dir=tmp_path).game_dir == tmp_path


@pytest.mark.parametrize("name", ["", ".", "..", "../other", "a\\b", "D:/other"])
def test_installed_app_rejects_unsafe_directory_names(tmp_path: Path, name: str) -> None:
    (tmp_path / "steamapps").mkdir()
    (tmp_path / "steamapps/appmanifest_497360.acf").write_text(
        '"AppState" { "installdir" "' + name + '" }'
    )
    with pytest.raises(ValueError, match="installation directory"):
        steam.installed_app(tmp_path, "497360")


def test_duplicate_prefixes_are_not_silently_chosen(tmp_path: Path) -> None:
    other = tmp_path / "SD"
    (tmp_path / "steamapps").mkdir()
    (tmp_path / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders" { "1" { "path" "' + other.as_posix() + '" } }'
    )
    for library in (tmp_path, other):
        prefix = library / "steamapps/compatdata/497360/pfx"
        prefix.mkdir(parents=True)
        (prefix / "system.reg").touch()
    game = steam.SteamGame(tmp_path, other, other / "steamapps/common/GK3")
    with pytest.raises(ValueError, match="multiple GK3 Proton prefixes"):
        _ = game.compatdata
