"""Tests for visual comparison rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PIL import Image, ImageChops, ImageStat

from tests.visual.support import render
from tests.visual.support.render import _comparable_frames, frame_writer, write_comparisons
from tests.visual.support.saves import SaveGame

if TYPE_CHECKING:
    from pathlib import Path


def test_frame_writer_joins_all_pending_captures(tmp_path: Path) -> None:
    with frame_writer() as write:
        for index in range(5):
            write(Image.new("RGB", (8, 8), (index, 0, 0)), tmp_path / f"{index}.png")
    for index in range(5):
        with Image.open(tmp_path / f"{index}.png") as captured:
            assert captured.getpixel((0, 0)) == (index, 0, 0)


def test_frame_writer_propagates_encoding_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError), frame_writer() as write:
        write(Image.new("RGB", (8, 8)), tmp_path / "missing" / "frame.png")


def test_parallel_animations_join_every_job(tmp_path: Path) -> None:
    reference, current = tmp_path / "reference.png", tmp_path / "current.png"
    Image.new("RGB", (16, 12), "red").save(reference)
    Image.new("RGB", (32, 24), "blue").save(current)
    captures = tuple(
        (SaveGame(tmp_path / f"scene{index}.gk3", "Scene", "R25", "110a"), reference, current)
        for index in range(7)
    )
    _, animations = write_comparisons(captures, output=tmp_path / "comparisons")
    assert len(animations) == 7
    for path in animations:
        with Image.open(path) as animation:
            animation.seek(1)
            pixel = animation.getpixel((0, 0))
            assert isinstance(pixel, tuple)
            assert max(abs(a - b) for a, b in zip(pixel, (0, 0, 255), strict=True)) <= 3


def test_parallel_animation_failure_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object) -> None:
        message = "encoder failed"
        raise OSError(message)

    source = tmp_path / "source.png"
    Image.new("RGB", (16, 12), "red").save(source)
    monkeypatch.setattr(render, "_write_animation", fail)
    save = SaveGame(tmp_path / "scene.gk3", "Scene", "R25", "110a")
    with pytest.raises(OSError, match="encoder failed"):
        write_comparisons(((save, source, source),), output=tmp_path / "comparisons")


def test_high_quality_animation_preserves_dimensions_and_small_luminance_error(
    tmp_path: Path,
) -> None:
    reference = Image.frombytes("L", (16, 12), bytes((i * 47) % 256 for i in range(192))).convert(
        "RGB"
    )
    current = Image.frombytes("L", (48, 27), bytes((i * 73) % 256 for i in range(1296))).convert(
        "RGB"
    )
    left, right = tmp_path / "reference.png", tmp_path / "current.png"
    reference.save(left)
    current.save(right)
    expected = _comparable_frames(reference, current)
    assert expected[1].tobytes() == current.tobytes()
    save = SaveGame(tmp_path / "pixels.gk3", "Pixel fidelity", "R25", "110a")
    _, animations = write_comparisons(((save, left, right),), output=tmp_path / "comparisons")
    with Image.open(animations[0]) as animation:
        assert getattr(animation, "n_frames", 1) == 2
        assert animation.size == expected[0].size
        for index, frame in enumerate(expected):
            animation.seek(index)
            difference = ImageChops.difference(animation.convert("RGB"), frame)
            assert max(ImageStat.Stat(difference).mean) < 3


def test_writes_contact_sheet_and_two_frame_animation(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    current = tmp_path / "current.png"
    Image.new("RGB", (1024, 768), "red").save(reference)
    Image.new("RGB", (1920, 1080), "blue").save(current)
    save = SaveGame(tmp_path / "save0001.gk3", "Opening", "RM01", "DAY1")

    sheet, animations = write_comparisons(
        ((save, reference, current),),
        output=tmp_path / "comparisons",
    )

    assert sheet.is_file()
    assert animations == (tmp_path / "comparisons" / "save0001.webp",)
    with Image.open(animations[0]) as animation:
        assert animation.size == (1920, 1080)
        animation.seek(1)
        assert animation.tell() == 1
    with Image.open(sheet) as matrix:
        assert matrix.size == (1280, 394)


def test_appending_special_scene_keeps_save_row_and_animation(tmp_path: Path) -> None:
    reference = tmp_path / "reference-1024x768"
    current = tmp_path / "current-1920x1080"
    reference.mkdir()
    current.mkdir()
    output = tmp_path / "comparisons"
    save = SaveGame(tmp_path / "save0001.gk3", "Opening", "RM01", "DAY1")
    Image.new("RGB", (1024, 768), "red").save(reference / "save0001.png")
    Image.new("RGB", (1920, 1080), "blue").save(current / "save0001.png")
    write_comparisons(
        ((save, reference / "save0001.png", current / "save0001.png"),), output=output
    )
    original_time = (output / "save0001.webp").stat().st_mtime_ns
    special = SaveGame(tmp_path / "confirm-quit.gk3", "Quit", "confirm", "special")
    Image.new("RGB", (1024, 768), "black").save(reference / "confirm-quit.png")
    Image.new("RGB", (1920, 1080), "white").save(current / "confirm-quit.png")

    sheet, animations = write_comparisons(
        ((special, reference / "confirm-quit.png", current / "confirm-quit.png"),), output=output
    )

    assert {path.name for path in animations} == {"save0001.webp", "confirm-quit.webp"}
    assert (output / "save0001.webp").stat().st_mtime_ns == original_time
    with Image.open(sheet) as matrix:
        assert matrix.size == (1280, 788)


def test_archived_duplicate_names_keep_independent_animations(tmp_path: Path) -> None:
    output = tmp_path / "comparisons"
    reference = tmp_path / "reference"
    current = tmp_path / "current"
    reference.mkdir()
    current.mkdir()
    captures = []
    for key, color in (("save0001", "red"), ("archive-abcdef-save0001", "blue")):
        save = SaveGame(
            tmp_path / key / "save0001.gk3", "Same slot", "TE1", "309P", capture_stem=key
        )
        left, right = reference / f"{key}.png", current / f"{key}.png"
        Image.new("RGB", (16, 12), color).save(left)
        Image.new("RGB", (16, 12), "green").save(right)
        captures.append((save, left, right))
    _sheet, animations = write_comparisons(tuple(captures), output=output)
    assert {path.stem for path in animations} == {"save0001", "archive-abcdef-save0001"}
    for path in animations:
        with Image.open(path) as animation:
            expected = (255, 0, 0) if path.stem == "save0001" else (0, 0, 255)
            pixel = animation.getpixel((0, 0))
            assert isinstance(pixel, tuple)
            assert max(abs(a - b) for a, b in zip(pixel, expected, strict=True)) <= 3
    # A later one-row update reloads the archive entry from the persisted index.
    _, updated = write_comparisons((captures[0],), output=output)
    assert set(updated) == set(animations)
