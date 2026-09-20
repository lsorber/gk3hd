"""Tests for the authoritative production registry and shared runtime owner."""

from __future__ import annotations

import struct
from dataclasses import fields, replace

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP

from gk3hd.patch.binary.compiled import CompiledPayload
from gk3hd.patch.binary.operations import AssertBytes, ReplaceBytes
from gk3hd.patch.binary.x86 import BranchOpcode, decode_rel32_branch
from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS, ProfileError, _index_build_profiles
from gk3hd.patch.catalog import PATCHES, PLANNER, PROFILES
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import (
    MouseMoveDispatchABI,
    StaleMouseMoveCompiler,
)
from gk3hd.patch.definitions.normalize_keyboard_camera_motion import KeyboardCameraMotionCompiler
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import (
    TransitionFrameABI,
    TransitionFrameCompiler,
)
from gk3hd.patch.definitions.runtime2d import Runtime2DCompiler
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.fingerprint import FingerprintFeatureCompiler
from gk3hd.patch.definitions.runtime2d.geometry import (
    AUTHORED_FRAME_HEIGHT,
    RESTORE_PROGRESS_LOGICAL_HEIGHT,
    RESTORE_PROGRESS_LOGICAL_WIDTH,
)
from gk3hd.patch.definitions.runtime2d.inventory import InventoryFeatureCompiler
from gk3hd.patch.definitions.runtime2d.inventory_alpha import (
    build_effect_constructor_wrapper,
    build_scaled_font_alpha_callback,
)
from gk3hd.patch.definitions.runtime2d.layout import (
    RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET,
    RESOURCE_SEGMENT,
    SYSTEM_CONTROL_FULL_DAMAGE_RECT_OFFSET,
    SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET,
    SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET,
    RuntimeSegmentAddress,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler
from gk3hd.patch.definitions.runtime2d.room_rendering import (
    DirectRoomRenderingCompiler,
    RoomRenderingABI,
)
from gk3hd.patch.definitions.runtime2d.sidney_composition import build_cursor_blt_trace_helper
from gk3hd.patch.definitions.runtime2d.sidney_construction import SidneyConstructionCompiler
from gk3hd.patch.definitions.runtime2d.sidney_input import (
    build_input_dispatch_wrapper,
    build_periodic_cursor_select_thunk,
    build_periodic_cursor_select_wrapper,
    build_pointer_motion_dispatch_thunk,
    build_pointer_motion_dispatch_wrapper,
    build_reference_canvas_input_wrapper,
    build_tbt_input_wrapper,
)
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler
from gk3hd.patch.definitions.runtime2d.system import SystemScreenCompiler
from gk3hd.patch.definitions.runtime2d.system.load_save import LoadSaveFeatureCompiler
from gk3hd.patch.definitions.runtime2d.system.menu_tooltip import TooltipFeatureCompiler
from gk3hd.patch.model import BuildContext, BuildId, PatchId, ProfileId, ResourceKind


def test_build_registry_rejects_duplicate_ids_and_hashes_before_indexing() -> None:
    """Dictionary construction cannot conceal conflicting build declarations."""
    duplicate = replace(GOG_BUILD, label="Duplicate ID fixture")
    with pytest.raises(ProfileError, match="duplicate build profile ID"):
        _index_build_profiles((GOG_BUILD, duplicate))

    duplicate_hash = replace(GOG_BUILD, id=BuildId("duplicate_hash"))
    with pytest.raises(ProfileError, match="duplicate build profile SHA-256"):
        _index_build_profiles((GOG_BUILD, duplicate_hash))


def test_build_profiles_snapshot_caller_owned_fact_mappings() -> None:
    """Mutable reverse-engineering inputs cannot mutate a live profile later."""
    sites = dict(GOG_BUILD.sites)
    symbols = dict(GOG_BUILD.symbols)
    profile = replace(GOG_BUILD, sites=sites, symbols=symbols)
    expected_site_count = len(sites)
    expected_symbol_count = len(symbols)

    sites.clear()
    symbols.clear()

    assert len(profile.sites) == expected_site_count
    assert len(profile.symbols) == expected_symbol_count


def test_registry_has_only_canonical_version_free_ids() -> None:
    """The public registry contains no compatibility aliases or lineage versions."""
    assert set(PATCHES) == {
        PatchId("enable_modern_resolutions"),
        PatchId("fix_keyboard_camera_speed"),
        PatchId("maximize_graphics_quality"),
        PatchId("prevent_save_warning_dialogs"),
        PatchId("prevent_transition_flicker"),
        PatchId("remove_disc_requirement"),
        PatchId("scale_fixed_interfaces"),
        PatchId("skip_all_movies"),
        PatchId("speed_up_surface_checks"),
        PatchId("stabilize_mouse_input"),
    }
    assert all(not patch_id.endswith(("_v1", "_v2", "_v3")) for patch_id in PATCHES)
    assert len(PATCHES) == len(set(PATCHES))


def test_rendering_quality_is_one_complete_declarative_policy() -> None:
    """LOD, filtering, and texture ceilings cannot drift into partial profiles."""
    patch_id = PatchId("maximize_graphics_quality")
    build = BuildContext(build_id=next(iter(SUPPORTED_BUILDS)))
    plan = PLANNER.plan_explicit({patch_id}, build)
    symbols = {operation.symbol for operation in plan.compile_operations()}
    assert {
        "quality.model_lod_default",
        "quality.anisotropy_default",
        "quality.gamma_default",
        "quality.gamma_shared_scalar_restore",
        "quality.gamma_identity_red",
        "quality.gamma_identity_green",
        "quality.gamma_identity_blue",
        "textures.high_quality_limits",
    } <= symbols

    all_operations = {operation.symbol: operation for operation in plan.compile_operations()}
    operations = {
        operation.symbol: operation
        for operation in plan.compile_operations()
        if isinstance(operation, ReplaceBytes)
    }
    assert isinstance(all_operations["quality.gamma_default"], AssertBytes)
    assert isinstance(all_operations["quality.gamma_shared_scalar_restore"], AssertBytes)
    assert "quality.gamma_default" not in operations
    assert "quality.gamma_shared_scalar_restore" not in operations
    assert operations["quality.gamma_identity_red"].replacement == bytes.fromhex(
        "8b ce c1 e1 07 90 90 90 90"
    )
    assert operations["quality.gamma_identity_green"].replacement == bytes.fromhex(
        "8b c6 c1 e0 07 90 90 90 90"
    )
    assert operations["quality.gamma_identity_blue"].replacement == bytes.fromhex(
        "8b d6 c1 e2 07 90 90 90 90"
    )


def test_savegame_warnings_keep_logging_without_opening_a_modal_reporter() -> None:
    """The persistence call changes sink, not classification or warning text."""
    patch_id = PatchId("prevent_save_warning_dialogs")
    assert patch_id in PROFILES[ProfileId("recommended")].patches
    for build_id, profile in SUPPORTED_BUILDS.items():
        plan = PLANNER.plan_explicit({patch_id}, BuildContext(build_id=build_id))
        operations = plan.compile_operations()
        replacement = next(
            operation for operation in operations if operation.symbol == "savegame.warning_report"
        )
        assert isinstance(replacement, ReplaceBytes)
        assert decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=replacement.va,
            instruction=replacement.replacement,
        ) == profile.address("savegame.warning_log")
        assert {operation.symbol for operation in operations} == {
            "savegame.warning_report_context_before",
            "savegame.warning_report",
            "savegame.warning_report_context_after",
        }


def test_every_profile_plans_for_every_supported_build() -> None:
    """Named profiles resolve deterministically for each exact supported input."""
    for build_id in SUPPORTED_BUILDS:
        context = BuildContext(build_id=build_id)
        for profile_id in PROFILES:
            first = PLANNER.plan_profile(profile_id, context)
            second = PLANNER.plan_profile(profile_id, context)
            assert first.patch_ids == second.patch_ids


def test_runtime_is_the_only_owner_of_shared_2d_hooks() -> None:
    """All shared presentation claims belong to one registry-visible compositor."""
    runtime = PATCHES[PatchId("scale_fixed_interfaces")]
    hook_claims = {claim.key for claim in runtime.ownership if claim.kind is ResourceKind.HOOK}
    assert hook_claims == {
        "final_2d_blitter",
        "clipped_sprite_dispatch",
        "fixed_interface_pointer_dispatch",
        "software_cursor_presentation",
    }
    for patch_id, definition in PATCHES.items():
        if patch_id != runtime.id:
            assert not (definition.ownership & runtime.ownership)


def test_sidney_pillarbox_is_intrinsic_to_the_fixed_interface() -> None:
    """The fitted SIDNEY composition must not require a no-op policy patch."""
    fit = PATCHES[PatchId("scale_fixed_interfaces")]
    assert PatchId("pillarbox_sidney") not in PATCHES
    assert PatchId("pillarbox_sidney") not in PROFILES[ProfileId("recommended")].patches
    assert not {claim for claim in fit.ownership if claim.kind is ResourceKind.FEATURE_POLICY}


def test_recommended_profile_retains_story_movies() -> None:
    """Fast-start movie skipping belongs to automation, not the player profile."""
    assert PatchId("skip_all_movies") not in PROFILES[ProfileId("recommended")].patches


def test_runtime_compilation_has_one_intrinsic_sidney_policy() -> None:
    """The compositor has no constructor switch for an unsupported SIDNEY variant."""
    build = BuildContext(build_id=next(iter(SUPPORTED_BUILDS)))
    plan = PLANNER.plan_explicit({PatchId("scale_fixed_interfaces")}, build)

    operation = next(
        operation
        for operation in plan.compile_operations()
        if isinstance(operation, CompiledPayload)
        and isinstance(operation.compiler, Runtime2DCompiler)
    )
    assert isinstance(operation, CompiledPayload)
    assert isinstance(operation.compiler, Runtime2DCompiler)
    assert tuple(field.name for field in fields(Runtime2DCompiler)) == ("profile",)
    assert PATCHES[PatchId("scale_fixed_interfaces")].requires == frozenset(
        {
            PatchId("enable_modern_resolutions"),
            PatchId("prevent_transition_flicker"),
            PatchId("stabilize_mouse_input"),
        }
    )


def test_transition_compiler_receives_the_exact_planned_build_profile() -> None:
    """Generated transition code never relies on an implicit executable layout."""
    for build_id, profile in SUPPORTED_BUILDS.items():
        build = BuildContext(build_id=build_id)
        plan = PLANNER.plan_explicit({PatchId("prevent_transition_flicker")}, build)
        operation = plan.compile_operations()[0]
        assert isinstance(operation, CompiledPayload)
        assert isinstance(operation.compiler, TransitionFrameCompiler)
        assert operation.compiler.profile is profile


def test_keyboard_camera_patch_is_independent_and_configurable() -> None:
    """Manual camera timing has one standalone owner and a validated speed input."""
    for build_id, profile in SUPPORTED_BUILDS.items():
        build = BuildContext(build_id=build_id)
        plan = PLANNER.plan_explicit({PatchId("fix_keyboard_camera_speed")}, build)
        assert plan.patch_ids == (PatchId("fix_keyboard_camera_speed"),)
        operation = plan.compile_operations()[0]
        assert isinstance(operation, CompiledPayload)
        assert isinstance(operation.compiler, KeyboardCameraMotionCompiler)
        assert operation.compiler.profile is profile
        assert operation.compiler.reference_updates_per_second == 30.0

    profile = next(iter(SUPPORTED_BUILDS.values()))
    assert (
        KeyboardCameraMotionCompiler(
            profile=profile,
            reference_updates_per_second=20.0,
        ).reference_updates_per_second
        == 20.0
    )
    with pytest.raises(ValueError, match="between 1 and 240"):
        KeyboardCameraMotionCompiler(profile=profile, reference_updates_per_second=0.0)
    with pytest.raises(ValueError, match="between 1 and 240"):
        KeyboardCameraMotionCompiler(profile=profile, reference_updates_per_second=241.0)
    with pytest.raises(ValueError, match="must be finite"):
        KeyboardCameraMotionCompiler(profile=profile, reference_updates_per_second=float("nan"))


def test_keyboard_camera_bridge_is_timed_resolution_neutral_and_keyboard_scoped() -> None:
    """The emitted bridge owns keyboard timing without replacing shared mouse input."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = KeyboardCameraMotionCompiler(profile=profile)
    section_va = 0x00743000
    wrapper = compiler._build_keyboard_wrapper(section_va=section_va)
    bridge = compiler._build_conversion_bridge(section_va=section_va)

    assert b"\xff\x15" + struct.pack("<I", profile.address("win32.timeGetTime")) in wrapper
    assert struct.pack("<I", section_va + compiler._off_max_delta_ms) in wrapper
    assert struct.pack("<I", section_va + compiler._off_keyboard_active) in wrapper
    assert b"\xc2\x0c\x00" in wrapper
    assert bytes.fromhex("db 45 0c ff b0 44 01 00 00 d9 5d 10") in bridge
    assert b"\x83\xff\x03" in bridge
    assert b"\x83\xff\x04" in bridge
    assert b"\x83\xff\x02" in bridge
    assert struct.pack("<I", profile.address("high_resolution_3d.display_width_ptr")) in bridge
    assert struct.pack("<I", profile.address("high_resolution_3d.display_height_ptr")) in bridge

    # The only source sites are the keyboard dispatch and the shared
    # conversion reached under its transient marker. The independent physical
    # mouse caller at 0x00449EFB is neither redirected nor claimed.
    camera_claims = PATCHES[PatchId("fix_keyboard_camera_speed")].ownership
    assert {claim.key for claim in camera_claims if claim.kind is ResourceKind.HOOK} == {
        "keyboard_camera_motion_conversion",
        "keyboard_camera_motion_dispatch",
    }


def test_transition_repair_scopes_redraw_to_the_concrete_room_layer() -> None:
    """Scene histories remain coherent without touching modal compositors."""
    compiler = TransitionFrameCompiler(profile=next(iter(SUPPORTED_BUILDS.values())))
    scene_wrapper = compiler._build_scene_wrapper(
        wrapper_va=0x3000,
        repair_active_va=0x12345670,
        room_presentation_active_va=0x12345674,
        handoff_pending_va=0x1018,
        scene_invalidation_count_va=0x1030,
        seed_pages_remaining_va=0x1038,
        flip_count_va=0x1000,
        last_seed_flip_generation_va=0x101C,
        seed_count_va=0x103C,
        last_seed_result_va=0x1040,
    )
    first_call = scene_wrapper.index(b"\xe8")
    assert decode_rel32_branch(
        opcode=BranchOpcode.CALL,
        site_va=0x3000 + first_call,
        instruction=scene_wrapper[first_call : first_call + 5],
    ) == compiler.profile.address("ui.current_layer")
    assert (
        struct.pack("<I", compiler.profile.address("transition.room_layer_vtable")) in scene_wrapper
    )
    assert b"\xff\x05" + struct.pack("<I", 0x1030) in scene_wrapper
    assert b"\xa1" + struct.pack("<I", 0x1000) in scene_wrapper
    assert b"\x3b\x05" + struct.pack("<I", 0x101C) in scene_wrapper


def test_transition_presentation_retains_native_flip() -> None:
    """Modal page ownership and frame cadence remain GK3's native contract."""
    compiler = TransitionFrameCompiler(profile=next(iter(SUPPORTED_BUILDS.values())))
    wrapper_va = 0x3000
    wrapper = compiler._build_flip_wrapper(
        wrapper_va=wrapper_va,
        flip_count_va=0x1000,
        flips_since_begin_va=0x1004,
        repair_active_va=0x1008,
        room_presentation_active_va=0x1050,
        last_flip_result_va=0x100C,
        handoff_pending_va=0x1020,
        seed_pages_remaining_va=0x1024,
        last_seed_flip_generation_va=0x1030,
        exit_2d_count_va=0x1028,
        frame_phase_va=0x102C,
        pre_flip_presenter_slot_va=0x1034,
        post_flip_presenter_slot_va=0x1048,
        post_flip_presenter_call_count_va=0x104C,
        last_presented_flip_generation_va=0x103C,
        presenter_call_count_va=0x1040,
        presenter_retry_skip_count_va=0x1044,
    )
    primary_va = compiler.profile.address("transition.primary_surface_ptr")
    native_flip = b"\xa1" + struct.pack("<I", primary_va) + b"\x56\x6a\x00\x50\x8b\x08\xff\x51\x2c"
    assert native_flip in wrapper
    assert b"\xff\x51\x1c" not in wrapper  # no BltFast presentation substitute
    assert b"\xff\x51\x58" not in wrapper  # no patch-owned cadence loop
    # A linked presenter runs synchronously at the native render-thread Flip
    # boundary; a standalone transition patch leaves the callback cell zero.
    assert b"\xa1" + struct.pack("<I", 0x1034) + b"\x85\xc0" in wrapper
    assert b"\xff\xd0" in wrapper
    # The linked callback is composed once for each pending native page even
    # when Flip retries it. Successful-Flip generation also advances across
    # retained 2D frames which have no BeginScene.
    generation_gate = b"\xa1" + struct.pack("<I", 0x1000) + b"\x3b\x05" + struct.pack("<I", 0x103C)
    assert generation_gate in wrapper
    assert b"\xff\x05" + struct.pack("<I", 0x1040) in wrapper
    assert b"\xff\x05" + struct.pack("<I", 0x1044) in wrapper
    # A 2D interface initializes its own retained pages.  The transition
    # presenter must not copy the newly presented interface into a peer whose
    # producer history has not run.
    tail = wrapper[wrapper.index(native_flip) + len(native_flip) :]
    assert b"\xff\x51\x1c" not in tail


