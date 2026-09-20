"""Dense border sampling keeps tiled panel layout in original logical coordinates."""

from __future__ import annotations

import struct

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import (
    UI_FILTER_SEGMENT,
    UI_FRAMES_SEGMENT,
    RuntimeSymbols,
)
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system.bordered_screens import BorderedScreenFeatureCompiler
from gk3hd.patch.definitions.runtime2d.ui_frames import (
    BLIT_ONLY_IMAGES,
    DEATH_BUTTON_IMAGES,
    EVIDENCE_FINGERPRINT_IMAGES,
    FONT_BUTTON_IMAGES,
    HELP_BUTTON_IMAGES,
    MESSAGE_BUTTON_IMAGES,
    OPAQUE_INVENTORY_IMAGES,
    OPTIONS_ACTION_IMAGES,
    OPTIONS_LABEL_IMAGES,
    OPTIONS_TAB_IMAGES,
    QUIT_BUTTON_IMAGES,
    SIDNEY_ID_IMAGES,
    SIDNEY_SEPARATOR_IMAGES,
    SIDNEY_TAB_IMAGES,
    TIMEBLOCK_BUTTON_IMAGES,
    TITLE_BUTTON_IMAGES,
    TUTORIAL_IMAGES,
    UI_IMAGES,
    build_dimensions,
    build_high_dimensions,
    build_resource_match,
    build_source,
    build_surface_match,
)
from gk3hd.textures.upscale.fingerprint import EVIDENCE_FINGERPRINT_NAMES
from gk3hd.textures.upscale.thumbnail_recipes import RGB565_THUMBNAIL_SIZES


def test_empty_scoped_matcher_catalog_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires at least one resource"):
        build_resource_match(wrapper_va=0x100000, images=())
    with pytest.raises(ValueError, match="requires at least one resource"):
        build_surface_match(
            wrapper_va=0x100000, resource_match_va=0x101000, manager_va=0x102000, images=()
        )


def test_font_buttons_share_all_generation_sizes_and_states() -> None:
    assert len(FONT_BUTTON_IMAGES) == 13
    assert {name for name, _, _ in FONT_BUTTON_IMAGES} == {
        f"rc_so_{family}_{state}".encode()
        for family in ("advanced", "quit", "restore", "save")
        for state in (
            ("std", "hov", "dwn", "dis") if family == "restore" else ("std", "hov", "dwn")
        )
    }
    assert all(entry in UI_IMAGES for entry in FONT_BUTTON_IMAGES)


def test_history_separator_preserves_authored_cache_height() -> None:
    assert SIDNEY_SEPARATOR_IMAGES == ((b"s_bit_space1", 2, 1),)
    assert all(entry in UI_IMAGES for entry in SIDNEY_SEPARATOR_IMAGES)
    # The blank twelve-pixel separator is retained as a constant native fill.
    assert all(name != b"s_bit_space2" for name, _, _ in UI_IMAGES)


def test_matcher_storage_has_room_for_batch_catalogs() -> None:
    # Reserve the final 0x1000 for the separately scoped blit-only catalog.
    # Capacity is not gained by matching arbitrary prefixes.
    images = tuple((f"batch_{index:04d}_state".encode(), 32, 32) for index in range(900))
    payload = build_resource_match(wrapper_va=0x800000, images=images)
    assert len(payload) <= UI_FRAMES_SEGMENT.size - 0x3000
    assert len(payload) <= UI_FILTER_SEGMENT.size - 0x800


def test_opaque_inventory_resource_matches_its_native_conversion_contract() -> None:
    assert OPAQUE_INVENTORY_IMAGES == ((b"undefined9", 94, 94),)
    for name, width, height in OPAQUE_INVENTORY_IMAGES:
        assert (name, width, height) in UI_IMAGES
        assert RGB565_THUMBNAIL_SIZES[name.decode().upper() + ".BMP"] == (width, height)


