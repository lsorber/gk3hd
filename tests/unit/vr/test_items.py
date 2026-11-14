"""Original resource bindings, label provenance and exact overlay pixels."""

from __future__ import annotations

import struct
from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image

from gk3hd.vr.items import encode_catalog, inventory_visuals, validate_catalog


def bitmap() -> bytes:
    image = Image.new("RGB", (3, 1))
    image.putdata([(255, 0, 255), (0, 0, 0), (12, 34, 56)])
    stream = BytesIO()
    image.save(stream, format="BMP")
    return stream.getvalue()


def test_item_feedback_uses_original_binding_label_and_premultiplied_pixels() -> None:
    read = Mock(return_value=bitmap())
    visuals = inventory_visuals(
        b"[VERBS]\nNOTEPAD, up=i_notebook, type=Inventory\nLOOK, up=i_look, type=Normal",
        b"ignored=value\n[ToolTips]\nv_notepad=Notebook\n[Other]\nv_notepad=Wrong",
        read,
    )
    assert len(visuals) == 1
    item = visuals[0]
    assert item.name == "NOTEPAD"
    assert item.label == "Notebook"
    assert item.label_key == "V_NOTEPAD"
    assert (item.width, item.height) == (3, 1)
    assert item.bgra == bytes((0, 0, 0, 0, 0, 0, 0, 255, 56, 34, 12, 255))
    read.assert_called_once_with("I_NOTEBOOK.BMP")


def test_proprietary_rgb565_is_decoded_without_a_texture_extraction_step() -> None:
    source = struct.pack("<4sHH2H", b"61nM", 1, 2, 0xF81F, 0xF800)
    item = inventory_visuals(
        b"[VERBS]\nTEST, up=test.bmp, type=Inventory",
        b"[ToolTips]\nN_TEST=Test item",
        Mock(return_value=source),
    )[0]
    assert item.label == "Test item"
    assert item.label_key == "N_TEST"
    assert item.bgra == bytes((0, 0, 0, 0, 0, 0, 255, 255))


def test_missing_translation_has_an_explicit_identifier_fallback() -> None:
    item = inventory_visuals(
        b"[VERBS]\nSOME_ITEM, up=icon, type=Inventory", b"", Mock(return_value=bitmap())
    )[0]
    assert item.label == "Some item"
    assert item.label_key is None


@pytest.mark.parametrize(
    "reference", ["../icon", "sub/icon", "sub\\icon", "C:icon", "icon.png", ""]
)
def test_resource_names_cannot_escape_the_original_bitmap_catalog(reference: str) -> None:
    read = Mock()
    with pytest.raises(ValueError, match="invalid inventory icon binding"):
        inventory_visuals(f"[VERBS]\nITEM, up={reference}, type=Inventory".encode(), b"", read)
    read.assert_not_called()


def test_conflicting_bindings_are_rejected_without_reading_artwork() -> None:
    read = Mock()
    with pytest.raises(ValueError, match="conflicting"):
        inventory_visuals(
            b"[VERBS]\nITEM, up=one, type=Inventory\nitem, up=two, type=Inventory", b"", read
        )
    read.assert_not_called()


def test_icon_dimensions_are_bounded_before_allocating_an_overlay() -> None:
    image = Image.new("RGB", (129, 1))
    stream = BytesIO()
    image.save(stream, format="BMP")
    with pytest.raises(ValueError, match="dimensions exceed"):
        inventory_visuals(
            b"[VERBS]\nITEM, up=one, type=Inventory", b"", Mock(return_value=stream.getvalue())
        )


def test_large_labels_are_rejected_instead_of_silently_clipped() -> None:
    read = Mock()
    with pytest.raises(ValueError, match="label is empty or oversized"):
        inventory_visuals(
            b"[VERBS]\nITEM, up=one, type=Inventory", b"[ToolTips]\nV_ITEM=" + b"a" * 193, read
        )
    read.assert_not_called()


def test_catalog_roundtrip_preserves_localized_original_resources() -> None:
    visuals = inventory_visuals(
        b"[VERBS]\nNOTE, up=icon, type=Inventory",
        "[ToolTips]\nV_NOTE=Café notebook".encode("cp1252"),
        Mock(return_value=bitmap()),
    )
    catalog = encode_catalog(visuals)
    validate_catalog(catalog)
    assert "Café notebook".encode() in catalog
    assert visuals[0].bgra in catalog
    validate_catalog(encode_catalog(()))


@pytest.mark.parametrize(
    "damage", ["truncated", "trailing", "count", "dimensions", "name", "label"]
)
def test_installed_catalog_rejects_malformed_or_oversized_data(damage: str) -> None:
    catalog = bytearray(
        encode_catalog(
            inventory_visuals(
                b"[VERBS]\nNOTE, up=icon, type=Inventory",
                b"[ToolTips]\nV_NOTE=Notebook",
                Mock(return_value=bitmap()),
            )
        )
    )
    if damage == "truncated":
        catalog.pop()
    elif damage == "trailing":
        catalog += b"\0"
    elif damage == "count":
        struct.pack_into("<I", catalog, 8, 257)
    elif damage == "dimensions":
        struct.pack_into("<H", catalog, 16, 129)
    elif damage == "name":
        catalog[20] = ord("/")
    else:
        catalog[24] = 0
    with pytest.raises(ValueError, match="inventory visual catalog"):
        validate_catalog(bytes(catalog))