def test_direct_room_presenter_keeps_cursor_native() -> None:
    """Room overlays retain one final-page callback without a second cursor owner."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    action_lifetime_helper_va = 0x00801000
    caption_frame_presenter_va = 0x00801100
    tooltip_frame_presenter_va = 0x00801200
    payload = compiler.cursor_feature().build_cursor_frame_presenter(
        wrapper_va=wrapper_va,
        action_lifetime_helper_va=action_lifetime_helper_va,
        cursor_state_va=0x00802000,
        caption_frame_presenter_va=caption_frame_presenter_va,
        tooltip_frame_presenter_va=tooltip_frame_presenter_va,
        loadsave_frame_presenter_va=0x00801300,
        room_presentation_active_va=0x00791008,
        fixed_canvas_owner_va=0x00801400,
        loadsave_root_ptr_va=0x00801404,
        closeup_frame_presenter_va=0x00801500,
        closeup_destination_handle_va=0x00801504,
        confirm_quit_cursor_suspended_va=0x00801508,
    )

    call_targets = [
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    ]
    assert call_targets[0] == action_lifetime_helper_va
    assert caption_frame_presenter_va in call_targets
    assert tooltip_frame_presenter_va in call_targets
    assert b"\x83\x3d" + struct.pack("<I", 0x00791008) + b"\x00" in payload
    # Direct room rendering never uses the former private surface as an owner.
    assert b"\x83\x3d" + struct.pack("<I", 0x00790000) + b"\x00" not in payload
    # A fixed retained canvas may still require a final native manager draw
    # after cache replay; the direct room branch exits before that code.
    assert profile.address("cursor.manager_draw") in call_targets


def test_closeup_seeds_exactly_two_physical_pages_at_the_flip_owner() -> None:
    """A fixed CloseUp repairs both peers without permanent full redraw."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    target_va = 0x00801000
    owner_va = 0x00802000
    root_va = 0x00802004
    destination_va = 0x00802008
    last_owner_va = 0x0080200C
    budget_va = 0x00802010
    count_va = 0x00802014
    payload = compiler.fixed_screen_feature().build_closeup_frame_presenter(
        wrapper_va=0x00800000,
        target_va=target_va,
        fixed_canvas_owner_va=owner_va,
        shared_root_ptr_va=root_va,
        destination_handle_va=destination_va,
        full_damage_region_va=0x00802100,
        last_owner_va=last_owner_va,
        seed_budget_va=budget_va,
        present_count_va=count_va,
    )
    assert b"\x3b\x35" + struct.pack("<I", root_va) in payload
    assert b"\x81\x3e" + struct.pack("<I", profile.address("closeup.vtable")) in payload
    assert b"\xc7\x05" + struct.pack("<I", budget_va) + b"\x02\x00\x00\x00" in payload
    assert b"\xff\x0d" + struct.pack("<I", budget_va) in payload
    assert b"\xff\x05" + struct.pack("<I", count_va) in payload
    assert any(
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=0x00800000 + offset,
            instruction=payload[offset : offset + 5],
        )
        == target_va
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    )


def test_confirm_quit_copies_completed_front_page_to_returned_back_page_once() -> None:
    """The modal seed validates ownership and never writes to the scan-out page."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    pending_va = 0x00802000
    result_va = 0x00802004
    count_va = 0x00802008
    seeded_root_va = 0x0080200C
    shared_root_va = 0x00802010
    payload = compiler.fixed_screen_feature().build_confirm_quit_post_flip_presenter(
        wrapper_va=wrapper_va,
        pending_va=pending_va,
        result_va=result_va,
        copy_count_va=count_va,
        seeded_root_va=seeded_root_va,
        shared_root_ptr_va=shared_root_va,
        cursor_suspended_va=0x00802014,
        cursor_resume_helper_va=0x00802100,
    )

    calls = [
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    ]
    # Resume once after a successful cursor-free modal seed, or separately
    # after a dismissed dialog has been replaced by a completed room page.
    assert calls == [profile.address("ui.current_layer"), 0x00802100, 0x00802100]
    assert b"\x83\x3d" + struct.pack("<I", pending_va) + b"\x00" in payload
    assert b"\x3b\x05" + struct.pack("<I", shared_root_va) in payload
    assert b"\x81\x38" + struct.pack("<I", profile.address("confirm_quit.vtable")) in payload
    assert struct.pack("<I", profile.address("transition.back_surface_ptr")) in payload
    assert struct.pack("<I", profile.address("transition.primary_surface_ptr")) in payload
    assert b"\xff\x51\x1c" in payload
    assert b"\xa3" + struct.pack("<I", result_va) in payload
    assert b"\xc7\x05" + struct.pack("<I", pending_va) + bytes(4) in payload
    assert b"\xff\x05" + struct.pack("<I", count_va) in payload


def test_confirm_quit_repairs_the_outgoing_cursor_on_both_pages_before_show() -> None:
    """The modal starts from one cursor-free room generation on both peers."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    room_root_va = 0x00802000
    cursor_rect_va = 0x00802010
    destination_handle_va = 0x00802020
    destination_wrapper_va = 0x00802024
    collection_va = 0x00802030
    repair_rect_va = 0x00802040
    primary_surface_ptr_va = profile.address("transition.primary_surface_ptr")
    back_surface_ptr_va = profile.address("transition.back_surface_ptr")
    payload = compiler.fixed_screen_feature().build_confirm_quit_room_repair_helper(
        wrapper_va=wrapper_va,
        room_root_va=room_root_va,
        cursor_rect_va=cursor_rect_va,
        destination_handle_va=destination_handle_va,
        destination_wrapper_va=destination_wrapper_va,
        collection_va=collection_va,
        repair_rect_va=repair_rect_va,
        primary_surface_ptr_va=primary_surface_ptr_va,
        back_surface_ptr_va=back_surface_ptr_va,
    )

    room_vtable = struct.pack("<I", profile.address("transition.room_layer_vtable"))
    assert b"\x81\x3e" + room_vtable in payload
    calls = [
        int(instruction.op_str, 16)
        for instruction in Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, wrapper_va)
        if instruction.mnemonic == "call" and instruction.op_str.startswith("0x")
    ]
    assert calls == [profile.address("ui.current_layer")]
    assert payload.index(b"\x3b\xc6") < payload.index(
        b"\x8b\x1d" + struct.pack("<I", destination_handle_va)
    )
    assert b"\x8b\x1d" + struct.pack("<I", destination_handle_va) in payload
    assert b"\x8b\x3d" + struct.pack("<I", destination_wrapper_va) in payload
    assert b"\x8b\x7f\x2c" in payload
    assert b"\xa1" + struct.pack("<I", primary_surface_ptr_va) in payload
    assert b"\x8b\x15" + struct.pack("<I", back_surface_ptr_va) in payload
    assert b"\xff\x90\xa0\x00\x00\x00" in payload
    assert b"\x92" in payload
    assert b"\xff\x51\x1c" in payload
    assert payload.endswith(b"\x61\x9d\xc3")
    assert len(payload) <= 0x200

    show = compiler.fixed_screen_feature().build_state_wrapper(
        state_va=0x00803000,
        value=1,
        target_va=0x00401000,
        wrapper_va=0x00804000,
        pre_call_va=wrapper_va,
    )
    pre_call = next(offset for offset, byte in enumerate(show) if byte == BranchOpcode.CALL)
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=0x00804000 + pre_call,
            instruction=show[pre_call : pre_call + 5],
        )
        == wrapper_va
    )
    assert pre_call < show.index(b"\xc7\x05" + struct.pack("<I", 0x00803000))


def test_backdrop_slices_preserve_physical_coordinates_and_restore_scope() -> None:
    """Native dim caches must never inherit the surrounding dialog affine."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    state_vas = (0x00801000, 0x00801004, 0x00801008)
    payload = compiler.fixed_screen_feature().build_physical_backdrop_wrapper(
        wrapper_va=wrapper_va,
        transform_mode_va=state_vas[0],
        render_depth_va=state_vas[1],
        input_active_va=state_vas[2],
    )
    assert payload.startswith(
        bytes.fromhex("9c 81 39")
        + struct.pack("<I", profile.address("transition.room_layer_vtable"))
    )
    native_scope = payload.index(bytes.fromhex("55 8b ec 56 8b f1"))
    guard = payload[:native_scope]
    # Only a RoomLayer underneath the current Binocular layer skips its stale
    # backdrop. Preserve all registers/flags and both thiscall arguments; null
    # and other layers still enter the original physical-cache transaction.
    assert bytes.fromhex("85 c0 74") in guard
    assert bytes.fromhex("81 38") + struct.pack("<I", profile.address("binocular.vtable")) in guard
    assert bytes.fromhex("61 9d c2 08 00 61 9d") in guard
    lookup = guard.index(b"\xe8")
    assert decode_rel32_branch(
        opcode=BranchOpcode.CALL,
        site_va=wrapper_va + lookup,
        instruction=guard[lookup : lookup + 5],
    ) == profile.address("ui.current_layer")
    cursor = 0
    for address in state_vas:
        saved = payload.index(bytes.fromhex("ff 35") + struct.pack("<I", address), cursor)
        cleared = payload.index(
            bytes.fromhex("c7 05") + struct.pack("<I", address) + bytes(4), saved
        )
        assert saved < cleared
        cursor = cleared + 10
    call = payload.index(bytes.fromhex("ff 75 0c ff 75 08 8b ce"), cursor) + 8
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + call,
            instruction=payload[call : call + 5],
        )
        == wrapper_va + 0xC0
    )
    cursor = call + 5
    for address in reversed(state_vas):
        cursor = payload.index(bytes.fromhex("8f 05") + struct.pack("<I", address), cursor) + 6
    assert payload[cursor : cursor + 5] == bytes.fromhex("5e c9 c2 08 00")
    native = profile.site("ui.backdrop_draw_entry")
    assert payload[0xC0:0xC5] == native.original
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=wrapper_va + 0xC5,
            instruction=payload[0xC5:0xCA],
        )
        == native.va + 5
    )


def test_console_draw_restores_parent_scope_and_forwards_native_arguments() -> None:
    """The global console does not borrow a retained modal or action-menu root."""
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    state_vas = (0x00801000, 0x00801004, 0x00801008, 0x0080100C)
    payload = compiler.fixed_screen_feature().build_console_draw_scope(
        wrapper_va=wrapper_va, owner_va=0x00802000, damage_helper_va=0x00803000, state_vas=state_vas
    )
    prefix = b"".join(
        b"\xff\x35"
        + struct.pack("<I", address)
        + b"\xc7\x05"
        + struct.pack("<I", address)
        + bytes(4)
        for address in state_vas
    )
    prefix = bytes.fromhex("ff 35 00 20 80 00 89 0d 00 20 80 00") + prefix
    assert payload.startswith(prefix + bytes.fromhex("8b 44 24 1c"))
    damage_call = len(prefix) + 4
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + damage_call,
            instruction=payload[damage_call : damage_call + 5],
        )
        == 0x00803000
    )
    arguments = payload[len(prefix) : damage_call + 5] + bytes.fromhex("50 ff 74 24 1c")
    assert payload.startswith(prefix + arguments)
    call = len(prefix + arguments)
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + call,
            instruction=payload[call : call + 5],
        )
        == compiler._native_draw_va
    )
    suffix = b"".join(b"\x8f\x05" + struct.pack("<I", address) for address in reversed(state_vas))
    assert payload[call + 5 :] == suffix + bytes.fromhex("8f 05 00 20 80 00 c2 08 00")
    assert len(payload) <= compiler._off_console_draw_scope_limit - compiler._off_console_draw_scope


def test_confirm_quit_cursor_pause_does_not_dim_the_native_backdrop_again() -> None:
    """The worker lease must preserve native rendering and cache brightness."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    payload = compiler.fixed_screen_feature().build_confirm_quit_cursor_suspend_helper(
        wrapper_va=0x00800000,
        cursor_refcount_va=0x00801004,
        cursor_suspended_va=0x00801008,
    )
    assert bytes.fromhex("c7 46 30 00 00 00 00") in payload
    assert bytes.fromhex("ff 50 64") not in payload  # no patch-owned surface Lock
    assert bytes.fromhex("ff 90 80 00 00 00") not in payload  # or Unlock
    assert payload.endswith(bytes.fromhex("c3"))


@pytest.mark.parametrize("destructor", [False, True])
def test_unused_quit_dialog_cleanup_cannot_restore_an_unowned_cursor_count(
    destructor: bool,
) -> None:
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    ).fixed_screen_feature()
    token = 0x00801000
    transitions = ((token, (1, 4), 2),)
    if destructor:
        payload = compiler.build_destructor_wrapper(
            wrapper_va=0x00800000,
            render_depth_va=0x00802000,
            input_active_va=0x00802004,
            clear_pending_va=0x00802008,
            root_ptr_va=0x0080200C,
            transform_mode_va=0x00802010,
            target_va=0x00400000,
            state_transitions=transitions,
        )
    else:
        payload = compiler.build_state_wrapper(
            wrapper_va=0x00800000,
            state_va=0x00802000,
            value=0,
            target_va=0x00400000,
            state_transitions=transitions,
        )
    write = b"\xc7\x05" + struct.pack("<II", token, 2)
    # Either suspended (1) or modal-resumed (4) owns cleanup. Dormant (0),
    # already-pending (2), and not-yet-suspended (3) states remain untouched.
    guarded_write = b"\x81\x3d" + struct.pack("<II", token, 4) + b"\x75\x0a" + write
    assert guarded_write in payload
    assert b"\x81\x3d" + struct.pack("<II", token, 1) + b"\x74\x0c" in payload
    assert payload.count(write) == 1
    resume = compiler.build_confirm_quit_cursor_resume_helper(
        wrapper_va=0x00800000, cursor_refcount_va=0x00802000, cursor_suspended_va=token
    )
    assert b"\xc7\x05" + struct.pack("<II", token, 4) in resume


def test_confirm_quit_retires_the_previous_toolbar_tooltip_generation() -> None:
    """A cached toolbar tooltip cannot outlive entry into the quit modal."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = TooltipFeatureCompiler(
        symbols=RuntimeSymbols(
            segments=(RuntimeSegmentAddress(RESOURCE_SEGMENT, 0, 0, 0x00900000),)
        ),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    state = iter(range(0x00802000, 0x00802200, 4))
    payload = compiler.build_tooltip_frame_presenter(
        wrapper_va=wrapper_va,
        object_ptr_va=next(state),
        destination_handle_va=next(state),
        damage_ptr_va=next(state),
        target_va=0x00801000,
        background_helper_va=0x00801100,
        presented_rect_va=next(state),
        visible_latch_va=next(state),
        composition_pending_va=next(state),
        text_pointer_va=next(state),
        text_length_va=next(state),
        mouse_owner_va=next(state),
        hover_target_va=next(state),
        captured_hover_owner_va=next(state),
        hover_identity_valid_va=next(state),
        render_damage_region_va=next(state),
        panel_surface_va=next(state),
        panel_owner_va=next(state),
        panel_capture_mode_va=next(state),
        panel_capture_result_va=next(state),
        depth_va=next(state),
        present_count_va=next(state),
        fixed_modal_object_ptr_va=next(state),
        frame_call_count_va=next(state),
    )

    call_targets = [
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    ]
    assert profile.address("ui.current_layer") in call_targets
    assert b"\x81\x38" + struct.pack("<I", profile.address("confirm_quit.vtable")) in payload


def test_root_arms_post_draw_request_only_after_native_traversal_returns() -> None:
    """A page-copy request cannot expose a partially constructed modal root."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    target_va = 0x00801000
    request_va = 0x00802000
    payload = compiler.fixed_screen_feature().build_root_draw_wrapper(
        wrapper_va=wrapper_va,
        render_depth_va=0x00803000,
        input_active_va=0x00803004,
        clear_pending_va=0x00803008,
        root_ptr_va=0x0080300C,
        transform_mode_va=0x00803010,
        transform_mode=10,
        input_enabled=True,
        target_va=target_va,
        post_draw_request_va=request_va,
        post_draw_request_owner_va=0x00802004,
    )
    native_call = next(
        offset
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
        and decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        == target_va
    )
    request_store = payload.index(b"\xc7\x05" + struct.pack("<I", request_va) + b"\x01\x00\x00\x00")
    assert native_call < request_store


