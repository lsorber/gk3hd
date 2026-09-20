"""Tests for visual save-game discovery and selection."""

from pathlib import Path

import pytest

from tests.visual.support.saves import (
    SaveGame,
    SaveGameError,
    catalog_save_games,
    find_save_directory,
    prefer_native_save_slots,
    select_save_games,
)


def _save(index: int) -> SaveGame:
    return SaveGame(
        path=Path(f"save{index}.gk3"),
        description=f"Save {index}",
        room=f"RM{index}",
        timeblock="DAY1_10AM",
    )


def _write_save(path: Path, *fields: str) -> None:
    data = bytearray(0xF8)
    data[:8] = b"GK3!Save"
    for field in fields:
        encoded = field.encode("ascii")
        data.extend(len(encoded).to_bytes(4, "little"))
        data.extend(encoded)
        data.append(0)
    path.write_bytes(data)


def test_find_save_directory_is_case_insensitive(tmp_path: Path) -> None:
    expected = tmp_path / "SAVE GAMES"
    expected.mkdir()

    assert find_save_directory(tmp_path) == expected


def test_find_save_directory_accepts_override(tmp_path: Path) -> None:
    expected = tmp_path / "my saves"
    expected.mkdir()

    assert find_save_directory(tmp_path, expected) == expected


def test_find_save_directory_falls_back_to_populated_game_root(tmp_path: Path) -> None:
    (tmp_path / "Save Games").mkdir()
    _write_save(tmp_path / "save0001.gk3", "One", "RM01", "DAY1_10AM")

    assert find_save_directory(tmp_path) == tmp_path


def test_catalog_uses_natural_order_and_reads_metadata(tmp_path: Path) -> None:
    _write_save(tmp_path / "save10.gk3", "Ten", "RM10", "DAY2_2PM")
    _write_save(tmp_path / "save2.GK3", "Two", "RM02", "DAY1_10AM")

    saves = catalog_save_games(tmp_path)

    assert [save.path.name for save in saves] == ["save2.GK3", "save10.gk3"]
    assert saves[0].description == "Two"
    assert saves[0].room == "RM02"
    assert saves[0].timeblock == "DAY1_10AM"


def test_all_saves_include_archives_without_colliding_or_machine_specific_names(
    tmp_path: Path,
) -> None:
    catalogs = []
    for root_name in ("first", "relocated"):
        root = tmp_path / root_name
        for relative, description in (
            ("save0001.gk3", "Current"),
            (".hidden/save0001.gk3", "Hidden"),
            ("archive/older/save0001.gk3", "Older"),
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_save(path, description, "te4", "309p")
        assert len(catalog_save_games(root)) == 1
        saves = catalog_save_games(root, recursive=True)
        assert len(saves) == len({save.output_stem for save in saves}) == 3
        assert all(save.path.is_file() for save in saves)
        assert next(save for save in saves if save.path.parent == root).output_stem == "save0001"
        assert {save.description for save in saves} == {
            "Current",
            ".hidden: Hidden",
            "archive/older: Older",
        }
        catalogs.append([(save.output_stem, save.description) for save in saves])
    assert catalogs[0] == catalogs[1]


def test_default_selection_spans_the_catalog() -> None:
    saves = tuple(_save(index) for index in range(21))

    selected = select_save_games(saves)

    assert [save.path.stem for save in selected] == [
        "save0",
        "save2",
        "save4",
        "save7",
        "save9",
        "save11",
        "save13",
        "save16",
        "save18",
        "save20",
    ]


def test_explicit_count_and_single_save_selection() -> None:
    saves = tuple(_save(index) for index in range(21))

    assert [save.path.stem for save in select_save_games(saves, count=3)] == [
        "save0",
        "save10",
        "save20",
    ]
    assert select_save_games(saves, count=1) == (saves[10],)


def test_all_selects_every_save() -> None:
    saves = tuple(_save(index) for index in range(21))

    assert select_save_games(saves, all_saves=True) == saves


def test_native_slots_exclude_quick_saves_and_developer_fixtures() -> None:
    native = (_save(1), _save(2))
    saves = (
        SaveGame(Path("fastsave.gk3"), "Quick", "RM", "DAY1"),
        SaveGame(Path("gk3hd-museum.gk3"), "Fixture", "RM", "DAY1"),
        SaveGame(Path("save0001.gk3"), "One", "RM", "DAY1"),
        SaveGame(Path("save0002.gk3"), "Two", "RM", "DAY1"),
    )

    selected = prefer_native_save_slots(saves)

    assert [save.path.name for save in selected] == ["save0001.gk3", "save0002.gk3"]
    assert prefer_native_save_slots(native) == native


@pytest.mark.parametrize("count", [0, -1])
def test_count_must_be_positive(count: int) -> None:
    with pytest.raises(SaveGameError, match="at least 1"):
        select_save_games((_save(1),), count=count)


def test_count_and_all_are_mutually_exclusive() -> None:
    with pytest.raises(SaveGameError, match="cannot be used together"):
        select_save_games((_save(1),), count=1, all_saves=True)
