"""Release preparation orders local checks, tag creation and draft uploads safely."""

from __future__ import annotations

import hashlib
import json
import zipfile
from functools import partial
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from gk3hd import package
from gk3hd.renderer.artifact import RendererAsset


@pytest.mark.parametrize("textures", [False, True])
@pytest.mark.parametrize("renderer", [False, True])
def test_release_can_replace_or_reuse_renderer_and_textures_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, textures: bool, renderer: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    texture_lock = Path("texture-lock.json")
    renderer_lock = Path("renderer-lock.json")
    texture_lock.write_text('{"tag":"v1.0"}')
    Path("CHANGELOG.md").write_text(
        "## v1.1 (2026-09-27)\n\n### Fix\n\n- **package**: improve release drafting\n\n"
        "## v1.0 (2026-09-20)\n\n- initial commit\n"
    )
    archive = Path("dxvk-sarek-1.13.0-gk3hd.1.dll")
    archive.write_bytes(b"verified local DLL fixture")
    companions = (archive.with_suffix(".json"), archive.with_suffix(".txt"))
    for companion in companions:
        companion.write_bytes(b"verified companion fixture")
    asset = RendererAsset(
        archive,
        "1.13.0-gk3hd.1",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive.stat().st_size,
        tuple((path, hashlib.sha256(path.read_bytes()).hexdigest()) for path in companions),
    )
    renderer_lock.write_text(json.dumps(asset.lock("v1.0")))
    monkeypatch.setattr(package, "_LOCK", texture_lock)
    monkeypatch.setattr(package, "_RENDERER_LOCK", renderer_lock)
    events: list[tuple[str, ...]] = []

    def run(*arguments: str, capture: bool = False) -> str:
        del capture
        events.append(arguments)
        if arguments[:2] == ("git", "symbolic-ref"):
            return "main"
        if arguments[:3] == ("git", "diff", "--cached"):
            return "release metadata"
        if arguments[:2] == ("uv", "run") or arguments[:2] == ("git", "tag"):
            # Metadata must already be correct before checks and the immutable tag.
            assert json.loads(texture_lock.read_text())["tag"] == ("v1.1" if textures else "v1.0")
            renderer_url = json.loads(renderer_lock.read_text())["asset_url"]
            assert ("/v1.1/" in renderer_url) is renderer
        return ""

    def pack(version: str) -> tuple[Path, ...]:
        texture_lock.write_text(json.dumps({"tag": f"v{version}"}))
        return (Path("textures-part01.zip"), Path("textures-part02.zip"))

    texture_verify = Mock()
    renderer_verify = Mock()
    monkeypatch.setattr(package, "_run", run)
    monkeypatch.setattr(package, "_release_version", Mock(return_value="1.1"))
    monkeypatch.setattr(package, "_pack", pack)
    monkeypatch.setattr(package, "inspect_dll", Mock(return_value=asset))
    monkeypatch.setattr(package, "_verify_remote", texture_verify)
    monkeypatch.setattr(package, "_verify_renderer_remote", renderer_verify)

    assert (
        package._prepare(None, textures=textures, renderer=archive if renderer else None) == "v1.1"
    )
    assert (
        events.index(("uv", "run", "--no-sync", "poe", "lint"))
        < events.index(("uv", "run", "--no-sync", "poe", "test"))
        < events.index(("uv", "build"))
        < events.index(("git", "tag", "-a", "v1.1", "-m", "v1.1"))
    )
    create = next(event for event in events if event[:3] == ("gh", "release", "create"))
    assert "--draft" in create
    assert "--verify-tag" in create
    assert create[create.index("--notes") + 1] == (
        "## v1.1 (2026-09-27)\n\n### Fix\n\n- **package**: improve release drafting"
    )
    assert "--generate-notes" not in create
    assert not any(event[:3] == ("gh", "release", "edit") for event in events)
    uploads = [event for event in events if event[:3] == ("gh", "release", "upload")]
    expected = ("textures-part01.zip", "textures-part02.zip") if textures else ()
    if renderer:
        expected += tuple(str(path) for path in asset.uploads)
    assert uploads == (
        [("gh", "release", "upload", "v1.1", "--repo", "lsorber/gk3hd", *expected)]
        if expected
        else []
    )
    assert texture_verify.call_count == (1 if textures else 2)
    assert texture_verify.call_args.kwargs == {"allow_draft": textures}
    assert renderer_verify.call_count == (1 if renderer else 2)
    assert renderer_verify.call_args.kwargs == {"allow_draft": renderer}