def test_tooltip_draw_scope_brackets_only_the_concrete_native_producer() -> None:
    """Staged tooltip publication preserves native fallback and exact damage."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(
            segments=(RuntimeSegmentAddress(RESOURCE_SEGMENT, 0, 0, 0x00900000),)
        ),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    depth_va = 0x00801000
    count_va = 0x00801004
    target_va = 0x00525470
    dest_handle_va = 0x00804000
    object_ptr_va = 0x00804004
    damage_ptr_va = 0x0080400C
    payload = (
        compiler.menu_feature()
        .tooltip_feature()
        .build_tooltip_draw_wrapper(
            wrapper_va=wrapper_va,
            depth_va=depth_va,
            count_va=count_va,
            target_va=target_va,
            dest_handle_va=dest_handle_va,
            object_ptr_va=object_ptr_va,
            damage_ptr_va=damage_ptr_va,
        )
    )

    assert payload.startswith(b"\x55\x8b\xec\x83\xec\x04\x53\x8b\xd9")
    assert b"\x89\x1d" + struct.pack("<I", object_ptr_va) in payload
    assert b"\x8b\x45\x08\xa3" + struct.pack("<I", dest_handle_va) in payload
    assert (
        b"\x81\x3d"
        + struct.pack("<I", profile.address("display.dimensions") + 4)
        + struct.pack("<I", 768)
        in payload
    )
    assert b"\x80\x7b\x18\x00" in payload
    assert b"\xff\x05" + struct.pack("<I", depth_va) in payload
    assert b"\xff\x05" + struct.pack("<I", count_va) in payload
    assert b"\x8b\x45\x0c\xa3" + struct.pack("<I", damage_ptr_va) in payload
    assert b"\xff\x75\x0c\xff\x75\x08\x8b\xcb" in payload
    assert b"\xff\x0d" + struct.pack("<I", depth_va) in payload
    assert payload.endswith(b"\x8b\x45\xfc\x5b\xc9\xc2\x08\x00")
    calls = [
        target
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
        and (
            target := decode_rel32_branch(
                opcode=BranchOpcode.CALL,
                site_va=wrapper_va + offset,
                instruction=payload[offset : offset + 5],
            )
        )
        is not None
    ]
    assert calls == [target_va]


def test_modal_tooltip_resolver_scopes_idle_toolbar_points_before_native_lookup() -> None:
    """Delayed toolbar lookups reuse the event path's exact inverse once."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    action_root_ptr_va = 0x00801000
    trace_va = 0x00802000
    action_layout_helper_va = 0x00803000
    system_root_ptr_va = 0x00804000
    toolbar_input_valid_va = 0x00804004
    toolbar_input_depth_va = 0x00804008
    toolbar_input_wrapper_va = 0x00805000
    toolbar_inverse_count_va = 0x0080400C
    driving_map_active_va = 0x00804010
    driving_map_input_depth_va = 0x00804014
    input_dispatcher_va = 0x00806000
    payload = (
        compiler.menu_feature()
        .tooltip_feature()
        .build_modal_tooltip_resolver_wrapper(
            wrapper_va=wrapper_va,
            action_root_ptr_va=action_root_ptr_va,
            action_layout_helper_va=action_layout_helper_va,
            trace_va=trace_va,
            system_root_ptr_va=system_root_ptr_va,
            toolbar_input_valid_va=toolbar_input_valid_va,
            toolbar_input_depth_va=toolbar_input_depth_va,
            toolbar_input_wrapper_va=toolbar_input_wrapper_va,
            toolbar_inverse_count_va=toolbar_inverse_count_va,
            driving_map_active_va=driving_map_active_va,
            driving_map_input_depth_va=driving_map_input_depth_va,
            input_dispatcher_va=input_dispatcher_va,
        )
    )

    dimensions_va = profile.address("display.dimensions")
    reference_gate = b"\x81\x3d" + struct.pack("<I", dimensions_va + 4) + struct.pack("<I", 768)
    assert payload.startswith(reference_gate)
    assert decode_rel32_branch(
        opcode=BranchOpcode.JUMP,
        site_va=wrapper_va + 16,
        instruction=payload[16:21],
    ) == profile.address("tooltip.resolve_hover")
    assert b"\x8b\x35" + struct.pack("<I", action_root_ptr_va) in payload
    assert b"\xff\x05" + struct.pack("<I", trace_va) in payload
    assert b"\xa3" + struct.pack("<I", trace_va + 0x28) in payload
    assert b"\x81\x3e" + struct.pack("<I", profile.address("action_menu.vtable")) in payload
    # ActionMenu still receives the physical point and remains the only root
    # queried directly by this wrapper.
    assert b"\x8b\x06\x57\x8b\xce\xff\x90\xbc\x00\x00\x00" in payload
    assert b"\x89\x73\x10\x8b\x4b\x14\x56" in payload
    call_targets = [
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    ]
    assert call_targets == [action_layout_helper_va, profile.address("tooltip.set_descriptor")]
    assert b"\x83\x3d" + struct.pack("<I", toolbar_input_depth_va) + b"\x00" in payload
    assert b"\x83\x3d" + struct.pack("<I", toolbar_input_valid_va) + b"\x00" in payload
    assert b"\x8b\x35" + struct.pack("<I", system_root_ptr_va) in payload
    assert b"\xff\x05" + struct.pack("<I", toolbar_inverse_count_va) in payload
    jump_targets = {
        target
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.JUMP
        and (
            target := decode_rel32_branch(
                opcode=BranchOpcode.JUMP,
                site_va=wrapper_va + offset,
                instruction=payload[offset : offset + 5],
            )
        )
        is not None
    }
    assert b"\x83\x3d" + struct.pack("<I", driving_map_active_va) + b"\x00" in payload
    assert b"\x83\x3d" + struct.pack("<I", driving_map_input_depth_va) + b"\x00" in payload
    assert input_dispatcher_va in jump_targets
    assert toolbar_input_wrapper_va in jump_targets
    assert b"\xc2\x04\x00" in payload
    assert decode_rel32_branch(
        opcode=BranchOpcode.JUMP,
        site_va=wrapper_va + len(payload) - 5,
        instruction=payload[-5:],
    ) == profile.address("tooltip.resolve_hover")


def test_tooltip_visibility_edge_requests_one_native_damage_generation() -> None:
    """The animation's SetVisible edge schedules, but does not draw, a frame."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(
            segments=(RuntimeSegmentAddress(RESOURCE_SEGMENT, 0, 0, 0x00900000),)
        ),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    action_lifetime_helper_va = 0x00801000
    fixed_modal_object_ptr_va = 0x00801004
    present_request_count_va = 0x00801008
    frame_request_pending_va = 0x0080100C
    room_presentation_active_va = 0x00801010
    payload = (
        compiler.menu_feature()
        .tooltip_feature()
        .build_tooltip_visibility_wrapper(
            wrapper_va=wrapper_va,
            action_lifetime_helper_va=action_lifetime_helper_va,
            room_presentation_active_va=room_presentation_active_va,
            fixed_modal_object_ptr_va=fixed_modal_object_ptr_va,
            present_request_count_va=present_request_count_va,
            frame_request_pending_va=frame_request_pending_va,
        )
    )

    assert payload.startswith(b"\x53\x56\x57\x8b\xf1\x8a\x5e\x18")
    assert b"\x3a\x5e\x18" in payload
    assert (
        b"\x81\x3d"
        + struct.pack("<I", profile.address("display.dimensions") + 4)
        + struct.pack("<I", 768)
        in payload
    )
    assert b"\x83\x3d" + struct.pack("<I", room_presentation_active_va) + b"\x00" in payload
    assert b"\x83\x3d" + struct.pack("<I", fixed_modal_object_ptr_va) + b"\x00" in payload
    assert (
        b"\xc7\x05" + struct.pack("<I", frame_request_pending_va) + b"\x01\x00\x00\x00" in payload
    )
    assert b"\xff\x05" + struct.pack("<I", present_request_count_va) in payload
    call_targets = [
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    ]
    assert call_targets == [
        profile.address("tooltip.set_visible"),
        action_lifetime_helper_va,
    ]
    assert payload.endswith(b"\x8b\xc7\x5f\x5e\x5b\xc2\x04\x00")


def test_tooltip_fixed_layer_epilogue_presents_both_native_pages() -> None:
    """The non-reentrant fixed-layer boundary renders both rotating pages."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    pending_va = 0x00801000
    consume_count_va = 0x00801004
    payload = (
        compiler.menu_feature()
        .tooltip_feature()
        .build_tooltip_fixed_layer_epilogue_wrapper(
            wrapper_va=wrapper_va,
            frame_request_pending_va=pending_va,
            frame_request_consume_count_va=consume_count_va,
        )
    )

    assert b"\x83\x3d" + struct.pack("<I", pending_va) + b"\x00" in payload
    assert b"\x83\x25" + struct.pack("<I", pending_va) + b"\x00" in payload
    assert b"\xff\x05" + struct.pack("<I", consume_count_va) in payload
    call_targets = [
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    ]

    assert call_targets == [
        profile.address("engine.render_frame"),
        profile.address("engine.render_frame"),
    ]
    assert payload.endswith(b"\x5f\x5e\x5b\xc2\x04\x00")


def test_destructor_preserves_native_this_across_patch_owned_com_releases() -> None:
    """Patch-owned COM releases cannot clobber a stock destructor's ECX."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    target_va = 0x00401000
    payload = compiler.fixed_screen_feature().build_destructor_wrapper(
        wrapper_va=wrapper_va,
        render_depth_va=0x00801000,
        input_active_va=0x00801004,
        clear_pending_va=0x00801008,
        root_ptr_va=0x0080100C,
        transform_mode_va=0x00801010,
        target_va=target_va,
        extra_release_vas=(0x00801014, 0x00801018),
    )

    assert payload.startswith(b"\x51")
    assert payload.count(b"\xff\x52\x08") == 2
    pop_this_offset = payload.index(b"\x59")
    assert payload[pop_this_offset + 1 : pop_this_offset + 3] == b"\x33\xc0"
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=wrapper_va + len(payload) - 5,
            instruction=payload[-5:],
        )
        == target_va
    )


def test_destructor_withdraws_only_its_owned_publication_before_reentrant_teardown() -> None:
    """A delayed modal destructor cannot expose or erase another UI lifetime."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    owner_va = 0x00801000
    modal_va = 0x00801004
    pending_va = 0x00801008
    release_va = 0x0080100C
    payload = compiler.fixed_screen_feature().build_destructor_wrapper(
        wrapper_va=wrapper_va,
        render_depth_va=0x00801100,
        input_active_va=0x00801104,
        clear_pending_va=0x00801108,
        root_ptr_va=0x0080110C,
        transform_mode_va=0x00801110,
        target_va=0x00401000,
        extra_release_vas=(release_va,),
        publication_owner_va=owner_va,
        pre_clear_vas=(owner_va, modal_va, pending_va),
    )

    owner_compare = b"\x3b\x0d" + struct.pack("<I", owner_va)
    owner_clear = b"\xa3" + struct.pack("<I", owner_va)
    modal_clear = b"\xa3" + struct.pack("<I", modal_va)
    pending_clear = b"\xa3" + struct.pack("<I", pending_va)
    release = b"\xff\x52\x08"
    assert payload.startswith(owner_compare)
    assert payload.index(owner_compare) < payload.index(owner_clear)
    assert payload.index(owner_clear) < payload.index(modal_clear) < payload.index(pending_clear)
    assert payload.index(pending_clear) < payload.index(release)
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=wrapper_va + len(payload) - 5,
            instruction=payload[-5:],
        )
        == 0x00401000
    )


def test_action_lifetime_retires_only_the_owned_system_scope() -> None:
    """A removed transient menu cannot clear a replacement system root."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    shared_root_va = 0x00801004
    payload = (
        compiler.menu_feature()
        .action_feature()
        .build_action_lifetime_helper(
            wrapper_va=wrapper_va,
            action_root_ptr_va=0x00801000,
            shared_root_ptr_va=shared_root_va,
            render_depth_va=0x00801008,
            input_active_va=0x0080100C,
            clear_pending_va=0x00801010,
            transform_mode_va=0x00801014,
            retire_count_va=0x00801064,
            last_root_va=0x00801068,
            last_layer_va=0x0080106C,
        )
    )

    assert b"\x39\x35" + struct.pack("<I", shared_root_va) in payload
    assert b"\xa3" + struct.pack("<I", shared_root_va) in payload


@pytest.mark.parametrize("argument_bytes", [8, 16])
@pytest.mark.parametrize("height", [768, 800, 2160])
@pytest.mark.parametrize("map_active", [False, True])
def test_tooltip_chrome_has_one_owner_during_full_frame_redraws(
    argument_bytes: int,
    height: int,
    map_active: bool,
) -> None:
    """Full-map and HD compositors replace chrome; ordinary 1024 stays native."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(
            segments=(RuntimeSegmentAddress(RESOURCE_SEGMENT, 0, 0, 0x00900000),)
        ),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    target_va = 0x00534870
    payload = (
        compiler.menu_feature()
        .tooltip_feature()
        .build_tooltip_decoration_wrapper(
            wrapper_va=wrapper_va,
            target_va=target_va,
            argument_bytes=argument_bytes,
        )
    )

    cpu = Uc(UC_ARCH_X86, UC_MODE_32)
    cpu.mem_map(0x400000, 0x600000)
    cpu.mem_write(wrapper_va, payload)
    # The native callee returns a sentinel; suppression returns zero.
    cpu.mem_write(target_va, b"\xb8\x7b\x00\x00\x00\xc2" + struct.pack("<H", argument_bytes))
    cpu.mem_write(profile.address("display.dimensions") + 4, struct.pack("<I", height))
    cpu.mem_write(
        0x00900000 + RESOURCE_DRIVING_MAP_INPUT_ACTIVE_OFFSET,
        struct.pack("<I", map_active),
    )
    stack, stop = 0x008F0000, 0x008E0000
    cpu.mem_write(stack, struct.pack("<I", stop) + bytes(argument_bytes))
    cpu.reg_write(UC_X86_REG_ESP, stack)
    cpu.emu_start(wrapper_va, stop, count=100)
    assert cpu.reg_read(UC_X86_REG_EAX) == (123 if height == 768 and not map_active else 0)
    assert cpu.reg_read(UC_X86_REG_ESP) == stack + 4 + argument_bytes


def test_room_status_draw_wrapper_scopes_only_the_exact_owner() -> None:
    """The proven room caption draws synchronously while a modal is current."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    object_ptr_va = 0x00801000
    present_depth_va = 0x00801004
    draw_count_va = 0x00801008
    payload = compiler.room_status_feature().build_room_text_draw_wrapper(
        wrapper_va=wrapper_va,
        object_ptr_va=object_ptr_va,
        present_depth_va=present_depth_va,
        draw_count_va=draw_count_va,
    )

    call_targets = [
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    ]
    assert call_targets.count(profile.address("room_text.draw")) == 2
    assert profile.address("ui.current_layer") in call_targets

    # Scope, class, and first-child identity precede the synchronous draw.
    assert (
        b"\x81\x3e" + struct.pack("<I", profile.address("transition.room_layer_vtable")) in payload
    )
    assert b"\x83\x7e\x50\x00\x0f\x8e" in payload
    assert b"\x8b\x76\x4c\x85\xf6" in payload
    assert b"\x39\x1e" in payload
    assert b"\x89\x1d" + struct.pack("<I", object_ptr_va) in payload
    # A toolbar or ActionMenu temporarily replaces ui.current_layer, but the
    # already-proven caption object must still take the scaled owner path.
    assert b"\x3b\x1d" + struct.pack("<I", object_ptr_va) in payload
    # A modal does not clear the exact live sibling identity; the next room's
    # first-child draw replaces it deterministically.
    assert b"\x3b\x1d" + struct.pack("<I", object_ptr_va) in payload
    assert b"\xff\x05" + struct.pack("<I", present_depth_va) in payload
    assert b"\xff\x0d" + struct.pack("<I", present_depth_va) in payload
    assert b"\xff\x05" + struct.pack("<I", draw_count_va) in payload
    # Direct presentation requires no deferred/cache/page-repair dependencies.
    for symbol in ("transition.primary_surface_ptr", "transition.back_surface_ptr"):
        assert struct.pack("<I", profile.address(symbol)) not in payload
    assert payload.endswith(b"\x8b\x45\xfc\x5f\x5e\x5b\xc9\xc2\x08\x00")


def test_room_status_fill_records_the_exact_authored_rectangle() -> None:
    """Backing diagnostics prove whether the synchronous fill was classified."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    fill_count_va = 0x00801000
    payload = compiler.room_status_feature().build_room_status_fill_wrapper(
        wrapper_va=0x00800000,
        present_depth_va=0x00801004,
        fill_count_va=fill_count_va,
    )

    assert b"\xff\x05" + struct.pack("<I", fill_count_va) in payload


def test_font_alpha_compositor_scales_only_the_published_glyph_pair() -> None:
    """A translucent glyph retains the same affine as its opaque generation."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = InventoryFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
    )
    wrapper_va = 0x00800000
    item_active_va = 0x00801000
    output_rect_va = 0x00801010
    source_rect_va = 0x00801020
    dest_width_va = 0x00801030
    dest_height_va = 0x00801034
    inventory_count_va = 0x00801038
    item_alpha_handle_va = 0x0080103C
    denominator_va = 0x00801040
    numerator_va = 0x00801044
    x_offset_va = 0x00801048
    y_offset_va = 0x0080104C
    scaled_vtable_va = 0x00801050
    font_scaled_vtable_va = 0x00801054
    selected_vtable_va = 0x00801058
    font_active_va = 0x0080105C
    font_count_va = 0x00801060
    physical_height_va = 0x0080106C
    hd_font_active_va = 0x00801070
    hd_font_count_va = 0x008010F4
    payload = build_effect_constructor_wrapper(
        compiler,
        wrapper_va=wrapper_va,
        item_draw_active_va=item_active_va,
        output_rect_va=output_rect_va,
        source_rect_va=source_rect_va,
        dest_width_va=dest_width_va,
        dest_height_va=dest_height_va,
        transform_count_va=inventory_count_va,
        item_alpha_handle_va=item_alpha_handle_va,
        item_dense_source_va=0x008010F8,
        denominator_va=denominator_va,
        numerator_va=numerator_va,
        x_offset_va=x_offset_va,
        y_offset_va=y_offset_va,
        scaled_alpha_vtable_va=scaled_vtable_va,
        font_scaled_alpha_vtable_va=font_scaled_vtable_va,
        selected_vtable_va=selected_vtable_va,
        hud_font_active_va=font_active_va,
        hud_font_point_va=0x00801080,
        hud_font_alpha_transform_count_va=font_count_va,
        hd_font_active_va=hd_font_active_va,
        hd_font_source_transform_count_va=hd_font_count_va,
        physical_height_va=physical_height_va,
    )

    assert b"\x83\x3d" + struct.pack("<I", font_active_va) + b"\x00" in payload
    assert b"\x83\x3d" + struct.pack("<I", hd_font_active_va) + b"\x00" in payload
    assert b"\xff\x05" + struct.pack("<I", hd_font_count_va) in payload
    assert b"\x8b\x74\x24\x2c" in payload
    assert b"\xff\x05" + struct.pack("<I", font_count_va) in payload
    assert struct.pack("<I", physical_height_va) in payload
    assert (
        b"\xc7\x05"
        + struct.pack("<I", selected_vtable_va)
        + struct.pack("<I", font_scaled_vtable_va)
        in payload
    )
    assert (
        b"\xc7\x05" + struct.pack("<I", selected_vtable_va) + struct.pack("<I", scaled_vtable_va)
        in payload
    )
    assert b"\x8b\x15" + struct.pack("<I", selected_vtable_va) + b"\x89\x10" in payload
    # The pre-existing Inventory owner remains an independent exact branch of
    # the one shared constructor dispatcher.
    assert b"\x83\x3d" + struct.pack("<I", item_active_va) + b"\x00" in payload
    assert b"\x3b\x05" + struct.pack("<I", item_alpha_handle_va) in payload
    assert (
        compiler._off_effect_constructor_wrapper + len(payload)
        <= compiler._off_scaled_alpha_callback
    )
    assert decode_rel32_branch(
        opcode=BranchOpcode.JUMP,
        site_va=wrapper_va + len(payload) - 5,
        instruction=payload[-5:],
    ) == profile.address("bitmap.effect_constructor")


def test_hud_font_wrapper_preserves_atlas_and_effect_arguments() -> None:
    """The screen affine changes only the destination point passed to GK3."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    root_ptr_va = 0x00801010
    payload = compiler.load_save_feature().build_loadsave_font_wrapper(
        wrapper_va=0x00800000,
        root_ptr_va=root_ptr_va,
        font_rect_helper_va=0x00802100,
        hud_font_active_va=0x00801020,
        hud_font_transform_count_va=0x00801028,
        hud_font_last_point_va=0x00801030,
        hd_font_active_va=0x00801058,
        hd_font_handle_count_va=0x00801060,
        hd_font_handles_va=0x00801064,
        room_status_present_depth_va=0x00801068,
    )

    # Saved scopes, saved POINT, local POINT and PUSHAD put arg3 at +0x44.
    # Replace it only with this frame's local POINT at +0x20; arg4 (+0x48)
    # and arg5 (+0x4c) stay untouched.
    assert payload.count(b"\x8d\x44\x24\x20\x89\x44\x24\x44") == 2
    assert b"\x89\x44\x24\x48" not in payload
    assert b"\x89\x44\x24\x4c" not in payload
    # CloseUp/Fingerprint HUD copies and the late room-caption submissions made by
    # Inventory and the in-game toolbar are accepted only for their exact
    # classes and a non-negative POINT inside x<1024, y<32.
    assert b"\x81\x38" + struct.pack("<I", profile.address("closeup.vtable")) in payload
    assert b"\x81\x38" + struct.pack("<I", profile.address("fingerprint.vtable")) in payload
    assert b"\xa1" + struct.pack("<I", root_ptr_va) + b"\x85\xc0" in payload
    assert b"\x81\x38" + struct.pack("<I", profile.address("inventory.vtable")) in payload
    assert b"\x81\x38" + struct.pack("<I", profile.address("ingame_toolbar.vtable")) in payload
    assert b"\x8b\x74\x24\x44\x85\xf6" in payload
    assert b"\x3d\x00\x04\x00\x00" in payload
    assert b"\x83\xf9\x20" in payload
    # The scoped call duplicates all five original arguments in reverse order;
    # GK3 therefore receives untouched arg4/arg5 along with the mapped point.
    assert payload.count(b"\xff\x74\x24\x2c") == 5


