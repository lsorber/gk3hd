"""Hermetic tests for the only supported installation manifest."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from gk3hd.patch.manifest import (
    ManifestError,
    ManifestIdentity,
    PatchManifest,
    manifest_path_for_exe,
)
from gk3hd.patch.model import BuildId, PatchId, ProfileId

if TYPE_CHECKING:
    from pathlib import Path

ORIGINAL_HASH = "a" * 64
INSTALLED_HASH = "b" * 64
PLAN_DIGEST = "c" * 64


def _manifest() -> PatchManifest:
    return PatchManifest.create(
        identity=ManifestIdentity(
            package_version="1.0.0",
            source_commit="abc123",
            build_id=BuildId("gog"),
            original_sha256=ORIGINAL_HASH,
            profile=ProfileId("recommended"),
            patches=(PatchId("remove_disc_requirement"),),
            width=1920,
            height=1080,
            plan_digest=PLAN_DIGEST,
            backup_path="GK3.exe.bak",
        ),
        installed_sha256=INSTALLED_HASH,
    )


def test_current_manifest_round_trips_without_shape_loss(tmp_path: Path) -> None:
    """Every current schema field survives deterministic JSON serialization."""
    path = manifest_path_for_exe(tmp_path / "GK3.exe")
    expected = _manifest()
    path.write_text(expected.to_json(), encoding="utf-8")

    loaded = PatchManifest.from_path(path)

    assert loaded == expected
    assert loaded.to_json().endswith("\n")


@pytest.mark.parametrize("executable", ["GK3.exe", "gk3.exe", "GK3.steam.exe"])
def test_patch_state_uses_component_filename(tmp_path: Path, executable: str) -> None:
    """Patch state follows the same naming convention as textures and renderer."""
    assert manifest_path_for_exe(tmp_path / executable) == tmp_path / ".gk3hd-patch.json"


def test_current_reader_rejects_old_schema(tmp_path: Path) -> None:
    """Production verification never canonicalizes an old development manifest."""
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"schema": 1}), encoding="utf-8")

    with pytest.raises(ManifestError, match="unsupported development layout"):
        PatchManifest.from_path(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", "1920"),
        ("height", 0),
        ("patches", "remove_disc_requirement"),
        ("original_sha256", "not-a-hash"),
        ("backup_path", "../GK3.exe.bak"),
        ("backup_created", "yes"),
        ("applied_at_utc", "2026-08-12"),
    ],
)
def test_current_reader_rejects_coercible_or_unsafe_fields(field: str, value: object) -> None:
    """Malformed JSON never reaches backup or external-state operations."""
    payload = json.loads(_manifest().to_json())
    payload[field] = value

    with pytest.raises(ManifestError, match="missing or mis-types"):
        PatchManifest.from_json(json.dumps(payload))


def test_old_manifest_filename_does_not_supply_installation_evidence(tmp_path: Path) -> None:
    """An obsolete sidecar cannot authenticate an installation or its backup."""
    exe = tmp_path / "GK3.exe"
    old_path = exe.with_name("GK3.exe.patch_manifest_v1.json")
    old_path.write_text(
        json.dumps({"backup_path": "GK3.exe.bak", "target_sha256": ORIGINAL_HASH}),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="cannot read manifest"):
        PatchManifest.from_path(manifest_path_for_exe(exe))
    assert old_path.is_file()


def test_manifest_requires_explicit_backup_ownership() -> None:
    """Missing ownership evidence is rejected, never inferred from old defaults."""
    payload = json.loads(_manifest().to_json())
    payload.pop("backup_created")

    with pytest.raises(ManifestError, match="missing or mis-types"):
        PatchManifest.from_json(json.dumps(payload))
