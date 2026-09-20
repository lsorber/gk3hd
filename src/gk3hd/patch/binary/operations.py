"""Typed, self-validating mutations over a PE32 image."""

from __future__ import annotations

from dataclasses import dataclass

from gk3hd.patch.model import (
    AddressSpan,
    MutableExecutable,
    PatchId,
    PatchOperation,
    ResourceClaim,
    ResourceKind,
)


class OperationError(Exception):
    """Report an invalid operation plan, source image, or installed image."""


@dataclass(frozen=True, slots=True)
class AssertBytes(PatchOperation):
    """Validate an immutable semantic anchor without claiming a mutation."""

    owner: PatchId
    symbol: str
    va: int
    expected: bytes

    @property
    def is_mutation(self) -> bool:
        """Assertions never change executable state."""
        return False

    def __post_init__(self) -> None:
        """Require an actual byte signature at a valid virtual address."""
        if self.va < 0 or not self.expected:
            detail = f"{self.symbol} has an empty or negative-address assertion"
            raise OperationError(detail)

    @property
    def claim(self) -> ResourceClaim:
        """Identify the assertion independently from writable ranges."""
        return ResourceClaim(ResourceKind.BYTE_RANGE, f"assert:{self.symbol}")

    @property
    def span(self) -> None:
        """Assertions do not participate in write-overlap checks."""
        return None

    @property
    def payload(self) -> None:
        """Assertions have no replacement payload."""
        return None

    def validate_source(self, image: MutableExecutable) -> None:
        """Require the semantic anchor in the source image."""
        _require_bytes(image, self.va, self.expected, self.symbol, phase="precheck")

    def apply(self, image: MutableExecutable) -> None:
        """Leave the asserted bytes unchanged."""

    def verify(self, image: MutableExecutable) -> None:
        """Require the semantic anchor in the installed image."""
        _require_bytes(image, self.va, self.expected, self.symbol, phase="postcheck")


@dataclass(frozen=True, slots=True)
class ReplaceBytes(PatchOperation):
    """Replace one exact original byte sequence at a virtual address."""

    owner: PatchId
    symbol: str
    va: int
    expected: bytes
    replacement: bytes

    @property
    def is_mutation(self) -> bool:
        """Exact byte replacements change executable state."""
        return True

    def __post_init__(self) -> None:
        """Reject length-changing writes before planning begins."""
        if self.va < 0 or not self.expected:
            detail = f"{self.symbol} has an empty or negative-address replacement"
            raise OperationError(detail)
        if len(self.expected) != len(self.replacement):
            detail = (
                f"{self.symbol} changes length from {len(self.expected)} to {len(self.replacement)}"
            )
            raise OperationError(detail)

    @property
    def claim(self) -> ResourceClaim:
        """Claim this exact virtual-address byte range."""
        return ResourceClaim(ResourceKind.BYTE_RANGE, f"0x{self.va:08x}:{len(self.replacement)}")

    @property
    def span(self) -> AddressSpan:
        """Return the half-open write interval."""
        return AddressSpan(self.va, self.va + len(self.replacement))

    @property
    def payload(self) -> bytes:
        """Return the installed bytes."""
        return self.replacement

    def validate_source(self, image: MutableExecutable) -> None:
        """Require the one supported pristine byte sequence."""
        _require_bytes(image, self.va, self.expected, self.symbol, phase="precheck")

    def apply(self, image: MutableExecutable) -> None:
        """Write the replacement into the in-memory image."""
        image.write_bytes(image.va_to_offset(self.va), self.replacement)

    def verify(self, image: MutableExecutable) -> None:
        """Require the exact installed byte sequence."""
        _require_bytes(image, self.va, self.replacement, self.symbol, phase="postcheck")


def _require_bytes(
    image: MutableExecutable,
    va: int,
    expected: bytes,
    symbol: str,
    *,
    phase: str,
) -> None:
    actual = image.read_bytes(image.va_to_offset(va), len(expected))
    if actual != expected:
        detail = (
            f"{phase} failed for {symbol} at 0x{va:08x}: "
            f"expected {expected.hex()}, got {actual.hex()}"
        )
        raise OperationError(detail)