def test_hud_font_wrapper_restores_outer_scopes_after_nested_submission() -> None:
    """A nested glyph cannot clear the outer glyph's HUD or atlas scope."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    hud_font_active_va = 0x00801020
    hd_font_active_va = 0x00801058
    payload = compiler.load_save_feature().build_loadsave_font_wrapper(
        wrapper_va=0x00800000,
        root_ptr_va=0x00801010,
        font_rect_helper_va=0x00802100,
        hud_font_active_va=hud_font_active_va,
        hud_font_transform_count_va=0x00801028,
        hud_font_last_point_va=0x00801030,
        hd_font_active_va=hd_font_active_va,
        hd_font_handle_count_va=0x00801060,
        hd_font_handles_va=0x00801064,
        room_status_present_depth_va=0x00801068,
    )

    assert payload.startswith(
        b"\xff\x35"
        + struct.pack("<I", hd_font_active_va)
        + b"\xff\x35"
        + struct.pack("<I", hud_font_active_va)
        + b"\xff\x35"
        + struct.pack("<I", 0x00801034)
        + b"\xff\x35"
        + struct.pack("<I", 0x00801030)
        + b"\x83\xec\x08\x60"
    )
    for offset, state_va in (
        (0x0C, 0x00801030),
        (0x10, 0x00801034),
        (0x14, hud_font_active_va),
        (0x18, hd_font_active_va),
    ):
        assert b"\x8b\x44\x24" + bytes([offset]) + b"\xa3" + struct.pack("<I", state_va) in payload
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x00800000))
    # No unclassified tail-jump may restore outer flags before native draws.
    # The density scope carries the matched handle, not a generic true flag.
    assert b"\xa3" + struct.pack("<I", hd_font_active_va) in payload
    assert b"\xc7\x05" + struct.pack("<II", hd_font_active_va, 1) not in payload
    native_transfers = [
        insn.mnemonic for insn in instructions if insn.op_str == hex(compiler._font_blt_target_va)
    ]
    assert native_transfers == ["call"]
    assert payload.endswith(b"\x58\x83\xc4\x18\xc2\x14\x00")


def test_hd_font_atlas_scope_requires_a_vetted_handle() -> None:
    """Glyph submission consumes only handles vetted during metric loading."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    payload = compiler.load_save_feature().build_loadsave_font_wrapper(
        wrapper_va=0x00800000,
        root_ptr_va=0x00801010,
        font_rect_helper_va=0x00802100,
        hud_font_active_va=0x00801020,
        hud_font_transform_count_va=0x00801028,
        hud_font_last_point_va=0x00801030,
        hd_font_active_va=0x00801058,
        hd_font_handle_count_va=0x00801060,
        hd_font_handles_va=0x00801064,
        room_status_present_depth_va=0x00801068,
    )

    assert b"\x8b\x0d" + struct.pack("<I", 0x00801060) in payload
    assert b"\x0f\xb7\x14\x7d" + struct.pack("<I", 0x00801064) in payload
    assert struct.pack("<I", profile.address("bitmap.resolve_resource")) not in payload


def test_hd_font_metrics_normalize_complete_native_tables() -> None:
    """The loader maps every 4x marker coordinate back to logical space."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    payload = compiler.load_save_feature().build_hd_font_metrics_wrapper(
        wrapper_va=wrapper_va,
        normalize_count_va=0x00801000,
        handle_count_va=0x00801004,
        handles_va=0x00801008,
    )

    assert payload.startswith(b"\x60")
    assert b"\xf7\x42\x38\x03\x00\x00\x00" in payload
    assert b"\xf7\x42\x3c\x03\x00\x00\x00" in payload
    assert b"\x0f\xb7\x14\x7d" + struct.pack("<I", 0x00801008) in payload
    assert b"\x66\x89\x04\x4d" + struct.pack("<I", 0x00801008) in payload
    assert b"\x83\xf9\x40" in payload
    assert b"\x0f\xb7\x44\x4e\x50" in payload  # 257 inline boundary WORDs
    assert b"\x8b\xbe\x58\x02\x00\x00" in payload  # row-X table pointer
    assert b"\x8b\xae\x5c\x02\x00\x00" in payload  # row-Y table pointer
    assert b"\x66\x83\xc0\x03\x66\xc1\xe8\x02" in payload
    assert compiler._font_metrics_original in payload
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=wrapper_va + len(payload) - 5,
            instruction=payload[-5:],
        )
        == compiler._font_metrics_continue_va
    )


def test_inventory_hide_withdraws_the_same_lifetime_as_destruction() -> None:
    """Normal Inventory Exit hides a retained object instead of destroying it."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = InventoryFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
    )
    wrapper_va = 0x00800000
    active_va = 0x00801000
    first_page_va = 0x00801004
    second_page_va = 0x00801008
    render_depth_va = 0x0080100C
    input_active_va = 0x00801010
    clear_pending_va = 0x00801014
    root_va = 0x00801018
    mode_va = 0x0080101C
    target_va = profile.address("ui.hide")
    payload = compiler._build_lifetime_wrapper(
        wrapper_va=wrapper_va,
        target_va=target_va,
        active_inventory_va=active_va,
        first_page_surface_va=first_page_va,
        second_page_surface_va=second_page_va,
        system_render_depth_va=render_depth_va,
        system_input_active_va=input_active_va,
        system_clear_pending_va=clear_pending_va,
        system_root_ptr_va=root_va,
        system_transform_mode_va=mode_va,
    )

    assert payload.startswith(b"\x3b\x0d" + struct.pack("<I", active_va))
    for address in (
        active_va,
        first_page_va,
        second_page_va,
        render_depth_va,
        input_active_va,
        clear_pending_va,
        root_va,
        mode_va,
    ):
        assert b"\xa3" + struct.pack("<I", address) in payload
    assert b"\x3b\x0d" + struct.pack("<I", root_va) in payload
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=wrapper_va + len(payload) - 5,
            instruction=payload[-5:],
        )
        == target_va
    )
    assert compiler._off_destructor_wrapper + len(payload) <= compiler._off_hide_wrapper
    assert compiler._off_hide_wrapper + len(payload) <= compiler._off_clear_page_helper


def test_font_alpha_scaler_delegates_pixel_semantics_to_gk3() -> None:
    """Resampling changes local coordinates but leaves every blend rule native."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = InventoryFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
    )
    callback_va = 0x00800000
    payload = build_scaled_font_alpha_callback(
        compiler,
        callback_va=callback_va,
        source_rect_va=0x00801000,
        dest_width_va=0x00801010,
        dest_height_va=0x00801014,
        trace_va=0x00801020,
    )

    call_targets = {
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=callback_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset, opcode in enumerate(payload[:-4])
        if opcode == BranchOpcode.CALL
    }
    assert profile.address("bitmap.effect_callback") in call_targets
    # The effect constructor advances its source base to the clipped source
    # rectangle. The resampler must not add the original atlas offset again.
    assert b"\x03\x05" + struct.pack("<I", 0x00801000) + b"\x89\x45\xd0" not in payload
    assert b"\x03\x05" + struct.pack("<I", 0x00801004) + b"\x89\x45\xd4" not in payload
    # Both exclusive loop bounds use JGE after ``cmp index, extent``. A JLE
    # here returns before processing the initial zero-valued row or column.
    assert payload.count(b"\x0f\x8d") >= 2
    assert payload.endswith(b"\x5f\x5e\x5b\x8b\xe5\x5d\xc2\x10\x00")


def _caption_compiler() -> CaptionFeatureCompiler:
    """Return a caption compiler with explicit synthetic runtime addresses."""
    return CaptionFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=next(iter(SUPPORTED_BUILDS.values())),
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )


def test_caption_segment_keeps_mutable_state_before_executable_slots() -> None:
    """Caption cache state and COM wrappers cannot overlap injected code."""
    compiler = _caption_compiler()

    assert compiler._off_cleanup_scaled_rect + 16 <= compiler._off_cache_surface
    assert compiler._off_cache_destination_surface + 4 <= compiler._off_draw_wrapper
    assert compiler._off_cache_generation_rect + 16 <= compiler._off_draw_wrapper
    assert compiler._off_draw_wrapper < compiler._off_draw_wrapper_limit
    assert compiler._off_draw_wrapper_limit == compiler._off_destructor_wrapper
    assert compiler._off_cache_ensure_helper < compiler._off_cache_ensure_helper_limit
    assert compiler._off_cache_ensure_helper_limit <= compiler._section_size


def test_caption_draw_wrapper_publishes_one_bounded_native_transaction() -> None:
    """The exact Caption class queues at most CaptionMgr's native capacity."""
    compiler = _caption_compiler()
    wrapper_va = 0x00800000
    geometry_va = 0x00800500
    payload = compiler._build_draw_wrapper(
        wrapper_va=wrapper_va,
        geometry_helper_va=geometry_va,
        queue_count_va=0x0080000C,
        entries_va=0x00800040,
        defer_count_va=0x00800010,
        overflow_count_va=0x00800020,
        room_presentation_active_va=0x00791008,
    )

    assert b"\x83\xf8\x03" in payload
    assert b"\x6b\xc0\x38" in payload
    assert b"\x83\x3d" + struct.pack("<I", 0x00791008) + b"\x00" in payload
    call_targets = {
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    }
    assert geometry_va in call_targets
    assert compiler.profile.address("caption.draw") in call_targets
    assert payload.endswith(b"\xc2\x08\x00")


def test_caption_glyph_recorder_is_owned_by_live_caption_scope() -> None:
    """Only Caption's nested final glyph blits contribute to its tight cache."""
    wrapper_va = 0x00801500
    active_object_va = 0x00800018
    glyph_rect_valid_va = 0x00800254
    glyph_rect_va = 0x00800258
    damage_record_helper_va = 0x00801100
    payload = CaptionFeatureCompiler._build_glyph_recorder(
        wrapper_va=wrapper_va,
        active_object_va=active_object_va,
        glyph_rect_valid_va=glyph_rect_valid_va,
        glyph_rect_va=glyph_rect_va,
        damage_record_helper_va=damage_record_helper_va,
    )

    assert b"\x83\x3d" + struct.pack("<I", active_object_va) + b"\x00" in payload
    assert b"\xbf" + struct.pack("<I", glyph_rect_valid_va) in payload
    assert b"\xba" + struct.pack("<I", glyph_rect_va) in payload
    call_offset = payload.index(bytes([BranchOpcode.CALL]))
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + call_offset,
            instruction=payload[call_offset : call_offset + 5],
        )
        == damage_record_helper_va
    )
    assert payload.endswith(b"\x61\xc3")


def test_caption_presenter_owns_font_scope_and_scaled_cleanup() -> None:
    """Final-page replay validates the class and chains its cleanup union."""
    compiler = _caption_compiler()
    presenter_va = 0x00800300
    active_object_va = 0x00800018
    active_clip_va = 0x0080001C
    presenter = compiler._build_presenter(
        wrapper_va=presenter_va,
        queue_count_va=0x0080000C,
        entries_va=0x00800040,
        active_object_va=active_object_va,
        active_clip_va=active_clip_va,
        present_count_va=0x00800014,
        destination_handle_va=0x00810000,
        room_presentation_active_va=0x00791008,
        cache_ensure_helper_va=0x00801180,
        cache_surface_va=0x00800108,
        cache_ready_va=0x00800110,
        cache_object_count_va=0x00800114,
        cache_objects_va=0x00800118,
        cache_rect_va=0x00800124,
        cache_generation_rect_va=0x00800268,
        current_rect_va=0x00800134,
        glyph_rect_valid_va=0x00800254,
        glyph_rect_va=0x00800258,
        cache_bltfx_va=0x008001C0,
        cache_fill_result_va=0x00800234,
        cache_present_result_va=0x0080023C,
        cache_build_count_va=0x00800240,
        cache_replay_count_va=0x00800244,
        cache_destination_wrapper_va=0x0080024C,
        cache_destination_surface_va=0x00800250,
    )
    augmenter = compiler._build_damage_augmenter(
        wrapper_va=0x00800700,
        pending_valid_va=0x0080002C,
        pending_rect_va=0x00800030,
        augment_count_va=0x00800028,
    )

    assert b"\x81\x3b" + struct.pack("<I", compiler.profile.address("caption.vtable")) in presenter
    assert b"\x89\x1d" + struct.pack("<I", active_object_va) in presenter
    assert b"\xa3" + struct.pack("<I", active_clip_va) in presenter
    assert presenter.endswith(b"\x83\xc4\x04\x61\x9d\xc3")
    assert b"\x6a\x10" in presenter
    assert b"\xff\x50\x1c" in presenter
    for dimension_va in (
        compiler.profile.address("display.dimensions"),
        compiler.profile.address("display.dimensions") + 4,
        0x00790004,
        0x00790008,
    ):
        assert struct.pack("<I", dimension_va) in augmenter
    assert b"\xc7\x05" + struct.pack("<I", 0x0080002C) + b"\x00" * 4 in augmenter


def test_action_layout_publishes_its_owner_at_authored_height() -> None:
    """Reference geometry still participates in exact modal teardown."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    state_va = 0x00802000
    payload = (
        compiler.menu_feature()
        .action_feature()
        .build_action_layout_helper(
            wrapper_va=0x00800000,
            state_va=state_va,
        )
    )
    height_test = payload.index(
        b"\x81\x3d"
        + struct.pack("<I", profile.address("display.dimensions") + 4)
        + struct.pack("<I", 768)
    )
    authored_branch = height_test + 10
    authored_target = (
        authored_branch + 6 + struct.unpack_from("<i", payload, authored_branch + 2)[0]
    )
    owner_store = payload.rindex(b"\x89\x35" + struct.pack("<I", state_va + 0x20))

    assert payload[authored_branch : authored_branch + 2] == b"\x0f\x86"
    assert authored_target == owner_store


def test_toolbar_blt_ownership_includes_live_popup_outside_root() -> None:
    """An upward list owns its backing and first rows, without owning room art."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    source_rect_va = 0x00801000
    payload = (
        compiler.menu_feature()
        .action_feature()
        .build_toolbar_blt_helper(
            wrapper_va=0x00800000,
            preview_surface_va=0x00801300,
            dropdown_ptr_va=0x00801304,
            root_ptr_va=0x00801040,
            source_rect_va=source_rect_va,
            target_rect_va=0x00801050,
            dest_rect_va=0x00801060,
            transform_count_va=0x00801070,
            clipped_source_rect_va=0x00801200,
            cursor_surface_classifier_va=0x00802000,
            input_snapshot_valid_va=0x00801248,
            input_snapshot_source_rect_va=0x0080124C,
            input_snapshot_target_rect_va=0x0080125C,
        )
    )

    # Compare every destination edge directly with the matching live-root edge.
    # Near edges outside the root branch on JL; far edges branch on JG. This
    # exact containment policy replaced a wide proximity gate whose ``CMP``
    # operands were documented backwards and consequently rejected every
    # legitimate toolbar child.
    comparisons = (
        (
            b"\x8b\x46\x00\x3b\x05" + struct.pack("<I", source_rect_va),
            b"\x0f\x8c",
        ),
        (
            b"\x8b\x46\x04\x3b\x05" + struct.pack("<I", source_rect_va + 4),
            b"\x0f\x8c",
        ),
        (
            b"\x8b\x46\x08\x3b\x05" + struct.pack("<I", source_rect_va + 8),
            b"\x0f\x8f",
        ),
        (
            b"\x8b\x46\x0c\x3b\x05" + struct.pack("<I", source_rect_va + 12),
            b"\x0f\x8f",
        ),
    )
    for prefix, expected_branch in comparisons:
        branch_offset = payload.index(prefix) + len(prefix)
        assert payload[branch_offset : branch_offset + 2] == expected_branch

    # Root misses must validate the exact visible popup and all four edges.
    assert b"\x8b\x15" + struct.pack("<I", 0x00801304) in payload
    assert b"\x81\x3a" + struct.pack("<I", profile.address("resolution_dropdown.vtable")) in payload
    assert bytes.fromhex("80 7a 18 00") in payload
    for displacement in (0, 4, 8, 12):
        assert b"\x3b\x42" + bytes([0x1C + displacement]) in payload

    # Buttons now retain logical dimensions before clipping. A late dense-
    # extent shrink here would apply density twice and lose image fragments.
    assert b"\x83\x7a\x3c\x44" not in payload
    for width in (240, 268, 340, 676):
        assert b"\x3d" + struct.pack("<I", width) not in payload


