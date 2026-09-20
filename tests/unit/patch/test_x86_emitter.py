"""Golden tests for labels and relocations in the focused x86 emitter."""

from __future__ import annotations

import pytest

from gk3hd.patch.binary.x86 import (
    BranchOpcode,
    Condition,
    X86Emitter,
    X86EmitterError,
    decode_rel32_branch,
    encode_rel32_branch,
)


def test_emitter_resolves_forward_and_backward_rel32_labels() -> None:
    """CALL and conditional JMP targets resolve from the end of each displacement."""
    emitter = X86Emitter(base_va=0x1000)
    emitter.label("start")
    emitter.call("finish")
    emitter.jump_if(Condition.NOT_EQUAL, "start")
    emitter.label("finish")
    emitter.ret()

    assert emitter.build() == bytes.fromhex("e8 06 00 00 00 0f 85 f5 ff ff ff c3")
    assert emitter.listing() == (("start", 0, 0x1000), ("finish", 11, 0x100B))


def test_emitter_resolves_absolute_label_address() -> None:
    """Absolute relocations include the injected section's base address."""
    emitter = X86Emitter(base_va=0x4000)
    emitter.absolute_label("data")
    emitter.label("data")
    emitter.raw(bytes.fromhex("de ad be ef"))

    assert emitter.build() == bytes.fromhex("04 40 00 00 de ad be ef")


def test_emitter_rejects_unresolved_labels_and_oversize_payloads() -> None:
    """Invalid generated code fails before it can be installed."""
    emitter = X86Emitter(base_va=0)
    emitter.jump("missing")

    with pytest.raises(X86EmitterError, match="unresolved"):
        emitter.build()

    bounded = X86Emitter(base_va=0)
    bounded.raw(b"toolong")
    with pytest.raises(X86EmitterError, match="only 3"):
        bounded.build(maximum_size=3)


def test_emitter_resolves_absolute_rel32_calls_and_jumps() -> None:
    """Absolute targets use the loaded instruction address, not a file offset."""
    emitter = X86Emitter(base_va=0x00401000)
    emitter.call_absolute(0x00402000)
    emitter.jump_absolute(0x00400000)

    assert emitter.build() == bytes.fromhex("e8 fb 0f 00 00 e9 f6 ef ff ff")


def test_emitter_rejects_absolute_rel32_without_a_load_address() -> None:
    """External branches cannot silently treat an unknown payload VA as zero."""
    emitter = X86Emitter(base_va=0)

    with pytest.raises(X86EmitterError, match="final virtual address"):
        emitter.call_absolute(0x00402000)
    with pytest.raises(X86EmitterError, match="final virtual address"):
        emitter.jump_absolute(0x00402000)


def test_emitter_resolves_forward_and_backward_short_branches() -> None:
    """Explicit rel8 branches retain compact payload layouts and enforce range."""
    emitter = X86Emitter(base_va=0)
    emitter.label("loop")
    emitter.jump_short_if(Condition.NOT_EQUAL, "done")
    emitter.jump_short("loop")
    emitter.label("done")
    emitter.ret()

    assert emitter.build() == bytes.fromhex("75 02 eb fc c3")


def test_rel32_hook_helpers_round_trip_with_nop_padding() -> None:
    """All compilers share one checked encoding for external hook windows."""
    site_va = 0x00401000
    target_va = 0x00802000
    payload = encode_rel32_branch(
        opcode=BranchOpcode.CALL,
        site_va=site_va,
        target_va=target_va,
        size=8,
    )

    assert payload[5:] == b"\x90\x90\x90"
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=site_va,
            instruction=payload[:5],
        )
        == target_va
    )
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=site_va,
            instruction=payload[:5],
        )
        is None
    )
