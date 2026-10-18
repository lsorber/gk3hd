"""Execute current-frame native label composition and its ownership boundaries."""

from __future__ import annotations

import struct
from dataclasses import replace
from functools import cache
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.mutations import ExecutableMutationPlan, MutableExecutableImage
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.catalog import PLANNER
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d import layout
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import BuildContext, PatchError, ProfileId
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.definitions.runtime2d.captions import CaptionCacheABI
    from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipCacheABI
    from gk3hd.patch.definitions.vr_panel import VRPanelABI


@pytest.fixture(scope="module")
def source() -> bytes:
    """Share immutable producer bytes across modules, never mutable images."""
    return _source_bytes()


@cache
def _source_bytes() -> bytes:
    """Use real producer payloads, not a matching fabricated cache manifest."""
    plan = PLANNER.plan_profile(ProfileId("recommended"), BuildContext(build_id=GOG_BUILD.id))
    pristine = _source(GOG_BUILD)
    apply = ExecutableMutationPlan.apply

    def populate(owner: ExecutableMutationPlan, image: MutableExecutableImage) -> None:
        for mutation in owner._mutations:
            if not 0x401000 <= mutation.va < 0x800000:
                continue
            offset = image.va_to_offset(mutation.va)
            if image.read_bytes(offset, len(mutation.expected)) == bytes(len(mutation.expected)):
                image.write_bytes(offset, mutation.expected)
                pristine.write_bytes(pristine.va_to_offset(mutation.va), mutation.expected)
        apply(owner, image)

    with pytest.MonkeyPatch.context() as context:
        context.setattr(ExecutableMutationPlan, "apply", populate)
        OperationExecutor().execute(pristine, plan.compile_operations())
    image = OperationExecutor().execute(pristine, plan.compile_operations())
    return image.to_bytes()


@pytest.mark.parametrize("changed", ["magic", "version", "caps", "descriptor", "cells", "world"])
def test_tooltip_dependencies_fail_before_writing(source: bytes, changed: str) -> None:
    image = PEFile(source)
    tooltip = TooltipFeatureCompiler.cache_abi(image)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    symbols = layout.RuntimeImage(image).prepare()
    base = symbols.va(layout.SYSTEM_CONTROL_SEGMENT.logical_name)
    if changed in {"magic", "version", "caps", "descriptor"}:
        address = (
            base
            + {
                "magic": layout.SYSTEM_CONTROL_TOOLTIP_CACHE_ABI_OFFSET,
                "version": layout.SYSTEM_CONTROL_TOOLTIP_CACHE_ABI_OFFSET + 8,
                "caps": layout.SYSTEM_CONTROL_TOOLTIP_PANEL_DESCRIPTOR_OFFSET + 0x68,
                "descriptor": layout.SYSTEM_CONTROL_TOOLTIP_PANEL_DESCRIPTOR_OFFSET,
            }[changed]
        )
        image.write_u32_va(address, 0)
    elif changed == "cells":
        tooltip = replace(tooltip, surface_va=tooltip.surface_va + 4)
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    compiler = VRPanelCompiler(
        profile=GOG_BUILD,
        expected_presenter_va=image.read_u32_va(slot),
        world_enabled_va=0 if changed == "world" else scene.abi(image).enabled_va,
        tooltip=tooltip,
    )
    before = image.to_bytes()
    with pytest.raises(PatchError, match="tooltip"):
        compiler.apply(image)
    assert image.to_bytes() == before