def test_resolution_dropdown_highlight_uses_exact_child_identity() -> None:
    """The solid hover primitive shares the popup affine without heuristics."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    pending_ptr_va = 0x00801000
    source_rect_va = 0x00802000
    target_rect_va = 0x00802010
    full_damage_region_va = 0x00803000
    transform_count_va = 0x00804000
    trace_va = 0x00805000
    target_va = profile.address("solid_color.draw")
    payload = (
        compiler.menu_feature()
        .dropdown_feature()
        .build_resolution_dropdown_highlight_wrapper(
            wrapper_va=wrapper_va,
            pending_ptr_va=pending_ptr_va,
            source_rect_va=source_rect_va,
            target_rect_va=target_rect_va,
            full_damage_region_va=full_damage_region_va,
            transform_count_va=transform_count_va,
            trace_va=trace_va,
            target_va=target_va,
        )
    )

    # Only popup+0x134 with the recovered concrete vtable can enter the affine.
    assert b"\xa1" + struct.pack("<I", pending_ptr_va) in payload
    assert b"\x05\x34\x01\x00\x00\x3b\xd8" in payload
    assert b"\x81\x3b" + struct.pack("<I", profile.address("solid_color.vtable")) in payload
    # The transformed draw receives complete damage, restores its authored
    # rectangle, and publishes one diagnostic count. Native calls stay intact.
    assert b"\x68" + struct.pack("<I", full_damage_region_va) in payload
    assert b"\xff\x05" + struct.pack("<I", transform_count_va) in payload
    assert b"\xff\x05" + struct.pack("<I", trace_va) in payload
    target_calls = [
        offset
        for offset in range(len(payload) - 4)
        if decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        == target_va
    ]
    assert len(target_calls) == 2


def test_resolution_dropdown_lifetime_begins_before_its_first_draw() -> None:
    """SetVisible owns fit/publication so the popup cannot expose a raw frame."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    input_active_va = 0x00801000
    root_ptr_va = 0x00801800
    pending_ptr_va = 0x00802000
    seed_budget_va = 0x00802500
    saved_root_bottom_va = 0x00802600
    root_bottom_valid_va = 0x00802700
    fit_helper_va = 0x00803000
    target_va = profile.address("resolution_dropdown.set_visible")
    payload = (
        compiler.menu_feature()
        .dropdown_feature()
        .build_resolution_dropdown_visibility_wrapper(
            wrapper_va=wrapper_va,
            input_active_va=input_active_va,
            root_ptr_va=root_ptr_va,
            pending_ptr_va=pending_ptr_va,
            seed_budget_va=seed_budget_va,
            saved_root_bottom_va=saved_root_bottom_va,
            root_bottom_valid_va=root_bottom_valid_va,
            fit_helper_va=fit_helper_va,
            target_va=target_va,
        )
    )

    # The complete lifetime owner has a dedicated bounded code slot.
    assert len(payload) <= (
        compiler._off_resolution_dropdown_visibility_limit
        - compiler._off_resolution_dropdown_visibility_wrapper
    )

    # The Boolean argument and exact toolbar scope gate Show. Fit precedes
    # publication, while Hide clears only an identical retained pointer.
    assert b"\x80\x7c\x24\x04\x00" in payload
    assert b"\x83\x3d" + struct.pack("<I", input_active_va) + b"\x00" in payload
    assert b"\x89\x0d" + struct.pack("<I", pending_ptr_va) in payload
    assert b"\x39\x0d" + struct.pack("<I", pending_ptr_va) in payload
    assert b"\xc7\x05" + struct.pack("<I", seed_budget_va) + b"\x02\x00\x00\x00" in payload
    assert b"\x8b\x50\x28\x89\x15" + struct.pack("<I", saved_root_bottom_va) in payload
    assert b"\x8b\x51\x28\x39\x50\x28" in payload
    assert b"\x8b\x15" + struct.pack("<I", saved_root_bottom_va) + b"\x89\x50\x28" in payload
    fit_call = next(
        offset
        for offset in range(len(payload) - 4)
        if decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        == fit_helper_va
    )
    assert fit_call < payload.index(b"\x89\x0d" + struct.pack("<I", pending_ptr_va))
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=wrapper_va + len(payload) - 5,
            instruction=payload[-5:],
        )
        == target_va
    )


def test_resolution_dropdown_redraws_every_row_after_parent_damage() -> None:
    """A changed toolbar cannot repaint through a partially damaged sibling list."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    full_damage_region_va = 0x00801000
    full_damage_rect_va = 0x00801020
    target_va = profile.address("resolution_dropdown.draw")
    payload = (
        compiler.menu_feature()
        .dropdown_feature()
        .build_resolution_dropdown_present_helper(
            wrapper_va=wrapper_va,
            pending_ptr_va=0x00802000,
            root_ptr_va=0x00803000,
            saved_root_bottom_va=0x00803004,
            root_bottom_valid_va=0x00803008,
            render_depth_va=0x00802004,
            full_damage_region_va=full_damage_region_va,
            full_damage_rect_va=full_damage_rect_va,
            target_va=target_va,
        )
    )

    # The helper is reached only from an already damage-gated toolbar draw. It
    # must therefore pass complete damage unconditionally; consulting a seed
    # counter here would regress later hover/tooltip generations to partial
    # row redraws.
    assert b"\xb8" + struct.pack("<I", full_damage_region_va) in payload
    assert (
        b"\x83\x3d"
        not in payload[: payload.index(b"\xb8" + struct.pack("<I", full_damage_region_va))]
    )
    assert b"\x8b\x15" + struct.pack("<I", 0x00803004) + b"\x89\x50\x28" in payload
    assert b"\xc7\x05" + struct.pack("<I", 0x00803008) + bytes(4) in payload
    assert any(
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        == target_va
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    )


def test_resolution_dropdown_fit_is_driven_by_overflow_at_reference_height() -> None:
    """The runtime mode list can overflow even on the 1024x768 reference screen."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    root_ptr_va = 0x00802000
    payload = (
        compiler.menu_feature()
        .dropdown_feature()
        .build_resolution_dropdown_fit_helper(
            wrapper_va=0x00800000,
            root_ptr_va=root_ptr_va,
        )
    )

    # enable_modern_resolutions can expose many more rows than the original
    # list at any framebuffer height. The signed overflow calculation, not a
    # resolution threshold, is the sole no-op decision.
    forbidden_height_gate = (
        b"\x81\x3d" + struct.pack("<I", compiler._physical_width_va + 4) + struct.pack("<I", 768)
    )
    assert forbidden_height_gate not in payload
    assert b"\x8b\x3d" + struct.pack("<I", root_ptr_va) in payload
    assert b"\x8b\x46\x28\x2b\xc5" in payload
    assert b"\x29\x6e\x20\x29\x6e\x28" in payload


def test_cursor_hotspot_adjustment_is_shared_by_drawing_and_save_under() -> None:
    """Busy and offset cursors scale around the pointer, not the sprite corner."""
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    feature = compiler.cursor_feature()
    helper = 0x00803A50
    payload = feature.build_cursor_hotspot_adjustment(wrapper_va=helper)
    assert len(payload) <= 0xB0
    assert payload.startswith(b"\x9c\x60")
    assert payload.endswith(b"\x61\x9d\xc3")
    assert b"\x81\xfd\x00\x03\x00\x00" in payload
    for offset in (0x28, 0x2C):
        assert b"\x8b\x46" + bytes([offset]) in payload
        assert b"\x2b\x46" + bytes([offset]) in payload
    # Both wrappers fit their existing slots and call the identical transform.
    base = 0x00800000
    for wrapper in (
        feature.build_cursor_scope_wrapper(
            wrapper_va=base, cursor_active_va=0x00802000, hotspot_va=helper
        ),
        feature.build_cursor_bounds_wrapper(wrapper_va=base, hotspot_va=helper),
        feature.build_cursor_prep_wrapper(
            wrapper_va=base,
            cursor_state_va=0x00801000,
            cursor_active_va=0x00802000,
            sidney_root_ptr_va=0x00803000,
            hotspot_va=helper,
        ),
    ):
        assert len(wrapper) <= 0x100
        assert any(
            insn.mnemonic == "call" and insn.op_str == hex(helper)
            for insn in Cs(CS_ARCH_X86, CS_MODE_32).disasm(wrapper, base)
        )


def test_cursor_preparation_accepts_exact_startup_scope_before_scene_lookup() -> None:
    """A synchronous cursor does not require the not-yet-created scene dispatcher."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    base = 0x00800000
    scope_va = 0x00802000
    payload = compiler.cursor_feature().build_cursor_prep_wrapper(
        wrapper_va=base,
        cursor_state_va=0x00801000,
        cursor_active_va=scope_va,
        sidney_root_ptr_va=0x00803000,
        hotspot_va=0x00803A50,
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, base))
    scoped = next(
        i for i, insn in enumerate(instructions) if insn.op_str == f"ebx, dword ptr [{scope_va:#x}]"
    )
    branch = instructions[scoped + 1]
    assert branch.mnemonic == "je"
    destination = int(branch.op_str, 16) - base
    # The fast path still validates both caller-owned geometry pointers. It
    # skips only the scene lifetime lookup and queued SIDNEY point repair.
    assert payload[destination : destination + 6] == b"\x8b\x74\x24\x2c\x85\xf6"
    assert instructions[scoped].address < base + payload.index(
        b"\xa1" + struct.pack("<I", profile.address("engine.loop"))
    )
    assert b"\x8b\x74\x24\x30\x85\xf6" in payload[destination:]
    assert b"\x8b\x40\x70\x3b\xc3" in payload  # Queued calls still require identity.
    assert len(payload) <= 0x100


def test_cursor_manager_keeps_native_draw_and_scopes_sidney_point_repair() -> None:
    """Direct rooms retain native save-under; only SIDNEY rewrites old points."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    stage_surface_va = 0x00790000
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    payload = compiler.cursor_feature().build_cursor_manager_draw_wrapper(
        wrapper_va=0x00800000,
        cursor_state_va=0x00801000,
        sidney_active_depth_va=0x00802000,
    )

    assert b"\x8b\x44\x24\x28\xa3" + struct.pack("<I", 0x00801000 + 128) in payload
    assert b"\x83\x3d" + struct.pack("<I", 0x00802000) + b"\x00" in payload
    assert struct.pack("<I", profile.address("loadgame.vtable")) not in payload
    assert struct.pack("<I", profile.address("savegame.vtable")) not in payload
    assert b"\xff\x05" + struct.pack("<I", 0x00804000) not in payload
    assert b"\x83\x3d" + struct.pack("<I", stage_surface_va) + b"\x00" not in payload
    assert struct.pack("<I", profile.address("ui.current_layer")) not in payload
    assert struct.pack("<I", profile.address("transition.room_layer_vtable")) not in payload
    assert b"\xff\x05" + struct.pack("<I", 0x00801000 + 144) not in payload
    assert b"\x61\x9d\xc2\x08\x00" not in payload
    assert b"\xff\x05" + struct.pack("<I", 0x00801000 + 84) in payload
    assert decode_rel32_branch(
        opcode=BranchOpcode.JUMP,
        site_va=0x00800000 + len(payload) - 5,
        instruction=payload[-5:],
    ) == profile.address("cursor.manager_draw")


def test_loadsave_post_draw_cursor_uses_native_manager_transaction() -> None:
    """A completed fitted root re-submits any live cursor at the z-order boundary."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    payload = compiler.cursor_feature().build_loadsave_post_draw_cursor_presenter(
        wrapper_va=0x00803000
    )

    # The helper uses the concrete destination passed by the completed root,
    # skips the authored reference path, and follows GK3's live manager chain.
    assert b"\x8b\x5c\x24\x1c\x85\xdb" in payload
    assert b"\x81\x3d" + struct.pack("<I", profile.address("display.dimensions") + 4) in payload
    assert b"\x8b\x15" + struct.pack("<I", profile.address("engine.loop")) in payload
    assert b"\x81\x3e" + struct.pack("<I", profile.address("cursor.manager_vtable")) in payload
    assert b"\x83\x7e\x70\x00" in payload
    call_site = payload.index(b"\xe8")
    assert decode_rel32_branch(
        opcode=BranchOpcode.CALL,
        site_va=0x00803000 + call_site,
        instruction=payload[call_site : call_site + 5],
    ) == profile.address("cursor.manager_draw")
    assert b"\x8d\x86\xb4\x01\x00\x00\x50\x53\x8b\xce" in payload
    assert struct.pack("<II", 1920, 1080) not in payload
    assert struct.pack("<II", 3840, 2160) not in payload


def test_restore_progress_sizes_the_concrete_owner_during_construction() -> None:
    """Dense storage and logical presentation diverge at the model owner."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    payload = compiler.load_save_feature().build_restore_progress_background_attach_wrapper(
        wrapper_va=wrapper_va,
    )

    call_targets = [
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        for offset in range(len(payload) - 4)
        if payload[offset] == BranchOpcode.CALL
    ]
    assert call_targets.count(profile.address("restore_progress.background_attach")) == 1

    # The exact constructor call proves both the producer class and that the
    # resource has already been selected. No name/dimension classifier or
    # lifetime publication participates in the policy.
    assert (
        compiler._restore_progress_background_attach_call_va
        == profile.site("restore_progress.background_attach_call").va
    )
    assert b"\x8b\x3d" + struct.pack("<I", profile.address("display.dimensions") + 4) in payload
    assert b"\x69\xc0" + struct.pack("<I", RESTORE_PROGRESS_LOGICAL_WIDTH) in payload
    assert b"\x69\xc0" + struct.pack("<I", RESTORE_PROGRESS_LOGICAL_HEIGHT) in payload
    assert b"\xb9" + struct.pack("<I", AUTHORED_FRAME_HEIGHT) in payload
    assert b"\x89\x46\x28" in payload
    assert b"\x89\x46\x2c" in payload
    assert b"\x89\x46\x30" in payload
    assert b"\x89\x46\x34" in payload

    # The native return value and thiscall RET 4 contract survive the affine;
    # no named output mode, resource pointer, or delayed update hook exists.
    assert b"\x50" in payload
    assert struct.pack("<II", 1920, 1080) not in payload
    assert struct.pack("<II", 3840, 2160) not in payload
    assert payload.endswith(b"\x58\x5f\x5e\x5b\xc9\xc2\x04\x00")

    draw_depth_va = 0x00801000
    initial_show = compiler.load_save_feature().build_restore_progress_draw_scope_wrapper(
        wrapper_va=0x00802000,
        native_va=profile.address("restore_progress.initial_show"),
        draw_depth_va=draw_depth_va,
        argument_bytes=0,
    )
    canvas_update = compiler.load_save_feature().build_restore_progress_draw_scope_wrapper(
        wrapper_va=0x00803000,
        native_va=profile.address("restore_progress.canvas_update"),
        draw_depth_va=draw_depth_va,
        argument_bytes=4,
    )
    for scope_wrapper, scope_va, native_va in (
        (initial_show, 0x00802000, profile.address("restore_progress.initial_show")),
        (canvas_update, 0x00803000, profile.address("restore_progress.canvas_update")),
    ):
        assert b"\xff\x05" + struct.pack("<I", draw_depth_va) in scope_wrapper
        assert b"\xff\x0d" + struct.pack("<I", draw_depth_va) in scope_wrapper
        assert any(
            decode_rel32_branch(
                opcode=BranchOpcode.CALL,
                site_va=scope_va + offset,
                instruction=scope_wrapper[offset : offset + 5],
            )
            == native_va
            for offset in range(len(scope_wrapper) - 4)
            if scope_wrapper[offset] == BranchOpcode.CALL
        )
        assert struct.pack("<II", 1920, 1080) not in scope_wrapper
        assert struct.pack("<II", 3840, 2160) not in scope_wrapper
    assert initial_show.endswith(b"\x58\x5e\xc9\xc3")
    assert canvas_update.endswith(b"\x58\x5e\xc9\xc2\x04\x00")