def test_failed_renderer_preflight_never_changes_version_or_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    run = Mock(return_value="")
    bump = Mock()
    monkeypatch.setattr(package, "_run", run)
    monkeypatch.setattr(package, "_release_version", bump)
    monkeypatch.setattr(package, "inspect_dll", Mock(side_effect=ValueError("wrong renderer")))
    with pytest.raises(ValueError, match="wrong renderer"):
        package._prepare(None, textures=True, renderer=Path("unreviewed.dll"))
    bump.assert_not_called()
    assert not any(
        call.args[:2] in {("git", "tag"), ("git", "add"), ("git", "push")}
        for call in run.call_args_list
    )


def _local_release_command(
    events: list[tuple[str, ...]], failure: str, *arguments: str, capture: bool = False
) -> str:
    del capture
    events.append(arguments)
    if arguments[0] == "uv":
        if arguments[1] == "run" and "--no-sync" not in arguments:
            msg = "gk3hd.exe is locked"
            raise RuntimeError(msg)
        if failure == "interrupt":
            raise KeyboardInterrupt
        if arguments[1] == failure or (arguments[1] == "run" and arguments[-1] == failure):
            msg = "local preparation failed"
            raise RuntimeError(msg)
    return "main" if arguments[:2] == ("git", "symbolic-ref") else ""


@pytest.mark.parametrize("existing_changelog", [False, True])
@pytest.mark.parametrize("failure", ["bump", "pack", "lock", "lint", "test", "build", "interrupt"])
def test_failed_local_preparation_restores_metadata_without_committing_or_tagging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, existing_changelog: bool, failure: str
) -> None:
    monkeypatch.chdir(tmp_path)
    texture_lock = Path("texture-lock.json")
    renderer_lock = Path("renderer-lock.json")
    monkeypatch.setattr(package, "_LOCK", texture_lock)
    monkeypatch.setattr(package, "_RENDERER_LOCK", renderer_lock)
    original = {
        Path("pyproject.toml"): b'[project]\r\nversion = "1.0.0"\r\n',
        Path("uv.lock"): b"original lock\r\n",
        texture_lock: b'{"tag":"v1.0.0"}\r\n',
        renderer_lock: b'{"tag":"v1.0.0"}\r\n',
    }
    if existing_changelog:
        original[Path("CHANGELOG.md")] = b"original changelog\r\n"
    for path, content in original.items():
        path.write_bytes(content)
    unrelated = Path("notes.txt")
    unrelated.write_bytes(b"keep these notes")
    events: list[tuple[str, ...]] = []

    def fail() -> None:
        msg = "local preparation failed"
        raise RuntimeError(msg)

    def bump(_version: str | None) -> str:
        Path("pyproject.toml").write_bytes(b"updated project")
        Path("uv.lock").write_bytes(b"updated lock")
        Path("CHANGELOG.md").write_bytes(b"updated changelog")
        if failure == "bump":
            fail()
        return "1.1.0"

    def pack(_version: str) -> tuple[Path, ...]:
        texture_lock.write_bytes(b"updated textures")
        if failure == "pack":
            fail()
        return ()

    monkeypatch.setattr(package, "_run", partial(_local_release_command, events, failure))
    monkeypatch.setattr(package, "_release_version", bump)
    monkeypatch.setattr(package, "_pack", pack)
    monkeypatch.setattr(package, "_verify_renderer_remote", Mock())
    asset = Mock(spec=RendererAsset)
    asset.lock.return_value = {"tag": "v1.1.0"}
    asset.uploads = ()
    monkeypatch.setattr(package, "inspect_dll", Mock(return_value=asset))
    error = KeyboardInterrupt if failure == "interrupt" else RuntimeError
    with pytest.raises(error):
        package._prepare(None, textures=True, renderer=Path("renderer.dll"))
    for path, content in original.items():
        assert path.read_bytes() == content
    assert Path("CHANGELOG.md").exists() is existing_changelog
    assert unrelated.read_bytes() == b"keep these notes"
    assert not any(
        event[:2] in {("git", "add"), ("git", "commit"), ("git", "tag"), ("git", "push")}
        for event in events
    )