def _configured_machine(
    source: bytes,
    caption_state: str,
    tooltip_state: str,
    owner: int,
) -> tuple[Uc, CaptionCacheABI, TooltipCacheABI, VRPanelABI, int]:
    image = PEFile(source)
    caption = CaptionFeatureCompiler.cache_abi(image)
    tooltip = TooltipFeatureCompiler.cache_abi(image)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    previous = GOG_BUILD.address("ui.container_draw")
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    image.write_u32_va(slot, previous)
    compiler = VRPanelCompiler(
        profile=GOG_BUILD,
        expected_presenter_va=previous,
        world_enabled_va=scene.abi(image).enabled_va,
        caption=caption,
        tooltip=tooltip,
    )
    compiler.apply(image)
    compiler.postcheck(image)
    panel = compiler.abi(image)
    cpu = _machine(image)
    module, resolve, bridge, query = (_HEAP + offset for offset in (0xA000, 0xA100, 0xA200, 0xA300))
    wrapper, device = _HEAP + 0x5000, _HEAP + 0x6000

    def word(address: int, value: int) -> None:
        cpu.mem_write(address, struct.pack("<I", value))

    def read(address: int) -> int:
        return struct.unpack("<I", cpu.mem_read(address, 4))[0]

    for address, value in (
        (panel.enabled_va, 1),
        (scene.abi(image).enabled_va, 1),
        (GOG_BUILD.address("win32.GetModuleHandleA"), module),
        (GOG_BUILD.address("win32.GetProcAddress"), resolve),
        (GOG_BUILD.address("high_resolution_3d.render_wrapper_ptr"), wrapper),
        (wrapper + 0x4E8, device),
        (panel.ownership_query_slot_va, query),
        (caption.replay_count_va, 0xFFFFFFFF if caption_state == "wrap" else 17),
        (tooltip.replay_count_va, 0xFFFFFFFF if tooltip_state == "wrap" else 29),
        (caption.ready_va, caption_state != "not_ready"),
        (caption.surface_va, 0 if caption_state == "missing" else _HEAP + 0x8000),
        (tooltip.visible_va, tooltip_state != "hidden"),
        (tooltip.pending_va, tooltip_state == "pending"),
        (tooltip.surface_va, 0 if tooltip_state == "missing" else _HEAP + 0x9000),
        (query + 16, owner),
        (panel.recenter_va, 1),
    ):
        word(address, value)
    for name, value, pointer in (
        ("high_resolution_3d.display_width_ptr", 1280, _HEAP + 0xC000),
        ("high_resolution_3d.display_height_ptr", 800, _HEAP + 0xC004),
    ):
        word(GOG_BUILD.address(name), pointer)
        word(pointer, value)
    cpu.mem_write(caption.rect_va, struct.pack("<4i", 100, 600, 1100, 750))
    cpu.mem_write(tooltip.source_rect_va, struct.pack("<4i", 0, 0, 118, 21))
    cpu.mem_write(tooltip.destination_rect_va, struct.pack("<4i", 702, 432, 820, 453))
    cpu.mem_write(previous, b"\xc3")
    cpu.mem_write(module, bytes.fromhex("c2 04 00"))
    cpu.mem_write(resolve, bytes.fromhex("c2 08 00"))
    cpu.mem_write(bridge, bytes.fromhex("c2 0c 00"))
    cpu.mem_write(query, b"\xa1" + struct.pack("<I", query + 16) + b"\xc3")

    return cpu, caption, tooltip, panel, image.read_u32_va(slot)


def _submission(cpu: Uc, panel: VRPanelABI, device: int) -> tuple[int, int, list[tuple[int, ...]]]:
    def read(address: int) -> int:
        return struct.unpack("<I", cpu.mem_read(address, 4))[0]

    stack = cpu.reg_read(UC_X86_REG_ESP)
    assert read(stack + 4) == device
    operation = read(stack + 8)
    parts: list[tuple[int, ...]] = []
    if operation == 1:
        assert read(stack + 12) == 0
    else:
        assert read(stack + 12) == panel.frame_va
        assert (read(panel.frame_va + 8), read(panel.frame_va + 12)) == (1280, 800)
        if operation in (4, 5):
            assert all(
                struct.unpack("<f", cpu.mem_read(panel.frame_va + 192 + index * 40 + 36, 4))[0] == 1
                for index in range(read(panel.frame_va + 188))
            )
            parts = [
                struct.unpack("<3I6i", cpu.mem_read(panel.frame_va + 192 + index * 40, 36))
                for index in range(read(panel.frame_va + 188))
            ]
    return operation, read(panel.recenter_va), parts


def _publish(cpu: Uc, producers: tuple[tuple[str, int], ...]) -> None:
    for state, counter in producers:
        if state != "stale":
            value = struct.unpack("<I", cpu.mem_read(counter, 4))[0]
            cpu.mem_write(counter, struct.pack("<I", (value + 1) & 0xFFFFFFFF))


