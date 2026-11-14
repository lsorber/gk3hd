"""Compose the complete seated VR program without changing files or flat input."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from gk3hd.patch.definitions.vr_audio import VRListenerABI, VRListenerCompiler
from gk3hd.patch.definitions.vr_floor import VRFloorCompiler
from gk3hd.patch.definitions.vr_game_menu import VRGameMenuABI, VRGameMenuCompiler
from gk3hd.patch.definitions.vr_gps import VRGPSCompiler
from gk3hd.patch.definitions.vr_hud_compiler import VRHudABI, VRHudCompiler
from gk3hd.patch.definitions.vr_input import VRInputABI, VRInputCompiler
from gk3hd.patch.definitions.vr_input_lifetime import compile_input_lifetime
from gk3hd.patch.definitions.vr_item_hint import VRItemHintABI, VRItemHintCompiler
from gk3hd.patch.definitions.vr_item_use import VRItemUseABI, VRItemUseCompiler
from gk3hd.patch.definitions.vr_loading import VRLoadingCompiler
from gk3hd.patch.definitions.vr_menu_compiler import VRMenuCompiler
from gk3hd.patch.definitions.vr_mirror import VRMirrorABI, VRMirrorCompiler
from gk3hd.patch.definitions.vr_navigation import VRNavigationABI, VRNavigationCompiler
from gk3hd.patch.definitions.vr_ownership import VROwnershipABI, VROwnershipCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelABI, VRPanelCompiler
from gk3hd.patch.definitions.vr_presentation import VRPresentationCompiler
from gk3hd.patch.definitions.vr_protagonist import VRProtagonistCompiler
from gk3hd.patch.definitions.vr_return import VRReturnABI, VRReturnCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneABI, VRSceneCompiler
from gk3hd.patch.definitions.vr_scenery import VRSceneryCompiler
from gk3hd.patch.definitions.vr_text import VRTextABI, VRTextCompiler
from gk3hd.patch.definitions.vr_texture_lookup import compile_texture_lookup
from gk3hd.patch.definitions.vr_visibility import VRVisibilityCompiler
from gk3hd.patch.definitions.vr_world import VRWorldABI, VRWorldCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile


@dataclass(frozen=True, slots=True)
class VRProgram:
    """Verified dormant hooks and the shared controls used by a VR launcher."""

    image: PEFile
    scene: VRSceneABI
    panel: VRPanelABI
    ownership: VROwnershipABI
    world: VRWorldABI
    navigation: VRNavigationABI
    inputs: VRInputABI
    text: VRTextABI
    mirror: VRMirrorABI
    hud: VRHudABI
    audio: VRListenerABI
    game_menu: VRGameMenuABI
    item_hint: VRItemHintABI
    observer_return: VRReturnABI

    @property
    def switches(self) -> tuple[int, ...]:
        """Launch activation set, excluding producer-owned render switches."""
        return (
            self.scene.enabled_va,
            self.panel.enabled_va,
            self.ownership.enabled_va,
            self.world.enabled_va,
            self.navigation.enabled_va,
            self.inputs.enabled_va,
            self.text.enabled_va,
            self.text.keyboard_enabled_va,
            self.mirror.enabled_va,
            self.game_menu.enabled_va,
        )

    @property
    def stereo_only_switches(self) -> tuple[int, ...]:
        """Activate an output that never displays the ordinary desktop mirror.

        Native fallback pages remain available through the shared finalizer.
        Desktop/PC-VR launchers must use ``switches`` instead.
        """
        return (*self.switches, self.hud.stereo_only_va)


def compile_vr(
    source: PEFile,
    *,
    profile: BuildProfile,
    units_per_meter: float,
    renderer_location: Literal["game", "isolated"] = "game",
    item_visuals: bytes = b"",
) -> VRProgram:
    """Build all supported VR features atomically on a clone of the flat patch.

    The source must contain the recommended interface and transition patches.
    World scale is explicit; the service supplies documented inch-based units.
    Physical-headset size/comfort qualification remains separate.
    All switches remain off on disk. Launch activation and artifact matching
    are separate requirements, not implied by a successful compilation.
    """
    if renderer_location not in {"game", "isolated"}:
        msg = "unknown VR renderer location"
        raise ValueError(msg)
    image = source.clone()
    floor = VRFloorCompiler(profile=profile)
    floor.apply(image)
    floor.postcheck(image)
    scene = VRSceneCompiler(
        profile=profile,
        units_per_meter=units_per_meter,
        deferred_frame=True,
        mirror_world=True,
        prewarm_scene=True,
        floor=floor.abi(image),
    )
    scene.apply(image)
    scene.postcheck(image)
    scene_abi = scene.abi(image)
    menus = VRMenuCompiler(profile=profile, world_enabled_va=scene_abi.enabled_va)
    menus.apply(image)
    menus.postcheck(image)
    hud = VRHudCompiler(profile=profile, world_enabled_va=scene_abi.enabled_va)
    hud.apply(image)
    hud.postcheck(image)
    gps = VRGPSCompiler(profile=profile, world_enabled_va=scene_abi.enabled_va)
    gps.apply(image)
    gps.postcheck(image)
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    panel = VRPanelCompiler(
        profile=profile,
        expected_presenter_va=image.read_u32_va(slot),
        world_enabled_va=scene_abi.enabled_va,
        caption=CaptionFeatureCompiler.cache_abi(image),
        tooltip=TooltipFeatureCompiler.cache_abi(image),
        menus=menus.abi(image),
        hud=hud.abi(image),
        gps=gps.abi(image),
    )
    panel.apply(image)
    panel.postcheck(image)
    panel_abi = panel.abi(image)
    ownership = VROwnershipCompiler(
        profile=profile, scene=scene_abi, panel=panel_abi, gps=gps.abi(image)
    )
    ownership.apply(image)
    ownership.postcheck(image)
    world = VRWorldCompiler(profile=profile, scene=scene_abi)
    world.apply(image)
    world.postcheck(image)
    navigation = VRNavigationCompiler(profile=profile, panel=panel_abi, scene=scene_abi)
    navigation.apply(image)
    navigation.postcheck(image)
    game_menu, observer_return = _compile_game_menu(
        image, profile, panel_abi, scene_abi, ownership.abi(image)
    )
    inputs = VRInputCompiler(
        profile=profile,
        panel=panel_abi,
        world=world.abi(image),
        navigation=navigation.abi(image),
        item_use=_compile_item_use(image, profile),
        expected_presenter_va=image.read_u32_va(slot),
    )
    inputs.apply(image)
    inputs.postcheck(image)
    item_hint = _compile_item_hint(image, inputs, item_visuals)
    text = VRTextCompiler(
        profile=profile, panel=panel_abi, expected_presenter_va=image.read_u32_va(slot)
    )
    text.apply(image)
    text.postcheck(image)
    mirror = VRMirrorCompiler(profile=profile)
    for compiler in (
        VRVisibilityCompiler.for_scene(image, profile, scene_abi),
        VRLoadingCompiler(profile=profile, panel=panel_abi, scene=scene_abi, text=text.abi(image)),
        VRPresentationCompiler(profile=profile, panel=panel_abi, scene=scene_abi),
        mirror,
        audio := VRListenerCompiler(
            profile=profile, scene=scene_abi, ownership=ownership.abi(image)
        ),
    ):
        compiler.apply(image)
        compiler.postcheck(image)
    if renderer_location == "isolated":
        _isolate_renderer(image)
    program = VRProgram(
        image,
        scene_abi,
        panel_abi,
        ownership.abi(image),
        world.abi(image),
        navigation.abi(image),
        inputs.abi(image),
        text.abi(image),
        mirror.abi(image),
        hud.abi(image),
        audio.abi(image),
        game_menu,
        item_hint,
        observer_return,
    )
    _require_dormant(program)
    return program


def _require_dormant(program: VRProgram) -> None:
    """Every opt-in consumer must remain off until the launch transaction."""
    if any(program.image.read_u32_va(address) for address in program.stereo_only_switches):
        msg = "VR compilation must remain dormant until explicitly launched"
        raise PatchError(msg)


def _compile_game_menu(
    image: PEFile,
    profile: BuildProfile,
    panel: VRPanelABI,
    scene: VRSceneABI,
    ownership: VROwnershipABI,
) -> tuple[VRGameMenuABI, VRReturnABI]:
    """Verify the menu's position between completed presentation and input."""
    observer_return = _compile_return(image, profile, panel, scene, ownership)
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    compiler = VRGameMenuCompiler(
        profile=profile,
        panel=panel,
        expected_presenter_va=image.read_u32_va(slot),
        observer_return=observer_return,
    )
    compiler.apply(image)
    compiler.postcheck(image)
    return compiler.abi(image), observer_return


