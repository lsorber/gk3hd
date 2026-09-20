"""Typed entry points exchanged by the menu runtime domains."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DropdownRuntimeExports:
    """Entry addresses exported by the graphics-options dropdown domain."""

    draw_wrapper_va: int
    visibility_wrapper_va: int
    highlight_wrapper_va: int
    present_helper_va: int


@dataclass(frozen=True, slots=True)
class ActionMenuRuntimeExports:
    """Entry addresses exported by ActionMenu and toolbar composition."""

    action_root_wrapper_va: int
    action_destructor_wrapper_va: int
    toolbar_root_wrapper_va: int
    toolbar_destructor_wrapper_va: int
    toolbar_layout_va: int
    toolbar_cursor_warp_va: int
    action_layout_helper_va: int
    action_lifetime_helper_va: int
    toolbar_blt_helper_va: int


@dataclass(frozen=True, slots=True)
class TooltipRuntimeExports:
    """Entry addresses exported by tooltip lookup and retained presentation."""

    visibility_wrapper_va: int
    draw_wrapper_va: int
    base_wrapper_va: int
    border_wrapper_va: int
    modal_resolver_va: int
    fixed_layer_epilogue_va: int
    frame_presenter_va: int
    transfer_affine_va: int
