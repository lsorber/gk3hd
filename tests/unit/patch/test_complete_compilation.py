"""Compile complete public plans without distributing a copyrighted executable."""

import struct

import pytest

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.mutations import ExecutableMutationPlan, MutableExecutableImage
from gk3hd.patch.builds import SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.catalog import PLANNER
from gk3hd.patch.model import BuildContext, ProfileId


def _source(profile: BuildProfile) -> PEFile:
    """Sparse PE containing only the signatures already declared by the patcher."""
    data = bytearray(0x400000)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x14C, 1, 0, 0, 0, 0xE0, 0x10F)
    struct.pack_into("<H", data, 0x98, 0x10B)
    for offset, value in ((28, 0x400000), (32, 0x1000), (36, 0x200), (56, 0x400000), (60, 0x1000)):
        struct.pack_into("<I", data, 0x98 + offset, value)
    struct.pack_into("<I", data, 0x98 + 92, 16)
    struct.pack_into("<2I", data, 0x98 + 104, 0x380000, 40)
    struct.pack_into(
        "<5I",
        data,
        0x380000,
        0x380080,
        0,
        0,
        0x380040,
        profile.address("win32.Ellipse") - 0x400000,
    )
    data[0x380040:0x38004A] = b"GDI32.dll\0"
    struct.pack_into("<I", data, 0x380080, 0x3800A0)
    data[0x3800A0:0x3800AA] = b"\0\0Ellipse\0"
    struct.pack_into(
        "<8sIIIIIIHHI",
        data,
        0x178,
        b".text",
        0x3FF000,
        0x1000,
        0x3FF000,
        0x1000,
        0,
        0,
        0,
        0,
        0xE0000020,
    )
    image = PEFile(data)
    for site in profile.sites.values():
        image.write_bytes(
            image.va_to_offset(site.va - len(site.context_before)),
            site.context_before + site.original + site.context_after,
        )
    for owner, offset, target in (
        ("inventory", 0, "inventory.destructor"),
        ("inventory", 0xA0, "ui.container_draw"),
        ("inventory", 0xDC, "ui.hide"),
        ("inventory", 0x30, "inventory.layout"),
        ("inventory_item", 0xA0, "inventory_item.draw"),
        ("caption", 0, "caption.destructor"),
        ("caption", 0xA0, "caption.draw"),
        ("driving_map", 0xA0, "ui.container_draw"),
        ("timeblock", 0xA0, "timeblock.draw"),
        ("fingerprint", 0x80, "fingerprint.dust"),
    ):
        image.write_u32_va(profile.address(f"{owner}.vtable") + offset, profile.address(target))
    image.write_u32_va(
        profile.address("bitmap_node.destructor_slot"), profile.address("bitmap_node.destructor")
    )
    width = profile.site("display.width_initializer")
    image.write_u32_va(width.va + len(width.original), profile.address("display.dimensions"))
    return image


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
@pytest.mark.parametrize("group", ["recommended", "testing"])
def test_complete_plan_is_deterministic_and_verifiable(
    profile: BuildProfile, group: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Public plans fit their payload bounds and independently verify every byte."""
    source = _source(profile)
    plan = PLANNER.plan_profile(ProfileId(group), BuildContext(build_id=profile.id))
    operations = plan.compile_operations()
    # Some native pointers/call sites are declared by the hook owners rather
    # than BuildProfile. Populate only otherwise-empty original-image slots
    # from those declared contracts, then remove this fixture adapter before
    # testing. This checks compiler composition, not original-game identity.
    apply = ExecutableMutationPlan.apply

    def populate(owner: ExecutableMutationPlan, image: MutableExecutableImage) -> None:
        for mutation in owner._mutations:
            if not 0x401000 <= mutation.va < 0x800000:
                continue
            offset = image.va_to_offset(mutation.va)
            if image.read_bytes(offset, len(mutation.expected)) == bytes(len(mutation.expected)):
                image.write_bytes(offset, mutation.expected)
                source.write_bytes(source.va_to_offset(mutation.va), mutation.expected)
        apply(owner, image)

    with monkeypatch.context() as context:
        context.setattr(ExecutableMutationPlan, "apply", populate)
        OperationExecutor().execute(source, operations)
    pristine = source.to_bytes()
    first = OperationExecutor().execute(source, operations)
    second = OperationExecutor().execute(source, operations)
    assert first.to_bytes() == second.to_bytes()
    assert source.to_bytes() == pristine
    assert first.to_bytes() != pristine
    for operation in operations:
        operation.verify(first)
