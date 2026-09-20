"""Retain dense Inventory and Save/Restore controls at authored dimensions."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    INVENTORY_NAVIGATION_CLEAR_OFFSET,
    INVENTORY_NAVIGATION_DIMENSIONS_OFFSET,
    INVENTORY_NAVIGATION_INPUT_OFFSET,
    INVENTORY_NAVIGATION_INPUT_STRIDE,
    INVENTORY_NAVIGATION_SEGMENT,
    INVENTORY_NAVIGATION_SOURCE_OFFSET,
    INVENTORY_NAVIGATION_STATE_OFFSET,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.sidney_images import build_image_dimensions
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

IMAGES = (
    (b"inv_highlight", 99, 98),
    (b"inv_scrollback", 22, 22),
    (b"inv_scrolldn_dis", 22, 20),
    (b"inv_scrolldn_dwn", 22, 20),
    (b"inv_scrolldn_hov", 22, 20),
    (b"inv_scrolldn_std", 22, 20),
    (b"inv_scrollup_dis", 22, 20),
    (b"inv_scrollup_dwn", 22, 20),
    (b"inv_scrollup_hov", 22, 20),
    (b"inv_scrollup_std", 22, 20),
    (b"saveload_scrollback", 22, 22),
    (b"saveload_scrolldn_dis", 22, 20),
    (b"saveload_scrolldn_dwn", 22, 20),
    (b"saveload_scrolldn_hov", 22, 20),
    (b"saveload_scrolldn_std", 22, 20),
    (b"saveload_scrollup_dis", 22, 20),
    (b"saveload_scrollup_dwn", 22, 20),
    (b"saveload_scrollup_hov", 22, 20),
    (b"saveload_scrollup_std", 22, 20),
)
SURFACES_SIZE = len(IMAGES) * 4
SCROLLBAR_PAIR_OFFSET = 0x08
SCROLLBAR_DIMENSIONS_OFFSET = 0xA00
SCROLLBAR_HEIGHT_OFFSET = 0xA80
SCROLLBAR_PAGE_SIZE_OFFSET = 0xD00
LOADSAVE_CONTROL_PREDICATE_OFFSET = 0x1D00


def build_loadsave_control_predicate(*, wrapper_va: int, state_va: int) -> bytes:
    """Identify retained dense arrows/track without confusing raster size with layout."""
    code = X86Emitter(base_va=wrapper_va)
    for index, (name, _, _) in enumerate(IMAGES):
        if name.startswith(b"saveload_scroll"):
            code.raw(b"\x3b\x05" + struct.pack("<I", state_va + index * 4))
            code.jump_if(Condition.EQUAL, "dimensions")
    code.label("native")
    code.raw(b"\xf8\xc3")
    code.label("dimensions")
    code.raw(b"\x83\x78\x38\x58")
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.raw(b"\x83\x78\x3c\x50")
    code.jump_if(Condition.EQUAL, "dense")
    code.raw(b"\x83\x78\x3c\x58")
    code.jump_if(Condition.NOT_EQUAL, "native")
    code.label("dense")
    code.raw(b"\xf9\xc3")
    return code.build()


def build_scrollbar_dimensions(
    *, wrapper_va: int, dimensions_pointer_va: int, reference_pair_va: int
) -> bytes:
    """Return Inventory's authored pair in HD, retaining native smaller modes."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x9c\x8b\x0d" + struct.pack("<I", dimensions_pointer_va))
    code.raw(b"\x81\x39\x00\x04\x00\x00")
    code.jump_if(Condition.ABOVE, "authored")
    code.raw(b"\x81\x79\x04\x00\x03\x00\x00")
    code.jump_if(Condition.BELOW_OR_EQUAL, "done")
    code.label("authored")
    code.raw(b"\xb9" + struct.pack("<I", reference_pair_va))
    code.label("done")
    code.raw(b"\x9d\xc3")
    return code.build()


def build_scrollbar_height(*, wrapper_va: int, dimensions_va: int) -> bytes:
    """Resolve the height through the same layout selector, preserving other registers."""
    code = X86Emitter(base_va=wrapper_va)
    code.call_absolute(dimensions_va)
    code.raw(b"\x8b\x49\x04\xc3")
    return code.build()


def build_scrollbar_page_size(*, wrapper_va: int, dimensions_va: int) -> bytes:
    """Derive visible rows from the same height that sizes the scrollbar."""
    code = X86Emitter(base_va=wrapper_va)
    code.call_absolute(dimensions_va)
    code.raw(b"\x8b\x41\x04\x6a\x64\x59\x99\xf7\xf9\x48\xc3")
    return code.build()


