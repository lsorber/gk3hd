"""Small label-aware x86 emitter for gk3hd's injected instruction subset."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Self

REL32_SIZE = 4
REL32_INSTRUCTION_SIZE = 5
NEAR_CONDITIONAL_SIZE = 6


class BranchOpcode(IntEnum):
    """Near relative branch opcodes used by hooks and emitted wrappers."""

    CALL = 0xE8
    JUMP = 0xE9


class Condition(IntEnum):
    """Near conditional-branch opcode suffixes supported by the emitter."""

    EQUAL = 0x84
    NOT_EQUAL = 0x85
    BELOW = 0x82
    ABOVE_OR_EQUAL = 0x83
    BELOW_OR_EQUAL = 0x86
    ABOVE = 0x87
    SIGN = 0x88
    NOT_SIGN = 0x89
    LESS = 0x8C
    GREATER_OR_EQUAL = 0x8D
    LESS_OR_EQUAL = 0x8E
    GREATER = 0x8F


class RelocationKind(StrEnum):
    """Kinds of deferred label references emitted into code."""

    REL8 = "rel8"
    REL32 = "rel32"
    REL32_ABSOLUTE = "rel32_absolute"
    ABSOLUTE32 = "absolute32"


@dataclass(frozen=True, slots=True)
class Relocation:
    """One deferred label reference in an emitted byte stream."""

    kind: RelocationKind
    offset: int
    target: str | int


class X86EmitterError(Exception):
    """Report duplicate labels, unresolved symbols, or invalid relocations."""


def encode_rel32_branch(
    *,
    opcode: BranchOpcode,
    site_va: int,
    target_va: int,
    size: int = REL32_INSTRUCTION_SIZE,
) -> bytes:
    """Encode one checked near branch plus deterministic NOP padding."""
    if size < REL32_INSTRUCTION_SIZE:
        detail = f"rel32 branch needs {REL32_INSTRUCTION_SIZE} bytes, got {size}"
        raise X86EmitterError(detail)
    displacement = target_va - (site_va + REL32_INSTRUCTION_SIZE)
    try:
        encoded = struct.pack("<i", displacement)
    except struct.error as exc:
        detail = f"rel32 target 0x{target_va:08x} is out of range from 0x{site_va:08x}"
        raise X86EmitterError(detail) from exc
    return bytes((opcode,)) + encoded + bytes((0x90,)) * (size - REL32_INSTRUCTION_SIZE)


def decode_rel32_branch(
    *,
    opcode: BranchOpcode,
    site_va: int,
    instruction: bytes,
) -> int | None:
    """Return one exact five-byte branch target, or ``None`` on mismatch."""
    if len(instruction) != REL32_INSTRUCTION_SIZE or instruction[0] != opcode:
        return None
    displacement = struct.unpack("<i", instruction[1:])[0]
    return site_va + REL32_INSTRUCTION_SIZE + displacement


class X86Emitter:
    """Emit deterministic x86 bytes with named labels and checked relocations."""

    def __init__(self, *, base_va: int) -> None:
        """Create an empty emitter whose first byte loads at ``base_va``."""
        self._base_va = base_va
        self._code = bytearray()
        self._labels: dict[str, int] = {}
        self._relocations: list[Relocation] = []

    @property
    def offset(self) -> int:
        """Return the next byte offset."""
        return len(self._code)

    def label(self, name: str) -> None:
        """Bind a unique label to the current offset."""
        if name in self._labels:
            detail = f"duplicate x86 label {name!r}"
            raise X86EmitterError(detail)
        self._labels[name] = self.offset

    def raw(self, payload: bytes) -> None:
        """Append an already-reviewed instruction fragment."""
        self._code.extend(payload)

    def __iadd__(self, payload: bytes) -> Self:
        """Append a reviewed raw fragment while retaining fluent local assembly."""
        self.raw(payload)
        return self

    def nop(self, count: int = 1) -> None:
        """Append ``count`` one-byte NOP instructions."""
        if count < 0:
            detail = f"negative NOP count {count}"
            raise X86EmitterError(detail)
        self._code.extend(bytes((0x90,)) * count)

    def ret(self) -> None:
        """Append a near return instruction."""
        self._code.append(0xC3)

    def push_imm8(self, value: int) -> None:
        """Append PUSH imm8 after validating its signed range."""
        try:
            encoded = struct.pack("<b", value)
        except struct.error as exc:
            detail = f"PUSH imm8 value {value} is out of range"
            raise X86EmitterError(detail) from exc
        self._code.append(0x6A)
        self._code.extend(encoded)

    def push_imm32(self, value: int) -> None:
        """Append PUSH imm32."""
        self._code.append(0x68)
        self._code.extend(struct.pack("<I", value))

    def call(self, label: str) -> None:
        """Append a rel32 CALL to a label."""
        self._code.append(0xE8)
        self._append_relocation(RelocationKind.REL32, label)

    def call_absolute(self, target_va: int) -> None:
        """Append a checked rel32 CALL to an absolute virtual address."""
        if self._base_va == 0:
            detail = "absolute rel32 CALL requires the payload's final virtual address"
            raise X86EmitterError(detail)
        self._code.append(0xE8)
        self._append_relocation(RelocationKind.REL32_ABSOLUTE, target_va)

    def jump(self, label: str) -> None:
        """Append a rel32 JMP to a label."""
        self._code.append(0xE9)
        self._append_relocation(RelocationKind.REL32, label)

    def jump_short(self, label: str) -> None:
        """Append a short rel8 JMP to a label."""
        self._code.append(0xEB)
        self._append_relocation(RelocationKind.REL8, label)

    def jump_absolute(self, target_va: int) -> None:
        """Append a checked rel32 JMP to an absolute virtual address."""
        if self._base_va == 0:
            detail = "absolute rel32 JMP requires the payload's final virtual address"
            raise X86EmitterError(detail)
        self._code.append(0xE9)
        self._append_relocation(RelocationKind.REL32_ABSOLUTE, target_va)

    def jump_if(self, condition: Condition, label: str) -> None:
        """Append a near rel32 conditional jump to a label."""
        self._code.extend((0x0F, condition))
        self._append_relocation(RelocationKind.REL32, label)

    def jump_short_if(self, condition: Condition, label: str) -> None:
        """Append a short rel8 conditional jump to a label."""
        self._code.append(int(condition) - 0x10)
        self._append_relocation(RelocationKind.REL8, label)

    def loop_short(self, label: str) -> None:
        """Append an x86 LOOP rel8 instruction to a label."""
        self._code.append(0xE2)
        self._append_relocation(RelocationKind.REL8, label)

    def absolute_label(self, label: str) -> None:
        """Append an absolute 32-bit virtual address for a label."""
        self._append_relocation(RelocationKind.ABSOLUTE32, label)

    def build(self, *, maximum_size: int | None = None) -> bytes:
        """Resolve every label and return immutable code within an optional bound."""
        code = bytearray(self._code)
        for relocation in self._relocations:
            self._resolve_relocation(code, relocation)

        if maximum_size is not None and len(code) > maximum_size:
            detail = f"x86 payload uses {len(code)} bytes but only {maximum_size} are available"
            raise X86EmitterError(detail)
        return bytes(code)

    def listing(self) -> tuple[tuple[str, int, int], ...]:
        """Return label names, section offsets, and absolute addresses for review."""
        return tuple(
            (name, offset, self._base_va + offset)
            for name, offset in sorted(self._labels.items(), key=lambda item: item[1])
        )

    def _append_relocation(self, kind: RelocationKind, target: str | int) -> None:
        relocation_offset = self.offset
        displacement_size = 1 if kind is RelocationKind.REL8 else REL32_SIZE
        self._code.extend(bytes(displacement_size))
        self._relocations.append(Relocation(kind=kind, offset=relocation_offset, target=target))

    def _resolve_relocation(self, code: bytearray, relocation: Relocation) -> None:
        """Resolve one type-checked label or absolute rel32 reference."""
        if relocation.kind is RelocationKind.ABSOLUTE32:
            target_offset = self._label_offset(relocation.target)
            struct.pack_into("<I", code, relocation.offset, self._base_va + target_offset)
            return

        if relocation.kind is RelocationKind.REL32:
            target_offset = self._label_offset(relocation.target)
            displacement = target_offset - (relocation.offset + REL32_SIZE)
        elif relocation.kind is RelocationKind.REL8:
            target_offset = self._label_offset(relocation.target)
            displacement = target_offset - (relocation.offset + 1)
            try:
                struct.pack_into("<b", code, relocation.offset, displacement)
            except struct.error as exc:
                detail = f"rel8 target {relocation.target!r} is out of range"
                raise X86EmitterError(detail) from exc
            return
        elif isinstance(relocation.target, int):
            displacement = relocation.target - (self._base_va + relocation.offset + REL32_SIZE)
        else:
            detail = "absolute rel32 relocation does not name an address"
            raise X86EmitterError(detail)
        try:
            struct.pack_into("<i", code, relocation.offset, displacement)
        except struct.error as exc:
            detail = f"rel32 target {relocation.target!r} is out of range"
            raise X86EmitterError(detail) from exc

    def _label_offset(self, target: str | int) -> int:
        """Return one bound label offset or report a relocation type mismatch."""
        if not isinstance(target, str):
            detail = "label relocation does not name a label"
            raise X86EmitterError(detail)
        target_offset = self._labels.get(target)
        if target_offset is None:
            detail = f"unresolved x86 label {target!r}"
            raise X86EmitterError(detail)
        return target_offset
