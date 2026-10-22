from pathlib import Path

import pytest

from gk3hd.videos.catalog import find_movies, movie_format, replacement_name


def test_inventory_reads_headers_and_matches_case_insensitive_selections(tmp_path: Path) -> None:
    bink = tmp_path / "Intro.BIK"
    bink.write_bytes(b"BIKf" + bytes(28))
    avi = tmp_path / "Sierra.avi"
    avi.write_bytes(b"RIFF" + bytes(4) + b"AVI ")
    unknown = tmp_path / "unused.bik"
    unknown.write_bytes(b"not video data")
    assert movie_format(bink) == "Bink"
    assert movie_format(avi) == "AVI"
    assert movie_format(unknown) is None
    assert find_movies(tmp_path) == (bink, avi)
    assert find_movies(tmp_path, ["sierra.*"]) == (avi,)
    with pytest.raises(ValueError, match="not recognizable"):
        find_movies(tmp_path, ["unused.bik"])


def test_missing_selection_is_not_silently_ignored(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no original movie matches"):
        find_movies(tmp_path, ["missing.bik"])


@pytest.mark.parametrize("intro_name", ["intro.bik", "INTRO.AVI"])
def test_intro_is_processed_before_alphabetically_earlier_movies(
    tmp_path: Path, intro_name: str
) -> None:
    for name in ("202aend.bik", intro_name, "Sierra.avi"):
        (tmp_path / name).write_bytes(b"BIKf" + bytes(28))
    assert [path.name for path in find_movies(tmp_path)] == [
        intro_name,
        "202aend.bik",
        "Sierra.avi",
    ]
    assert [path.name for path in find_movies(tmp_path, ["202*"])] == ["202aend.bik"]


def test_replacements_have_distinct_case_stable_short_asset_names() -> None:
    assert replacement_name("Sierra.avi") == "GK3HD-SIERRA.AVI"
    assert replacement_name("INTRO.BIK") == replacement_name("intro.avi") == "GK3HD-INTRO.AVI"
    assert replacement_name("Parch1Geo.avi") == "GK3HD-PARCH1GEO.AVI"
    assert len(replacement_name("x" * 20 + ".avi")) == 30


@pytest.mark.parametrize("name", ["", "../intro.bik", "C:\\intro.bik", "x" * 21 + ".avi", "é.bik"])
def test_unsupported_asset_names_are_rejected_before_installation(name: str) -> None:
    with pytest.raises(ValueError, match=r"filename|asset name"):
        replacement_name(name)