def test_cursor_capacity_scales_a_private_copy_at_the_native_allocator() -> None:
    """Physical cursor capacity grows without changing serialized logical state."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    wrapper_va = 0x00800000
    cursor_state_va = 0x00801000
    payload = compiler.cursor_feature().build_cursor_capacity_wrapper(
        wrapper_va=wrapper_va,
        cursor_state_va=cursor_state_va,
    )

    # The original POINT is read once into stack-owned storage. The selected
    # live engine height drives a ceil(value * height / 768) transform, with no
    # write through the caller's pointer and no UHD/HD constants.
    assert b"\x8b\x06\x89\x45\xf8\x8b\x46\x04\x89\x45\xfc" in payload
    assert b"\xa1" + struct.pack("<I", profile.address("engine.loop")) in payload
    assert b"\x8b\x58\x34" in payload
    assert payload.count(b"\x0f\xaf\xc3\x05\xff\x02\x00\x00") == 2
    assert payload.count(b"\xb9\x00\x03\x00\x00\xf7\xf1") == 2
    assert b"\x89\x06" not in payload
    assert b"\x89\x46\x04" not in payload
    # Both native bitmap handles are resolved immediately after allocation and
    # their exact requested/doubled-capacity wrappers are published before the
    # first cursor copy can enter a transformed interface traversal.
    assert payload.count(b"\x8b\x0d" + struct.pack("<I", profile.address("resource.manager"))) == 2
    assert b"\x8b\x47\x04\x85\xc0" in payload
    assert b"\x8b\x47\x08\x85\xc0" in payload
    assert b"\xa3" + struct.pack("<I", cursor_state_va + 148) in payload
    assert b"\xa3" + struct.pack("<I", cursor_state_va + 88) in payload

    call_sites = [
        offset
        for offset in range(len(payload) - 4)
        if decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + offset,
            instruction=payload[offset : offset + 5],
        )
        == profile.address("cursor.platform_initialize")
    ]
    assert len(call_sites) == 2  # regular POINT and null-preserving fallback
    assert payload.endswith(b"\x5f\x5e\x5b\xc9\xc2\x08\x00")


def test_cursor_final_stretch_preserves_bltfast_edge_clipping_contract() -> None:
    """Scaled cursor fragments crop source and destination before DirectDraw."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    state_va = 0x00801000
    presented_source_va = 0x00801100
    payload = compiler.cursor_feature().build_cursor_final_wrapper(
        wrapper_va=0x00800000,
        cursor_transform_count_va=0x00802000,
        cursor_state_va=state_va,
        cursor_presented_source_rect_va=presented_source_va,
        density_probe_va=0x00803000,
        blend_wrapper_va=0x00804000,
        cursor_display_blt_count_va=0x00802004,
        cursor_display_blt_result_va=0x00802008,
    )

    # All four target edges are inverse-mapped by the authored-height affine,
    # and the final stretch consumes the paired clipped source scratch rather
    # than the caller's source rectangle directly.
    assert payload.count(b"\x69\xc0" + struct.pack("<I", 768)) == 4
    assert payload.count(b"\x99\xf7\xfb") == 4
    assert b"\x68" + struct.pack("<I", state_va + 56) in payload
    assert b"\xff\x75\x14" not in payload
    for destination_offset in (40, 44, 48, 52):
        assert struct.pack("<I", state_va + destination_offset) in payload
    for source_offset in (56, 60, 64, 68):
        assert struct.pack("<I", state_va + source_offset) in payload
    # Display publication copies the complete source into independent durable
    # state; private save-under calls may continue to use +56 scratch without
    # corrupting the source/destination pair sampled by release probes.
    assert b"\xbe" + struct.pack("<I", state_va + 8) in payload
    assert b"\xbf" + struct.pack("<I", presented_source_va) in payload
    assert b"\xb9\x04\x00\x00\x00\xf3\xa5" in payload
    # Exact destination publication precedes the authored-height scale gate.
    # Reference Load/Save pages keep native pixels but still give their final
    # cache compositor a physical handle on which to redraw the cursor.
    physical_handle_store = b"\xa3" + struct.pack("<I", state_va + 132)
    height_gate = b"\x81\xfb" + struct.pack("<I", 768)
    assert payload.index(physical_handle_store) < payload.index(height_gate)
    assert len(payload) <= compiler._off_control_cursor_final_limit - (
        compiler._off_control_cursor_final_wrapper
    )
    # A fully external cursor is the same successful no-op as BltFast, never
    # an empty RECT submitted to the DirectDraw stretch primitive.
    assert b"\xb8\x01\x00\x00\x00\x59\x5f\x5e\x5b\xc9\xc2\x14\x00" in payload


def test_shared_system_blitter_classifies_only_published_cursor_surfaces() -> None:
    """Every fixed interface bypasses one semantically proven cursor restore."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    cursor_state_va = 0x00801000
    payload = compiler.cursor_feature().build_cursor_surface_classifier(
        wrapper_va=0x00800000,
        cursor_state_va=cursor_state_va,
        trace_va=0x00802000,
    )

    # Exact known composition, presented-source, and learned save-under wrapper
    # identities take the short path on either side of every fixed-interface
    # transfer. Capturing a framebuffer background into save-under is just as
    # cursor-owned as restoring that private surface back to the framebuffer.
    for state_offset in (80, 72, 88, 148):
        assert b"\x3b\x15" + struct.pack("<I", cursor_state_va + state_offset) in payload
        assert b"\x3b\x0d" + struct.pack("<I", cursor_state_va + state_offset) in payload

    # Classification is now identity-only. The allocator owns publication, so
    # no first-use dimension, hotspot, engine-chain, or resolution heuristic
    # remains in this hot shared-blitter predicate.
    assert struct.pack("<I", cursor_state_va + 152) not in payload
    assert struct.pack("<I", profile.address("engine.loop")) not in payload
    assert payload.endswith(b"\xb8\x01\x00\x00\x00\xc3")


def test_loadsave_completes_each_redraw_and_composes_the_final_page() -> None:
    """Every transformed redraw is complete; pre-Flip owns presentation."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    selector = compiler.load_save_feature().build_loadsave_damage_selector(
        wrapper_va=0x00800000,
        native_damage_ptr_va=0x00801200,
        native_damage_count_va=0x00801204,
        native_damage_rects_va=0x00801300,
        selection_rects_va=0x00801400,
        selection_repair_count_va=0x00801440,
        selection_repair_pending_va=0x00801444,
        full_damage_region_va=0x00801500,
    )
    cache = compiler.load_save_feature().build_loadsave_cache_update_helper(
        wrapper_va=0x00802000,
        ddraw_va=0x00802004,
        back_surface_va=0x00802008,
        surface_va=0x0080200C,
        owner_va=0x00802010,
        ready_va=0x00802014,
        descriptor_va=0x00802100,
        source_rect_va=0x00802170,
        scratch_rect_va=0x00802180,
        create_result_va=0x00802018,
        capture_result_va=0x0080201C,
        capture_count_va=0x00802020,
        full_capture_count_va=0x00802024,
        selection_repair_pending_va=0x00802030,
        full_damage_region_va=0x00802200,
        post_draw_cursor_presenter_va=0x00804000,
    )
    page_clear = compiler.load_save_feature().build_loadsave_page_clear_helper(
        wrapper_va=0x00802800,
        back_surface_va=0x00802804,
        bltfx_va=0x00802808,
        result_va=0x0080280C,
        count_va=0x00802810,
    )
    presenter = compiler.load_save_feature().build_loadsave_frame_presenter(
        wrapper_va=0x00803000,
        current_layer_va=0x00805000,
        root_ptr_va=0x00802100,
        fixed_canvas_owner_va=0x00802104,
        cache_surface_va=0x0080200C,
        cache_ready_va=0x00802014,
        source_rect_va=0x00802170,
        back_surface_va=0x00802008,
        present_result_va=0x00802028,
        present_count_va=0x0080202C,
        frame_present_count_va=0x00802110,
    )

    # The selector repairs all three concrete highlight children before Draw.
    # Every interaction redraw uses the complete collection after repairing
    # the dynamic selection rectangles. The native collection is still traced
    # for bounded diagnostics.
    for child_offset in (0x2C4, 0x2C8, 0x2CC):
        assert b"\x8b\xb9" + struct.pack("<I", child_offset) in selector
    assert b"\xff\x05" + struct.pack("<I", 0x00801440) in selector
    assert b"\xbe" + struct.pack("<I", 0x00801500) in selector
    assert struct.pack("<I", compiler.transition_abi.successful_flip_count_va) not in selector
    assert selector.endswith(b"\x8b\xc6\x5f\x5e\x5d\x5a\x5b\xc3")

    # Post-Draw captures the SAME complete generation requested by pre-Draw,
    # never the obsolete native partial region still on the caller's stack.
    # Otherwise dragging updates the value but leaves old rows/thumb pixels.
    assert cache.startswith(b"\x60\xbd" + struct.pack("<I", 0x00802200))
    assert b"\x8b\x6c\x24\x28" not in cache
    assert b"\x83\x3d" + struct.pack("<I", 0x00802030) not in cache
    assert b"\x57\xff\x50\x18" in cache
    assert b"\x8b\x1d" + struct.pack("<I", 0x00802008) in cache
    assert b"\x8b\x07\x6a\x10" in cache  # DDBLTFAST_WAIT
    assert b"\x57\xff\x50\x1c" in cache
    assert b"\x3d\x00\x04\x00\x00" in cache
    assert b"\xc7\x05" + struct.pack("<I", 0x00802014) + b"\x01\x00\x00\x00" in cache
    assert b"\xff\x05" + struct.pack("<I", 0x00802024) in cache
    assert b"\xc7\x05" + struct.pack("<I", 0x00802030) + b"\x00\x00\x00\x00" in cache
    cursor_call = cache.rindex(b"\xe8")
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=0x00802000 + cursor_call,
            instruction=cache[cursor_call : cursor_call + 5],
        )
        == 0x00804000
    )
    assert cache.endswith(b"\x61\xc2\x08\x00")

    # The first two owner generations start from a clean page. Later no-damage
    # traversals must not erase a page after the cached composition has been
    # presented; the root wrapper resets this budget for a replacement owner.
    assert b"\x83\x3d" + struct.pack("<I", 0x00802810) + b"\x02" in page_clear
    assert b"\x8b\x35" + struct.pack("<I", 0x00802804) in page_clear
    assert b"\x68" + struct.pack("<I", 0x00802808) in page_clear
    assert b"\xff\x05" + struct.pack("<I", 0x00802810) in page_clear
    assert page_clear.endswith(b"\x61\x9d\xc3")

    # The authoritative pre-Flip edge validates exact object ownership, then
    # submits one cache-to-current-back BltFast before tooltip/cursor layering.
    assert b"\x8b\x1d" + struct.pack("<I", 0x00802104) in presenter
    assert b"\x3b\x1d" + struct.pack("<I", 0x00802100) in presenter
    presenter_instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(presenter, 0x00803000))
    assert any(i.mnemonic == "call" and i.op_str == "0x805000" for i in presenter_instructions)
    assert b"\x3b\xc3\x0f\x85" in presenter  # Never cover a different current modal.
    assert b"\x83\x3d" + struct.pack("<I", 0x00802014) + b"\x00" in presenter
    assert b"\x8b\x3d" + struct.pack("<I", 0x00802008) in presenter
    assert b"\x8b\x07\x6a\x10" in presenter  # DDBLTFAST_WAIT
    assert b"\x56\x6a\x00\x6a\x00\x57\xff\x50\x1c" in presenter
    assert b"\xff\x05" + struct.pack("<I", 0x0080202C) in presenter
    assert b"\xff\x05" + struct.pack("<I", 0x00802110) in presenter
    assert b"\xc7\x05" + struct.pack("<I", 0x00802014) + bytes(4) not in presenter
    assert presenter.endswith(b"\x61\x9d\xc3")


def test_loadsave_maps_late_preview_and_repairs_selection_before_draw() -> None:
    """Dynamic native redraws use the already transformed child layout."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    feature = compiler.load_save_feature()
    destination_va = 0x00801100
    payload = feature.build_loadsave_background_helper(
        control_predicate_va=0x00807000,
        wrapper_va=0x00800000,
        rect_transform_va=0x00801000,
        root_ptr_va=0x00801010,
        source_rect_va=0x00801020,
        dest_rect_va=destination_va,
        scroll_raw_top_va=0x00801040,
        scroll_origin_seen_va=0x00801044,
        preview_trace_va=0x00801090,
    )
    # The native selected preview owns the real rectangle; the final sink
    # no longer compares against a construction-time empty placeholder.
    assert b"\x8b\x96\xf8\x02\x00\x00\x2b\x96\xf0\x02\x00\x00" in payload
    assert b"\xc7\x45\x28" + struct.pack("<I", destination_va) in payload
    assert b"\xbe" + struct.pack("<I", 0x00801050) not in payload
    # A stock background is accepted only at the root origin with complete
    # authored source/destination extents; dirty slices must not repaint it.
    assert b"\x81\x78\x38\x80\x02\x00\x00" in payload
    assert b"\x81\x78\x3c\xe0\x01\x00\x00" in payload
    for offset in (0, 4):
        assert b"\x83\x7a" + bytes([offset, 0]) in payload
    for offset, extent in ((8, 640), (12, 480)):
        assert b"\x81\x7a" + bytes([offset]) + struct.pack("<I", extent) in payload
    # Thumb height is dynamic. Recognize the live concrete child (+0xD4)
    # and its full destination, not a guessed 22x23 track-tile size.
    assert b"\x83\x78\x38\x16\x0f\x85" in payload
    assert b"\x8b\x9b\xd4\x00\x00\x00" in payload
    assert b"\x81\x3b" + struct.pack("<I", profile.address("scrollbar_thumb.vtable")) in payload
    assert b"\xb9" + struct.pack("<I", destination_va) in payload
    assert len(payload) <= (
        feature._off_loadsave_preview_attach - feature._off_loadsave_background_helper
    )

    attach = feature.build_loadsave_preview_attach(
        wrapper_va=0x00802000, layout_root_va=0x00801010, preview_rect_va=0x00801050
    )
    # Replay the original virtual once with the original arguments. Restrict
    # the correction to this root's concrete embedded child.
    assert attach.count(b"\xff\x92\xc4\x00\x00\x00") == 1
    assert b"\x8d\x9e\x2c\xfd\xff\xff\x3b\x1d" + struct.pack("<I", 0x00801010) in attach
    # Query the source's dimensions even when native SetImage only moves an
    # unchanged bitmap. Never derive size from the already scaled live RECT.
    assert b"\x8b\x0d" + struct.pack("<I", profile.address("bitmap.manager")) in attach
    dimensions_call = next(
        instruction
        for instruction in Cs(CS_ARCH_X86, CS_MODE_32).disasm(attach, 0x00802000)
        if instruction.mnemonic == "call" and instruction.op_str.startswith("0x")
    )
    assert int(dimensions_call.op_str, 16) == profile.address("bitmap.dimensions")
    assert (
        attach.count(b"\x0f\xaf\x05" + struct.pack("<I", profile.address("display.dimensions") + 4))
        == 4
    )
    # Use the native SetRect to invalidate both positions; publish the final
    # diagnostic rectangle afterwards and preserve the native call result.
    assert attach.index(b"\xff\x90\xa8\x00\x00\x00") < attach.index(
        b"\xbf" + struct.pack("<I", 0x00801050)
    )
    assert attach.endswith(b"\x61\x9d\x5e\xc9\xc2\x08\x00")
    assert (
        len(attach) <= feature._off_loadsave_font_rect_helper - feature._off_loadsave_preview_attach
    )

    layout = feature.build_loadsave_layout_wrapper(
        wrapper_va=0x00808000,
        rect_transform_va=0x00801000,
        layout_root_va=0x00801010,
        selection_rects_va=0x00801120,
        initial_preview_transform_va=0x00801200,
        initial_button_transform_va=0x00801300,
    )
    # An initially selected real screenshot needs fitting too. Both positive
    # extents must be proved before the transform; zero/negative placeholders
    # jump past it and remain untouched for a later real bitmap attachment.
    preview_at = layout.index(b"\x8d\x8e\xf0\x02\x00\x00")
    preview_code = list(
        Cs(CS_ARCH_X86, CS_MODE_32).disasm(layout[preview_at:], 0x00808000 + preview_at)
    )
    preview_call = next(item for item in preview_code if item.mnemonic == "call")
    extent_guards = [item for item in preview_code if item.mnemonic == "jle"]
    assert len(extent_guards) == 2
    assert all(
        int(item.op_str, 16) == preview_call.address + preview_call.size for item in extent_guards
    )
    assert int(preview_call.op_str, 16) == 0x00801200
    assert b"\x8d\xb6\xf0\x02\x00\x00" not in layout

    release = feature.build_scrollbar_release_dispatch(
        wrapper_va=0x00803000,
        input_depth_va=0x00804000,
        input_wrapper_va=0x00805000,
        native_stub_va=0x00806000,
    )
    # Captured release bypasses the normal parent traversal. Only an outermost
    # Load/Save event takes the existing POINT mapper; Inventory and already
    # mapped callbacks tail-dispatch the native/dense-mask stub directly.
    assert release.startswith(b"\x83\x3d" + struct.pack("<I", 0x00804000) + b"\x00\x75")
    for layer in ("loadgame.vtable", "savegame.vtable"):
        assert b"\x81\x38" + struct.pack("<I", profile.address(layer)) in release
    assert b"\xb8" + struct.pack("<I", 0x00806000) in release
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=0x00803000 + len(release) - 10,
            instruction=release[-10:-5],
        )
        == 0x00805000
    )
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=0x00803000 + len(release) - 5,
            instruction=release[-5:],
        )
        == 0x00806000
    )
    assert (
        len(release)
        <= feature._off_loadsave_scroll_input_mapped_point
        - feature._off_loadsave_scroll_arrow_release_dispatch
    )

    selector = feature.build_loadsave_damage_selector(
        wrapper_va=0x00802000,
        native_damage_ptr_va=0x00802100,
        native_damage_count_va=0x00802104,
        native_damage_rects_va=0x00802200,
        selection_rects_va=0x00802300,
        selection_repair_count_va=0x00802340,
        selection_repair_pending_va=0x00802344,
        full_damage_region_va=0x00802400,
    )
    for child_offset, canonical_offset in ((0x2C4, 0), (0x2C8, 16), (0x2CC, 32)):
        assert b"\x8b\xb9" + struct.pack("<I", child_offset) in selector
        assert b"\xa1" + struct.pack("<I", 0x00802300 + canonical_offset) in selector
        assert b"\xa1" + struct.pack("<I", 0x00802308 + canonical_offset) in selector
    assert b"\xbe" + struct.pack("<I", 0x00802400) in selector
    assert len(selector) <= (
        feature._off_loadsave_background_helper - feature._off_loadsave_damage_selector
    )


def test_binocular_root_clears_only_nonempty_widescreen_pillars_after_draw() -> None:
    """The direct binocular root owns two guarded post-3D pillar fills."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    surface_va = 0x00802020
    bltfx_va = 0x00802040
    left_rect_va = 0x00802080
    right_rect_va = 0x00802090
    payload = compiler.fixed_screen_feature().build_root_draw_wrapper(
        wrapper_va=0x00803000,
        render_depth_va=0x00802000,
        input_active_va=0x00802004,
        clear_pending_va=0x00802008,
        root_ptr_va=0x0080200C,
        transform_mode_va=0x00802010,
        transform_mode=compiler._mode_composite,
        input_enabled=True,
        target_va=0x00402000,
        post_clear_surface_va=surface_va,
        post_clear_bltfx_va=bltfx_va,
        post_clear_rect_vas=(left_rect_va, right_rect_va),
    )

    assert b"\x8b\x35" + struct.pack("<I", surface_va) in payload
    guard = b"\xa1" + struct.pack("<I", left_rect_va)
    guard += b"\x3b\x05" + struct.pack("<I", left_rect_va + 8)
    assert guard in payload
    assert payload.count(b"\x68" + struct.pack("<I", compiler._ddblt_colorfill_wait)) == 2
    assert b"\x68" + struct.pack("<I", left_rect_va) in payload
    assert b"\x68" + struct.pack("<I", right_rect_va) in payload