def test_sidney_teniers_preview_keeps_inventory_alpha_metrics_separate() -> None:
    assert (b"tempstant9", 94, 94) in BLIT_ONLY_IMAGES
    assert not any(name.startswith(b"tempstant") for name, _, _ in UI_IMAGES)
    assert not any(name.endswith(b"_op") for name, _, _ in BLIT_ONLY_IMAGES)


def test_tutorial_diagrams_keep_original_layout_dimensions() -> None:
    assert TUTORIAL_IMAGES == (
        (b"bothkeys", 131, 140),
        (b"mousemvt", 160, 154),
        (b"lcmouse", 38, 51),
        (b"rcmouse", 38, 51),
    )
    assert all(entry in UI_IMAGES for entry in TUTORIAL_IMAGES)


def test_sidney_tabs_preserve_native_dimensions_for_every_state() -> None:
    assert {name for name, _, _ in SIDNEY_TAB_IMAGES} == {
        f"b_{label}_{state}".encode()
        for label in ("addata", "analyze", "email", "files", "makeid", "search", "suspt", "transl")
        for state in ("u", "h", "d", "x")
    }
    assert len(SIDNEY_TAB_IMAGES) == 32
    assert all((width, height) == (76, 13) for _, width, height in SIDNEY_TAB_IMAGES)
    assert all(entry in UI_IMAGES for entry in SIDNEY_TAB_IMAGES)


def test_evidence_images_match_the_complete_fixed_size_generation_family() -> None:
    assert len(EVIDENCE_FINGERPRINT_IMAGES) == 12
    assert {name.decode().upper() + ".BMP" for name, _, _ in EVIDENCE_FINGERPRINT_IMAGES} == (
        EVIDENCE_FINGERPRINT_NAMES
    )
    assert all((width, height) == (41, 51) for _, width, height in EVIDENCE_FINGERPRINT_IMAGES)
    assert all(entry in UI_IMAGES for entry in EVIDENCE_FINGERPRINT_IMAGES)


def test_death_button_states_keep_native_metrics_with_fourfold_sources() -> None:
    assert {name for name, _, _ in DEATH_BUTTON_IMAGES} == {
        f"ds_{label}_{state}".encode()
        for label in ("rtry", "rest", "quit")
        for state in ("n", "h", "d", "x")
    }
    assert all((width, height) == (81, 26) for _, width, height in DEATH_BUTTON_IMAGES)
    assert all(entry in UI_IMAGES for entry in DEATH_BUTTON_IMAGES)


def test_timeblock_button_states_keep_native_metrics_with_fourfold_sources() -> None:
    assert {name for name, _, _ in TIMEBLOCK_BUTTON_IMAGES} == {
        f"tb_{label}_{state}".encode()
        for label in ("cont", "save")
        for state in ("u", "h", "d", "x")
    }
    assert all((width, height) == (81, 26) for _, width, height in TIMEBLOCK_BUTTON_IMAGES)
    assert all(entry in UI_IMAGES for entry in TIMEBLOCK_BUTTON_IMAGES)


def test_title_button_states_keep_native_metrics_with_fourfold_sources() -> None:
    assert {name for name, _, _ in TITLE_BUTTON_IMAGES} == {
        f"title_{label}_{state}".encode()
        for label in ("intro", "play", "restore", "quit")
        for state in ("u", "h", "d", "x")
    }
    assert all((width, height) == (81, 26) for _, width, height in TITLE_BUTTON_IMAGES)
    assert all(entry in UI_IMAGES for entry in TITLE_BUTTON_IMAGES)


def test_quit_button_states_keep_native_metrics_with_fourfold_sources() -> None:
    assert {name for name, _, _ in QUIT_BUTTON_IMAGES} == {
        f"qg_{label}_{state}".encode() for label in ("yes", "no", "ts") for state in ("u", "h", "d")
    }
    assert all(
        (width, height) == (117 if name.startswith(b"qg_ts_") else 81, 26)
        for name, width, height in QUIT_BUTTON_IMAGES
    )
    assert all(entry in UI_IMAGES for entry in QUIT_BUTTON_IMAGES)


