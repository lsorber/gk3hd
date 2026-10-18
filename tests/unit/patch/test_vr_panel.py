"""Final-page VR presentation preserves ordinary composition and callback ABI."""

from __future__ import annotations

import struct
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.layout import CAPTION_SEGMENT, RuntimeImage
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_registry import _caption_compiler
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.definitions.vr_panel import VRPanelABI


def _image(profile: BuildProfile) -> PEFile:
    image = _source(profile)
    TransitionFrameCompiler(profile=profile).apply(image)
    return image


def _assert_panel_scale(machine: Uc, frame_va: int, operation: int) -> None:
    width, distance = struct.unpack("<2f", machine.mem_read(frame_va + 20, 8))
    assert width == pytest.approx(2.4 if operation == 0 else 1.6)
    assert distance == pytest.approx(1.6)


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_panel_is_dormant_and_verifies_on_supported_builds(profile: BuildProfile) -> None:
    image = _image(profile)
    compiler = VRPanelCompiler(profile=profile)
    compiler.apply(image)
    compiler.postcheck(image)
    abi = compiler.abi(image)
    assert image.read_u32_va(abi.enabled_va) == 0
    assert image.read_u32_va(abi.submitted_frames_va) == 0
    with pytest.raises(PatchError, match="already installed"):
        compiler.apply(image)


def test_unknown_presenter_is_rejected_before_mutation() -> None:
    image = _image(GOG_BUILD)
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    image.write_u32_va(slot, GOG_BUILD.address("ui.container_draw"))
    before = image.to_bytes()
    with pytest.raises(PatchError, match="unexpected final-page presenter"):
        VRPanelCompiler(profile=GOG_BUILD).apply(image)
    assert image.to_bytes() == before


@pytest.mark.parametrize("changed", ["payload", "redirect"])
def test_modified_panel_installation_fails_verification(changed: str) -> None:
    image = _image(GOG_BUILD)
    compiler = VRPanelCompiler(profile=GOG_BUILD)
    compiler.apply(image)
    address = (
        compiler.abi(image).frame_va
        if changed == "payload"
        else TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    )
    image.write_bytes(image.va_to_offset(address), b"\xcc")
    with pytest.raises(PatchError, match="verification"):
        compiler.postcheck(image)


def _linked_panel(
    *, paired: bool = False, captions: bool = False
) -> tuple[PEFile, VRPanelABI, int]:
    image = _image(GOG_BUILD)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    # A verified caller supplies its already-installed presenter, not an
    # arbitrary runtime chain discovered by scanning machine instructions.
    previous = GOG_BUILD.address("ui.container_draw")
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    image.write_u32_va(slot, previous)
    world_enabled = scene.abi(image).enabled_va if paired else 0
    caption = None
    if captions:
        runtime = RuntimeImage(image)
        symbols = runtime.prepare()
        producer = replace(_caption_compiler(), symbols=symbols, profile=GOG_BUILD)
        runtime.add_section(
            CAPTION_SEGMENT.logical_name,
            producer._payload(section_va=symbols.va(CAPTION_SEGMENT.logical_name)),
            CAPTION_SEGMENT.characteristics,
        )
        caption = CaptionFeatureCompiler.cache_abi(image)
    compiler = VRPanelCompiler(
        profile=GOG_BUILD,
        expected_presenter_va=previous,
        world_enabled_va=world_enabled,
        caption=caption,
    )
    compiler.apply(image)
    compiler.postcheck(image)
    return image, compiler.abi(image), image.read_u32_va(slot)


