"""Recognize supported editions without accepting unknown executable variants."""

import pytest

from gk3hd.patch.builds import (
    GOG_BUILD,
    GOG_INSTALLER_BUILD,
    BuildProfile,
    ProfileError,
    profile_for_sha256,
)


@pytest.mark.parametrize(
    ("sha256", "build"),
    [
        ("e9605cc8f3adefd29c74afa87a3b5426c540e45015e5ecc4ba33dd13b931c93a", GOG_INSTALLER_BUILD),
        ("ca544d6d6fe940da1b7787faefbf675990779dc5de4bbeca75f684d177996875", GOG_BUILD),
    ],
)
def test_recognizes_stock_and_hotfixed_gog_executables(sha256: str, build: BuildProfile) -> None:
    assert profile_for_sha256(sha256) == build
    assert profile_for_sha256(sha256.upper()) == build


def test_nearby_unknown_hash_still_requires_explicit_build_support() -> None:
    unknown = GOG_INSTALLER_BUILD.original_sha256[:-1] + "b"
    with pytest.raises(ProfileError, match="unsupported GK3 executable SHA-256"):
        profile_for_sha256(unknown)
