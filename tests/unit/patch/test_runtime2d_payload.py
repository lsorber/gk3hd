"""Tests for deterministic injected-segment composition."""

from __future__ import annotations

import pytest

from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.model import PatchError


def test_segment_payload_builds_one_zero_filled_image() -> None:
    builder = SegmentPayloadBuilder(owner="runtime2d.system", segment="control", size=16)
    builder.place(label="header", offset=0, payload=b"ABCD", limit=4)
    builder.reserve(label="state", offset=8, size=4)
    builder.place(label="tail", offset=12, payload=b"XY")

    assert builder.build() == b"ABCD" + bytes(8) + b"XY" + bytes(2)


@pytest.mark.parametrize(
    ("first_offset", "second_offset"),
    [(4, 4), (4, 5), (5, 4)],
)
def test_segment_payload_rejects_every_overlap(
    first_offset: int,
    second_offset: int,
) -> None:
    builder = SegmentPayloadBuilder(owner="runtime2d.system", segment="control", size=16)
    builder.place(label="first", offset=first_offset, payload=b"1234")

    with pytest.raises(PatchError, match="payload overlap"):
        builder.place(label="second", offset=second_offset, payload=b"5678")


def test_segment_payload_rejects_a_slot_overflow_before_build() -> None:
    builder = SegmentPayloadBuilder(owner="runtime2d.system", segment="control", size=16)

    with pytest.raises(PatchError, match="past its 0x8 limit"):
        builder.place(label="wrapper", offset=4, payload=b"12345", limit=8)
