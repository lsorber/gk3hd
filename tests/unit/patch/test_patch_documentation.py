"""Enforce the user-facing documentation contract for selectable patches."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest

from gk3hd.patch.definitions import engine as definitions
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import StaleMouseMoveCompiler
from gk3hd.patch.definitions.normalize_keyboard_camera_motion import KeyboardCameraMotionCompiler
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.compiler import Runtime2DCompiler
from gk3hd.patch.definitions.runtime2d.fingerprint import FingerprintFeatureCompiler
from gk3hd.patch.definitions.runtime2d.inventory import InventoryFeatureCompiler
from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler
from gk3hd.patch.definitions.runtime2d.room_rendering import DirectRoomRenderingCompiler
from gk3hd.patch.definitions.runtime2d.sidney_construction import SidneyConstructionCompiler
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler
from gk3hd.patch.definitions.runtime2d.system import SystemScreenCompiler
from gk3hd.patch.definitions.runtime2d.system.binoculars import BinocularFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.blit_dispatch import BlitDispatchCompiler
from gk3hd.patch.definitions.runtime2d.system.cursor import CursorFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.fixed_screens import FixedScreenFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.load_save import LoadSaveFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_action import ActionMenuFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_dropdown import DropdownFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menus import MenuFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.room_status import RoomStatusFeatureCompiler
from gk3hd.patch.definitions.speed_up_surface_checks import SurfaceCheckCompiler

if TYPE_CHECKING:
    from collections.abc import Callable

_SECTIONS = ("Outcome:", "Before:", "After:", "Strategy:", "Boundaries:")

_DOCUMENTED_PATCHES: tuple[type[object] | Callable[..., object], ...] = (
    definitions._remove_disc_requirement,
    definitions._prevent_save_warning_dialogs,
    definitions._skip_all_movies,
    definitions._maximize_graphics_quality,
    definitions._enable_modern_resolutions,
    TransitionFrameCompiler,
    StaleMouseMoveCompiler,
    KeyboardCameraMotionCompiler,
    SurfaceCheckCompiler,
    DirectRoomRenderingCompiler,
    Runtime2DCompiler,
    CaptionFeatureCompiler,
    FingerprintFeatureCompiler,
    InventoryFeatureCompiler,
    ResourceDispatchCompiler,
    SidneyConstructionCompiler,
    SidneyPresentationCompiler,
    SystemScreenCompiler,
    BinocularFeatureCompiler,
    BlitDispatchCompiler,
    CursorFeatureCompiler,
    FixedScreenFeatureCompiler,
    LoadSaveFeatureCompiler,
    MenuFeatureCompiler,
    ActionMenuFeatureCompiler,
    DropdownFeatureCompiler,
    TooltipFeatureCompiler,
    RoomStatusFeatureCompiler,
)


@pytest.mark.parametrize("patch", _DOCUMENTED_PATCHES, ids=lambda patch: patch.__name__)
def test_patch_docstring_uses_the_shared_contract(
    patch: type[object] | Callable[..., object],
) -> None:
    """Require every patch to explain outcome, transition, strategy, and scope."""
    docstring = inspect.getdoc(patch)
    assert docstring is not None
    positions = [docstring.find(section) for section in _SECTIONS]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)
