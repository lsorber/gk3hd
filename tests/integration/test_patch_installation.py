"""Optional full-executable contract test isolated in a temporary directory."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from gk3hd.patch.binary.compiled import CompiledPayload
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.builds import profile_for_sha256
from gk3hd.patch.definitions.guard_stale_mouse_move_targets import StaleMouseMoveCompiler
from gk3hd.patch.definitions.normalize_keyboard_camera_motion import KeyboardCameraMotionCompiler
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.runtime2d import Runtime2DCompiler
from gk3hd.patch.definitions.runtime2d.fingerprint import FingerprintFeatureCompiler
from gk3hd.patch.definitions.runtime2d.inventory import InventoryFeatureCompiler
from gk3hd.patch.definitions.runtime2d.layout import (
    GPS_SEGMENT,
    GPS_TRANSFER_OFFSET,
    ROOM_RENDERING_SEGMENT,
    UI_FRAMES_DIMENSIONS_OFFSET,
    UI_FRAMES_SEGMENT,
    RuntimeLayout,
)
from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler
from gk3hd.patch.definitions.runtime2d.room_rendering import DirectRoomRenderingCompiler
from gk3hd.patch.definitions.runtime2d.sidney_construction import SidneyConstructionCompiler
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler
from gk3hd.patch.definitions.runtime2d.system import SystemScreenCompiler
from gk3hd.patch.definitions.speed_up_surface_checks import SurfaceCheckCompiler
from gk3hd.patch.install.configuration import NoopConfiguration
from gk3hd.patch.install.transaction import Installer
from gk3hd.patch.manifest import manifest_path_for_exe
from gk3hd.patch.model import PatchError, PatchId, ProfileId
from gk3hd.system.files import sha256_file


def _supplied_original() -> Path:
    """Return the explicit private fixture or skip with one stable reason."""
    value = os.environ.get("GK3_TEST_EXE")
    if not value:
        pytest.skip("set GK3_TEST_EXE to a supported original executable")
    path = Path(value)
    if not path.is_file():
        pytest.skip("GK3_TEST_EXE does not point to a file")
    return path


@pytest.mark.integration
def test_recommended_install_verifies_and_restores_a_temporary_copy(tmp_path: Path) -> None:
    """The complete plan never reads or mutates the user's installed executable."""
    source = _supplied_original()
    exe = tmp_path / "GK3.exe"
    shutil.copy2(source, exe)
    original_sha256 = sha256_file(exe)
    installer = Installer(configuration=NoopConfiguration(), process_probe=lambda: False)

    # Compile the stock-art oracle as well as the player profile. Reference
    # transport repairs do not install modern fixed-interface transforms.
    baseline = installer.prepare(
        exe=exe,
        profile=None,
        patches=tuple(
            PatchId(value)
            for value in (
                "prevent_save_warning_dialogs",
                "prevent_transition_flicker",
                "remove_disc_requirement",
                "skip_all_movies",
                "stabilize_mouse_input",
            )
        ),
        width=1024,
        height=768,
    )
    assert PatchId("scale_fixed_interfaces") not in baseline.plan.patch_ids
    assert PatchId("maximize_graphics_quality") not in baseline.plan.patch_ids

    prepared_by_resolution = {
        (width, height): installer.prepare(
            exe=exe,
            profile=ProfileId("recommended"),
            patches=(),
            width=width,
            height=height,
        )
        for width, height in (
            (1024, 768),
            (1920, 1080),
            (2560, 1600),
            (3440, 1440),
            (3840, 2160),
        )
    }
    # Every injected transform reads GK3's live dimensions. Resolution changes
    # belong only to the external configuration transaction, so one executable
    # and one plan identity must serve reference, widescreen, 16:10, ultrawide,
    # and higher-density modes without patch-time geometry variants.
    assert len({item.installed_sha256 for item in prepared_by_resolution.values()}) == 1
    assert len({item.plan_digest for item in prepared_by_resolution.values()}) == 1

    prepared = prepared_by_resolution[(1920, 1080)]
    manifest = installer.apply(exe=exe, prepared=prepared)
    report = installer.verify(exe=exe)

    assert report.installed_sha256 == manifest.installed_sha256
    assert manifest_path_for_exe(exe).is_file()

    # Verification must inspect the injected native code itself.  Hook bytes,
    # section markers, and a matching manifest are insufficient if a payload
    # body is stale or corrupted in memory or on disk.
    profile = profile_for_sha256(original_sha256)
    for compiler, section_name, payload_offset in (
        (
            TransitionFrameCompiler(profile=profile),
            TransitionFrameCompiler._section_name,
            TransitionFrameCompiler._off_flip_wrapper,
        ),
        (
            StaleMouseMoveCompiler(profile=profile),
            StaleMouseMoveCompiler._section_name,
            StaleMouseMoveCompiler._off_wrapper,
        ),
        (
            KeyboardCameraMotionCompiler(profile=profile),
            KeyboardCameraMotionCompiler.section_name,
            KeyboardCameraMotionCompiler._off_keyboard_wrapper,
        ),
        (
            SurfaceCheckCompiler(profile=profile),
            SurfaceCheckCompiler.section_name,
            SurfaceCheckCompiler._lock_offset,
        ),
    ):
        corrupted = PEFile.from_path(exe)
        section = corrupted.get_section(section_name)
        assert section is not None
        byte_offset = section.pointer_to_raw_data + payload_offset
        original = corrupted.read_bytes(byte_offset, 1)
        corrupted.write_bytes(byte_offset, bytes((original[0] ^ 0xFF,)))
        with pytest.raises(PatchError, match="postcheck failed"):
            compiler.postcheck(corrupted)

    runtime_compiler = next(
        operation.compiler
        for operation in prepared.plan.compile_operations()
        if isinstance(operation, CompiledPayload)
        and isinstance(operation.compiler, Runtime2DCompiler)
    )
    # Exercise one immutable payload in every logical segment of the shared
    # fixed-interface section.  This guards the compositor's complete feature
    # boundary instead of proving only the outer .gk2d header and hook table.
    for logical_section, payload_offset in (
        (SidneyConstructionCompiler._section_name, SidneyConstructionCompiler._off_width_const),
        (
            SidneyPresentationCompiler._section_name,
            SidneyPresentationCompiler._off_root_draw_wrapper,
        ),
        (InventoryFeatureCompiler._section_name, InventoryFeatureCompiler._off_draw_wrapper),
        (ResourceDispatchCompiler._section_name, ResourceDispatchCompiler._off_wrapper),
        (FingerprintFeatureCompiler._section_name, FingerprintFeatureCompiler._off_wrapper),
        (UI_FRAMES_SEGMENT.logical_name, UI_FRAMES_DIMENSIONS_OFFSET),
        (GPS_SEGMENT.logical_name, GPS_TRANSFER_OFFSET),
        (
            ROOM_RENDERING_SEGMENT.logical_name,
            DirectRoomRenderingCompiler._off_layout_version,
        ),
        (SystemScreenCompiler._section_name, SystemScreenCompiler._off_root_draw_wrapper),
        (
            SystemScreenCompiler._control_section_name,
            SystemScreenCompiler._off_control_blt_wrapper,
        ),
        (
            SystemScreenCompiler._loadsave_section_name,
            SystemScreenCompiler._off_loadsave_layout_wrapper,
        ),
    ):
        corrupted = PEFile.from_path(exe)
        shared = corrupted.get_section(RuntimeLayout.section_name)
        segment = RuntimeLayout.segment(logical_section)
        assert shared is not None
        assert segment is not None
        byte_offset = shared.pointer_to_raw_data + segment.offset + payload_offset
        original = corrupted.read_bytes(byte_offset, 1)
        corrupted.write_bytes(byte_offset, bytes((original[0] ^ 0xFF,)))
        try:
            runtime_compiler.postcheck(corrupted)
        except PatchError:
            continue
        pytest.fail(f"runtime verification accepted corrupted {logical_section} payload")

    installer.restore(exe=exe)
    assert sha256_file(exe) == original_sha256
    assert not manifest_path_for_exe(exe).exists()
    assert not exe.with_suffix(".exe.bak").exists()
