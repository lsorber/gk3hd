"""Prepare the supported original game for either VR player."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.normalize import normalize_source
from gk3hd.patch.builds import profile_for_sha256
from gk3hd.patch.catalog import PLANNER
from gk3hd.patch.manifest import PatchManifest, manifest_path_for_exe
from gk3hd.patch.model import BuildContext, ProfileId
from gk3hd.system.files import sha256_file

if TYPE_CHECKING:
    from pathlib import Path

    from gk3hd.patch.builds import BuildProfile

DEFAULT_PROFILE = ProfileId("recommended")


def original_source(exe: Path) -> Path:
    """Resolve a verified original in either a stock or patched game directory."""
    manifest_path = manifest_path_for_exe(exe)
    if not manifest_path.exists():
        profile_for_sha256(sha256_file(exe))
        return exe
    manifest = PatchManifest.from_path(manifest_path)
    backup = exe.parent / manifest.backup_path
    digest = sha256_file(backup)
    profile = profile_for_sha256(digest)
    if digest != manifest.original_sha256 or profile.id != manifest.build_id:
        msg = "flat backup differs from its supported original; cannot prepare VR"
        raise ValueError(msg)
    return backup


def prepare_base_game(
    raw: bytes, *, profile_id: ProfileId = DEFAULT_PROFILE
) -> tuple[PEFile, BuildProfile]:
    """Apply the common executable patches before compiling the VR player."""
    profile = profile_for_sha256(hashlib.sha256(raw).hexdigest())
    plan = PLANNER.plan_profile(profile_id, BuildContext(build_id=profile.id))
    flat = OperationExecutor().execute(PEFile(normalize_source(raw)), plan.compile_operations())
    return flat, profile
