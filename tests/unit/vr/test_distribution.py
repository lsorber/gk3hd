"""Release component delivery never includes purchased data or executes binaries."""

from __future__ import annotations

import hashlib
import shutil
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock
from zipfile import ZipFile, ZipInfo

import pytest

from gk3hd.vr import artifact, distribution
from gk3hd.vr.android import notices
from gk3hd.vr.standalone.paths import APK_FILENAME
from tests.unit.renderer.test_artifact import renderer_dll, vr_dll
from tests.unit.vr.standalone.test_build import components

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["components", "renderer_dll", "vr_dll"]


@pytest.fixture
def build(components: Path, vr_dll: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    assert vr_dll.parent == components
    monkeypatch.setattr(distribution, "RECIPE", artifact.RECIPE)
    payload = b"Third-party notice"
    monkeypatch.setattr(
        notices,
        "COMPONENT_LICENSES",
        dict.fromkeys(notices.COMPONENT_LICENSES, hashlib.sha256(payload).hexdigest()),
    )
    for name in notices.COMPONENT_LICENSES:
        (components / name).write_bytes(payload)
    return components


def _release(date: str, tag: str = "v1.2.0") -> dict[str, object]:
    name = distribution.asset_name()
    return {
        "draft": False,
        "prerelease": False,
        "tag_name": tag,
        "published_at": date,
        "assets": [
            {
                "name": name,
                "digest": "sha256:" + "a" * 64,
                "size": 1234,
                "state": "uploaded",
                "browser_download_url": f"https://github.com/lsorber/gk3hd/releases/download/{tag}/{name}",
            }
        ],
    }


def test_archive_roundtrip_excludes_game_saves_and_build_trees(build: Path) -> None:
    for name in ("GK3.exe", "save0001.gk3", "private.brn", "account.txt"):
        (build / name).write_bytes(b"private, never distribute")
    archive = distribution.archive(build, build / "release")
    with ZipFile(archive) as data:
        assert not {"GK3.exe", "save0001.gk3", "private.brn", "account.txt"} & set(data.namelist())
        assert b"Source code (zip)" in data.read("SOURCES.txt")
        assert b"Michael Ringgaard" in data.read("ANDROID-THIRD-PARTY-NOTICES.txt")
    target = build / "unpacked"
    target.mkdir()
    distribution._extract(archive, target)
    for name in ("gk3hd-standalone.apk", "openxr_wxr32.dll"):
        assert (target / name).read_bytes() == (build / name).read_bytes()


def test_pc_archive_needs_only_the_verified_renderer(build: Path) -> None:
    (build / APK_FILENAME).unlink()
    kind = distribution.AssetKind.RENDERER
    renderer = distribution.renderer_path(build)
    archive = distribution.archive(build, build / "release", kind=kind)
    target = build / "unpacked"
    target.mkdir()

    distribution._extract(archive, target, kind=kind)

    assert {path.name for path in target.iterdir()} == {
        renderer.name,
        renderer.with_suffix(".json").name,
        renderer.with_suffix(".txt").name,
    }
    assert (target / renderer.name).read_bytes() == renderer.read_bytes()


def test_android_source_changes_only_invalidate_the_standalone_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind = distribution.AssetKind.RENDERER
    pc, standalone = distribution.asset_name(kind), distribution.asset_name()
    monkeypatch.setattr(distribution, "source_hashes", lambda: {"Android.java": "new content"})

    assert distribution.asset_name(kind) == pc
    assert distribution.asset_name() != standalone


def test_rejected_apk_signer_prevents_publication_of_the_component_archive(build: Path) -> None:
    def reject(apk: Path) -> None:
        assert apk.read_bytes() == (build / APK_FILENAME).read_bytes()
        message = "The APK does not have the configured Android release signer"
        raise ValueError(message)

    output = build / "release"
    with pytest.raises(ValueError, match="configured Android release signer"):
        distribution.archive(build, output, signer=Mock(verify=reject))
    assert list(output.iterdir()) == []


def test_changed_component_license_prevents_publication_of_the_archive(build: Path) -> None:
    (build / "OpenXR-WXR-LICENSE.txt").write_text("Different license", encoding="utf-8")
    output = build / "release"
    with pytest.raises(ValueError, match=r"component license: OpenXR-WXR-LICENSE\.txt"):
        distribution.archive(build, output)
    assert not output.exists()


def test_download_uses_verified_inventory_and_reuses_unchanged_components(
    build: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = distribution.archive(build, build / "release")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(
        distribution,
        "published_asset",
        lambda _kind: ("https://example.invalid/file", digest, archive.stat().st_size),
    )
    monkeypatch.setattr(distribution, "cache_directory", lambda: build / "cache")

    def download(_url: str, destination: Path, **_kwargs: object) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, destination)
        return destination

    monkeypatch.setattr(distribution, "download_verified", download)
    first = distribution.components()
    (first / "retained-local-note.txt").write_bytes(b"not a managed output")
    assert distribution.components() == first
    assert (first / "retained-local-note.txt").read_bytes() == b"not a managed output"
    (first / "openxr_wxr32.dll").write_bytes(b"corrupted runtime")
    with pytest.raises(ValueError, match="changed"):
        distribution.components()


@pytest.mark.parametrize("stage", ["download", "extract"])
def test_overlapping_component_preparation_preserves_the_active_cache_writer(
    build: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    archive = distribution.archive(build, build / "release")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(
        distribution,
        "published_asset",
        lambda _kind: ("https://example.invalid/file", digest, archive.stat().st_size),
    )
    monkeypatch.setattr(distribution, "cache_directory", lambda: build / "cache")
    extract = distribution._extract

    def download(_url: str, destination: Path, **_kwargs: object) -> Path:
        if stage == "download":
            with pytest.raises(RuntimeError, match="another gk3hd transaction"):
                distribution.components()
        shutil.copyfile(archive, destination)
        return destination

    def unpack(source: Path, destination: Path, *, kind: distribution.AssetKind) -> None:
        if stage == "extract":
            with pytest.raises(RuntimeError, match="another gk3hd transaction"):
                distribution.components()
        extract(source, destination, kind=kind)

    fetch = Mock(side_effect=download)
    monkeypatch.setattr(distribution, "download_verified", fetch)
    monkeypatch.setattr(distribution, "_extract", unpack)
    installed = distribution.components()
    fetch.assert_called_once()
    assert distribution.components() == installed
    assert (installed / "openxr_wxr32.dll").read_bytes() == (
        build / "openxr_wxr32.dll"
    ).read_bytes()


@pytest.mark.parametrize("tag", ["v1.3", "v1.3.0"])
def test_discovery_uses_publication_order_and_ignores_drafts(
    monkeypatch: pytest.MonkeyPatch, tag: str
) -> None:
    old, newer, draft = (
        _release("2026-10-20"),
        _release("2026-10-25", tag),
        _release("2026-10-28"),
    )
    draft["draft"] = True
    monkeypatch.setattr(distribution, "_release_page", lambda _page: [newer, draft, old])
    url, digest, size = distribution.published_asset()
    assert f"/{tag}/" in url
    assert digest == "a" * 64
    assert size == 1234


def test_no_published_compatible_build_explains_the_development_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(distribution, "_release_page", lambda _page: [])
    with pytest.raises(RuntimeError, match=r"No compatible.*published"):
        distribution.components()


def test_package_verification_requires_source_from_the_same_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _release("2026-11-11", "v1.3.0")
    older = _release("2026-10-20", "v1.2.0")
    source = {
        "name": distribution.source_asset_name(),
        "state": "uploaded",
        "size": 12345,
        "digest": "sha256:" + "b" * 64,
        "browser_download_url": (
            "https://github.com/lsorber/gk3hd/releases/download/v1.2.0/"
            + distribution.source_asset_name()
        ),
    }
    cast("list[object]", older["assets"]).append(source)
    monkeypatch.setattr(distribution, "_release_page", lambda _page: [release, older])

    assert distribution.published_asset()[1] == "a" * 64
    with pytest.raises(RuntimeError, match="needs one matching source archive"):
        distribution.published_asset(require_source=True)

    source["browser_download_url"] = str(source["browser_download_url"]).replace("v1.2.0", "v1.3.0")
    cast("list[object]", release["assets"]).append(source)
    assert distribution.published_asset(require_source=True) == distribution.published_asset()


@pytest.mark.parametrize("field", ["digest", "size", "state", "browser_download_url"])
def test_invalid_latest_release_never_falls_back_to_an_older_build(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    newer = _release("2026-10-25", "v1.3.0")
    cast("list[dict[str, object]]", newer["assets"])[0][field] = "invalid"
    monkeypatch.setattr(
        distribution, "_release_page", lambda _page: [_release("2026-10-20"), newer]
    )
    download = Mock()
    monkeypatch.setattr(distribution, "download_verified", download)
    with pytest.raises(RuntimeError, match=r"invalid|URL"):
        distribution.components()
    download.assert_not_called()


@pytest.mark.parametrize(
    "bad_entry",
    [
        "../escape",
        "game/private.brn",
        "duplicate",
        "symlink",
        "SOURCES.txt",
        "ANDROID-THIRD-PARTY-NOTICES.txt",
    ],
)
def test_foreign_duplicate_and_symlink_entries_never_extract(build: Path, bad_entry: str) -> None:
    original = distribution.archive(build, build / "release")
    poisoned = build / "invalid.zip"
    with ZipFile(original) as source, ZipFile(poisoned, "w") as target:
        for entry in source.infolist():
            if bad_entry == entry.filename:
                target.writestr(entry, b"Unexpected source")
            elif bad_entry == "symlink" and entry.filename == "openxr_wxr32.dll":
                link = ZipInfo(entry.filename)
                link.external_attr = 0o120777 << 16
                target.writestr(link, b"/outside")
            else:
                target.writestr(entry, source.read(entry.filename))
        if bad_entry not in {"symlink", "SOURCES.txt", "ANDROID-THIRD-PARTY-NOTICES.txt"}:
            if bad_entry == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate name"):
                    target.writestr("openxr_wxr32.dll", b"foreign")
            else:
                target.writestr(bad_entry, b"foreign")
    destination = build / "output"
    destination.mkdir()
    with pytest.raises(ValueError, match=r"only the expected|source document differs"):
        distribution._extract(poisoned, destination)
    assert list(destination.iterdir()) == []
