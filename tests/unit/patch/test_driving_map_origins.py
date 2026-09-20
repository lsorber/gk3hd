"""The reference and HD game share only the necessary map-origin corrections."""

import struct

import pytest

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.builds import SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.definitions.runtime2d.resource_driving_map import correct_location_origins
from gk3hd.textures.upscale.driving_map import driving_map_overlay_origin
from tests.unit.patch.test_binary_operations import FakeExecutable


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=list(SUPPORTED_BUILDS))
def test_constructor_positions_match_both_texture_states_without_other_edits(
    profile: BuildProfile,
) -> None:
    sites = [profile.site(f"driving_map.{name}.origin") for name in ("TR1", "RL1", "TRE")]
    image = FakeExecutable(bytearray(max(site.va + len(site.original) for site in sites) + 16))
    for site in sites:
        image.write_bytes(site.va, site.original)
    before = bytes(image.data)
    plan = ExecutableMutationPlan(owner="map alignment test")
    correct_location_origins(plan, profile)
    plan.apply(image)
    for name, site in zip(("TR1", "RL1", "TRE"), sites, strict=True):
        payload = image.read_bytes(site.va, len(site.original))
        first_short = payload.startswith(b"\x6a")
        next_push = 2 if first_short else 5
        y = struct.unpack_from("<b" if first_short else "<I", payload, 1)[0]
        x = struct.unpack_from(
            "<b" if payload[next_push:].startswith(b"\x6a") else "<I", payload, next_push + 1
        )[0]
        assert (x, y) == driving_map_overlay_origin(f"DM_{name}.BMP")
        assert (x, y) == driving_map_overlay_origin(f"DM_{name}_UL.BMP")
        image.write_bytes(site.va, site.original)
    assert bytes(image.data) == before