def build_source(
    *,
    wrapper_va: int,
    state_va: int,
    current_layer_va: int,
    inventory_vtable_va: int,
    loadgame_vtable_va: int,
    savegame_vtable_va: int,
) -> bytes:
    """Scale private source coordinates only within each retained image's owner."""
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8d\x6c\x24\x24\x8b\x45\x04\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    for index, (name, width, height) in enumerate(IMAGES):
        label = f"next_{index}"
        code.raw(b"\x3b\x05" + struct.pack("<I", state_va + index * 4))
        code.jump_if(Condition.NOT_EQUAL, label)
        for offset, value in ((0x38, width * 4), (0x3C, height * 4)):
            code.raw(b"\x81\x78" + bytes([offset]) + struct.pack("<I", value))
            code.jump_if(Condition.NOT_EQUAL, "done")
        code.jump("matched" if name.startswith(b"inv_") else "loadsave")
        code.label(label)
    code.jump("done")
    code.label("matched")
    code.call_absolute(current_layer_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x81\x38" + struct.pack("<I", inventory_vtable_va))
    code.jump_if(Condition.NOT_EQUAL, "done")
    code.jump("sample")
    code.label("loadsave")
    code.call_absolute(current_layer_va)
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "done")
    code.raw(b"\x81\x38" + struct.pack("<I", loadgame_vtable_va))
    code.jump_if(Condition.EQUAL, "sample")
    code.raw(b"\x81\x38" + struct.pack("<I", savegame_vtable_va))
    code.jump_if(Condition.NOT_EQUAL, "done")
    code.label("sample")
    code.raw(b"\x8b\x75\x0c\x85\xf6")
    code.jump_if(Condition.EQUAL, "done")
    scratch_va = state_va + SURFACES_SIZE
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\xc1\xe0\x02")
        code.raw(b"\xa3" + struct.pack("<I", scratch_va + offset))
    code.raw(b"\xc7\x45\x0c" + struct.pack("<I", scratch_va))
    code.label("done")
    code.raw(b"\x61\xc3")
    return code.build()


def build_clear(*, state_va: int) -> bytes:
    """Forget surface identities only when the inventory is destroyed."""
    return (
        b"".join(
            b"\xc7\x05" + struct.pack("<I", state_va + offset) + bytes(4)
            for offset in range(0, SURFACES_SIZE, 4)
        )
        + b"\xc3"
    )


def build_input_scope(*, argument_count: int, cursor_position_va: int) -> bytes:
    """Expose the already-authored event POINT to native page/drag cursor queries."""
    if argument_count not in {1, 3}:
        msg = "inventory scrollbar events require one or three arguments"
        raise PatchError(msg)
    code = X86Emitter(base_va=0)
    code.raw(b"\x55\x8b\xec\x83\xec\x10\x89\x45\xfc\x89\x4d\xf8")
    for offset, local in ((0, 0xF4), (4, 0xF0)):
        code.raw(b"\xa1" + struct.pack("<I", cursor_position_va + offset))
        code.raw(b"\x89\x45" + bytes([local]))
    code.raw(b"\x8b\x45\x08\x8b\x10")
    code.raw(b"\x89\x15" + struct.pack("<I", cursor_position_va))
    code.raw(b"\x8b\x50\x04\x89\x15" + struct.pack("<I", cursor_position_va + 4))
    code.raw({1: b"", 3: b"\xff\x75\x10\xff\x75\x0c"}[argument_count])
    code.raw(b"\xff\x75\x08\x8b\x4d\xf8\xff\x55\xfc")
    for offset, local in ((0, 0xF4), (4, 0xF0)):
        code.raw(b"\x8b\x55" + bytes([local]))
        code.raw(b"\x89\x15" + struct.pack("<I", cursor_position_va + offset))
    code.raw(b"\xc9\xc2" + struct.pack("<H", argument_count * 4))
    return code.build()


