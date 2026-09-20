"""Tests for deterministic executable redirect composition."""

from __future__ import annotations

import struct

import pytest

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.x86 import BranchOpcode, encode_rel32_branch
from gk3hd.patch.model import PatchError


class _Image:
    """Minimal executable image used to observe planned writes."""

    def __init__(self, reads: dict[tuple[int, int], bytes]) -> None:
        self.writes: list[tuple[int, bytes]] = []
        self.reads = reads

    @staticmethod
    def va_to_offset(va: int) -> int:
        return va - 0x400000

    def write_bytes(self, offset: int, payload: bytes) -> None:
        self.writes.append((offset, payload))

    def read_bytes(self, offset: int, size: int) -> bytes:
        return self.reads[(offset, size)]


def test_plan_encodes_and_orders_pointer_and_branch_redirects() -> None:
    plan = ExecutableMutationPlan(owner="test")
    expected_call = b"\xe8\0\0\0\0\x90"
    plan.pointer(label="later pointer", slot_va=0x401020, expected=0, target_va=0x500000)
    plan.branch(
        label="earlier call",
        opcode=BranchOpcode.CALL,
        site_va=0x401000,
        expected=expected_call,
        target_va=0x500100,
        size=6,
    )
    image = _Image({(0x1000, 6): expected_call, (0x1020, 4): bytes(4)})

    plan.apply(image)

    assert image.writes == [
        (
            0x1000,
            encode_rel32_branch(
                opcode=BranchOpcode.CALL,
                site_va=0x401000,
                target_va=0x500100,
                size=6,
            ),
        ),
        (0x1020, struct.pack("<I", 0x500000)),
    ]


def test_plan_rejects_overlapping_redirects() -> None:
    plan = ExecutableMutationPlan(owner="test")
    plan.pointer(label="vtable", slot_va=0x401000, expected=0, target_va=0x500000)

    with pytest.raises(PatchError, match="executable mutation overlap"):
        plan.replace(
            label="branch",
            va=0x401002,
            expected=b"\xe8\0\0\0\0",
            payload=b"\xe9\0\0\0\0",
        )


@pytest.mark.parametrize(("va", "payload"), [(0, b"x"), (0x401000, b"")])
def test_plan_rejects_invalid_mutations(va: int, payload: bytes) -> None:
    plan = ExecutableMutationPlan(owner="test")

    with pytest.raises(PatchError, match="invalid mutation"):
        plan.replace(label="invalid", va=va, expected=payload, payload=payload)


def test_plan_validates_all_sources_before_writing() -> None:
    plan = ExecutableMutationPlan(owner="test")
    plan.pointer(label="first", slot_va=0x401000, expected=0, target_va=0x500000)
    plan.pointer(label="mismatch", slot_va=0x401010, expected=0, target_va=0x500010)
    image = _Image({(0x1000, 4): bytes(4), (0x1010, 4): b"bad!"})

    with pytest.raises(PatchError, match="source mismatch at mismatch"):
        plan.apply(image)

    assert image.writes == []


def test_plan_rejects_mixed_pristine_and_installed_redirects() -> None:
    plan = ExecutableMutationPlan(owner="test")
    plan.pointer(label="first", slot_va=0x401000, expected=0, target_va=0x500000)
    plan.pointer(label="second", slot_va=0x401010, expected=0, target_va=0x500010)
    image = _Image(
        {
            (0x1000, 4): struct.pack("<I", 0x500000),
            (0x1010, 4): bytes(4),
        }
    )

    with pytest.raises(PatchError, match="partially installed"):
        plan.apply(image)

    assert image.writes == []


def test_plan_accepts_complete_installed_state_for_deterministic_rebuild() -> None:
    plan = ExecutableMutationPlan(owner="test")
    plan.pointer(label="pointer", slot_va=0x401000, expected=0, target_va=0x500000)
    installed = struct.pack("<I", 0x500000)
    image = _Image({(0x1000, 4): installed})

    plan.apply(image)

    assert image.writes == [(0x1000, installed)]


def test_plan_verify_requires_every_redirect_to_be_installed() -> None:
    plan = ExecutableMutationPlan(owner="test")
    plan.pointer(label="pointer", slot_va=0x401000, expected=0, target_va=0x500000)

    with pytest.raises(PatchError, match="redirects are not installed"):
        plan.verify(_Image({(0x1000, 4): bytes(4)}))

    installed = _Image({(0x1000, 4): struct.pack("<I", 0x500000)})
    plan.verify(installed)


def test_identity_claim_does_not_create_a_false_partial_state() -> None:
    plan = ExecutableMutationPlan(owner="test")
    plan.replace(label="identity", va=0x401000, expected=b"same", payload=b"same")
    plan.pointer(label="redirect", slot_va=0x401010, expected=0, target_va=0x500000)
    image = _Image({(0x1000, 4): b"same", (0x1010, 4): bytes(4)})

    plan.apply(image)

    assert image.writes == [(0x1000, b"same"), (0x1010, struct.pack("<I", 0x500000))]