@pytest.mark.parametrize("caption_state", ["fresh", "stale", "not_ready", "missing", "wrap"])
@pytest.mark.parametrize(
    "tooltip_state", ["fresh", "stale", "pending", "hidden", "missing", "wrap"]
)
@pytest.mark.parametrize("owner", [1, 2, 0], ids=["world", "modal", "closed"])
def test_labels_share_one_frame_and_never_replace_modal_interfaces(
    source: bytes,
    caption_state: str,
    tooltip_state: str,
    owner: int,
) -> None:
    cpu, caption, tooltip, panel, entry = _configured_machine(
        source, caption_state, tooltip_state, owner
    )
    previous = GOG_BUILD.address("ui.container_draw")
    module, resolve, bridge, query = (_HEAP + offset for offset in (0xA000, 0xA100, 0xA200, 0xA300))
    device = _HEAP + 0x6000
    snapshots: list[tuple[int, int, list[tuple[int, ...]]]] = []
    publish = True

    def word(address: int, value: int) -> None:
        cpu.mem_write(address, struct.pack("<I", value))

    def read(address: int) -> int:
        return struct.unpack("<I", cpu.mem_read(address, 4))[0]

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == previous and publish:
            _publish(
                current,
                (
                    (caption_state, caption.replay_count_va),
                    (tooltip_state, tooltip.replay_count_va),
                ),
            )
        elif address == module:
            current.reg_write(UC_X86_REG_EAX, 123)
        elif address == resolve:
            current.reg_write(UC_X86_REG_EAX, bridge)
        elif address == bridge:
            snapshots.append(_submission(current, panel, device))
            current.reg_write(UC_X86_REG_EAX, 0)

    cpu.hook_add(UC_HOOK_CODE, observe)

    def invoke() -> None:
        word(_STACK, _RETURN)
        cpu.reg_write(UC_X86_REG_ESP, _STACK)
        cpu.reg_write(UC_X86_REG_EBX, 99)
        cpu.reg_write(UC_X86_REG_ECX, 77)
        cpu.emu_start(entry, _RETURN, count=3000)
        assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
        assert cpu.reg_read(UC_X86_REG_EBX) == 99
        assert cpu.reg_read(UC_X86_REG_ECX) == 77

    invoke()
    assert read(tooltip.isolation_enabled_va) == int(owner != 0)
    parts = _expected_parts(caption_state, tooltip_state, owner, caption.key)
    operation = {0: 1, 2: 5 if parts else 0}.get(owner, 4 if parts else 2)
    assert snapshots == [(operation, 3 if parts and owner == 1 else 1, parts)]
    if owner == 2:
        assert struct.unpack("<f", cpu.mem_read(panel.frame_va + 20, 4))[0] == pytest.approx(2.4)
    # No fresh publication in a following frame must remove both sources,
    # even while their prior surfaces and visibility remain readable.
    publish = False
    invoke()
    assert snapshots[-1] == ({0: 1, 2: 0}.get(owner, 2), int(owner == 0), [])
    # A modal screen after any label batch must not inherit transparency.
    word(query + 16, 2)
    word(panel.recenter_va, 3)
    invoke()
    assert snapshots[-1] == (0, 1, [])
    assert read(panel.frame_va + 188) == 0


@pytest.mark.parametrize("panel_enabled", [False, True])
@pytest.mark.parametrize("world_enabled", [False, True])
def test_isolation_ownership_is_current_before_native_ui_and_released_on_failure(
    source: bytes, panel_enabled: bool, world_enabled: bool
) -> None:
    cpu, _caption, tooltip, panel, entry = _configured_machine(source, "stale", "stale", 1)
    previous = GOG_BUILD.address("ui.container_draw")
    cpu.mem_write(panel.enabled_va, struct.pack("<I", panel_enabled))
    cpu.mem_write(panel.world_enabled_va, struct.pack("<I", world_enabled))
    cpu.mem_write(tooltip.isolation_enabled_va, struct.pack("<I", 1))
    observed = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == previous:
            observed.append(
                struct.unpack("<I", current.mem_read(tooltip.isolation_enabled_va, 4))[0]
            )
        elif address == _HEAP + 0xA000:
            # The renderer is unavailable. Publication must be withdrawn,
            # never leave a forced reference-height owner behind.
            current.reg_write(UC_X86_REG_EAX, 0)

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.mem_write(_STACK, struct.pack("<I", _RETURN))
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.emu_start(entry, _RETURN, count=3000)
    assert observed == [int(panel_enabled and world_enabled)]
    assert cpu.mem_read(tooltip.isolation_enabled_va, 4) == bytes(4)


