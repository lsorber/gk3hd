"""Authoritative patch definitions, profiles, and planner instance."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from gk3hd.patch.binary.compiled import CompiledPayload
from gk3hd.patch.builds import SUPPORTED_BUILDS
from gk3hd.patch.definitions.engine import ENGINE_PATCHES
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import StaleMouseMoveCompiler
from gk3hd.patch.definitions.normalize_keyboard_camera_motion import KeyboardCameraMotionCompiler
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d import Runtime2DCompiler
from gk3hd.patch.definitions.speed_up_surface_checks import SurfaceCheckCompiler
from gk3hd.patch.model import (
    CompilationContext,
    PatchDefinition,
    PatchId,
    PatchProfile,
    ProfileId,
    ResourceClaim,
    ResourceKind,
)
from gk3hd.patch.planner import PatchPlanner

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Mapping

    from gk3hd.patch.binary.compiled import PatchCompiler


def _compiled_definition(
    *,
    patch_id: str,
    name: str,
    description: str,
    ownership: frozenset[ResourceClaim],
    compiler_factory: Callable[[CompilationContext], PatchCompiler],
) -> PatchDefinition:
    """Create a definition for one cohesive generated payload compiler."""
    owner = PatchId(patch_id)
    sections = tuple(claim for claim in ownership if claim.kind is ResourceKind.SECTION)
    if len(sections) != 1:
        msg = f"compiled patch {patch_id!r} must own exactly one injected section"
        raise ValueError(msg)
    primary_resource = sections[0]

    def build_operations(context: CompilationContext) -> tuple[CompiledPayload, ...]:
        return (
            CompiledPayload(
                owner=owner,
                symbol=f"{patch_id}.compiled_payload",
                resource=primary_resource,
                compiler=compiler_factory(context),
            ),
        )

    return PatchDefinition(
        id=owner,
        name=name,
        description=description,
        build_operations=build_operations,
        supported_builds=frozenset(SUPPORTED_BUILDS),
        ownership=ownership,
    )


_TRANSITION_SECTION = ResourceClaim(ResourceKind.SECTION, ".gk3dd")
_MOUSE_SECTION = ResourceClaim(ResourceKind.SECTION, ".gk3ui")
_RUNTIME_SECTION = ResourceClaim(ResourceKind.SECTION, ".gk2d")
_CAMERA_SECTION = ResourceClaim(ResourceKind.SECTION, ".gkcam")
_SURFACE_CHECK_SECTION = ResourceClaim(ResourceKind.SECTION, ".gklock")


_GENERATED_PATCHES = (
    _compiled_definition(
        patch_id="speed_up_surface_checks",
        name="Speed up graphics-surface checks",
        description="Avoid full-screen readbacks in surface checks.",
        ownership=frozenset(
            {
                _SURFACE_CHECK_SECTION,
                ResourceClaim(ResourceKind.HOOK, "surface_check_lock"),
                ResourceClaim(ResourceKind.HOOK, "surface_check_unlock"),
            }
        ),
        compiler_factory=lambda context: SurfaceCheckCompiler(
            profile=SUPPORTED_BUILDS[context.build.build_id]
        ),
    ),
    _compiled_definition(
        patch_id="fix_keyboard_camera_speed",
        name="Fix keyboard camera speed",
        description="Keep camera speed steady at any resolution/FPS.",
        ownership=frozenset(
            {
                _CAMERA_SECTION,
                ResourceClaim(ResourceKind.HOOK, "keyboard_camera_motion_dispatch"),
                ResourceClaim(ResourceKind.HOOK, "keyboard_camera_motion_conversion"),
            }
        ),
        compiler_factory=lambda context: KeyboardCameraMotionCompiler(
            profile=SUPPORTED_BUILDS[context.build.build_id]
        ),
    ),
    _compiled_definition(
        patch_id="prevent_transition_flicker",
        name="Prevent transition flicker",
        description="Fix broken frames between UI and 3D views.",
        ownership=frozenset(
            {
                _TRANSITION_SECTION,
                ResourceClaim(ResourceKind.HOOK, "directdraw_flip"),
                ResourceClaim(ResourceKind.HOOK, "directdraw_primary_blt"),
                ResourceClaim(ResourceKind.HOOK, "direct3d_begin_scene"),
                ResourceClaim(ResourceKind.HOOK, "direct3d_scene_setup"),
            }
        ),
        compiler_factory=lambda context: TransitionFrameCompiler(
            profile=SUPPORTED_BUILDS[context.build.build_id]
        ),
    ),
    _compiled_definition(
        patch_id="stabilize_mouse_input",
        name="Stabilize mouse input",
        description="Prevent stale mouse events causing UI crashes.",
        ownership=frozenset(
            {
                _MOUSE_SECTION,
                ResourceClaim(ResourceKind.HOOK, "window_mouse_move_dispatch"),
                ResourceClaim(ResourceKind.HOOK, "ui_event_target_dispatch"),
                ResourceClaim(ResourceKind.HOOK, "ui_tree_hit_test_dispatch"),
            }
        ),
        compiler_factory=lambda context: StaleMouseMoveCompiler(
            profile=SUPPORTED_BUILDS[context.build.build_id]
        ),
    ),
    replace(
        _compiled_definition(
            patch_id="scale_fixed_interfaces",
            name="Scale fixed interfaces",
            description="Scale UI, text and cursors like 1024x768.",
            ownership=frozenset(
                {
                    _RUNTIME_SECTION,
                    ResourceClaim(ResourceKind.HOOK, "final_2d_blitter"),
                    ResourceClaim(ResourceKind.HOOK, "clipped_sprite_dispatch"),
                    ResourceClaim(ResourceKind.HOOK, "fixed_interface_pointer_dispatch"),
                    ResourceClaim(ResourceKind.HOOK, "software_cursor_presentation"),
                }
            ),
            compiler_factory=lambda context: Runtime2DCompiler(
                profile=SUPPORTED_BUILDS[context.build.build_id],
            ),
        ),
        # The UI runtime consumes the modern display dimensions, transition
        # Flip-generation ABI, and mouse-dispatch ABI. Its direct room boundary
        # is intrinsic to the runtime payload rather than a separate stage.
        requires=frozenset(
            {
                PatchId("enable_modern_resolutions"),
                PatchId("prevent_transition_flicker"),
                PatchId("stabilize_mouse_input"),
            }
        ),
    ),
)

_PATCH_ITEMS = (
    *ENGINE_PATCHES.values(),
    *_GENERATED_PATCHES,
)


def _index_unique[T, K: Hashable](
    items: tuple[T, ...], *, id_of: Callable[[T], K], label: str
) -> Mapping[K, T]:
    """Build one immutable registry without losing duplicate declarations."""
    result: dict[K, T] = {}
    for item in items:
        item_id = id_of(item)
        if item_id in result:
            detail = f"duplicate {label} ID {item_id!r}"
            raise ValueError(detail)
        result[item_id] = item
    return MappingProxyType(result)


PATCHES: Mapping[PatchId, PatchDefinition] = _index_unique(
    _PATCH_ITEMS,
    id_of=lambda definition: definition.id,
    label="patch",
)

_RECOMMENDED = frozenset(
    {
        PatchId("enable_modern_resolutions"),
        PatchId("maximize_graphics_quality"),
        PatchId("fix_keyboard_camera_speed"),
        PatchId("scale_fixed_interfaces"),
        PatchId("speed_up_surface_checks"),
        PatchId("prevent_save_warning_dialogs"),
        PatchId("prevent_transition_flicker"),
        PatchId("stabilize_mouse_input"),
        PatchId("remove_disc_requirement"),
    }
)

_PROFILE_ITEMS = (
    PatchProfile(
        id=ProfileId("recommended"),
        name="Recommended improvements",
        description="All improvements; keep movies (default).",
        patches=_RECOMMENDED,
    ),
    PatchProfile(
        id=ProfileId("testing"),
        name="Testing shortcuts",
        description="All improvements; skip all movies, including story videos.",
        patches=_RECOMMENDED | {PatchId("skip_all_movies")},
    ),
)

PROFILES: Mapping[ProfileId, PatchProfile] = _index_unique(
    _PROFILE_ITEMS,
    id_of=lambda profile: profile.id,
    label="profile",
)

PLANNER = PatchPlanner(PATCHES, PROFILES)
