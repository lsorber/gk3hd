"""Keep the console's responsive anchors and scale its authored inner layout."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    CONSOLE_DAMAGE_OFFSET,
    CONSOLE_OWNER_OFFSET,
    CONSOLE_SEGMENT,
    CONSOLE_TRANSFER_OFFSET,
    install_runtime_segment,
)
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile

RECT_OFFSET = 0x20
DAMAGE_REGION_OFFSET = 0x40
DAMAGE_RECT_OFFSET = 0x50
WIDTH_OFFSET = 0x100
BOUNDS_OFFSET = 0x180
FILL_OFFSET = 0x600
FILL_STRIDE = 0x300
FILL_TRAMPOLINE_OFFSET = 0x280
INPUT_STUB_OFFSET = 0xC00
INPUT_OFFSET = 0xD00
INPUT_SLOTS = tuple(f"console.pointer_{slot:02x}" for slot in range(0x44, 0x60, 4))
SITES = (
    "console.layout_width",
    "console.layout_bounds",
    "console.caret_entry",
    "console.border_entry",
)


def _scale_edge(code: X86Emitter, *, height_va: int, origin: int, label: str) -> None:
    """Map EAX around EBX's physical anchor, rounding signed edges consistently."""
    code.raw(b"\x2b\x43" + bytes([origin]))
    code.raw(b"\xf7\x2d" + struct.pack("<I", height_va))
    code.raw(b"\x05\x80\x01\x00\x00\x83\xd2\x00\xb9\x00\x03\x00\x00\xf7\xf9")
    # IDIV truncates; floor((delta * height + 384) / 768) also covers negative
    # clipped edges without a one-pixel discontinuity across the anchor.
    code.raw(b"\x85\xd2")
    code.jump_if(Condition.GREATER_OR_EQUAL, label)
    code.raw(b"\x48")
    code.label(label)
    code.raw(b"\x03\x43" + bytes([origin]))