def _panel_machine(
    outcome: str, *, captions: bool = False
) -> tuple[Uc, int, VRPanelABI, list[str], list[int]]:
    paired = captions or outcome in {"shared", "world_only", "close_failure", "disabled_mid"}
    image, abi, entry = _linked_panel(paired=paired, captions=captions)
    machine = _machine(image)
    previous = GOG_BUILD.address("ui.container_draw")
    world_enabled = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).abi(image).enabled_va
    module, resolve, bridge = (_HEAP + offset for offset in (0xA000, 0xA100, 0xA200))
    wrapper, device = _HEAP + 0x5000, _HEAP + 0x6000

    def word(address: int, value: int) -> None:
        machine.mem_write(address, struct.pack("<I", value))

    def read_word(address: int) -> int:
        return struct.unpack("<I", machine.mem_read(address, 4))[0]

    word(abi.enabled_va, outcome not in {"disabled", "world_only", "close_failure", "disabled_mid"})
    word(world_enabled, paired and outcome != "disabled_mid")
    word(GOG_BUILD.address("win32.GetModuleHandleA"), module)
    word(GOG_BUILD.address("win32.GetProcAddress"), resolve)
    word(GOG_BUILD.address("high_resolution_3d.render_wrapper_ptr"), wrapper)
    word(wrapper + 0x4E8, device)
    for name, value, pointer in (
        ("high_resolution_3d.display_width_ptr", 1280, _HEAP + 0xC000),
        ("high_resolution_3d.display_height_ptr", 800, _HEAP + 0xC004),
    ):
        word(GOG_BUILD.address(name), pointer)
        word(pointer, value)
    machine.mem_write(previous, bytes.fromhex("bb 78 56 34 12 c3"))
    machine.mem_write(module, bytes.fromhex("c2 04 00"))
    machine.mem_write(resolve, bytes.fromhex("c2 08 00"))
    machine.mem_write(bridge, bytes.fromhex("c2 0c 00"))
    calls: list[str] = []
    operations: list[int] = []

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == previous:
            calls.append("ordinary UI")
        elif address == module:
            current.reg_write(UC_X86_REG_EAX, 0 if outcome == "absent" else 123)
        elif address == resolve:
            current.reg_write(UC_X86_REG_EAX, bridge)
        elif address == bridge:
            stack = current.reg_read(UC_X86_REG_ESP)
            assert read_word(stack + 4) == device
            operation = read_word(stack + 8)
            operations.append(operation)
            if operation in {0, 2, 3}:
                calls.append({0: "VR panel", 2: "VR world finalizer", 3: "VR caption"}[operation])
                assert read_word(stack + 12) == abi.frame_va
                assert (read_word(abi.frame_va + 8), read_word(abi.frame_va + 12)) == (1280, 800)
                _assert_panel_scale(current, abi.frame_va, operation)
                word(abi.frame_va + 164, 1)
                current.reg_write(
                    UC_X86_REG_EAX,
                    0x80004005 if outcome == "failure" else (1 if outcome == "hidden" else 0),
                )
            else:
                assert operation == 1
                assert read_word(stack + 12) == 0
                current.reg_write(UC_X86_REG_EAX, 0x80004005 if outcome == "close_failure" else 0)

    machine.hook_add(UC_HOOK_CODE, observe)
    return machine, entry, abi, calls, operations