def test_help_navigation_states_keep_native_metrics_with_fourfold_sources() -> None:
    assert {name for name, _, _ in HELP_BUTTON_IMAGES} == {
        f"{label}_{state}".encode()
        for label in ("prev", "next", "exit")
        for state in ("u", "h", "d")
    }
    assert all((width, height) == (49, 28) for _, width, height in HELP_BUTTON_IMAGES)
    assert all(entry in UI_IMAGES for entry in HELP_BUTTON_IMAGES)


def test_message_buttons_keep_native_metrics_for_both_dialog_kinds() -> None:
    assert {name for name, _, _ in MESSAGE_BUTTON_IMAGES} == {
        f"msg_{label}_{state}".encode()
        for label in ("yes", "no", "ok")
        for state in ("u", "h", "d")
    }
    assert all((width, height) == (46, 26) for _, width, height in MESSAGE_BUTTON_IMAGES)
    assert all(entry in UI_IMAGES for entry in MESSAGE_BUTTON_IMAGES)


def test_options_tabs_preserve_their_distinct_native_widths() -> None:
    assert (
        tuple(
            (f"op_{label}_{state}".encode(), width, 29)
            for label, width in (("gamopt", 73), ("gropt", 72), ("sopt", 73))
            for state in ("r", "hi", "dwn")
        )
        == OPTIONS_TAB_IMAGES
    )
    assert all(entry in UI_IMAGES for entry in OPTIONS_TAB_IMAGES)


def test_options_action_buttons_keep_native_geometry_in_all_states() -> None:
    expected = tuple(
        (f"{label}_{state}".encode(), width, 17)
        for label, width in (("gamop_cms", 150), ("gropt_agopt", 165))
        for state in ("r", "hi", "dwn")
    )
    assert expected == OPTIONS_ACTION_IMAGES
    assert all(entry in UI_IMAGES for entry in OPTIONS_ACTION_IMAGES)


def test_options_labels_preserve_state_specific_widths() -> None:
    assert len(OPTIONS_LABEL_IMAGES) == 11
    assert (b"advop_mipmap_dis", 96, 16) in OPTIONS_LABEL_IMAGES
    assert (b"advop_mipmap_r", 95, 16) in OPTIONS_LABEL_IMAGES
    assert all(entry in UI_IMAGES for entry in OPTIONS_LABEL_IMAGES)


def test_id_card_states_keep_authored_metrics_for_both_characters() -> None:
    assert len(SIDNEY_ID_IMAGES) == 30
    assert {name for name, _, _ in SIDNEY_ID_IMAGES} == {
        f"{character}_{profession}".encode()
        for character in ("gab", "gra")
        for profession in (
            "auto",
            "blood",
            "coroner",
            "diaper",
            "doc",
            "elec",
            "emonthly",
            "ency",
            "freelance",
            "nopd",
            "nytimes",
            "plumb",
            "security",
            "shoes",
            "sportsi",
        )
    }
    assert all((width, height) == (254, 164) for _, width, height in SIDNEY_ID_IMAGES)
    assert all(entry in UI_IMAGES for entry in SIDNEY_ID_IMAGES)


def _disassemble(payload: bytes, limit: int) -> list[tuple[str, str]]:
    instructions = list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(payload, 0x800000))
    assert sum(i.size for i in instructions) == len(payload)
    assert len(payload) <= limit
    return [(i.mnemonic, i.op_str) for i in instructions]


