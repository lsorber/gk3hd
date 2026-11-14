"""Native UI lifetimes and retained controller shortcuts for standalone VR."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, decode_rel32_branch
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_loading import VRLoadingCompiler
from gk3hd.patch.definitions.vr_native_scene import emit_native_scene_guard
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_game_menu import VRGameMenuABI
    from gk3hd.patch.definitions.vr_input import VRInputABI
    from gk3hd.patch.definitions.vr_ownership import VROwnershipABI
    from gk3hd.patch.definitions.vr_panel import VRPanelABI


@dataclass(frozen=True, slots=True)
class VRInputLifetimeABI:
    """Read-only native owner key and independent explicit lifetime witnesses."""

    bind: int
    query: int
    epoch: int
    overflow: int
    transitions: int
    observed_key: int
    observations: int


def compile_input_lifetime(
    image: PEFile,
    *,
    profile: BuildProfile,
    panel: VRPanelABI,
    inputs: VRInputABI,
    ownership: VROwnershipABI,
    observe: bool = False,
    shortcuts: VRGameMenuABI | None = None,
) -> VRInputLifetimeABI:
    """Scope retained shortcuts to the native UI that receives them.

    The initial scope is ordinary room/inventory shortcuts. The renderer-owned
    Pause subpages keep ordinary input until they have their own lifetime.
    Passing the shortcut ABI links read/acknowledgement filters to the
    real native consumers. Producing a key alone never enables dispatch.
    """
    name = ".gk3ce"
    if image.get_section(name) is not None:
        msg = "native controller owner already exists"
        raise PatchError(msg)
    if shortcuts is not None:
        for slot, section_name in (
            (inputs.shortcut_filter_slot_va, ".gk3vi"),
            (shortcuts.shortcut_filter_slot_va, ".gk3gu"),
        ):
            owner_section = image.get_section(section_name)
            if (
                owner_section is None
                or image.read_u32_va(slot)
                or b"\xff\x15" + struct.pack("<I", slot)
                not in image.read_bytes(
                    owner_section.pointer_to_raw_data, owner_section.size_of_raw_data
                )
            ):
                msg = "native shortcut filter is absent or already owned"
                raise PatchError(msg)
    site = profile.site("vr.input_transition_begin")
    if image.read_bytes(image.va_to_offset(site.va), len(site.original + site.context_after)) != (
        site.original + site.context_after
    ):
        msg = "native input transition anchor changed"
        raise PatchError(msg)
    loading = image.get_section(VRLoadingCompiler.section_name)
    if loading is None:
        msg = "native controller owner requires compiled scene lifetimes"
        raise PatchError(msg)
    loading_base = image.rva_to_va(loading.virtual_address)
    redirects = []
    for label, offset in VRLoadingCompiler.scene_boundaries():
        point = profile.site(label)
        original = image.read_bytes(image.va_to_offset(point.va), 5)
        target = decode_rel32_branch(
            opcode=BranchOpcode.JUMP, site_va=point.va, instruction=original
        )
        if target != loading_base + offset:
            msg = "native input scene lifetime changed"
            raise PatchError(msg)
        redirects.append((point, original, target))

    section = image.add_section(name, bytes(0x2000), 0xE0000060)
    base = image.rva_to_va(section.virtual_address)
    thread, epoch, overflow = 0x10, 0x18, 0x20
    layer, scene, hand, mode, transitions = 0x24, 0x28, 0x2C, 0x30, 0x34
    observed_key, observations = 0x40, 0x48
    bridge, busy, unwinds = 0x4C, 0x50, 0x54
    bindings, reads, last_mask, decisions = 0x58, 0x5C, 0x60, 0x64
    module = 0x6C
    e = X86Emitter(base_va=base + 0x1000)

    def absolute(opcode: bytes, address: int) -> None:
        e.raw(opcode + struct.pack("<I", address))

    def state(opcode: bytes, offset: int) -> None:
        absolute(opcode, base + offset)

    def store(offset: int, value: int) -> None:
        state(b"\xc7\x05", offset)
        e.raw(struct.pack("<I", value))

    def active(rejected: str) -> None:
        for address in (inputs.enabled_va, panel.enabled_va):
            absolute(b"\x83\x3d", address)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, rejected)

    e.label("bind")
    active("bind_no")
    e.raw(bytes.fromhex("64 a1 24 00 00 00 85 c0"))  # TEB's Win32 thread identity.
    e.jump_if(Condition.EQUAL, "bind_no")
    state(b"\x83\x3d", thread)
    e.raw(b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "bind_existing")
    state(b"\xa3", thread)
    e.label("bind_existing")
    state(b"\x3b\x05", thread)
    e.raw(bytes.fromhex("0f 94 c0 0f b6 c0 c3"))
    e.label("bind_no")
    e.raw(bytes.fromhex("31 c0 c3"))

    e.label("query")
    e.raw(bytes.fromhex("9c 53 56 57"))
    active("unknown")
    e.raw(bytes.fromhex("64 a1 24 00 00 00 85 c0"))
    e.jump_if(Condition.EQUAL, "unknown")
    state(b"\x3b\x05", thread)
    e.jump_if(Condition.NOT_EQUAL, "unknown")
    state(b"\x83\x3d", overflow)
    e.raw(b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "unknown")
    absolute(b"\xa1", profile.address("engine.loop"))
    for instruction in (b"", bytes.fromhex("8b 80 44 04 00 00"), b"\x8b\x40\x44"):
        e.raw(instruction + bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "unknown")
    absolute(b"\x8b\x0d", profile.address("vr.room_global"))
    e.raw(bytes.fromhex("85 c9"))
    e.jump_if(Condition.EQUAL, "unknown")
    emit_native_scene_guard(e, profile, register="ecx", rejected="unknown")
    e.raw(bytes.fromhex("8b f1"))
    e.call_absolute(profile.address("ui.current_layer"))
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.EQUAL, "unknown")
    for key in ("vr.room_layer_vtable", "inventory.vtable"):
        e.raw(b"\x81\x38" + struct.pack("<I", profile.address(key)))
        e.jump_if(Condition.EQUAL, "known_layer")
    e.jump("unknown")
    e.label("known_layer")
    e.raw(bytes.fromhex("8b d8"))
    absolute(b"\x8b\x3d", panel.pointing_hand_va)
    e.raw(bytes.fromhex("83 ff 01"))
    e.jump_if(Condition.ABOVE, "unknown")
    e.call_absolute(ownership.query_va)
    e.raw(bytes.fromhex("85 c0"))
    e.jump_if(Condition.EQUAL, "unknown")
    for opcode, offset in (
        (b"\x3b\x1d", layer),
        (b"\x3b\x35", scene),
        (b"\x3b\x3d", hand),
        (b"\x3b\x05", mode),
    ):
        state(opcode, offset)
        e.jump_if(Condition.NOT_EQUAL, "changed")
    e.jump("key")
    e.label("changed")
    for opcode, offset in (
        (b"\x89\x1d", layer),
        (b"\x89\x35", scene),
        (b"\x89\x3d", hand),
        (b"\xa3", mode),
    ):
        state(opcode, offset)
    e.call("bump")
    e.label("key")
    state(b"\x83\x3d", overflow)
    e.raw(b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "unknown")
    # Read a coherent 64-bit key even if a loading thread retires the scene.
    # Epoch zero is never published, so this locked comparison only reads.
    e.raw(bytes.fromhex("31 c0 31 d2 31 db 31 c9"))
    state(bytes.fromhex("f0 0f c7 0d"), epoch)
    state(b"\x83\x3d", overflow)
    e.raw(b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "unknown")
    e.raw(bytes.fromhex("5f 5e 5b 9d"))
    e.raw(b"\xc3")
    e.label("unknown")
    e.raw(bytes.fromhex("5f 5e 5b 9d b8 00 00 00 00 ba 00 00 00 00 c3"))

    e.label("bump")
    e.raw(b"\x60")
    state(b"\xa1", epoch)
    state(b"\x8b\x15", epoch + 4)
    e.label("bump_retry")
    state(b"\x83\x3d", overflow)
    e.raw(b"\x00")
    e.jump_if(Condition.NOT_EQUAL, "bump_done")
    e.raw(bytes.fromhex("8b d8 8b ca 83 c3 01 83 d1 00 8b f3 0b f1"))
    e.jump_if(Condition.EQUAL, "bump_exhausted")
    state(bytes.fromhex("f0 0f c7 0d"), epoch)
    e.jump_if(Condition.NOT_EQUAL, "bump_retry")
    e.jump("bump_done")
    e.label("bump_exhausted")
    state(b"\xc7\x05", overflow)
    e.raw(struct.pack("<I", 1))
    e.label("bump_done")
    e.raw(bytes.fromhex("61 c3"))

    def lifetime(label: str) -> None:
        e.label(label)
        e.raw(bytes.fromhex("9c 60"))
        active(label + "_native")
        e.call("bump")
        state(bytes.fromhex("f0 ff 05"), transitions)
        e.label(label + "_native")
        e.raw(bytes.fromhex("61 9d"))

    lifetime("transition")
    e.raw(site.original)
    e.jump_absolute(site.va + len(site.original))
    for index, (_point, _original, target) in enumerate(redirects):
        lifetime(f"scene_{index}")
        e.jump_absolute(target)
    presenter_slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    previous = image.read_u32_va(presenter_slot)
    if shortcuts is not None:
        e.label("resolve")
        e.push_imm32(base + 0x80)
        absolute(b"\xff\x15", profile.address("win32.GetModuleHandleA"))
        state(b"\x3b\x05", module)
        e.jump_if(Condition.EQUAL, "resolved")
        state(b"\xa3", module)
        store(bridge, 0)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "resolved")
        e.push_imm32(base + 0xA0)
        e.raw(b"\x50")
        absolute(b"\xff\x15", profile.address("win32.GetProcAddress"))
        state(b"\xa3", bridge)
        e.label("resolved")
        e.raw(b"\xc3")
        for label, mask in (("filter_input", 10), ("filter_menu", 4)):
            e.label(label)
            e.raw(bytes.fromhex("9c 60"))
            e.call("resolve")
            state(b"\x83\x3d", bridge)
            e.raw(b"\x00")
            e.jump_if(Condition.EQUAL, label + "_done")
            e.push_imm32(0)
            e.push_imm32(2)
            state(b"\xff\x15", bridge)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.NOT_SIGN, label + "_done")
            state(b"\xff\x05", reads)
            e.raw(bytes((0x83, 0xE0, mask)))
            state(b"\xa3", last_mask)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, label + "_empty")
            state(b"\xff\x05", decisions)
            e.label(label + "_empty")
            e.raw(bytes.fromhex("89 44 24 14"))  # Only the saved EDX is replaced.
            e.label(label + "_done")
            e.raw(bytes.fromhex("61 9d c3"))
        e.label("observe")
        e.raw(bytes.fromhex("9c 60"))
        state(b"\x83\x3d", busy)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "nested")
        store(busy, 1)
        e.raw(b"\x68")
        e.absolute_label("unwind")
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
        e.call("bind")
        e.call("resolve")
        state(b"\x83\x3d", bridge)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "present_previous")
        e.raw(b"\x68")
        e.absolute_label("query")
        e.push_imm32(1)
        state(b"\xff\x15", bridge)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "present_previous")
        state(b"\xff\x05", bindings)
        e.label("present_previous")
        e.call_absolute(previous)
        e.call("resolve")  # The real loader can unload the runtime inside presentation.
        if observe:
            e.call("query")
            state(b"\xa3", observed_key)
            state(b"\x89\x15", observed_key + 4)
            state(b"\xff\x05", observations)
        state(b"\x83\x3d", bridge)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "present_done")
        e.push_imm32(0)
        e.push_imm32(3)
        state(b"\xff\x15", bridge)
        e.label("present_done")
        store(busy, 0)
        e.raw(bytes.fromhex("8b 04 24 64 a3 00 00 00 00 83 c4 08"))
        e.jump("present_return")
        e.label("nested")
        e.call_absolute(previous)
        e.label("present_return")
        e.raw(bytes.fromhex("61 9d c3"))
        e.label("unwind")
        e.raw(bytes.fromhex("8b 44 24 04 f7 40 04 06 00 00 00"))
        e.jump_if(Condition.EQUAL, "unwind_search")
        store(busy, 0)
        e.call("bump")
        state(b"\xff\x05", unwinds)
        e.label("unwind_search")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
    elif observe:
        e.label("observe")
        e.raw(bytes.fromhex("9c 60"))
        e.call("bind")
        e.call("query")
        state(b"\xa3", observed_key)
        state(b"\x89\x15", observed_key + 4)
        state(b"\xff\x05", observations)
        e.raw(bytes.fromhex("61 9d"))
        e.jump_absolute(previous)
    labels = {name: address for name, _offset, address in e.listing()}
    header = bytearray(0x1000)
    header[:8] = b"GK3COWN1"
    struct.pack_into("<Q", header, epoch, 1)
    if shortcuts is not None:
        for offset, text in (
            (0x80, b"openxr_wxr32.dll\0"),
            (0xA0, b"Gk3hdControllerShortcutsV1\0"),
        ):
            header[offset : offset + len(text)] = text
    payload = bytes(header) + e.build(maximum_size=0x1000)
    image.write_bytes(section.pointer_to_raw_data, payload)
    plan = ExecutableMutationPlan(owner="private_native_input_owner")
    plan.branch(
        label="native layer command lifetime",
        opcode=BranchOpcode.JUMP,
        site_va=site.va,
        expected=site.original,
        target_va=labels["transition"],
        size=len(site.original),
    )
    for index, (point, original, _target) in enumerate(redirects):
        plan.branch(
            label=point.symbol,
            opcode=BranchOpcode.JUMP,
            site_va=point.va,
            expected=original,
            target_va=labels[f"scene_{index}"],
            size=5,
        )
    if observe or shortcuts is not None:
        plan.pointer(
            label="private native input observation",
            slot_va=presenter_slot,
            expected=previous,
            target_va=labels["observe"],
        )
    if shortcuts is not None:
        for slot, label in (
            (inputs.shortcut_filter_slot_va, "filter_input"),
            (shortcuts.shortcut_filter_slot_va, "filter_menu"),
        ):
            plan.pointer(label=label, slot_va=slot, expected=0, target_va=labels[label])
    plan.apply(image)
    return VRInputLifetimeABI(
        labels["bind"],
        labels["query"],
        base + epoch,
        base + overflow,
        base + transitions,
        base + observed_key,
        base + observations,
    )
