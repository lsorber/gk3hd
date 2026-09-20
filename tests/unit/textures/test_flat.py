"""Keep flat-directory safety without scanning every new output's siblings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from gk3hd.textures import flat

if TYPE_CHECKING:
    from pathlib import Path


def test_fresh_names_do_not_enumerate_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbid_scan(*_args: object, **_kwargs: object) -> None:
        pytest.fail("a nonexistent name cannot resolve to another file's alias")

    monkeypatch.setattr(flat, "actual_files", forbid_scan)
    for name in ("FIRST.PNG", "LONGBI~1.PNG", "LONG_BITMAP_NAME.PNG"):
        destination = tmp_path / name
        with flat.protect_short_name_alias(destination):
            destination.write_bytes(name.encode("ascii"))
        assert destination.read_bytes() == name.encode("ascii")


def test_existing_literal_name_remains_in_place(tmp_path: Path) -> None:
    destination = tmp_path / "IMAGE.PNG"
    destination.write_bytes(b"original")
    with flat.protect_short_name_alias(destination):
        assert destination.read_bytes() == b"original"
        destination.write_bytes(b"replacement")
    assert destination.read_bytes() == b"replacement"
    assert list(tmp_path.iterdir()) == [destination]
