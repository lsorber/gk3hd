"""Compose non-overlapping redirects in an existing executable image."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal, Protocol

from gk3hd.patch.binary.x86 import BranchOpcode, encode_rel32_branch
from gk3hd.patch.model import PatchError


class MutableExecutableImage(Protocol):
    """Binary-image operations required to apply executable mutations."""

    def va_to_offset(self, va: int) -> int:
        """Translate a virtual address to a file offset."""
        ...

    def read_bytes(self, offset: int, size: int) -> bytes:
        """Read bytes from the executable image."""
        ...

    def write_bytes(self, offset: int, payload: bytes) -> None:
        """Write bytes to the executable image."""
        ...


@dataclass(frozen=True, slots=True)
class ExecutableMutation:
    """One named replacement at an existing executable virtual address."""

    label: str
    va: int
    expected: bytes
    payload: bytes

    @property
    def end_va(self) -> int:
        """Return the exclusive end of the mutation."""
        return self.va + len(self.payload)


class ExecutableMutationPlan:
    """Build one deterministic, overlap-checked native-redirect transaction.

    Outcome:
        Pointers and displaced branches are named and validated as one
        composition before any redirect is committed.

    Before:
        Compilers issued immediate writes whose ownership was implicit in
        statement order; overlapping or partially installed hooks could pass.

    After:
        Exact virtual-address mutations share one validation and commit
        boundary, with explicit pristine, installed, and partial-state rules.

    Strategy:
        Encode redirects at declaration time, reject intersecting claims, read
        every source interval before writing, and commit in address order.

    Boundaries:
        This plan owns existing-image replacements only. Injected-section
        layout and broader semantic anchors remain separate concerns.
    """

    __slots__ = ("_mutations", "_owner")

    def __init__(self, *, owner: str) -> None:
        """Create an empty mutation transaction for one compiler owner."""
        self._owner = owner
        self._mutations: list[ExecutableMutation] = []

    def replace(self, *, label: str, va: int, expected: bytes, payload: bytes) -> None:
        """Claim one exact existing-image interval."""
        if va <= 0 or not payload or len(expected) != len(payload):
            msg = f"{self._owner} {label} has invalid mutation at 0x{va:x}"
            raise PatchError(msg)
        mutation = ExecutableMutation(
            label=label,
            va=va,
            expected=bytes(expected),
            payload=bytes(payload),
        )
        for existing in self._mutations:
            if mutation.va < existing.end_va and existing.va < mutation.end_va:
                msg = (
                    f"{self._owner} executable mutation overlap: {label} "
                    f"0x{mutation.va:x}..0x{mutation.end_va:x} intersects "
                    f"{existing.label} 0x{existing.va:x}..0x{existing.end_va:x}"
                )
                raise PatchError(msg)
        self._mutations.append(mutation)

    def pointer(
        self,
        *,
        label: str,
        slot_va: int,
        expected: int | bytes,
        target_va: int,
    ) -> None:
        """Claim one little-endian 32-bit pointer redirect."""
        expected_payload = struct.pack("<I", expected) if isinstance(expected, int) else expected
        self.replace(
            label=label,
            va=slot_va,
            expected=expected_payload,
            payload=struct.pack("<I", target_va),
        )

    def branch(  # noqa: PLR0913 - branch encoding requires the complete native site contract.
        self,
        *,
        label: str,
        opcode: BranchOpcode,
        site_va: int,
        expected: bytes,
        target_va: int,
        size: int = 5,
    ) -> None:
        """Claim one relative CALL or JUMP redirect."""
        self.replace(
            label=label,
            va=site_va,
            expected=expected,
            payload=encode_rel32_branch(
                opcode=opcode,
                site_va=site_va,
                target_va=target_va,
                size=size,
            ),
        )

    def _require_uniform_state(
        self,
        pe: MutableExecutableImage,
        *,
        required: Literal["pristine", "installed"] | None,
    ) -> None:
        """Require one coherent transaction state without mutating the image."""
        observed_states: set[Literal["pristine", "installed"]] = set()
        for mutation in sorted(self._mutations, key=lambda item: item.va):
            actual = pe.read_bytes(pe.va_to_offset(mutation.va), len(mutation.expected))
            if mutation.expected == mutation.payload and actual == mutation.payload:
                # An identity claim is a useful ownership assertion but cannot
                # distinguish transaction state and must not create a false
                # partial-install report beside an actual redirect.
                continue
            if actual == mutation.payload:
                observed_states.add("installed")
            elif actual == mutation.expected:
                observed_states.add("pristine")
            else:
                msg = f"{self._owner} source mismatch at {mutation.label}"
                raise PatchError(msg)
        if len(observed_states) > 1:
            msg = f"{self._owner} executable redirects are partially installed"
            raise PatchError(msg)
        if required is not None and observed_states and observed_states != {required}:
            msg = f"{self._owner} executable redirects are not {required}"
            raise PatchError(msg)

    def apply(self, pe: MutableExecutableImage, /) -> None:
        """Validate one coherent source state, then commit every redirect."""
        self._require_uniform_state(pe, required=None)
        for mutation in sorted(self._mutations, key=lambda item: item.va):
            pe.write_bytes(pe.va_to_offset(mutation.va), mutation.payload)

    def verify(self, pe: MutableExecutableImage, /) -> None:
        """Require every declared redirect to contain its installed payload."""
        self._require_uniform_state(pe, required="installed")
