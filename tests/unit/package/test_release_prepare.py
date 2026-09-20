"""Release preparation orders local checks, tag creation and draft uploads safely."""

from __future__ import annotations

import hashlib
import json
import zipfile
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
    archive = Path("d7vk-2.2-gk3hd.3.dll")
    archive.write_bytes(b"verified local DLL fixture")
    companions = (archive.with_suffix(".json"), archive.with_suffix(".txt"))
    for companion in companions:
        companion.write_bytes(b"verified companion fixture")
    asset = RendererAsset(
        archive,
        "2.2-gk3hd.3",
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
        events.index(("uv", "run", "--locked", "poe", "lint"))
        < events.index(("uv", "run", "--locked", "poe", "test"))
        < events.index(("uv", "build"))
        < events.index(("git", "tag", "-a", "v1.1", "-m", "v1.1"))
    )
    create = next(event for event in events if event[:3] == ("gh", "release", "create"))
    assert "--draft" in create
    assert "--verify-tag" in create
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
