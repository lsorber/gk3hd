"""Private packaging verifies payloads without copying a compatibility prefix."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from gk3hd.vr.standalone import bundle as standalone_bundle
from gk3hd.vr.standalone.bundle import (
    REQUIRED_FILES,
    BundleManifest,
    build_bundle,
    component_bundle,
    inspect_bundle,
    require_component_base,
)

if TYPE_CHECKING:
    from pathlib import Path


def _files(tmp_path: Path) -> dict[str, Path]:
    files = {}
    for index, name in enumerate([*sorted(REQUIRED_FILES), "Data/core.brn"]):
        source = tmp_path / f"input-{index}"
        source.write_bytes(name.encode())
        files[name] = source
    return files


def test_bundle_describes_exact_bytes_and_progress(tmp_path: Path) -> None:
    files = _files(tmp_path)
    updates = []
    receipt = build_bundle(
        files, tmp_path / "private.zip", progress=lambda n, total: updates.append((n, total))
    )
    assert receipt.sha256 == hashlib.sha256(receipt.path.read_bytes()).hexdigest()
    assert receipt.files == len(files)
    assert inspect_bundle(receipt.path) == receipt
    assert updates[-1] == (receipt.payload_bytes, receipt.payload_bytes)
    with ZipFile(receipt.path) as archive:
        manifest = json.loads(archive.read("bundle.json"))
        assert manifest["schema"] == 1
        for name, entry in manifest["files"].items():
            payload = archive.read(name)
            assert entry == {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    assert not list(tmp_path.glob(".gk3hd-bundle-*"))


def test_non_bundle_is_rejected_before_transfer(tmp_path: Path) -> None:
    archive = tmp_path / "texture-pack.zip"
    with ZipFile(archive, "w") as contents:
        contents.writestr("image.png", b"not a game bundle")
    with pytest.raises(ValueError, match=r"missing bundle\.json"):
        inspect_bundle(archive)


def test_component_bundle_only_archives_changed_files_with_the_complete_inventory(
    tmp_path: Path,
) -> None:
    files = _files(tmp_path)
    old = inspect_bundle(build_bundle(files, tmp_path / "old.zip").path)
    replacement = b"new renderer bytes"
    files["ddraw.dll"].write_bytes(replacement)
    full = inspect_bundle(build_bundle(files, tmp_path / "full.zip").path)
    previous = json.dumps({"schema": 1, "files": old.inventory})
    component = component_bundle(full, previous, tmp_path / "component.zip")
    assert component is not None
    assert component.component_update
    assert component.files == full.files
    assert component.payload_bytes == full.payload_bytes
    with ZipFile(component.path) as archive:
        assert set(archive.namelist()) == {"bundle.json", "game/ddraw.dll"}
        assert archive.read("game/ddraw.dll") == replacement
        assert json.loads(archive.read("bundle.json")) == {"schema": 2, "files": full.inventory}


def test_component_bundle_keeps_full_transfer_when_the_receipt_cannot_reuse_files(
    tmp_path: Path,
) -> None:
    full = inspect_bundle(build_bundle(_files(tmp_path), tmp_path / "full.zip").path)
    output = tmp_path / "component.zip"
    for invalid in ("", '{"schema":1,"files":{}}', '{"schema":2}'):
        assert component_bundle(full, invalid, output) is None
    same = json.dumps({"schema": 1, "files": full.inventory})
    assert component_bundle(full, same, output) is None
    assert not output.exists()


def test_component_bundle_sends_additions_and_replacements_without_resending_game_data(
    tmp_path: Path,
) -> None:
    files = _files(tmp_path)
    old = inspect_bundle(build_bundle(files, tmp_path / "old.zip").path)
    files["ddraw.dll"].write_bytes(b"new renderer")
    added = tmp_path / "added"
    added.write_bytes(b"corrected backdrop")
    files["Data/backdrop.bsp"] = added
    full = inspect_bundle(build_bundle(files, tmp_path / "full.zip").path)
    previous = {"schema": 1, "bundle_sha256": old.sha256, "files": old.inventory}
    output = tmp_path / "component.zip"
    assert component_bundle(full, json.dumps(previous), output) is None
    update = component_bundle(full, json.dumps(previous), output, allow_additions=True)
    assert update is not None
    assert update.component_additions
    require_component_base(update, json.dumps(previous))
    require_component_base(
        update, json.dumps({"schema": 1, "bundle_sha256": update.sha256, "files": full.inventory})
    )
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "bundle.json",
            "game/Data/backdrop.bsp",
            "game/ddraw.dll",
        }
        assert archive.read("game/Data/backdrop.bsp") == b"corrected backdrop"
    with pytest.raises(ValueError, match="does not match the installed player"):
        require_component_base(update, json.dumps({**previous, "files": full.inventory}))


@pytest.mark.parametrize("change", ["remove", "new-directory", "too-many"])
def test_unbounded_inventory_changes_keep_the_full_transfer(tmp_path: Path, change: str) -> None:
    files = _files(tmp_path)
    source = files["Data/core.brn"]
    files["Data/obsolete.bsp"] = source
    old = inspect_bundle(build_bundle(files, tmp_path / "old.zip").path)
    if change == "remove":
        del files["Data/obsolete.bsp"]
    elif change == "new-directory":
        files["new/backdrop.bsp"] = source
    else:
        files.update({f"Data/added{index}.bsp": source for index in range(33)})
    full = inspect_bundle(build_bundle(files, tmp_path / "full.zip").path)
    previous = json.dumps({"schema": 1, "bundle_sha256": old.sha256, "files": old.inventory})
    assert (
        component_bundle(full, previous, tmp_path / "component.zip", allow_additions=True) is None
    )


def test_unchanged_inventory_can_be_verified_without_transferring_game_files(
    tmp_path: Path,
) -> None:
    full = inspect_bundle(build_bundle(_files(tmp_path), tmp_path / "full.zip").path)
    previous = {"schema": 1, "bundle_sha256": full.sha256, "files": full.inventory}
    update = component_bundle(
        full, json.dumps(previous), tmp_path / "update.zip", allow_verification=True
    )
    assert update is not None
    assert update.verification_only
    with ZipFile(update.path) as archive:
        assert archive.namelist() == ["bundle.json"]
    require_component_base(update, json.dumps(previous))
    changed = {**full.inventory, "game/ddraw.dll": {"size": 4, "sha256": "0" * 64}}
    with pytest.raises(ValueError, match="does not match the installed player"):
        require_component_base(update, json.dumps({**previous, "files": changed}))


def test_component_bundle_rechecks_replacement_bytes_from_the_full_archive(tmp_path: Path) -> None:
    files = _files(tmp_path)
    old = inspect_bundle(build_bundle(files, tmp_path / "old.zip").path)
    files["ddraw.dll"].write_bytes(b"new renderer")
    full = inspect_bundle(build_bundle(files, tmp_path / "full.zip").path)
    files["ddraw.dll"].write_bytes(b"bad renderer")
    build_bundle(files, tmp_path / "changed.zip").path.replace(full.path)
    with pytest.raises(ValueError, match="changed before transfer"):
        component_bundle(
            full, json.dumps({"schema": 1, "files": old.inventory}), tmp_path / "update.zip"
        )


def test_retry_produces_the_same_component_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _files(tmp_path)
    old = inspect_bundle(build_bundle(files, tmp_path / "old.zip").path)
    files["ddraw.dll"].write_bytes(b"new renderer")
    full = inspect_bundle(build_bundle(files, tmp_path / "full.zip").path)
    previous = json.dumps({"schema": 1, "files": old.inventory})
    first = component_bundle(full, previous, tmp_path / "first.zip")
    assert first is not None
    # A later retry can regenerate the archive from a differently ordered receipt.
    monkeypatch.setattr("zipfile.time.time", lambda: 2_000_000_000)
    reordered = BundleManifest(
        full.path, dict(reversed(full.inventory.items())), full.payload_bytes, 1
    )
    second = component_bundle(reordered, previous, tmp_path / "second.zip")
    assert second is not None
    assert first.sha256 == second.sha256


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "Data/CON.bmp",
        "Data/a.",
        "Data/a ",
        "Data\\a",
        "DDRAW.DLL",
        ".gk3hd-standalone.json",
        ".GK3HD-STANDALONE.JSON",
    ],
)
def test_unsafe_or_colliding_paths_never_publish(tmp_path: Path, name: str) -> None:
    files = _files(tmp_path)
    files[name] = files["ddraw.dll"]
    with pytest.raises(ValueError, match="Unsafe or duplicate"):
        build_bundle(files, tmp_path / "private.zip")
    assert not (tmp_path / "private.zip").exists()


def test_existing_output_is_preserved(tmp_path: Path) -> None:
    files = _files(tmp_path)
    output = tmp_path / "private.zip"
    output.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        build_bundle(files, output)
    assert output.read_bytes() == b"keep"


def test_changed_input_does_not_leave_partial_output(tmp_path: Path) -> None:
    files = _files(tmp_path)
    victim = files["ddraw.dll"]

    def change_later_input(_done: int, _total: int) -> None:
        victim.write_bytes(b"larger than the declared file")

    with pytest.raises(ValueError, match="changed during packaging"):
        build_bundle(files, tmp_path / "private.zip", progress=change_later_input)
    assert not (tmp_path / "private.zip").exists()
    assert not list(tmp_path.glob(".gk3hd-bundle-*"))


def test_failed_final_guard_cannot_publish_a_bundle(tmp_path: Path) -> None:
    files = _files(tmp_path)

    def changed() -> None:
        msg = "Source changed during preparation"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="Source changed"):
        build_bundle(files, tmp_path / "private.zip", before_publish=changed)
    assert not (tmp_path / "private.zip").exists()
    assert not list(tmp_path.glob(".gk3hd-bundle-*"))


def test_compressed_textures_keep_exact_pixels_and_separate_expanded_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _files(tmp_path)
    texture = tmp_path / "cached-payload"
    payload = b"BM" + bytes(900_000)
    texture.write_bytes(payload)
    files["gk3hd/textures/installed/MASK.BMP"] = texture
    monkeypatch.setattr(standalone_bundle, "MAX_ARCHIVE_BYTES", 32_000)
    monkeypatch.setattr(standalone_bundle, "MAX_PAYLOAD_BYTES", 1_000_000)
    receipt = build_bundle(files, tmp_path / "private.zip")
    assert receipt.path.stat().st_size < 32_000 < receipt.payload_bytes
    assert inspect_bundle(receipt.path) == receipt
    with ZipFile(receipt.path) as archive:
        entry = archive.getinfo("game/gk3hd/textures/installed/MASK.BMP")
        assert entry.compress_type == ZIP_DEFLATED
        assert archive.read(entry) == payload


def test_compression_does_not_bypass_expanded_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _files(tmp_path)
    source = tmp_path / "MASK.BMP"
    source.write_bytes(bytes(1024))
    files["MASK.BMP"] = source
    monkeypatch.setattr(standalone_bundle, "MAX_PAYLOAD_BYTES", 512)
    with pytest.raises(ValueError, match="storage bound"):
        build_bundle(files, tmp_path / "private.zip")
    assert not (tmp_path / "private.zip").exists()


def test_transfer_bound_stops_writing_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(standalone_bundle, "MAX_ARCHIVE_BYTES", 100)
    with pytest.raises(ValueError, match="transfer size limit"):
        build_bundle(_files(tmp_path), tmp_path / "private.zip")
    assert not (tmp_path / "private.zip").exists()
    assert not list(tmp_path.glob(".gk3hd-bundle-*"))


def test_installed_identity_checked_against_archived_bytes(tmp_path: Path) -> None:
    files = _files(tmp_path)
    identity = hashlib.sha256(files["ddraw.dll"].read_bytes()).hexdigest()
    files["ddraw.dll"].write_bytes(b"same file, replaced contents")
    with pytest.raises(ValueError, match="installed identity"):
        build_bundle(files, tmp_path / "private.zip", expected_sha256={"ddraw.dll": identity})
    assert not (tmp_path / "private.zip").exists()


@pytest.mark.parametrize("name", ["FLOORT~1.BMP", "L'ERMITAGE3.BMP"])
def test_original_texture_names_survive_transfer(tmp_path: Path, name: str) -> None:
    files = _files(tmp_path)
    files[f"gk3hd/textures/installed/{name}"] = files["ddraw.dll"]
    receipt = build_bundle(files, tmp_path / "private.zip")
    assert inspect_bundle(receipt.path) == receipt
    with ZipFile(receipt.path) as archive:
        assert (
            archive.read(f"game/gk3hd/textures/installed/{name}") == files["ddraw.dll"].read_bytes()
        )
