"""Unit tests for executable-operation preflight, composition, and verification."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.operations import AssertBytes, OperationError, ReplaceBytes
from gk3hd.patch.model import PatchId


@dataclass
class FakeExecutable:
    """Small identity-addressed image used to test operations without GK3."""

    data: bytearray

    def clone(self) -> FakeExecutable:
        """Return an independent byte and section copy."""
        return FakeExecutable(bytearray(self.data))

    def va_to_offset(self, va: int) -> int:
        """Use identity VA mapping for the synthetic image."""
        return va

    def read_bytes(self, offset: int, size: int) -> bytes:
        """Read bytes from the synthetic image."""
        return bytes(self.data[offset : offset + size])

    def write_bytes(self, offset: int, payload: bytes) -> None:
        """Write bytes into the synthetic image."""
        self.data[offset : offset + len(payload)] = payload


def test_executor_does_not_mutate_source() -> None:
    """A successful execution returns a verified clone and preserves its source."""
    source = FakeExecutable(bytearray.fromhex("00 01 02 03"))
    operation = ReplaceBytes(
        owner=PatchId("example"),
        symbol="example.site",
        va=1,
        expected=bytes.fromhex("01 02"),
        replacement=bytes.fromhex("aa bb"),
    )

    output = OperationExecutor().execute(source, (operation,))

    assert source.data == bytearray.fromhex("00 01 02 03")
    assert output.data == bytearray.fromhex("00 aa bb 03")


def test_executor_late_precondition_failure_preserves_source() -> None:
    """A late failed precondition discards the private image and preserves source."""
    source = FakeExecutable(bytearray.fromhex("00 01 02 03"))
    valid = ReplaceBytes(PatchId("example"), "valid", 0, b"\x00", b"\xaa")
    invalid = ReplaceBytes(PatchId("example"), "invalid", 3, b"\xff", b"\xbb")

    with pytest.raises(OperationError, match="precheck failed"):
        OperationExecutor().execute(source, (valid, invalid))

    assert source.data == bytearray.fromhex("00 01 02 03")


def test_executor_validates_declared_dependency_state() -> None:
    """A later operation may validate bytes installed by an earlier dependency."""
    source = FakeExecutable(bytearray.fromhex("00 01 02 03"))
    dependency = ReplaceBytes(PatchId("dependency"), "dependency", 1, b"\x01", b"\xaa")
    dependent = AssertBytes(PatchId("dependent"), "dependent", 1, b"\xaa")

    output = OperationExecutor().execute(source, (dependency, dependent))

    assert source.data == bytearray.fromhex("00 01 02 03")
    assert output.data == bytearray.fromhex("00 aa 02 03")


def test_executor_rejects_incompatible_overlaps() -> None:
    """Different payloads cannot claim overlapping virtual-address ranges."""
    source = FakeExecutable(bytearray(8))
    left = ReplaceBytes(PatchId("left"), "left", 1, b"\x00\x00", b"\x01\x01")
    right = ReplaceBytes(PatchId("right"), "right", 2, b"\x00\x00", b"\x02\x02")

    with pytest.raises(OperationError, match="overlap"):
        OperationExecutor().execute(source, (left, right))