def build_transfer(
    *, wrapper_va: int, owner_va: int, dimensions_va: int, rect_va: int, capture_return_va: int
) -> bytes:
    """Map the shared dispatcher's PUSHAD frame, returning console ownership.

    Caller rectangles are never mutated. Only framebuffer destinations and the
    native alpha compositor's framebuffer-source capture acquire an affine;
    source-density normalization and cursor exclusions precede this helper.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x60\x8b\xf9\x8b\x1d" + struct.pack("<I", owner_va) + b"\x85\xdb")
    code.jump_if(Condition.EQUAL, "unowned")
    code.raw(b"\x81\x3d" + struct.pack("<I", dimensions_va + 4) + struct.pack("<I", 768))
    code.jump_if(Condition.LESS_OR_EQUAL, "owned")
    code.raw(b"\x8b\x4f\x18\x85\xc9")
    code.jump_if(Condition.EQUAL, "owned")
    for offset in (0, 4):
        code.raw(b"\xa1" + struct.pack("<I", dimensions_va + offset))
        code.raw(b"\x39\x41" + bytes([0x38 + offset]))
        code.jump_if(Condition.NOT_EQUAL, "capture")
    code.raw(b"\xbd\x28\x00\x00\x00")
    code.jump("rectangle")
    code.label("capture")
    code.raw(b"\x81\x7f\x20" + struct.pack("<I", capture_return_va))
    code.jump_if(Condition.NOT_EQUAL, "owned")
    code.raw(b"\x8b\x77\x24\x85\xf6")
    code.jump_if(Condition.EQUAL, "owned")
    for offset in (0, 4):
        code.raw(b"\xa1" + struct.pack("<I", dimensions_va + offset))
        code.raw(b"\x39\x46" + bytes([0x38 + offset]))
        code.jump_if(Condition.NOT_EQUAL, "owned")
    code.raw(b"\xbd\x2c\x00\x00\x00")
    code.label("rectangle")
    code.raw(b"\x8b\x34\x2f\x85\xf6")
    code.jump_if(Condition.EQUAL, "owned")
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x46" + bytes([offset]))
        _scale_edge(
            code, height_va=dimensions_va + 4, origin=0x1C + offset % 8, label=f"edge{offset}"
        )
        code.raw(b"\xa3" + struct.pack("<I", rect_va + offset))
    code.raw(b"\xc7\x04\x2f" + struct.pack("<I", rect_va))
    code.label("owned")
    code.raw(b"\xc7\x44\x24\x1c\x01\x00\x00\x00\x61\xc3")
    code.label("unowned")
    code.raw(b"\xc7\x44\x24\x1c\x00\x00\x00\x00\x61\xc3")
    return code.build()


def build_fill(
    *, wrapper_va: int, trampoline_va: int, owner_va: int, profile: BuildProfile, caret: bool
) -> bytes:
    """Apply the same affine to native border fills and GDI caret rectangles."""
    rect_arg, arg_count = (0x14, 4) if caret else (0x0C, 3)
    dimensions = profile.address("display.dimensions")
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x55\x8b\xec\x83\xec\x10\x60\x8b\x1d" + struct.pack("<I", owner_va))
    code.raw(b"\x85\xdb")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x81\x3d" + struct.pack("<I", dimensions + 4) + struct.pack("<I", 768))
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code.raw(b"\x8b\x75" + bytes([rect_arg]) + b"\x85\xf6")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\xff\x75\x08" if caret else b"\xff\x71\x18")
    code.call_absolute(profile.address("bitmap.resolve_resource"))
    code.raw(b"\x85\xc0")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x8b\x48\x30\x85\xc9")
    code.jump_if(Condition.EQUAL, "native")
    for offset in (0, 4):
        code.raw(b"\xa1" + struct.pack("<I", dimensions + offset))
        code.raw(b"\x39\x41" + bytes([0x38 + offset]))
        code.jump_if(Condition.NOT_EQUAL, "native")
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x46" + bytes([offset]))
        _scale_edge(code, height_va=dimensions + 4, origin=0x1C + offset % 8, label=f"edge{offset}")
        code.raw(b"\x89\x45" + bytes([0xF0 + offset]))
    code.raw(b"\x8d\x45\xf0\x89\x45" + bytes([rect_arg]) + b"\x61")
    for arg in reversed(range(arg_count)):
        code.raw(b"\xff\x75" + bytes([8 + arg * 4]))
    code.call_absolute(trampoline_va)
    code.raw(b"\xc9\xc2" + struct.pack("<H", arg_count * 4))
    code.label("native")
    code.raw(b"\x61\xc9")
    code.jump_absolute(trampoline_va)
    return code.build()


def build_damage(*, wrapper_va: int, profile: BuildProfile, region_va: int, rect_va: int) -> bytes:
    """Select complete console damage when scaled roots redraw beneath it.

    EAX carries the original collection, ECX the console. Preserve native
    damage at reference-sized framebuffers. A high-resolution title redraws its full
    background even when native console damage is empty, so every subsequent
    console traversal must repaint its own bounded rectangle as well.
    """
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x81\x3d" + struct.pack("<I", profile.address("display.dimensions")))
    code.raw(struct.pack("<I", 1024))
    code.jump_if(Condition.GREATER, "complete")
    code.raw(b"\x81\x3d" + struct.pack("<I", profile.address("display.dimensions") + 4))
    code.raw(struct.pack("<I", 768))
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code.label("complete")
    code.raw(b"\x52")
    for offset in range(0, 16, 4):
        code.raw(b"\x8b\x51" + bytes([0x1C + offset]))
        code.raw(b"\x89\x15" + struct.pack("<I", rect_va + offset))
    code.raw(b"\x5a\xb8" + struct.pack("<I", region_va))
    code.label("native")
    code.raw(b"\xc3")
    return code.build()


def build_input(*, wrapper_va: int, profile: BuildProfile) -> bytes:
    """Invert console presentation only while dispatching its pointer event.

    EAX is the native one-POINT handler, ECX the concrete console. Its root
    stays physically anchored while child rectangles retain authored offsets.
    Give the handler a private POINT and scope the cursor cache to that same
    coordinate domain; caller-owned coordinates and physical bookkeeping survive.
    """
    height = profile.address("display.dimensions") + 4
    cursor = profile.address("input.cursor_position")
    code = X86Emitter(base_va=wrapper_va)
    code.raw(b"\x81\x3d" + struct.pack("<I", height) + struct.pack("<I", 768))
    code.jump_if(Condition.LESS_OR_EQUAL, "native")
    code.raw(b"\x83\x7c\x24\x04\x00")
    code.jump_if(Condition.EQUAL, "native")
    code.raw(b"\x55\x8b\xec\x83\xec\x10\x53\x56\x57\x8b\xd9\x8b\xf8\x8b\x75\x08")
    for offset in (0, 4):
        code.raw(b"\xa1" + struct.pack("<I", cursor + offset))
        code.raw(b"\x89\x45" + bytes([0xF8 + offset]))
        code.raw(b"\x8b\x46" + bytes([offset]) + b"\x2b\x43" + bytes([0x1C + offset]))
        # Full signed product and floor division preserve out-of-bounds events
        # too; clamping would turn an outside click into a hit on the border.
        code.raw(b"\xb9\x00\x03\x00\x00\xf7\xe9\x8b\x0d" + struct.pack("<I", height))
        code.raw(b"\xf7\xf9\x85\xd2")
        code.jump_if(Condition.GREATER_OR_EQUAL, f"edge{offset}")
        code.raw(b"\x48")
        code.label(f"edge{offset}")
        code.raw(b"\x03\x43" + bytes([0x1C + offset]) + b"\x89\x45" + bytes([0xF0 + offset]))
        code.raw(b"\xa3" + struct.pack("<I", cursor + offset))
    code.raw(b"\x8d\x45\xf0\x50\x8b\xcb\xff\xd7\x8b\xc8")
    for offset in (0, 4):
        code.raw(
            b"\x8b\x45" + bytes([0xF8 + offset]) + b"\xa3" + struct.pack("<I", cursor + offset)
        )
    code.raw(b"\x8b\xc1\x5f\x5e\x5b\xc9\xc2\x04\x00")
    code.label("native")
    code.raw(b"\xff\xe0")
    return code.build()


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsoleFeatureCompiler:
    """Own logical console layout and its non-Blt native rectangle consumers."""

    profile: BuildProfile
    id: ClassVar[str] = "runtime2d.console"

    def precheck(self, image: PEFile) -> None:
        """Require exact native instructions before installing adapters."""
        for name in (*SITES, *INPUT_SLOTS):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                message = f"{self.id} requires pristine {name}"
                raise PatchError(message)

    def build(self, base: int) -> tuple[bytes, ExecutableMutationPlan]:
        """Build one bounded console payload without redirecting shared Blt."""
        payload = SegmentPayloadBuilder(owner=self.id, segment="console", size=CONSOLE_SEGMENT.size)
        payload.place(label="identity", offset=0, payload=CONSOLE_SEGMENT.magic)
        payload.reserve(label="Draw owner", offset=CONSOLE_OWNER_OFFSET, size=4)
        payload.reserve(label="transfer rectangle", offset=RECT_OFFSET, size=16)
        payload.place(
            label="console damage collection",
            offset=DAMAGE_REGION_OFFSET,
            payload=struct.pack(
                "<4I", 0, base + DAMAGE_RECT_OFFSET, base + DAMAGE_RECT_OFFSET + 16, 0
            ),
        )
        payload.reserve(label="console damage bounds", offset=DAMAGE_RECT_OFFSET, size=16)
        mutations = ExecutableMutationPlan(owner=self.id)
        height = self.profile.address("display.dimensions") + 4
        width_site, bounds_site = (self.profile.site(name) for name in SITES[:2])
        code = X86Emitter(base_va=base + WIDTH_OFFSET)
        code.raw(b"\x51\x52\x8b\x0d" + struct.pack("<I", height) + b"\x81\xf9\x00\x03\x00\x00")
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(b"\x69\xc0\x00\x03\x00\x00\x99\xf7\xf9")
        code.label("native")
        code.raw(b"\x5a\x59" + width_site.original + b"\xc3")
        payload.place(
            label="logical width", offset=WIDTH_OFFSET, payload=code.build(), limit=BOUNDS_OFFSET
        )
        mutations.branch(
            label="console width",
            opcode=BranchOpcode.CALL,
            site_va=width_site.va,
            expected=width_site.original,
            size=len(width_site.original),
            target_va=base + WIDTH_OFFSET,
        )
        code = X86Emitter(base_va=base + BOUNDS_OFFSET)
        code.raw(b"\x60\x8b\xde\xa1" + struct.pack("<I", height) + b"\x3d\x00\x03\x00\x00")
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        for first, last in ((0x1C, 0x24), (0x20, 0x28)):
            code.raw(b"\x8b\x46" + bytes([last]))
            _scale_edge(code, height_va=height, origin=first, label=f"bound{first}")
            code.raw(b"\x89\x46" + bytes([last]))
        code.label("native")
        code.raw(b"\x61" + bounds_site.original)
        code.jump_absolute(bounds_site.va + len(bounds_site.original))
        payload.place(
            label="physical bounds",
            offset=BOUNDS_OFFSET,
            payload=code.build(),
            limit=CONSOLE_TRANSFER_OFFSET,
        )
        mutations.branch(
            label="console bounds",
            opcode=BranchOpcode.JUMP,
            site_va=bounds_site.va,
            expected=bounds_site.original,
            size=len(bounds_site.original),
            target_va=base + BOUNDS_OFFSET,
        )
        payload.place(
            label="shared transfer",
            offset=CONSOLE_TRANSFER_OFFSET,
            payload=build_transfer(
                wrapper_va=base + CONSOLE_TRANSFER_OFFSET,
                owner_va=base + CONSOLE_OWNER_OFFSET,
                dimensions_va=height - 4,
                rect_va=base + RECT_OFFSET,
                capture_return_va=self.profile.address("console.alpha_capture_return"),
            ),
            limit=FILL_OFFSET,
        )
        for index, name in enumerate(SITES[2:]):
            offset = FILL_OFFSET + index * FILL_STRIDE
            trampoline = base + offset + FILL_TRAMPOLINE_OFFSET
            site = self.profile.site(name)
            payload.place(
                label=name,
                offset=offset,
                payload=build_fill(
                    wrapper_va=base + offset,
                    trampoline_va=trampoline,
                    owner_va=base + CONSOLE_OWNER_OFFSET,
                    profile=self.profile,
                    caret=index == 0,
                ),
                limit=offset + FILL_TRAMPOLINE_OFFSET,
            )
            code = X86Emitter(base_va=trampoline)
            code.raw(site.original)
            code.jump_absolute(site.va + len(site.original))
            payload.place(
                label=name + " native",
                offset=offset + FILL_TRAMPOLINE_OFFSET,
                payload=code.build(),
                limit=offset + FILL_STRIDE,
            )
            mutations.branch(
                label=name,
                opcode=BranchOpcode.JUMP,
                site_va=site.va,
                expected=site.original,
                target_va=base + offset,
            )
        payload.place(
            label="pointer inverse",
            offset=INPUT_OFFSET,
            payload=build_input(wrapper_va=base + INPUT_OFFSET, profile=self.profile),
            limit=CONSOLE_DAMAGE_OFFSET,
        )
        payload.place(
            label="bounded overlay damage",
            offset=CONSOLE_DAMAGE_OFFSET,
            payload=build_damage(
                wrapper_va=base + CONSOLE_DAMAGE_OFFSET,
                profile=self.profile,
                region_va=base + DAMAGE_REGION_OFFSET,
                rect_va=base + DAMAGE_RECT_OFFSET,
            ),
        )
        for index, name in enumerate(INPUT_SLOTS):
            site = self.profile.site(name)
            offset = INPUT_STUB_OFFSET + index * 16
            code = X86Emitter(base_va=base + offset)
            code.raw(b"\xb8" + site.original)
            code.jump_absolute(base + INPUT_OFFSET)
            payload.place(label=name, offset=offset, payload=code.build(), limit=offset + 16)
            mutations.pointer(
                label=name,
                slot_va=site.va,
                expected=site.original,
                target_va=base + offset,
            )
        return payload.build(), mutations

    def apply(self, image: PEFile) -> None:
        """Install the feature and its exact local redirects."""
        section = install_runtime_segment(image, CONSOLE_SEGMENT)
        payload, mutations = self.build(image.rva_to_va(section.virtual_address))
        image.write_bytes(section.pointer_to_raw_data, payload)
        mutations.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify payload, hooks and pristine fallbacks against the compiler."""
        section = image.get_section(CONSOLE_SEGMENT.logical_name)
        if section is None:
            message = "Console runtime segment is missing"
            raise PatchError(message)
        payload, mutations = self.build(image.rva_to_va(section.virtual_address))
        if image.read_bytes(section.pointer_to_raw_data, len(payload)) != payload:
            message = "Console runtime payload differs from its compiler"
            raise PatchError(message)
        mutations.verify(image)