@pytest.mark.parametrize(
    "outcome",
    [
        "disabled",
        "success",
        "hidden",
        "failure",
        "absent",
        "shared",
        "world_only",
        "close_failure",
        "disabled_mid",
    ],
)
def test_completed_ui_runs_before_panel_and_keeps_caller_state(outcome: str) -> None:
    machine, entry, abi, calls, operations = _panel_machine(outcome)

    def word(address: int, value: int) -> None:
        machine.mem_write(address, struct.pack("<I", value))

    def read_word(address: int) -> int:
        return struct.unpack("<I", machine.mem_read(address, 4))[0]

    def invoke() -> None:
        word(_STACK, _RETURN)
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        machine.reg_write(UC_X86_REG_EBX, 99)
        machine.reg_write(UC_X86_REG_ECX, 77)
        machine.emu_start(entry, _RETURN, count=1000)
        assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
        assert machine.reg_read(UC_X86_REG_EBX) == 99
        assert machine.reg_read(UC_X86_REG_ECX) == 77

    invoke()
    assert calls == (
        ["ordinary UI", "VR panel"]
        if outcome in {"success", "hidden", "failure", "shared"}
        else ["ordinary UI"]
    )
    assert read_word(abi.submitted_frames_va) == (outcome in {"success", "shared"})
    assert read_word(abi.enabled_va) == (outcome in {"success", "hidden", "shared"})
    if outcome == "success":
        word(abi.enabled_va, 0)
        invoke()
        invoke()
        assert operations == [0, 1], "close only once, without submitting another frame"
        assert bytes(machine.mem_read(abi.frame_va + 28, 160)) == bytes(160)
    elif outcome == "shared":
        word(abi.enabled_va, 0)
        invoke()
        invoke()
        assert operations == [0, 1, 1], "paired finalizer runs even with no panel"
    else:
        invoke()
        assert read_word(abi.submitted_frames_va) == 0
        if outcome in {"world_only", "close_failure", "disabled_mid"}:
            assert operations == [1, 1], "every paired frame must reach completion"
        if outcome == "close_failure":
            assert read_word(abi.completion_result_va) == 0x80004005
        if outcome in {"world_only", "close_failure", "disabled_mid"}:
            image, _, _ = _linked_panel(paired=True)
            world = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).abi(image)
            assert read_word(world.enabled_va) == (outcome == "world_only")
    assert read_word(abi.presenter_calls_va) >= 2


@pytest.mark.parametrize("outcome", ["shared", "world_only", "close_failure", "disabled_mid"])
def test_completed_page_releases_world_draw_boundary_after_end_or_cancel(outcome: str) -> None:
    image, _, _ = _linked_panel(paired=True)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).abi(image)
    machine, entry, _, _, operations = _panel_machine(outcome)
    machine.mem_write(scene.frame_pending_va, struct.pack("<I", 1))
    machine.mem_write(_STACK, struct.pack("<I", _RETURN))
    machine.reg_write(UC_X86_REG_ESP, _STACK)
    machine.emu_start(entry, _RETURN, count=1000)
    assert operations == ([0] if outcome == "shared" else [1])
    assert struct.unpack("<I", machine.mem_read(scene.frame_pending_va, 4))[0] == 0
    assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4


@pytest.mark.parametrize("deferred", [False, True])
def test_paired_presenter_requires_verified_deferred_world(deferred: bool) -> None:
    image = _image(GOG_BUILD)
    world = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, deferred_frame=deferred)
    world.apply(image)
    enabled = world.abi(image).enabled_va
    before = image.to_bytes()
    if deferred:
        VRPanelCompiler(profile=GOG_BUILD, world_enabled_va=enabled).apply(image)
    else:
        with pytest.raises(PatchError, match="verified deferred"):
            VRPanelCompiler(profile=GOG_BUILD, world_enabled_va=enabled).apply(image)
        assert image.to_bytes() == before