def _compile_return(
    image: PEFile,
    profile: BuildProfile,
    panel: VRPanelABI,
    scene: VRSceneABI,
    ownership: VROwnershipABI,
) -> VRReturnABI:
    """Share the same native protagonist/observer transaction on every VR host."""
    protagonist = VRProtagonistCompiler(profile=profile)
    protagonist.apply(image)
    protagonist.postcheck(image)
    compiler = VRReturnCompiler(
        profile=profile,
        panel=panel,
        scene=scene,
        ownership=ownership,
        protagonist=protagonist.abi(image),
    )
    compiler.apply(image)
    compiler.postcheck(image)
    return compiler.abi(image)


def _compile_item_use(image: PEFile, profile: BuildProfile) -> VRItemUseABI:
    compiler = VRItemUseCompiler(profile=profile)
    compiler.apply(image)
    compiler.postcheck(image)
    return compiler.abi(image)


def _compile_item_hint(image: PEFile, inputs: VRInputCompiler, catalog: bytes) -> VRItemHintABI:
    """Bind feedback to the same input consumer and completed world boundary."""
    if inputs.world is None:
        msg = "VR item feedback requires the linked world input consumer"
        raise PatchError(msg)
    slot = TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va
    compiler = VRItemHintCompiler(
        profile=inputs.profile,
        panel=inputs.panel,
        input_enabled_va=inputs.abi(image).enabled_va,
        world_ready_va=inputs.world.ready_va,
        expected_presenter_va=image.read_u32_va(slot),
        catalog=catalog,
    )
    compiler.apply(image)
    compiler.postcheck(image)
    return compiler.abi(image)