def test_border_match_requires_terminated_name_and_exact_dense_dimensions() -> None:
    payload = build_resource_match(wrapper_va=0x800000)
    table_offset = struct.unpack_from("<I", payload, 2)[0] - 0x800000
    instructions = _disassemble(payload[:table_offset], 0x780)
    assert instructions[0] == ("pushal", "")
    assert instructions[-6:] == [
        ("popal", ""),
        ("clc", ""),
        ("ret", ""),
        ("popal", ""),
        ("stc", ""),
        ("ret", ""),
    ]
    assert len(payload) <= 0x6000
    assert UI_IMAGES
    assert len({name for name, _, _ in UI_IMAGES}) == len(UI_IMAGES)
    assert ("cmp", "edx, dword ptr [eax + 0x38]") in instructions
    assert ("cmp", "edx, dword ptr [eax + 0x3c]") in instructions
    assert ("cmp", "dl, 0x41") in instructions
    assert ("cmp", "dl, 0x5a") in instructions
    assert ("or", "dl, 0x20") in instructions
    assert ("movzx", "edx, word ptr [ebx]") in instructions
    assert ("movzx", "edx, word ptr [ebx + 2]") in instructions
    assert ("cmp", "dl, byte ptr [ebx + ecx + 5]") in instructions
    assert ("test", "dl, dl") in instructions
    assert ("cmp", "ecx, 0x20") in instructions
    for name, width, height in UI_IMAGES:
        stored_width, stored_height, length = struct.unpack_from("<HHB", payload, table_offset)
        assert (stored_width, stored_height) == (width * 4, height * 4)
        assert length == len(name) + 6
        assert payload[table_offset + 5 : table_offset + length] == name + b"\0"
        table_offset += length
    assert table_offset == len(payload)
    assert ("movzx", "ecx, byte ptr [ebx + 4]") in instructions
    assert all(
        name == name.lower() and len(name) < 32 and b"\0" not in name for name, _, _ in UI_IMAGES
    )


def test_border_dimensions_return_private_metrics_without_mutating_surface() -> None:
    payload = build_dimensions(wrapper_va=0x800000, match_va=0x810000, logical_va=0x820000)
    instructions = _disassemble(payload, 0x100)
    assert instructions[0] == ("call", "0x810000")
    assert ("sar", "edx, 2") in instructions
    assert ("mov", "dword ptr [0x820000], edx") in instructions
    assert ("mov", "dword ptr [0x820004], edx") in instructions
    assert ("mov", "eax, 0x820000") in instructions
    assert all(not operand.startswith("dword ptr [eax") for _, operand in instructions)


@pytest.mark.parametrize("size", [(0, 16), (16, 0), (-1, 16), (16384, 16), (16, 16384)])
def test_compact_matcher_rejects_extents_that_cannot_be_encoded(
    monkeypatch: pytest.MonkeyPatch, size: tuple[int, int]
) -> None:
    monkeypatch.setattr(
        "gk3hd.patch.definitions.runtime2d.ui_frames.UI_IMAGES", ((b"test", *size),)
    )
    with pytest.raises(ValueError, match="extent exceeds matcher record"):
        build_resource_match(wrapper_va=0x800000)


def test_border_surface_identity_is_resolved_from_live_table_without_registration() -> None:
    payload = build_surface_match(
        wrapper_va=0x800000, resource_match_va=0x810000, manager_va=0x820000
    )
    assert len(payload) <= 0x700
    sizes = sorted({(w * 4, h * 4) for _, w, h in UI_IMAGES})
    instructions = _disassemble(payload[: -len(sizes) * 8], 0x700)
    assert list(struct.iter_unpack("<II", payload[-len(sizes) * 8 :])) == sizes
    assert instructions[0] == ("pushal", "")
    assert instructions[-3:] == [("popal", ""), ("clc", ""), ("ret", "")]
    for instruction in (
        ("test", "eax, eax"),
        ("test", "edi, edi"),
        ("test", "ecx, ecx"),
        ("test", "esi, esi"),
        ("mov", "ecx, dword ptr [edi + 0x124]"),
        ("mov", "edi, dword ptr [edi + 0x120]"),
        ("cmp", "dword ptr [esi + 0x30], eax"),
        ("call", "0x810000"),
    ):
        assert instruction in instructions
    # No identity cache write: (0, 0) corner draws can precede GetDimensions,
    # and reused native resource/surface addresses cannot retain a dense tag.
    assert all(
        not operand.startswith("dword ptr [")
        for mnemonic, operand in instructions
        if mnemonic == "mov"
    )


