"""Visual captures must select a real row and prove that typing took effect."""

import struct

import pytest

from tests.visual.support import special
from tests.visual.support.windows import CaptureError


def mock_memory(
    monkeypatch: pytest.MonkeyPatch, values: dict[tuple[int, int], tuple[int, ...] | None]
) -> None:
    monkeypatch.setattr(special, "current_ui_layer_pointer", lambda _pid: 0x1000)

    def words(_pid: int, address: int, *, count: int = 1) -> tuple[int, ...] | None:
        return values[address, count]

    monkeypatch.setattr(special, "read_process_words", words)


@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (3840, 2160)])
def test_select_new_slot_from_current_row_bounds(
    monkeypatch: pytest.MonkeyPatch, size: tuple[int, int]
) -> None:
    width, height = size
    bounds = (width // 4, height // 3, width // 2, height // 3 + 16)
    mock_memory(
        monkeypatch,
        {
            (0x1000, 1): (special._SAVE_LAYER_VTABLE,),
            (0x12B4, 2): (0x2000, 0x2098),
            # Two rows: existing save first, new-slot row last.
            (0x206C, 1): (0x3000,),
            (0x301C, 4): bounds,
        },
    )
    assert special._save_name_entry(7, size) == (
        (bounds[0] + bounds[2]) // 2,
        (bounds[1] + bounds[3]) // 2,
    )


@pytest.mark.parametrize("rows", [(0, 0x204C), (0x2000, 0x2000), (0x2000, 0x204D), (1, 0xFFFF)])
def test_reject_damaged_or_excessive_row_list(
    monkeypatch: pytest.MonkeyPatch, rows: tuple[int, int]
) -> None:
    mock_memory(monkeypatch, {(0x1000, 1): (special._SAVE_LAYER_VTABLE,), (0x12B4, 2): rows})
    with pytest.raises(CaptureError, match="invalid native row list"):
        special._save_name_entry(7, (1280, 800))


@pytest.mark.parametrize("bounds", [(0, 2, 0, 3), (2, 4, 8, 3), (2, 4, 1281, 6), (2, 4, 8, 801)])
def test_do_not_click_hidden_or_invalid_row(
    monkeypatch: pytest.MonkeyPatch, bounds: tuple[int, int, int, int]
) -> None:
    mock_memory(
        monkeypatch,
        {
            (0x1000, 1): (special._SAVE_LAYER_VTABLE,),
            (0x12B4, 2): (0x2000, 0x204C),
            (0x2020, 1): (0x3000,),
            (0x301C, 4): bounds,
        },
    )
    with pytest.raises(CaptureError, match="not visible"):
        special._save_name_entry(7, (1280, 800))


@pytest.mark.parametrize("description", ["VR save", "GK3HD visual comparison", "café"])
def test_require_exact_typed_characters_before_capturing(
    monkeypatch: pytest.MonkeyPatch, description: str
) -> None:
    raw = description.encode("cp1252")
    count = (len(raw) + 3) // 4
    words = struct.unpack(f"<{count}I", raw.ljust(count * 4, b"\0"))
    mock_memory(
        monkeypatch,
        {
            (0x1000, 1): (special._SAVE_LAYER_VTABLE,),
            (0x1340, 1): (special._SAVE_NAME_EDITOR_VTABLE,),
            (0x1374, 2): (0x4000, len(raw)),
            (0x4000, count): words,
        },
    )
    assert special._save_name_matches(7, description)
    assert not special._save_name_matches(7, description[:-1])


@pytest.mark.parametrize(("pointer", "length"), [(0, 7), (0x4000, 0), (0x4000, 257)])
def test_empty_unavailable_or_oversized_editor_is_not_success(
    monkeypatch: pytest.MonkeyPatch, pointer: int, length: int
) -> None:
    mock_memory(
        monkeypatch,
        {
            (0x1000, 1): (special._SAVE_LAYER_VTABLE,),
            (0x1340, 1): (special._SAVE_NAME_EDITOR_VTABLE,),
            (0x1374, 2): (pointer, length),
        },
    )
    assert not special._save_name_matches(7, "VR save")


def test_layer_change_invalidates_editor(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_memory(monkeypatch, {(0x1000, 1): (special._ROOM_LAYER_VTABLE,)})
    assert not special._save_name_matches(7, "VR save")
    with pytest.raises(CaptureError, match="not the current interface"):
        special._save_name_entry(7, (1280, 800))


@pytest.mark.parametrize("contents", [None, (0x646162,)])
def test_unreadable_or_different_characters_are_not_success(
    monkeypatch: pytest.MonkeyPatch, contents: tuple[int, ...] | None
) -> None:
    mock_memory(
        monkeypatch,
        {
            (0x1000, 1): (special._SAVE_LAYER_VTABLE,),
            (0x1340, 1): (special._SAVE_NAME_EDITOR_VTABLE,),
            (0x1374, 2): (0x4000, 3),
            (0x4000, 1): contents,
        },
    )
    assert not special._save_name_matches(7, "new")


def test_unknown_editor_is_not_treated_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_memory(
        monkeypatch, {(0x1000, 1): (special._SAVE_LAYER_VTABLE,), (0x1340, 1): (0xFFFFFFFF,)}
    )
    assert not special._save_name_matches(7, "new")


def test_unreadable_row_list_is_not_clickable(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_memory(monkeypatch, {(0x1000, 1): (special._SAVE_LAYER_VTABLE,), (0x12B4, 2): None})
    with pytest.raises(CaptureError, match="row list is unreadable"):
        special._save_name_entry(7, (1280, 800))