@dataclass(frozen=True, slots=True, kw_only=True)
class InventoryNavigationCompiler:
    """Own navigation resources and align their scrollbar with the inventory grid."""

    profile: BuildProfile
    id: ClassVar[str] = "runtime2d.inventory_navigation"

    def precheck(self, image: PEFile) -> None:
        """Validate inventory-only scrollbar dimensions and visible-row calculation."""
        for name in (
            "inventory.scrollbar_width",
            "inventory.scrollbar_height",
            "inventory.scrollbar_page_size_call",
        ):
            site = self.profile.site(name)
            expected = site.original + site.context_after
            if image.read_bytes(image.va_to_offset(site.va), len(expected)) != expected:
                msg = f"{self.id} requires the pristine {name} instructions"
                raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Build one bounded resource-dimension and source-sampling segment."""
        section = install_runtime_segment(image, INVENTORY_NAVIGATION_SEGMENT)
        base = image.rva_to_va(section.virtual_address)
        state = base + INVENTORY_NAVIGATION_STATE_OFFSET
        payload = SegmentPayloadBuilder(
            owner=self.id,
            segment=INVENTORY_NAVIGATION_SEGMENT.logical_name,
            size=INVENTORY_NAVIGATION_SEGMENT.size,
        )
        payload.place(label="identity", offset=0, payload=INVENTORY_NAVIGATION_SEGMENT.magic)
        payload.place(
            label="scrollbar authored pair",
            offset=SCROLLBAR_PAIR_OFFSET,
            payload=struct.pack("<II", 1024, 768),
        )
        payload.reserve(
            label="surfaces, source rectangle, logical pair",
            offset=INVENTORY_NAVIGATION_STATE_OFFSET,
            size=SURFACES_SIZE + 24,
        )
        payload.place(
            label="logical dimensions",
            offset=INVENTORY_NAVIGATION_DIMENSIONS_OFFSET,
            payload=build_image_dimensions(
                wrapper_va=base + INVENTORY_NAVIGATION_DIMENSIONS_OFFSET,
                surfaces_va=state,
                images=IMAGES,
            ),
            limit=LOADSAVE_CONTROL_PREDICATE_OFFSET,
        )
        payload.place(
            label="Save/Restore control source predicate",
            offset=LOADSAVE_CONTROL_PREDICATE_OFFSET,
            payload=build_loadsave_control_predicate(
                wrapper_va=base + LOADSAVE_CONTROL_PREDICATE_OFFSET, state_va=state
            ),
            limit=INVENTORY_NAVIGATION_SEGMENT.size,
        )
        payload.place(
            label="source coordinates",
            offset=INVENTORY_NAVIGATION_SOURCE_OFFSET,
            payload=build_source(
                wrapper_va=base + INVENTORY_NAVIGATION_SOURCE_OFFSET,
                state_va=state,
                current_layer_va=self.profile.address("ui.current_layer"),
                inventory_vtable_va=self.profile.address("inventory.vtable"),
                loadgame_vtable_va=self.profile.address("loadgame.vtable"),
                savegame_vtable_va=self.profile.address("savegame.vtable"),
            ),
            limit=SCROLLBAR_DIMENSIONS_OFFSET,
        )
        payload.place(
            label="destructor cleanup",
            offset=INVENTORY_NAVIGATION_CLEAR_OFFSET,
            payload=build_clear(state_va=state),
            limit=INVENTORY_NAVIGATION_SOURCE_OFFSET,
        )
        dimensions = self.profile.address("display.dimension_pointers")
        dimensions_va = base + SCROLLBAR_DIMENSIONS_OFFSET
        payload.place(
            label="scrollbar layout dimensions",
            offset=SCROLLBAR_DIMENSIONS_OFFSET,
            payload=build_scrollbar_dimensions(
                wrapper_va=dimensions_va,
                dimensions_pointer_va=dimensions,
                reference_pair_va=base + SCROLLBAR_PAIR_OFFSET,
            ),
            limit=SCROLLBAR_HEIGHT_OFFSET,
        )
        payload.place(
            label="scrollbar grid height",
            offset=SCROLLBAR_HEIGHT_OFFSET,
            payload=build_scrollbar_height(
                wrapper_va=base + SCROLLBAR_HEIGHT_OFFSET, dimensions_va=dimensions_va
            ),
            limit=INVENTORY_NAVIGATION_INPUT_OFFSET,
        )
        for index, argument_count in enumerate((1, 3)):
            payload.place(
                label=f"inventory scrollbar {argument_count}-argument event",
                offset=INVENTORY_NAVIGATION_INPUT_OFFSET
                + index * INVENTORY_NAVIGATION_INPUT_STRIDE,
                payload=build_input_scope(
                    argument_count=argument_count,
                    cursor_position_va=self.profile.address("input.cursor_position"),
                ),
                limit=INVENTORY_NAVIGATION_INPUT_OFFSET
                + (index + 1) * INVENTORY_NAVIGATION_INPUT_STRIDE,
            )
        payload.place(
            label="scrollbar visible rows",
            offset=SCROLLBAR_PAGE_SIZE_OFFSET,
            payload=build_scrollbar_page_size(
                wrapper_va=base + SCROLLBAR_PAGE_SIZE_OFFSET, dimensions_va=dimensions_va
            ),
        )
        image.write_bytes(section.pointer_to_raw_data, payload.build())
        # The scrollbar is constructed before the grid's reference-size replay
        # and retained afterward. It must choose authored dimensions at creation,
        # not merely read the temporarily borrowed grid pair. Change no global
        # display pointer; keep native smaller-resolution construction intact.
        mutations = ExecutableMutationPlan(owner=self.id)
        width_site = self.profile.site("inventory.scrollbar_width")
        mutations.branch(
            label="scrollbar grid width",
            site_va=width_site.va,
            expected=width_site.original,
            target_va=dimensions_va,
            opcode=BranchOpcode.CALL,
            size=len(width_site.original),
        )
        height_site = self.profile.site("inventory.scrollbar_height")
        mutations.branch(
            label="scrollbar grid height",
            site_va=height_site.va,
            expected=height_site.original,
            target_va=base + SCROLLBAR_HEIGHT_OFFSET,
            opcode=BranchOpcode.CALL,
            size=len(height_site.original),
        )
        page_site = self.profile.site("inventory.scrollbar_page_size_call")
        mutations.branch(
            label="scrollbar authored page size",
            site_va=page_site.va,
            expected=page_site.original,
            target_va=base + SCROLLBAR_PAGE_SIZE_OFFSET,
            opcode=BranchOpcode.CALL,
        )
        mutations.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Require the owned segment; the central compiler verifies all bytes."""
        if image.get_section(INVENTORY_NAVIGATION_SEGMENT.logical_name) is None:
            msg = "inventory navigation segment is missing"
            raise PatchError(msg)