def test_high_blitter_clips_logical_source_and_preserves_native_destination_and_flags() -> None:
    site = GOG_BUILD.site("runtime2d.high_blt_dimensions")
    payload = build_high_dimensions(
        wrapper_va=0x800000,
        surface_match_va=0x810000,
        original=site.original,
        return_va=site.va + len(site.original),
    )
    instructions = _disassemble(payload, 0x100)
    assert payload.startswith(b"\x9c" + site.original + b"\x50\x8b\xc3")
    assert ("call", "0x810000") in instructions
    assert [(mnemonic, operand) for mnemonic, operand in instructions if mnemonic == "sar"] == [
        ("sar", "eax, 2"),
        ("sar", "ecx, 2"),
    ]
    assert instructions[-2:] == [("popfd", ""), ("jmp", "0x54f6bc")]


def test_final_border_sampling_scales_only_known_logical_callers_and_private_source() -> None:
    callers = tuple(
        GOG_BUILD.address(f"runtime2d.high_blt_{kind}_return") for kind in ("final", "fallback")
    )
    payload = build_source(
        wrapper_va=0x800000,
        surface_match_va=0x810000,
        scratch_va=0x820000,
        callers=callers,
        manager_va=0x830000,
        dimensions_va=0x840000,
    )
    instructions = _disassemble(payload, 0x200)
    assert payload.startswith(b"\x60\x8d\x6c\x24\x24")
    for caller in callers:
        assert b"\x81\x7d\x00" + struct.pack("<I", caller) in payload
    assert ("call", "0x810000") in instructions
    for offset in range(0, 16, 4):
        assert b"\xa3" + struct.pack("<I", 0x820000 + offset) in payload
    assert b"\xc7\x45\x0c" + struct.pack("<I", 0x820000) in payload
    assert b"\xc7\x45\x08" not in payload  # Destination pointer is untouched.
    assert b"\x89\x06" not in payload  # Caller-owned source RECT is untouched.
    # Two-level map detail selection changes only a validated live source and
    # its private clip, never logical puzzle coordinates or destination bounds.
    assert ("cmp", "dword ptr [0x840004], 0x600") in instructions
    assert ("cmp", "dword ptr [edx + 0x38], 0x558") in instructions
    assert ("cmp", "dword ptr [eax + 0x38], 0x1560") in instructions
    assert ("cmp", "dword ptr [esi + 0x30], edx") in instructions
    assert ("cmp", "byte ptr [esi + 0x17], 0") in instructions
    assert ("cmp", "byte ptr [esi + 0x14], 0") in instructions
    assert ("mov", "dword ptr [ebp + 4], eax") in instructions
    for offset in range(0, 16, 4):
        assert ("shl", f"dword ptr [{0x820000 + offset:#x}], 2") in instructions
    assert payload.endswith(b"\x61\xc3")


def test_help_visibility_retires_previous_page_damage_only_on_hd_transition() -> None:
    compiler = BorderedScreenFeatureCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=0x810000, height_va=0x810004),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=0x820000,
            room_presentation_active_va=0x820004,
            pre_flip_presenter_slot_va=0x820008,
            post_flip_presenter_slot_va=0x82000C,
        ),
    )
    payload = compiler.build_visibility(wrapper_va=0x800000)
    instructions = _disassemble(payload, 0x100)
    calls = [operand for mnemonic, operand in instructions if mnemonic == "call"]
    assert calls == [
        hex(GOG_BUILD.address("ui.set_visible")),
        hex(GOG_BUILD.address("transition.invalidate_all_damage")),
    ]
    dimensions = GOG_BUILD.address("display.dimensions")
    assert ("cmp", f"dword ptr [{dimensions:#x}], 0x400") in instructions
    assert ("cmp", f"dword ptr [{dimensions + 4:#x}], 0x300") in instructions
    assert instructions[-3:] == [("popal", ""), ("popfd", ""), ("ret", "4")]
