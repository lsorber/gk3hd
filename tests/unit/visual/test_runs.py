"""Both capture suites share dated folders and a portable, cumulative index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.visual.support.runs import comparison_run, merge_captures
from tests.visual.support.saves import SaveGame


def test_special_joins_latest_matching_normal_run(tmp_path: Path) -> None:
    parent = tmp_path
    for name, resolution in (
        ("20260901-120000", "3840x2160"),
        ("20260902-120000", "3840x2160"),
        ("20260903-120000", "1920x1080"),
        ("special-20260904-120000", "3840x2160"),
    ):
        (parent / name / "reference-1024x768").mkdir(parents=True)
        (parent / name / f"current-{resolution}").mkdir()

    assert comparison_run(tmp_path, append_resolution=(3840, 2160)) == (parent / "20260902-120000")
    explicit = parent / "20260901-120000"
    assert comparison_run(tmp_path, resume=explicit) == explicit


def test_special_can_start_a_normal_dated_run(tmp_path: Path) -> None:
    run = comparison_run(tmp_path, append_resolution=(3840, 2160))
    assert run.parent == tmp_path
    assert not run.name.startswith("special-")
    with pytest.raises(ValueError, match="does not exist"):
        comparison_run(tmp_path, resume=run)


def test_index_merges_suites_and_keeps_relative_paths(tmp_path: Path) -> None:
    reference = tmp_path / "reference-1024x768"
    current = tmp_path / "current-3840x2160"
    reference.mkdir()
    current.mkdir()
    output = tmp_path / "comparisons"
    output.mkdir()
    save = SaveGame(Path("save0009.gk3"), "Mosely Clothes", "rc1", "102p")
    special = SaveGame(Path("confirm-quit.gk3"), "Quit confirmation", "confirm", "special")
    first = (save, reference / "save0009.png", current / "save0009.png")
    second = (special, reference / "confirm-quit.png", current / "confirm-quit.png")
    merge_captures((first,), output=output)

    merged = merge_captures((second,), output=output)

    assert merged == (second, first)
    data = json.loads((output / "captures.json").read_text(encoding="utf-8"))
    assert data[1]["description"] == "Mosely Clothes"
    assert data[1]["reference"] == "reference-1024x768/save0009.png"
    assert merge_captures((first,), output=output) == merged


def test_legacy_run_retains_unindexed_paired_captures(tmp_path: Path) -> None:
    reference = tmp_path / "reference-1024x768"
    current = tmp_path / "current-3840x2160"
    reference.mkdir()
    current.mkdir()
    for folder in (reference, current):
        (folder / "save0001.png").touch()
    (reference / "unpaired.png").touch()
    output = tmp_path / "comparisons"
    output.mkdir()
    special = SaveGame(Path("confirm-quit.gk3"), "Quit", "confirm", "special")

    result = merge_captures(
        ((special, reference / "confirm-quit.png", current / "confirm-quit.png"),), output=output
    )

    assert [save.path.stem for save, _reference, _current in result] == ["confirm-quit", "save0001"]


def test_index_rejects_paths_outside_the_run(tmp_path: Path) -> None:
    output = tmp_path / "comparisons"
    output.mkdir()
    row = dict.fromkeys(("name", "description", "room", "timeblock", "reference", "current"), "x")
    row["reference"] = "../outside.png"
    (output / "captures.json").write_text(json.dumps([row]), encoding="utf-8")
    with pytest.raises(ValueError, match="inside the run"):
        merge_captures((), output=output)


def test_archived_slots_keep_separate_captures_when_index_is_reopened(tmp_path: Path) -> None:
    output = tmp_path / "comparisons"
    output.mkdir()
    entries = tuple(
        (
            SaveGame(Path("save0001.gk3"), label, "te4", "309p", capture_stem=stem),
            tmp_path / "reference-1024x768" / f"{stem or 'save0001'}.png",
            tmp_path / "current-1280x800" / f"{stem or 'save0001'}.png",
        )
        for label, stem in (("Current", ""), ("Archive", "archive-123-save0001"))
    )
    merged = merge_captures(entries, output=output)
    assert len(merged) == 2
    assert merge_captures((), output=output) == merged
    assert {save.output_stem for save, _, _ in merged} == {"save0001", "archive-123-save0001"}
    assert merge_captures(entries[:1], output=output) == merged
