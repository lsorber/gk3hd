"""Only verified native room subclasses can reach VR world producers."""

from __future__ import annotations

import pytest

from gk3hd.patch.builds import NATIVE_USER_SCENE_SUBCLASSES, SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.definitions.vr_native_scene import check_native_scene_types
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_complete_compilation import _source


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
@pytest.mark.parametrize("scene_name", [row[0] for row in NATIVE_USER_SCENE_SUBCLASSES])
@pytest.mark.parametrize("anchor", ["base", "type", "input", "pick"])
def test_changed_native_subclass_is_rejected_before_patch_writes(
    profile: BuildProfile, scene_name: str, anchor: str
) -> None:
    image = _source(profile)
    check_native_scene_types(image, profile)
    site = profile.site(f"vr.{scene_name}_scene_{anchor}")
    image.write_bytes(image.va_to_offset(site.va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError, match="native scene anchor changed"):
        VRSceneCompiler(profile=profile, units_per_meter=40).apply(image)
    assert image.to_bytes() == before


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_changed_subclass_invalidates_installed_scene_verification(profile: BuildProfile) -> None:
    image = _source(profile)
    compiler = VRSceneCompiler(profile=profile, units_per_meter=40)
    compiler.apply(image)
    site = profile.site("vr.laser_scene_input")
    image.write_bytes(image.va_to_offset(site.va), b"\xcc")
    with pytest.raises(PatchError, match="native scene anchor changed"):
        compiler.postcheck(image)