@pytest.mark.parametrize("outcome", ["success", "failed", "skipped", "hidden", "invalid", "modal"])
@pytest.mark.parametrize("counter", [23, 0xFFFFFFFF])
def test_native_tooltip_producer_publishes_only_a_completed_current_transfer(
    source: bytes, outcome: str, counter: int
) -> None:
    image = PEFile(source)
    cpu = _machine(image)
    base = layout.RuntimeImage(image).prepare().va(layout.SYSTEM_CONTROL_SEGMENT.logical_name)
    tooltip = TooltipFeatureCompiler.cache_abi(image)
    obj, pointer_check, layer = (_HEAP + offset for offset in (0x1000, 0xA000, 0x2000))
    helper = base + TooltipFeatureCompiler._off_tooltip_background_helper

    def word(address: int, value: int) -> None:
        cpu.mem_write(address, struct.pack("<I", value))

    for address, value in (
        (GOG_BUILD.address("display.dimensions") + 4, 800),
        (base + layout.SYSTEM_CONTROL_TOOLTIP_OBJECT_PTR_OFFSET, obj),
        (tooltip.visible_va, 1),
        (tooltip.replay_count_va, counter),
        (base + layout.SYSTEM_CONTROL_TOOLTIP_PANEL_BLT_RESULT_OFFSET, 0),
        (obj, GOG_BUILD.address("tooltip.vtable")),
        (obj + 0x194, _HEAP + 0x5000),
        (obj + 0x198, 4),
        (base + layout.SYSTEM_CONTROL_TOOLTIP_TEXT_POINTER_OFFSET, _HEAP + 0x5000),
        (base + layout.SYSTEM_CONTROL_TOOLTIP_TEXT_LENGTH_OFFSET, 4),
        (GOG_BUILD.address("win32.IsBadReadPtr"), pointer_check),
        (layer, GOG_BUILD.address("confirm_quit.vtable")),
        (_STACK, _RETURN),
    ):
        word(address, value)
    cpu.mem_write(obj + 0x18, bytes([outcome != "hidden"]))
    cpu.mem_write(obj + 0x188, b"\x01")
    cpu.mem_write(pointer_check, bytes.fromhex("c2 08 00"))
    cpu.mem_write(GOG_BUILD.address("ui.current_layer"), b"\xc3")
    cpu.mem_write(helper, b"\xc3")
    calls = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == GOG_BUILD.address("ui.current_layer"):
            current.reg_write(UC_X86_REG_EAX, layer if outcome == "modal" else 0)
        elif address == pointer_check:
            current.reg_write(UC_X86_REG_EAX, int(outcome == "invalid"))
        elif address == helper:
            calls.append(address)
            if outcome != "skipped":
                word(
                    base + layout.SYSTEM_CONTROL_TOOLTIP_PANEL_BLT_RESULT_OFFSET,
                    0 if outcome == "success" else 0x80004005,
                )

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.reg_write(UC_X86_REG_ESP, _STACK)
    cpu.reg_write(UC_X86_REG_EBX, 99)
    cpu.emu_start(base + TooltipFeatureCompiler._off_tooltip_frame_presenter, _RETURN, count=3000)
    result = struct.unpack("<I", cpu.mem_read(tooltip.replay_count_va, 4))[0]
    assert result == ((counter + 1) & 0xFFFFFFFF if outcome == "success" else counter)
    assert len(calls) == int(outcome in {"success", "failed", "skipped"})
    assert cpu.reg_read(UC_X86_REG_ESP) == _STACK + 4
    assert cpu.reg_read(UC_X86_REG_EBX) == 99


def _expected_parts(
    caption_state: str,
    tooltip_state: str,
    owner: int,
    key: int,
) -> list[tuple[int, ...]]:
    parts = []
    if owner in (1, 2):
        if caption_state in {"fresh", "wrap"}:
            parts.append((_HEAP + 0x8000, 9, key, 100, 600, 1100, 750, 100, 600))
        if owner == 1 and tooltip_state in {"fresh", "wrap"}:
            parts.append((_HEAP + 0x9000, 4, 0, 0, 0, 118, 21, 702, 432))
    return parts