@pytest.mark.parametrize(
    "state", ["fresh", "stale", "not_ready", "missing", "modal", "disabled", "wrap"]
)
def test_only_current_native_captions_become_noninteractive_world_overlays(state: str) -> None:
    image, _abi, _entry = _linked_panel(paired=True, captions=True)
    caption = CaptionFeatureCompiler.cache_abi(image)
    machine, entry, abi, calls, operations = _panel_machine("success", captions=True)
    query = _HEAP + 0xA300
    observed: list[tuple[int, int, tuple[int, ...]]] = []

    def word(address: int, value: int) -> None:
        machine.mem_write(address, struct.pack("<I", value))

    def read_word(address: int) -> int:
        return struct.unpack("<I", machine.mem_read(address, 4))[0]

    word(abi.ownership_query_slot_va, query)
    machine.mem_write(query, b"\xa1" + struct.pack("<I", query + 16) + b"\xc3")
    word(query + 16, 3 if state == "modal" else 1)
    word(abi.enabled_va, state != "disabled")
    word(caption.replay_count_va, 0xFFFFFFFF if state == "wrap" else 17)
    word(caption.ready_va, state != "not_ready")
    word(caption.surface_va, 0 if state == "missing" else _HEAP + 0x8000)
    machine.mem_write(caption.rect_va, struct.pack("<4i", 100, 600, 1100, 750))
    word(abi.recenter_va, 1)

    def observe(current: Uc, address: int, _size: int, _context: object) -> None:
        if address == GOG_BUILD.address("ui.container_draw") and state != "stale":
            word(caption.replay_count_va, (read_word(caption.replay_count_va) + 1) & 0xFFFFFFFF)
        elif address == _HEAP + 0xA200:
            stack = current.reg_read(UC_X86_REG_ESP)
            operation = read_word(stack + 8)
            if operation != 1:
                observed.append(
                    (
                        operation,
                        read_word(abi.recenter_va),
                        struct.unpack("<2I4i", machine.mem_read(abi.frame_va + 188, 24)),
                    )
                )
                _assert_panel_scale(current, abi.frame_va, operation)

    machine.hook_add(UC_HOOK_CODE, observe)

    def invoke() -> None:
        word(_STACK, _RETURN)
        machine.reg_write(UC_X86_REG_ESP, _STACK)
        machine.reg_write(UC_X86_REG_EBX, 99)
        machine.reg_write(UC_X86_REG_ECX, 77)
        machine.emu_start(entry, _RETURN, count=2000)
        assert machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
        assert machine.reg_read(UC_X86_REG_EBX) == 99
        assert machine.reg_read(UC_X86_REG_ECX) == 77

    invoke()
    expected = (
        1
        if state == "disabled"
        else 0
        if state == "modal"
        else 3
        if state in {"fresh", "wrap"}
        else 2
    )
    assert operations == [expected]
    assert calls[0] == "ordinary UI"
    if expected == 3:
        assert calls == ["ordinary UI", "VR caption"]
        assert observed == [(3, 3, (_HEAP + 0x8000, 1, 100, 600, 1100, 750))]
        # A subsequent ordinary interface never inherits source-alpha mode,
        # even if an explicit recenter flag is present at the same time.
        word(query + 16, 3)
        word(abi.recenter_va, 3)
        invoke()
        assert operations == [3, 0]
        assert observed[-1][:2] == (0, 1)
    elif expected != 1:
        assert observed[0][:2] == (expected, 1)


@pytest.mark.parametrize("changed", ["magic", "layout", "key", "caps", "pointer", "world"])
def test_caption_dependencies_are_verified_before_panel_writes(changed: str) -> None:
    image = _image(GOG_BUILD)
    runtime = RuntimeImage(image)
    symbols = runtime.prepare()
    producer = replace(_caption_compiler(), symbols=symbols, profile=GOG_BUILD)
    runtime.add_section(
        CAPTION_SEGMENT.logical_name,
        producer._payload(section_va=symbols.va(CAPTION_SEGMENT.logical_name)),
        CAPTION_SEGMENT.characteristics,
    )
    caption = CaptionFeatureCompiler.cache_abi(image)
    scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40, deferred_frame=True)
    scene.apply(image)
    base = symbols.va(CAPTION_SEGMENT.logical_name)
    if changed in {"magic", "layout", "key", "caps"}:
        address = {"magic": base, "layout": base + 8, "key": base + 0x228, "caps": base + 0x1B8}[
            changed
        ]
        image.write_u32_va(address, 0)
    elif changed == "pointer":
        caption = replace(caption, surface_va=caption.surface_va + 4)
    before = image.to_bytes()
    with pytest.raises(PatchError, match=r"caption|VR captions"):
        VRPanelCompiler(
            profile=GOG_BUILD,
            world_enabled_va=0 if changed == "world" else scene.abi(image).enabled_va,
            caption=caption,
        ).apply(image)
    assert image.to_bytes() == before