def _isolate_renderer(image: PEFile) -> None:
    """Resolve the private renderer without replacing the flat player's import."""
    descriptors = [
        row for row in image.iter_import_descriptors() if row.dll_name.casefold() == "ddraw.dll"
    ]
    if len(descriptors) != 1:
        msg = "VR player requires one original DirectDraw import descriptor"
        raise PatchError(msg)
    section = image.add_section(".vrload", b"gk3hd/vr/player/ddraw.dll\0", 0x40000040)
    image.write_u32_va(image.rva_to_va(descriptors[0].descriptor_rva + 12), section.virtual_address)


def verify_vr(
    source: PEFile,
    installed: PEFile,
    *,
    profile: BuildProfile,
    units_per_meter: float,
    renderer_location: Literal["game", "isolated"] = "game",
) -> VRProgram:
    """Rebuild from the flat baseline and verify every composed byte and link.

    Individual bridges replace earlier presenter links by design. Comparing
    the complete deterministic rebuild also verifies those final dependencies,
    without pretending intermediate presenter layouts are the final graph.
    """
    program = compile_vr(
        source,
        profile=profile,
        units_per_meter=units_per_meter,
        renderer_location=renderer_location,
        item_visuals=VRItemHintCompiler.catalog_bytes(installed),
    )
    if installed.to_bytes() != program.image.to_bytes():
        msg = (
            "The installed VR program differs from the verified composition. "
            "Run gk3hd vr install to update the PC VR player."
        )
        raise PatchError(msg)
    return program


def compile_standalone_vr(
    source: PEFile, *, profile: BuildProfile, units_per_meter: float, item_visuals: bytes = b""
) -> VRProgram:
    """Compose the shared guest fast path without changing PC-VR compilation."""
    program = compile_vr(
        source, profile=profile, units_per_meter=units_per_meter, item_visuals=item_visuals
    )
    compiler = VRSceneryCompiler.for_scene(
        program.image, profile, program.scene, VRLoadingCompiler.abi(program.image)
    )
    compiler.apply(program.image)
    compiler.postcheck(program.image)
    compile_input_lifetime(
        program.image,
        profile=profile,
        panel=program.panel,
        inputs=program.inputs,
        ownership=program.ownership,
        shortcuts=program.game_menu,
    )
    compile_texture_lookup(program.image, profile)
    return program


def verify_standalone_vr(
    source: PEFile, installed: PEFile, *, profile: BuildProfile, units_per_meter: float
) -> VRProgram:
    """Verify the complete standalone composition against an independent rebuild."""
    program = compile_standalone_vr(
        source,
        profile=profile,
        units_per_meter=units_per_meter,
        item_visuals=VRItemHintCompiler.catalog_bytes(installed),
    )
    if installed.to_bytes() != program.image.to_bytes():
        msg = "installed standalone VR program differs from the verified composition"
        raise PatchError(msg)
    return program