def test_loadsave_owns_fixed_canvas_for_its_exact_object_lifetime() -> None:
    """A stale screen cannot release a newer retained canvas's page lease."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    owner_va = 0x00802100
    show = compiler.fixed_screen_feature().build_state_wrapper(
        state_va=0x00802000,
        value=1,
        target_va=0x00400000,
        wrapper_va=0x00803000,
        fixed_canvas_owner_va=owner_va,
    )
    hide = compiler.fixed_screen_feature().build_state_wrapper(
        state_va=0x00802000,
        value=0,
        target_va=0x00400000,
        wrapper_va=0x00803100,
        fixed_canvas_owner_va=owner_va,
    )
    destructor = compiler.fixed_screen_feature().build_destructor_wrapper(
        wrapper_va=0x00803200,
        render_depth_va=0x00802004,
        input_active_va=0x00802008,
        clear_pending_va=0x0080200C,
        root_ptr_va=0x00802010,
        transform_mode_va=0x00802014,
        target_va=0x00401000,
        fixed_canvas_owner_va=owner_va,
    )
    root = compiler.fixed_screen_feature().build_root_draw_wrapper(
        wrapper_va=0x00803300,
        render_depth_va=0x00802004,
        input_active_va=0x00802008,
        clear_pending_va=0x0080200C,
        root_ptr_va=0x00802010,
        transform_mode_va=0x00802014,
        transform_mode=compiler._mode_loadsave,
        input_enabled=False,
        target_va=0x00402000,
        fixed_canvas_owner_va=owner_va,
    )

    assert b"\x89\x0d" + struct.pack("<I", owner_va) in show
    assert root.index(b"\x89\x0d" + struct.pack("<I", owner_va)) < root.index(
        b"\x89\x0d" + struct.pack("<I", 0x00802010)
    )
    owner_compare = b"\x3b\x0d" + struct.pack("<I", owner_va)
    hide_owner_clear = b"\xc7\x05" + struct.pack("<I", owner_va) + bytes(4)
    assert hide.index(owner_compare) < hide.index(hide_owner_clear)

    destructor_owner_clear = b"\x31\xc0\xa3" + struct.pack("<I", owner_va)
    assert destructor.index(owner_compare) < destructor.index(destructor_owner_clear)


def test_fixed_and_modal_roots_have_disjoint_damage_rectangles() -> None:
    """A fixed canvas cannot inherit a preceding modal root's local origin."""
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=next(iter(SUPPORTED_BUILDS.values())),
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    )
    control_base_va = 0x00800000
    full_rect_va = control_base_va + SYSTEM_CONTROL_FULL_DAMAGE_RECT_OFFSET
    modal_rect_va = control_base_va + SYSTEM_CONTROL_MODAL_DAMAGE_RECT_OFFSET
    modal_budget_va = control_base_va + SYSTEM_CONTROL_TOOLBAR_SEED_BUDGET_OFFSET
    fixed_root = compiler.fixed_screen_feature().build_root_draw_wrapper(
        wrapper_va=0x00803000,
        render_depth_va=0x00802000,
        input_active_va=0x00802004,
        clear_pending_va=0x00802008,
        root_ptr_va=0x0080200C,
        transform_mode_va=0x00802010,
        transform_mode=compiler._mode_reference_anchor,
        input_enabled=True,
        target_va=0x00402000,
        full_damage_region_va=0x00802020,
        full_damage_rect_va=full_rect_va,
    )

    modal_root = compiler.fixed_screen_feature().build_root_draw_wrapper(
        wrapper_va=0x00804000,
        render_depth_va=0x00802000,
        input_active_va=0x00802004,
        clear_pending_va=0x00802008,
        root_ptr_va=0x0080200C,
        transform_mode_va=0x00802010,
        transform_mode=compiler._mode_physical_canvas,
        input_enabled=False,
        target_va=0x00402000,
        full_damage_region_va=0x00802040,
        full_damage_rect_va=modal_rect_va,
        full_damage_uses_root_rect=True,
        full_damage_budget_va=modal_budget_va,
        full_damage_on_every_call=True,
    )

    right_edge = b"\xa3" + struct.pack("<I", full_rect_va + 8)
    bottom_edge = b"\xa3" + struct.pack("<I", full_rect_va + 12)
    modal_left = b"\xa3" + struct.pack("<I", modal_rect_va)
    modal_top = b"\xa3" + struct.pack("<I", modal_rect_va + 4)
    assert full_rect_va != modal_rect_va
    assert fixed_root.index(right_edge) < fixed_root.index(bottom_edge)
    assert struct.pack("<I", modal_rect_va) not in fixed_root
    assert modal_root.index(modal_left) < modal_root.index(modal_top)
    # The outer presenter has already damage-gated this small modal. Its root
    # therefore receives complete damage on every admitted call, while the
    # existing end-of-call budget consume still retires bounded page seeds.
    assert b"\xb8" + struct.pack("<I", 0x00802040) in modal_root
    assert modal_root.count(b"\x83\x3d" + struct.pack("<I", modal_budget_va) + b"\x00") == 1
    assert b"\xff\x0d" + struct.pack("<I", modal_budget_va) in modal_root


def test_closeup_input_restores_native_bottom_anchor_after_canvas_inverse() -> None:
    """CloseUp hit testing mirrors its authored-X/physical-Y presentation."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x00792000),
    )
    transform_mode_va = 0x00801000
    payload = build_reference_canvas_input_wrapper(
        compiler,
        wrapper_va=0x00800000,
        system_transform_mode_va=transform_mode_va,
        input_transform_count_va=0x00801004,
        input_source_x_va=0x00801008,
        input_logical_x_va=0x0080100C,
        input_logical_y_va=0x00801010,
    )

    mode_select = (
        b"\x83\x3d"
        + struct.pack("<I", transform_mode_va)
        + bytes([compiler._system_bottom_anchored_reference_canvas_mode])
    )
    restore_native_y = (
        b"\xa1"
        + struct.pack("<I", profile.address("display.dimensions") + 4)
        + b"\x2d\x00\x03\x00\x00\x01\x46\x04"
    )
    assert payload.index(mode_select) < payload.index(restore_native_y)


@pytest.mark.parametrize("height_va", [None, 0x00804124])
def test_toolbar_input_publishes_reentrant_logical_point_scope(height_va: int | None) -> None:
    """Only the canonical toolbar inverse brackets native logical-point use."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x00792000),
    )
    scope_depth_va = 0x00804000
    payload = build_tbt_input_wrapper(
        compiler,
        input_transform_count_va=0x00804004,
        input_source_x_va=0x00804008,
        input_logical_x_va=0x0080400C,
        input_logical_y_va=0x00804010,
        logical_rect_va=0x00804100,
        target_rect_va=0x00804110,
        persistent_root_va=None,
        rect_valid_va=0x00804120,
        scope_depth_va=scope_depth_va,
        toolbar_height_va=height_va,
    )

    scope_enter = b"\xff\x05" + struct.pack("<I", scope_depth_va)
    native_call = b"\xff\x74\x24\x20\xff\xd7"
    scope_exit = b"\xff\x0d" + struct.pack("<I", scope_depth_va)
    assert payload.index(scope_enter) < payload.index(native_call) < payload.index(scope_exit)
    # The invalid-publication path must save the native callback before POP
    # EDI restores the caller's object pointer. Fall through to JMP EAX.
    assert payload.endswith(bytes.fromhex("89 1e 89 6e 04 8b c7 59 5d 5f 5e 5b ff e0"))
    if height_va is not None:
        assert len(payload) <= 0x1E0
        assert payload.count(b"\x8b\x0d" + struct.pack("<I", height_va)) == 2
        assert payload.count(bytes.fromhex("69 c0 00 03 00 00")) == 2
        assert bytes.fromhex("83 c2 7e 52") in payload
        assert bytes.fromhex("83 c2 25 52") in payload
        assert struct.pack("<I", 0x00804110) not in payload


def test_input_scopes_preserve_modal_ownership_and_native_fallback() -> None:
    """Covering modals own input before a retained SIDNEY tree can claim it."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x00792000),
    )
    payload = build_input_dispatch_wrapper(
        compiler,
        wrapper_va=0x00800000,
        root_ptr_va=0x00801000,
        input_transform_count_va=0x00801004,
        input_source_x_va=0x00801008,
        input_logical_x_va=0x0080100C,
        driving_map_active_va=0x00801010,
        driving_map_input_depth_va=0x00801038,
        tbt_layer_va=0x00801014,
        tbt_target_rect_va=0x00801018,
        tbt_input_wrapper_va=0x00802000,
        system_active_va=0x00801028,
        system_root_ptr_va=0x0080102C,
        system_transform_mode_va=0x00801030,
        system_input_wrapper_va=0x00802100,
        toolbar_input_wrapper_va=0x00802200,
        reference_anchor_input_wrapper_va=0x00802300,
        reference_canvas_input_wrapper_va=0x00802400,
        binocs_input_wrapper_va=0x00802500,
        system_action_presented_root_va=0x00801034,
        system_native_input_vtables=(0x00500000, 0x00500004),
    )

    for native_vtable in (0x00500000, 0x00500004):
        comparison = b"\x81\x3a" + struct.pack("<I", native_vtable)
        # One guard handles the popup construction interval; the second runs
        # after the authoritative current-layer check for Load/Save mode.
        assert payload.count(comparison) == 2
    assert payload.endswith(b"\xff\xe0")
    assert payload.count(b"\xff\x05" + struct.pack("<I", 0x00801038)) == 1
    assert payload.count(b"\xff\x0d" + struct.pack("<I", 0x00801038)) == 1
    # A covering modal must reach the system affine before retained SIDNEY
    # or driving-map state is considered. The native query preserves both
    # EAX (event target) and ECX (dispatcher), including its comparison flags.
    modal_comparison = b"\x3b\x05" + struct.pack("<I", 0x0080102C) + b"\x59\x58"
    modal_at = payload.index(modal_comparison)
    retained_at = payload.index(b"\x83\x3d" + struct.pack("<I", 0x00801000))
    assert modal_at < retained_at
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x00800000))
    reference_branch = next(
        instruction for instruction in instructions if instruction.mnemonic == "jbe"
    )
    timeblock_at = int(reference_branch.op_str, 16) - 0x00800000
    assert payload[timeblock_at : timeblock_at + 3] == b"\x50\x51\xe8"
    assert payload[timeblock_at + 7 : timeblock_at + 15] == (
        b"\x3b\x05" + struct.pack("<I", 0x00801014) + b"\x59\x58"
    )
    branch = next(
        instruction
        for instruction in instructions
        if instruction.address == 0x00800000 + modal_at + len(modal_comparison)
    )
    assert branch.mnemonic == "je"
    dispatch_at = int(branch.op_str, 16) - 0x00800000
    assert payload[dispatch_at:].startswith(
        b"\x83\x3d"
        + struct.pack("<I", 0x00801030)
        + bytes([compiler._system_reference_anchor_mode])
    )
    # Death's renderer scales button centres and extents independently. It
    # must use the exact per-control inverse, never native physical input.
    death_guard = b"\x81\x3a" + struct.pack("<I", profile.address("death.vtable"))
    death_at = payload.index(death_guard)
    death_branch = payload[death_at + len(death_guard) + 2 :]
    assert death_branch.startswith(b"\x50\x51\xe8")
    assert death_branch[7:15] == modal_comparison
    assert death_branch[15:17] == b"\x0f\x85"
    assert death_branch[21:].startswith(b"\xba" + struct.pack("<I", 0x00802300) + b"\xff\xe2")


def test_loadsave_scrollbar_adapts_point_after_outer_hit_testing() -> None:
    """Scrollbar children receive native coordinates without remapping rows."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(width_va=0x00790004, height_va=0x00790008),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x00791000,
            room_presentation_active_va=0x00791008,
            pre_flip_presenter_slot_va=0x00791004,
            post_flip_presenter_slot_va=0x0079100C,
        ),
    ).load_save_feature()
    cursor_position_va = profile.address("input.cursor_position")

    for argument_count in (1, 3):
        wrapper = compiler.build_loadsave_scrollbar_input_wrapper(
            wrapper_va=0x00800000,
            argument_count=argument_count,
            input_depth_va=0x00801008,
            mapped_point_va=0x0080100C,
            inventory_input_va=0x00802000,
        )
        assert struct.pack("<I", AUTHORED_FRAME_HEIGHT) in wrapper
        # Shared class does not mean shared coordinate model: Inventory's root
        # already mapped this event, so restore this/target and tail-dispatch.
        inventory_guard = b"\x81\x38" + struct.pack("<I", profile.address("inventory.vtable"))
        assert inventory_guard in wrapper
        assert b"\x8b\x45\xfc\x8b\x4d\xf8\xc9\xe9" in wrapper
        assert wrapper.index(inventory_guard) < wrapper.index(struct.pack("<I", cursor_position_va))
        # SIDNEY shares the ScrollBar vtable but already uses authored points.
        # Only Load/Save may enter the physical-to-child conversion; null and
        # every other current root must restore this/target and tail-call it.
        load_guard = b"\x81\x38" + struct.pack("<I", profile.address("loadgame.vtable"))
        save_guard = b"\x81\x38" + struct.pack("<I", profile.address("savegame.vtable"))
        native_tail = b"\x8b\x45\xfc\x8b\x4d\xf8\xc9\xff\xe0"
        assert wrapper.index(inventory_guard) < wrapper.index(load_guard)
        assert wrapper.index(load_guard) < wrapper.index(save_guard) < wrapper.index(native_tail)
        assert wrapper.index(native_tail) < wrapper.index(struct.pack("<I", cursor_position_va))
        assert wrapper.count(struct.pack("<I", cursor_position_va)) == 3
        assert wrapper.count(struct.pack("<I", cursor_position_va + 4)) == 3
        assert wrapper.endswith(b"\xc9\xc2" + struct.pack("<H", argument_count * 4))
        assert len(wrapper) <= 0x100

    # Captured thumb motion is a different entry path: its POINT is physical
    # even for SIDNEY. Only that child callback enters the root input adapter.
    thumb = compiler.build_scrollbar_thumb_move_dispatch(
        stub_va=0x00800000, wrapper_va=0x00801000, sidney_adapter_va=0x00802000
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(thumb, 0x00800000))
    assert [(i.mnemonic, i.op_str) for i in instructions[:4]] == [
        ("push", "ecx"),
        ("call", hex(profile.address("ui.current_layer"))),
        ("pop", "ecx"),
        ("test", "eax, eax"),
    ]
    guard = b"\x81\x38" + struct.pack("<I", profile.address("sidney.root_destructor_slot"))
    assert guard in thumb
    assert b"\xba\x03\x00\x00\x00" in thumb
    assert [i.op_str for i in instructions if i.mnemonic == "jmp"] == ["0x802000", "0x801000"]
    conditional_targets = [i.op_str for i in instructions if i.mnemonic in {"je", "jne"}]
    assert len(conditional_targets) == 2
    assert len(set(conditional_targets)) == 1
    assert thumb.count(struct.pack("<I", profile.address("scrollbar_thumb.drag_move"))) == 2
    assert len(thumb) <= 0x80


def test_loadsave_scrollbar_input_stub_retains_pristine_native_target() -> None:
    """Each vtable stub publishes its original method to the shared adapter."""
    stub_va = 0x00800000
    wrapper_va = 0x00800100
    original_va = 0x004446E4
    payload = LoadSaveFeatureCompiler.build_loadsave_scrollbar_input_stub(
        stub_va=stub_va,
        wrapper_va=wrapper_va,
        original_va=original_va,
    )
    assert payload[:5] == b"\xb8" + struct.pack("<I", original_va)
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.JUMP,
            site_va=stub_va + 5,
            instruction=payload[5:],
        )
        == wrapper_va
    )
    assert len(payload) == 10


def test_loadsave_record_text_draw_scopes_exact_font_owner() -> None:
    """Record glyphs inherit their exact TextBox across a synchronous Draw."""
    wrapper_va = 0x00800000
    active_va = 0x00801000
    native_va = 0x004ED8E8
    payload = LoadSaveFeatureCompiler.build_loadsave_text_draw_wrapper(
        wrapper_va=wrapper_va,
        active_text_va=active_va,
        native_va=native_va,
    )
    assert payload.count(struct.pack("<I", active_va)) == 3
    call_at = payload.index(b"\xe8")
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + call_at,
            instruction=payload[call_at : call_at + 5],
        )
        == native_va
    )
    assert payload.endswith(b"\xc9\xc2\x08\x00")


def test_cursor_trace_restores_record_base_before_second_rectangle() -> None:
    """Nullable RECT copies must not write past a cursor ring record into code."""
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x790004, height_va=0x790008),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x792000),
    )
    payload = build_cursor_blt_trace_helper(
        compiler, wrapper_va=0x800000, trace_count_va=0x810000, trace_records_va=0x810010
    )
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(instruction.size for instruction in instructions) == len(payload)
    # Save the base after reading arg2, before the nullable destination branch.
    # Its null path and REP MOVSD path must converge on POP EDI, before arg3 is
    # read at the original stack offset and the source field is addressed.
    start = payload.index(bytes.fromhex("8b 74 24 2c 85 f6 57"))
    branch = start + 7
    assert payload[branch] == 0x74
    destination = bytes.fromhex("8d 7f 1c b9 04 00 00 00 f3 a5")
    assert payload[branch + 2 : branch + 2 + len(destination)] == destination
    restore = branch + 2 + len(destination)
    assert branch + 2 + struct.unpack_from("<b", payload, branch + 1)[0] == restore
    assert payload[restore : restore + 7] == bytes.fromhex("5f 8b 74 24 30 85 f6")
    source = bytes.fromhex("8d 7f 2c b9 04 00 00 00 f3 a5")
    assert payload[restore + 9 : restore + 9 + len(source)] == source
    assert compiler._cursor_blt_trace_stride == 44 + 16
    ring_end = (
        compiler._off_cursor_blt_trace_records
        + compiler._cursor_blt_trace_capacity * compiler._cursor_blt_trace_stride
    )
    assert ring_end <= compiler._off_motion_dispatch_wrapper