def test_release_cli_reports_invalid_zip_without_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(package, "_prepare", Mock(side_effect=zipfile.BadZipFile("bad ZIP")))
    result = CliRunner().invoke(package.app, ["draft", "--dll", "renderer.dll"])
    assert result.exit_code == 1
    assert "Error: bad ZIP" in result.output
    assert "Traceback" not in result.output


def test_publish_gate_checks_both_asset_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "lock.json"
    lock.write_text("{}")
    monkeypatch.setattr(package, "_LOCK", lock)
    monkeypatch.setattr(package, "_RENDERER_LOCK", lock)
    textures = Mock()
    renderer = Mock(side_effect=ValueError("renderer missing"))
    monkeypatch.setattr(package, "_verify_remote", textures)
    monkeypatch.setattr(package, "_verify_renderer_remote", renderer)
    result = CliRunner().invoke(package.app, ["verify"])
    assert result.exit_code == 1
    assert "renderer missing" in result.output
    textures.assert_called_once_with({})
    renderer.assert_called_once_with({})


@pytest.mark.parametrize("family", ["textures", "renderer"])
@pytest.mark.parametrize("draft", [False, True])
@pytest.mark.parametrize("allow_draft", [False, True])
def test_release_verification_handles_private_drafts_but_publication_rejects_them(
    monkeypatch: pytest.MonkeyPatch, *, family: str, draft: bool, allow_draft: bool
) -> None:
    tag = "v1.1.0"
    digest = "a" * 64
    filename = (
        "dxvk-sarek-1.13.0-gk3hd.1.dll" if family == "renderer" else "gk3hd-texture-pack-v1.1.0.zip"
    )
    names = (
        [filename, filename[:-4] + ".json", filename[:-4] + ".txt"]
        if family == "renderer"
        else [filename]
    )
    release = {
        "tagName": tag,
        "isDraft": draft,
        "assets": [
            {"name": name, "digest": "sha256:" + digest, "size": 123, "state": "uploaded"}
            for name in names
        ],
    }

    def run(*arguments: str, capture: bool = False) -> str:
        del capture
        if draft and arguments[:2] == ("gh", "api"):
            msg = "tag API cannot find private draft (HTTP 404)"
            raise RuntimeError(msg)
        return json.dumps(release)

    monkeypatch.setattr(package, "_run", run)
    if family == "renderer":
        lock = {
            "asset_url": f"https://github.com/lsorber/gk3hd/releases/download/{tag}/{filename}",
            "dll_sha256": digest,
            "dll_size": "123",
        }
        verify = package._verify_renderer_remote
    else:
        lock = {"tag": tag, "archives": [{"filename": filename, "sha256": digest, "size": 123}]}
        verify = package._verify_remote
    if draft and not allow_draft:
        with pytest.raises(ValueError, match="private draft"):
            verify(lock, allow_draft=allow_draft)
    else:
        verify(lock, allow_draft=allow_draft)


@pytest.mark.parametrize("inventory", [None, [], {}, {"isDraft": "false"}])
def test_release_verification_rejects_unknown_publication_state(
    monkeypatch: pytest.MonkeyPatch, inventory: object
) -> None:
    monkeypatch.setattr(package, "_run", Mock(return_value=json.dumps(inventory)))
    with pytest.raises(TypeError, match="invalid release inventory"):
        package._release_inventory("lsorber/gk3hd", "v1.1.0")


def test_release_notes_preserve_selected_changelog_entry_without_other_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    expected = (
        "## v1.1.0 (2026-09-27)\n\n### Fix\n\n"
        "- **package**: make release drafting reliable on Windows"
    )
    Path("CHANGELOG.md").write_text(
        "# Changelog\n\n## v1.10.0 (2027-01-01)\n\n- newer version\n\n"
        + expected
        + "\n\n## v1.0.0 (2026-09-20)\n\n- older version\n",
        encoding="utf-8",
    )
    assert package._release_notes("1.1.0") == expected
    with pytest.raises(ValueError, match=r"no release notes for v1\.1$"):
        package._release_notes("1.1")
