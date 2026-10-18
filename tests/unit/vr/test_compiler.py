"""Complete VR composition is deterministic, dormant and independently verifiable."""

from __future__ import annotations

import struct
from dataclasses import replace

import pytest
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.mutations import ExecutableMutationPlan, MutableExecutableImage
from gk3hd.patch.builds import SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.catalog import PLANNER
from gk3hd.patch.definitions.vr_gps import VRGPSCompiler
from gk3hd.patch.definitions.vr_hud_compiler import VRHudCompiler
from gk3hd.patch.definitions.vr_input import VRInputCompiler
from gk3hd.patch.definitions.vr_menu_compiler import VRMenuCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.model import BuildContext, PatchError, ProfileId
from gk3hd.vr.compiler import VRProgram, compile_vr, verify_vr
from tests.unit.patch.test_complete_compilation import _source
from tests.unit.patch.test_vr_scene import _HEAP, _STACK, _machine


@pytest.fixture(scope="module", params=SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def flat_bytes(request: pytest.FixtureRequest) -> tuple[bytes, BuildProfile]:
    """Populate declared native contracts, never distribute a game executable."""
    profile: BuildProfile = request.param
    source = _source(profile)
    for event in VRInputCompiler._events:
        source.write_u32_va(
            profile.address(f"input.{event}_slot"), profile.address(f"input.{event}")
        )
    for off, target in ((0x64, "vr.text_key"), (0x6C, "vr.save_character")):
        source.write_u32_va(profile.address("savegame_edit.vtable") + off, profile.site(target).va)
    source.write_u32_va(
        profile.address("savegame.vtable") + 0x6C, profile.site("vr.container_text_route").va
    )
    source.write_u32_va(
        profile.address("room_text.vtable"), profile.address("room_text.destructor")
    )
    plan = PLANNER.plan_profile(ProfileId("recommended"), BuildContext(build_id=profile.id))
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

    with pytest.MonkeyPatch.context() as context:
        context.setattr(ExecutableMutationPlan, "apply", populate)
        OperationExecutor().execute(source, plan.compile_operations())
    return OperationExecutor().execute(source, plan.compile_operations()).to_bytes(), profile


@pytest.fixture
def flat(flat_bytes: tuple[bytes, BuildProfile]) -> tuple[PEFile, BuildProfile]:
    """Reuse immutable compiled baselines, never a mutable image between tests."""
    data, profile = flat_bytes
    return PEFile(data), profile


@pytest.fixture(scope="module")
def compiled_baseline(flat_bytes: tuple[bytes, BuildProfile]) -> VRProgram:
    """Compile once per binary profile for tests of already-generated behavior."""
    data, profile = flat_bytes
    return compile_vr(PEFile(data), profile=profile, units_per_meter=40)


@pytest.fixture
def program(compiled_baseline: VRProgram) -> VRProgram:
    """Retain fresh mutable image bytes for every behavioral/fault test."""
    return replace(compiled_baseline, image=compiled_baseline.image.clone())


def test_complete_vr_compiles_without_mutating_flat_source(
    flat: tuple[PEFile, BuildProfile],
) -> None:
    source, profile = flat
    before = source.to_bytes()
    first = compile_vr(source, profile=profile, units_per_meter=40)
    second = verify_vr(source, first.image, profile=profile, units_per_meter=40)
    assert first.image.to_bytes() == second.image.to_bytes()
    assert source.to_bytes() == before
    assert first.panel.world_enabled_va == first.scene.enabled_va
    assert all(first.image.read_u32_va(address) == 0 for address in first.switches)
    assert first.mirror.enabled_va in first.switches
    assert first.mirror.enabled_va != first.scene.enabled_va


def test_late_compilation_failure_leaves_source_unchanged(
    flat: tuple[PEFile, BuildProfile],
) -> None:
    source, profile = flat
    source.write_bytes(source.va_to_offset(profile.site("vr.text_character").va), b"\xcc")
    before = source.to_bytes()
    with pytest.raises(PatchError, match="text native anchor"):
        compile_vr(source, profile=profile, units_per_meter=40)
    assert source.to_bytes() == before


def test_render_failure_does_not_allow_mirror_settings_to_replace_flat_preferences(
    flat: tuple[PEFile, BuildProfile], program: VRProgram
) -> None:
    """Execute the complete player's registry writer after its render hooks stop."""
    _source, profile = flat
    cpu = _machine(program.image)
    for address in program.switches:
        cpu.mem_write(address, struct.pack("<I", 1))
    for address in (program.scene.enabled_va, program.panel.enabled_va):
        cpu.mem_write(address, struct.pack("<I", 0))
    site = profile.site("vr.mirror_preferences")
    callback = _HEAP + 0xB000
    cpu.mem_write(struct.unpack("<I", site.original[2:])[0], struct.pack("<I", callback))
    cpu.mem_write(callback, bytes.fromhex("b8 05 00 00 00 c2 18 00"))
    name, value = _HEAP + 0x1000, _HEAP + 0x2000
    cpu.mem_write(name, b"Screen Width\0")
    cpu.mem_write(value, struct.pack("<I", 1280))
    cpu.mem_write(_STACK, struct.pack("<6I", 0x12345678, name, 0, 4, value, 4))
    forwarded = []

    def observe(_cpu: object, address: int, _size: int, _data: object) -> None:
        if address == callback:
            forwarded.append(address)

    cpu.hook_add(UC_HOOK_CODE, observe)
    cpu.emu_start(site.va, site.va + len(site.original), count=3000)
    assert not forwarded
    assert cpu.reg_read(UC_X86_REG_EAX) == 0
    assert bytes(cpu.mem_read(program.mirror.enabled_va, 4)) == struct.pack("<I", 1)


@pytest.mark.parametrize(("panel_active", "world_active"), [(1, 1), (0, 1), (1, 0), (0, 0)])
def test_native_ui_capture_follows_current_render_ownership_before_composition(
    flat: tuple[PEFile, BuildProfile], program: VRProgram, panel_active: int, world_active: int
) -> None:
    """Do not leave menu isolation dormant or retain last frame's ownership."""
    _source, profile = flat
    menu = VRMenuCompiler(profile=profile, world_enabled_va=program.scene.enabled_va).abi(
        program.image
    )
    hud = VRHudCompiler(profile=profile, world_enabled_va=program.scene.enabled_va).abi(
        program.image
    )
    gps = VRGPSCompiler(profile=profile, world_enabled_va=program.scene.enabled_va).abi(
        program.image
    )
    previous = program.panel.composition_presenter_va
    entry = program.panel.enabled_va - VRPanelCompiler._enabled + VRPanelCompiler._code
    cpu = _machine(program.image)
    wanted = panel_active & world_active
    for address, value in (
        (program.panel.enabled_va, panel_active),
        (program.scene.enabled_va, world_active),
        (program.inputs.enabled_va, 0),
        (menu.enabled_va, 1 - wanted),
        (hud.enabled_va, 1 - wanted),
        (gps.enabled_va, 1 - wanted),
    ):
        cpu.mem_write(address, struct.pack("<I", value))
    observed = []

    def before_native_composition(_cpu: object, address: int, _size: int, _data: object) -> None:
        if address == previous:
            observed.extend(
                struct.unpack("<I", cpu.mem_read(switch, 4))[0]
                for switch in (menu.enabled_va, hud.enabled_va, gps.enabled_va)
            )
            cpu.emu_stop()

    cpu.hook_add(UC_HOOK_CODE, before_native_composition)
    cpu.emu_start(entry, previous + 1, count=1000)
    assert observed == [wanted, wanted, wanted]


@pytest.mark.parametrize("feature", ["text", "navigation", "activation"])
def test_modified_program_is_rejected(
    flat: tuple[PEFile, BuildProfile], program: VRProgram, feature: str
) -> None:
    source, profile = flat
    address = {
        "text": program.text.presenter_va,
        "navigation": program.navigation.tick_va,
        "activation": program.inputs.enabled_va,
    }[feature]
    program.image.write_bytes(program.image.va_to_offset(address), b"\xcc")
    with pytest.raises(PatchError, match="differs from the verified composition"):
        verify_vr(source, program.image, profile=profile, units_per_meter=40)


def test_mismatched_calibration_is_rejected(
    flat: tuple[PEFile, BuildProfile], program: VRProgram
) -> None:
    source, profile = flat
    with pytest.raises(PatchError, match="differs from the verified composition"):
        verify_vr(source, program.image, profile=profile, units_per_meter=80)


def test_missing_flat_dependencies_leave_source_unchanged() -> None:
    profile = next(iter(SUPPORTED_BUILDS.values()))
    source = _source(profile)
    before = source.to_bytes()
    with pytest.raises(PatchError):
        compile_vr(source, profile=profile, units_per_meter=40)
    assert source.to_bytes() == before


def test_isolated_player_binds_only_its_private_renderer(flat: tuple[PEFile, BuildProfile]) -> None:
    source, profile = flat
    # Extend the sparse fixture's GDI-only import table with a declared DDraw
    # descriptor. This is format data, not a copy of a copyrighted executable.
    source.write_u32_va(source.image_base + source.optional_offset + 104, 0x380000)
    source.write_u32_va(source.image_base + source.optional_offset + 108, 60)
    source.write_bytes(source.va_to_offset(0x780014), bytes(20))
    source.write_u32_va(0x780014, 0x380200)
    source.write_u32_va(0x780020, 0x3800C0)
    source.write_u32_va(0x780024, 0x380240)
    source.write_bytes(source.va_to_offset(0x7800C0), b"DDRAW.dll\0")
    before = source.to_bytes()
    program = compile_vr(source, profile=profile, units_per_meter=40, renderer_location="isolated")
    imports = [row.dll_name for row in program.image.iter_import_descriptors()]
    assert "gk3hd/vr/player/ddraw.dll" in imports
    assert "DDRAW.dll" not in imports
    assert "GDI32.dll" in imports
    assert source.to_bytes() == before
    verify_vr(
        source, program.image, profile=profile, units_per_meter=40, renderer_location="isolated"
    )
    with pytest.raises(PatchError, match="differs from"):
        verify_vr(source, program.image, profile=profile, units_per_meter=40)


def test_missing_directdraw_import_cannot_publish_an_isolated_player(
    flat: tuple[PEFile, BuildProfile],
) -> None:
    source, profile = flat
    before = source.to_bytes()
    with pytest.raises(PatchError, match="DirectDraw import"):
        compile_vr(source, profile=profile, units_per_meter=40, renderer_location="isolated")
    assert source.to_bytes() == before