def _assert_death_motion_dispatch(wrapper: bytes, death_vtable: int, zodiac_vtable: int) -> int:
    death_at = wrapper.index(b"\x81\x38" + struct.pack("<I", death_vtable))
    # Preserve registers and ZF; null roots clear ZF without dereferencing.
    assert b"\x85\xc0\x75\x03\x40\xeb\x0e" in wrapper[:death_at]
    assert wrapper[death_at + 6 :].startswith(
        b"\x74\x06\x81\x38" + struct.pack("<I", zodiac_vtable) + b"\x5a\x59\x58\x0f\x84"
    )
    return death_at


def test_pointer_motion_tail_adapts_only_current_point_transactionally() -> None:
    """The trailing +0x78 traversal retains native delta and flag arguments."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x00792000),
    )
    wrapper_va = 0x00800000
    input_wrapper_va = 0x00801000
    thunk_va = 0x00802000
    system_root_ptr_va = 0x00792100
    toolbar_input_valid_va = 0x0079210C
    system_active_va = 0x00792108
    system_transform_mode_va = 0x00792104
    inventory_active_va = 0x00792110
    driving_map_active_va = 0x00792114
    tbt_layer_va = 0x00792118
    toolbar_vtable_va = profile.address("ingame_toolbar.vtable")
    wrapper = build_pointer_motion_dispatch_wrapper(
        wrapper_va=wrapper_va,
        input_wrapper_va=input_wrapper_va,
        thunk_va=thunk_va,
        native_dispatch_va=profile.address("mouse_move.motion_dispatch"),
        physical_width_va=compiler._physical_width_global_va,
        tbt_layer_va=tbt_layer_va,
        current_layer_va=compiler._current_layer_va,
        driving_map_active_va=driving_map_active_va,
        inventory_active_va=inventory_active_va,
        toolbar_input_valid_va=toolbar_input_valid_va,
        system_active_va=system_active_va,
        system_transform_mode_va=system_transform_mode_va,
        toolbar_transform_mode=compiler._system_popup_mode,
        reference_canvas_transform_mode=compiler._system_reference_canvas_mode,
        system_root_ptr_va=system_root_ptr_va,
        toolbar_vtable_va=toolbar_vtable_va,
        death_vtable_va=profile.address("death.vtable"),
        zodiac_vtable_va=profile.address("zodiac.vtable"),
        is_bad_read_ptr_va=profile.address("win32.IsBadReadPtr"),
    )
    thunk = build_pointer_motion_dispatch_thunk(compiler, wrapper_va=thunk_va)

    # Five original arguments are copied into a stack-local context. The
    # adapter receives only current POINT* and consumes it; this wrapper then
    # consumes the original five-argument native frame exactly once.
    width_check = b"\x81\x3d" + struct.pack("<I", compiler._physical_width_global_va)
    height_check = b"\x81\x3d" + struct.pack("<I", compiler._physical_width_global_va + 4)
    toolbar_check = b"\x83\x3d" + struct.pack("<I", toolbar_input_valid_va) + b"\x00"
    assert wrapper.startswith(b"\x83\x3d" + struct.pack("<I", tbt_layer_va) + b"\x00")
    timeblock_check = b"\x3b\x05" + struct.pack("<I", tbt_layer_va) + b"\x5a\x59\x58"
    assert wrapper.index(timeblock_check) < wrapper.index(width_check)
    assert wrapper.index(height_check) < wrapper.index(toolbar_check)
    death_at = _assert_death_motion_dispatch(
        wrapper, profile.address("death.vtable"), profile.address("zodiac.vtable")
    )
    assert wrapper.index(height_check) < death_at < wrapper.index(toolbar_check)
    inventory_check = b"\xa1" + struct.pack("<I", inventory_active_va) + b"\x85\xc0"
    assert (
        wrapper.index(height_check) < wrapper.index(inventory_check) < wrapper.index(toolbar_check)
    )
    assert b"\x3b\x05" + struct.pack("<I", system_root_ptr_va) in wrapper
    assert b"\x83\x3d" + struct.pack("<I", system_active_va) + b"\x00" in wrapper
    assert (
        b"\x83\x3d"
        + struct.pack("<I", system_transform_mode_va)
        + bytes([compiler._system_popup_mode])
    ) in wrapper
    root_check = b"\xa1" + struct.pack("<I", system_root_ptr_va) + b"\x85\xc0"
    assert root_check in wrapper
    assert wrapper.index(root_check) > wrapper.index(struct.pack("<I", system_transform_mode_va))
    assert b"\x81\x38" + struct.pack("<I", toolbar_vtable_va) in wrapper
    assert b"\xff\x15" + struct.pack("<I", profile.address("win32.IsBadReadPtr")) in wrapper
    assert b"\x81\x3d" + struct.pack("<I", compiler._physical_width_global_va) in wrapper
    assert struct.pack("<I", 1024) in wrapper
    assert struct.pack("<I", 768) in wrapper
    assert b"\x55\x8b\xec\x83\xec\x20\x89\x5d\xe8" in wrapper
    assert b"\x8d\x4d\xec\xb8" + struct.pack("<I", thunk_va) + b"\xff\x75\x08" in wrapper
    call_offset = wrapper.index(b"\xff\x75\x08\xe8") + 3
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + call_offset,
            instruction=wrapper[call_offset : call_offset + 5],
        )
        == input_wrapper_va
    )
    assert wrapper.endswith(b"\x8b\x7d\xe0\x8b\x75\xe4\x8b\x5d\xe8\xc9\xc2\x14\x00")

    # The thunk reconstructs offset/callback/flags/delta/current in native
    # right-to-left order, restores the original dispatcher as ECX, and calls
    # the untouched engine traversal.
    assert thunk.startswith(b"\xff\x71\x10\xff\x71\x0c\xff\x71\x08\xff\x71\x04")
    assert b"\xff\x74\x24\x14\x8b\x09" in thunk
    thunk_call = thunk.index(b"\xe8")
    assert decode_rel32_branch(
        opcode=BranchOpcode.CALL,
        site_va=thunk_va + thunk_call,
        instruction=thunk[thunk_call : thunk_call + 5],
    ) == profile.address("mouse_move.motion_dispatch")
    assert thunk.endswith(b"\xc2\x04\x00")


def test_periodic_cursor_selection_uses_shared_point_transaction() -> None:
    """The independent DirectInput poll adapts only its selector POINT."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = SidneyPresentationCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=profile,
        room_rendering_abi=RoomRenderingABI(
            width_va=0x00790004,
            height_va=0x00790008,
        ),
        mouse_move_abi=MouseMoveDispatchABI(ui_dispatch_adapter_slot_va=0x00792000),
    )
    wrapper_va = 0x00800000
    input_wrapper_va = 0x00801000
    thunk_va = 0x00802000
    wrapper = build_periodic_cursor_select_wrapper(
        wrapper_va=wrapper_va,
        input_wrapper_va=input_wrapper_va,
        thunk_va=thunk_va,
    )
    thunk = build_periodic_cursor_select_thunk(compiler, wrapper_va=thunk_va)

    assert wrapper.startswith(
        b"\x55\x8b\xec\x83\xec\x14\x89\x5d\xf4\x89\x75\xf0\x89\x7d\xec\x89\x4d\xf8"
    )
    assert b"\x8b\x45\x0c\x89\x45\xfc" in wrapper
    call_offset = wrapper.index(b"\xe8")
    assert (
        decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=wrapper_va + call_offset,
            instruction=wrapper[call_offset : call_offset + 5],
        )
        == input_wrapper_va
    )
    assert wrapper.endswith(b"\x8b\x7d\xec\x8b\x75\xf0\x8b\x5d\xf4\xc9\xc2\x08\x00")

    assert thunk.startswith(b"\xff\x71\x04\xff\x74\x24\x08\x8b\x09")
    thunk_call = thunk.index(b"\xe8")
    assert decode_rel32_branch(
        opcode=BranchOpcode.CALL,
        site_va=thunk_va + thunk_call,
        instruction=thunk[thunk_call : thunk_call + 5],
    ) == profile.address("mouse_move.cursor_select")
    assert thunk.endswith(b"\xc2\x04\x00")


def test_transition_blt_hook_only_observes_native_primary_handoffs() -> None:
    """Transition tracking leaves the original COM destination and call intact."""
    compiler = TransitionFrameCompiler(profile=next(iter(SUPPORTED_BUILDS.values())))
    wrapper = compiler._build_blt_wrapper(
        wrapper_va=0x3000,
        blt_count_va=0x1000,
        handoff_pending_va=0x1002,
        primary_blt_count_va=0x1004,
        repair_active_va=0x1008,
        seed_pages_remaining_va=0x100C,
        last_seed_flip_generation_va=0x1010,
        retry_caller_va=0x1014,
        retry_current_va=0x1018,
        retry_max_va=0x101C,
        retry_max_caller_va=0x1020,
        primary_blt_trace_va=0x1100,
    )
    primary_surface_va = compiler.profile.address("transition.primary_surface_ptr")

    # Preserve the entry destination before retry telemetry borrows EAX, then
    # classify that exact identity without rewriting the caller's COM frame.
    assert wrapper.startswith(b"\x8b\xd0")
    assert b"\x3b\x15" + struct.pack("<I", primary_surface_va) in wrapper
    assert b"\x3b\x05" + struct.pack("<I", primary_surface_va) not in wrapper
    assert b"\x89\x4c\x24\x04" not in wrapper
    # Invocation tail: reload the original `this`, discard the hook return
    # address, call IDirectDrawSurface4::Blt, and preserve native HRESULT tests.
    assert b"\x8b\x44\x24\x04\x8b\x10\x83\xc4\x04\xff\x52\x14" in wrapper


def test_modern_resolution_patch_only_exposes_modes() -> None:
    """Mode exposure does not smuggle in a private 3D presentation backend."""
    patch_id = PatchId("enable_modern_resolutions")
    definition = PATCHES[patch_id]
    assert definition.requires == frozenset()
    for build_id in SUPPORTED_BUILDS:
        build = BuildContext(build_id=build_id)
        plan = PLANNER.plan_explicit({patch_id}, build)
        operations = plan.compile_operations()
        assert {operation.symbol for operation in operations} == {
            "resolution.fallback",
            "resolution.menu_filter",
            "resolution.framebuffer_guard",
        }
        assert not any(isinstance(operation, CompiledPayload) for operation in operations)


def test_native_payload_layouts_are_deterministic_and_bounded() -> None:
    """Install and verification builds share stable, non-overlapping payloads."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    section_va = 0x00800000

    transition = TransitionFrameCompiler(profile=profile)
    transition_payloads = transition._build_wrappers(section_va)
    assert transition_payloads == transition._build_wrappers(section_va)
    transition._validate_wrapper_slots(transition_payloads)

    stale_mouse = StaleMouseMoveCompiler(profile=profile)
    stale_mouse_payloads = stale_mouse._build_payloads(section_va)
    assert stale_mouse_payloads == stale_mouse._build_payloads(section_va)
    stale_mouse._validate_payload_slots(stale_mouse_payloads)


def test_mouse_move_producer_coalesces_only_with_fixed_input_adapter() -> None:
    """The WndProc boundary drops superseded points without altering native input."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = StaleMouseMoveCompiler(profile=profile)
    section_va = 0x00800000
    payloads = compiler._build_payloads(section_va)
    wndproc = next(
        payload for _offset, payload, _limit, label in payloads if label == "WndProc wrapper"
    )

    adapter_va = section_va + compiler._off_ui_dispatch_adapter
    obsolete_count_va = section_va + compiler._off_obsolete_wndproc_point_count
    assert b"\x83\x3d" + struct.pack("<I", adapter_va) + b"\x00" in wndproc
    assert b"\xff\x15" + struct.pack("<I", profile.address("win32.GetCursorPos")) in wndproc
    assert b"\xff\x15" + struct.pack("<I", profile.address("win32.ScreenToClient")) in wndproc
    assert b"\xff\x05" + struct.pack("<I", obsolete_count_va) in wndproc
    # The queried POINT is restored before either native forwarding or the
    # common rejected-move cleanup owns the original stack frame again.
    assert b"\x8b\x4c\x24\x04\x89\x08\x8b\x0c\x24\x89\x48\x04" in wndproc
    assert compiler._off_obsolete_wndproc_point_count + 4 <= compiler._section_size
    assert compiler._off_tree_b8_wrapper - compiler._off_wndproc_wrapper - len(wndproc) >= 0x10


def test_mouse_move_inverse_has_one_common_traversal_owner() -> None:
    """Child selection and final dispatch share one outer coordinate scope."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = StaleMouseMoveCompiler(profile=profile)
    section_va = 0x00800000
    payloads = compiler._build_payloads(section_va)
    by_label = {label: payload for _offset, payload, _limit, label in payloads}
    adapter_slot = struct.pack("<I", section_va + compiler._off_ui_dispatch_adapter)

    # The call at MouseManager::move+0x175 brackets FUN_004BEBF0, which owns
    # every +B8/+BC child query and the final +0x50 event callback. Transform
    # there once; adapting an inner tree edge would inverse the logical POINT
    # again and reproduce the UHD Inventory hover miss.
    assert adapter_slot in by_label["UI-dispatch bridge"]
    for label in ("tree +0xB8 wrapper", "tree +0xBC wrapper", "tree +0xB4 wrapper"):
        assert adapter_slot not in by_label[label]


def test_mouse_callbacks_reject_non_executable_replacement_values() -> None:
    """Transient UI callbacks validate code targets, not only null pointers."""
    profile = next(iter(SUPPORTED_BUILDS.values()))
    compiler = StaleMouseMoveCompiler(profile=profile)
    section_va = 0x00800000
    payloads = compiler._build_payloads(section_va)
    by_label = {label: payload for _offset, payload, _limit, label in payloads}
    code_pointer_check = b"\xff\x15" + struct.pack("<I", profile.address("win32.IsBadCodePtr"))

    for label in (
        "tree +0xB8 wrapper",
        "tree +0xBC wrapper",
        "tree +0xB4 wrapper",
        "popup message wrapper",
        "popup query wrapper",
        "direct message wrapper",
    ):
        assert code_pointer_check in by_label[label]

    popup_site = profile.site("mouse_move.popup_message_dispatch")
    assert popup_site.va == 0x004BECE6
    assert popup_site.original == bytes.fromhex("8b 01 8d 55 08 52 ff 50 0c")
    # The wrapper replaces the leading MOV as well as the call. It must prove
    # ECX and reload [ECX], never mistake the unrelated incoming EAX for the
    # popup vtable (which drops every valid scripted message).
    popup_wrapper = by_label["popup message wrapper"]
    assert popup_wrapper.startswith(b"\x51\x6a\x04\x51")
    assert b"\x8b\x0c\x24\x8b\x01" in popup_wrapper
    popup_query_site = profile.site("mouse_move.popup_query_dispatch")
    assert popup_query_site.va == 0x004BEE44
    assert popup_query_site.original == bytes.fromhex("8b 01 ff 50 60")
    assert by_label["popup query wrapper"].endswith(b"\x6a\x01\x58\xc3")
    assert tuple(profile.site(name).va for name in compiler._direct_message_site_names) == (
        0x004BECB6,
        0x004BECC2,
        0x004BEDD0,
    )
    selected_site = profile.site("mouse_move.message_selected_dispatch")
    assert selected_site.va == 0x004BEE03
    assert selected_site.original == bytes.fromhex("8b 08 8b 01 ff 50 0c")


def test_native_compiler_identity_is_immutable_metadata() -> None:
    """Registry identity cannot be overridden as accidental constructor state."""
    for compiler_type in (
        TransitionFrameCompiler,
        StaleMouseMoveCompiler,
    ):
        assert tuple(field.name for field in fields(compiler_type)) == ("profile",)


def test_fixed_interface_compiler_graph_is_immutable() -> None:
    """Verification cannot observe state left behind by an earlier compilation."""
    expected_fields = {
        Runtime2DCompiler: ("profile",),
        DirectRoomRenderingCompiler: ("symbols", "profile"),
        SidneyConstructionCompiler: ("profile",),
        InventoryFeatureCompiler: ("symbols", "profile", "room_rendering_abi"),
        ResourceDispatchCompiler: ("symbols", "profile", "transition_abi"),
        FingerprintFeatureCompiler: ("symbols", "profile"),
        CaptionFeatureCompiler: (
            "symbols",
            "profile",
            "room_rendering_abi",
            "transition_abi",
        ),
        SystemScreenCompiler: (
            "symbols",
            "profile",
            "room_rendering_abi",
            "transition_abi",
        ),
        SidneyPresentationCompiler: (
            "symbols",
            "profile",
            "room_rendering_abi",
            "mouse_move_abi",
        ),
    }
    for compiler_type, names in expected_fields.items():
        assert tuple(field.name for field in fields(compiler_type)) == names
        assert compiler_type.__dataclass_params__.frozen
        assert hasattr(compiler_type, "__slots__")


def test_two_profiles_differ_only_in_movie_skipping() -> None:
    """Testing exercises the normal improvements without movie waits."""
    assert set(PROFILES) == {ProfileId("recommended"), ProfileId("testing")}
    recommended = PROFILES[ProfileId("recommended")].patches
    assert PatchId("skip_all_movies") not in recommended
    assert PROFILES[ProfileId("testing")].patches == recommended | {PatchId("skip_all_movies")}
