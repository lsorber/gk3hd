"""Renderer compatibility for an otherwise original-layout visual reference."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode
from gk3hd.patch.definitions.runtime2d.cursor_history import HISTORY_OFFSET, emit_history_adapter
from gk3hd.patch.definitions.runtime2d.resource_driving_map import correct_location_origins

if TYPE_CHECKING:
    from gk3hd.patch.builds import BuildProfile


def renderer_compatibility(data: bytes, profile: BuildProfile) -> bytes:
    """Preserve native cursor/color appearance on D7VK, without HD quality changes."""
    image = PEFile(data)
    size = 0x3A44
    section = image.add_section(".gk3ref", bytes(size), 0xE0000040)
    base = image.rva_to_va(section.virtual_address)
    payload = SegmentPayloadBuilder(owner="visual reference", segment="cursor history", size=size)
    emit_history_adapter(profile=profile, payload=payload, control_va=base)
    image.write_bytes(section.pointer_to_raw_data, payload.build())
    site = profile.site("cursor.restore_history_query")
    plan = ExecutableMutationPlan(owner="visual reference cursor history")
    plan.branch(
        label="renderer surface-history capability",
        opcode=BranchOpcode.CALL,
        site_va=site.va,
        expected=site.original,
        target_va=base + HISTORY_OFFSET,
        size=len(site.original),
    )
    # Native Windows ignores the old CRT ramp, while D7VK applies it. Keep
    # only that color-compatibility correction, not the full quality patch
    # (which also lifts upload limits and enables anisotropic filtering).
    for channel, replacement in (
        ("red", "8b ce c1 e1 07 90 90 90 90"),
        ("green", "8b c6 c1 e0 07 90 90 90 90"),
        ("blue", "8b d6 c1 e2 07 90 90 90 90"),
    ):
        site = profile.site(f"quality.gamma_identity_{channel}")
        plan.replace(
            label=f"native {channel} gamma",
            va=site.va,
            expected=site.original,
            payload=bytes.fromhex(replacement),
        )
    plan.apply(image)
    return bytes(image.data)


def aligned_map_reference(data: bytes, profile: BuildProfile) -> bytes:
    """Correct only three map anchors; preserve original pixels and UI rendering."""
    image = PEFile(data)
    plan = ExecutableMutationPlan(owner="visual reference map alignment")
    correct_location_origins(plan, profile)
    plan.apply(image)
    return bytes(image.data)
