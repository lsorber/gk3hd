"""Prepare a gk3hd package-version draft with pinned, optionally renewed assets."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console

import gk3hd.textures.pack.build as texture_pack
from gk3hd.renderer.artifact import inspect_dll, release_target
from gk3hd.renderer.artifact import validate_release_assets as validate_renderer_assets
from gk3hd.renderer.build import local_build
from gk3hd.system.discovery import discover_game
from gk3hd.system.files import atomic_write
from gk3hd.textures.pack.source import TexturePackSource
from gk3hd.textures.workspace import (
    UPSCALE_DIRECTORY,
    texture_pack_filename,
    texture_workspace_directory,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
    help="Prepare a gk3hd version for PyPI, optionally renewing its pinned assets.",
)
console = Console()
_REPOSITORY = "lsorber/gk3hd"
_LOCK = Path("src/gk3hd/assets/texture-pack-lock.json")
_RENDERER_LOCK = Path("src/gk3hd/assets/d7vk-lock.json")
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,2}")


def _run(*arguments: str, capture: bool = False) -> str:
    executable = shutil.which(arguments[0])
    if executable is None:
        msg = f"release preparation requires {arguments[0]} on PATH"
        raise RuntimeError(msg)
    result = subprocess.run(  # noqa: S603 - explicit argument lists, never shell strings.
        [executable, *arguments[1:]],
        check=False,
        text=True,
        capture_output=capture,
    )
    if result.returncode:
        msg = (
            f"{arguments[0]} {arguments[1]} failed; correct the reported problem before continuing"
        )
        if capture:
            msg += ": " + (result.stderr or result.stdout).strip()
        raise RuntimeError(msg)
    return result.stdout.strip() if capture else ""


def validate_release_assets(lock: object, release: object) -> None:
    """Match every pinned asset against GitHub's upload-computed digest and size."""
    source = TexturePackSource.from_lock(lock)
    if not source.assets:
        msg = "texture lock is empty; prepare the first release with --textures"
        raise ValueError(msg)
    if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
        msg = "GitHub returned an invalid release asset inventory"
        raise TypeError(msg)
    if not isinstance(lock, dict) or release.get("tag_name") != lock.get("tag"):
        msg = "GitHub release does not match the pinned texture tag"
        raise ValueError(msg)
    for expected in source.assets:
        name = (expected.archive_url or "").rsplit("/", maxsplit=1)[-1]
        matches = [
            asset
            for asset in release["assets"]
            if isinstance(asset, dict) and asset.get("name") == name
        ]
        if len(matches) != 1:
            msg = f"release asset {name} is missing or duplicated"
            raise ValueError(msg)
        asset = matches[0]
        if asset.get("state") != "uploaded" or (asset.get("size"), asset.get("digest")) != (
            expected.archive_size,
            "sha256:" + str(expected.archive_sha256),
        ):
            msg = f"release asset {name} is incomplete or differs from its pinned size/SHA-256"
            raise ValueError(msg)


def _release_inventory(repository: str, tag: str) -> dict[str, object]:
    """Read published or private draft assets through authenticated GitHub CLI."""
    release = json.loads(
        _run(
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "tagName,isDraft,assets",
            capture=True,
        )
    )
    if not isinstance(release, dict) or not isinstance(release.get("isDraft"), bool):
        msg = "GitHub returned an invalid release inventory"
        raise TypeError(msg)
    # Unlike the public tag API, gh release view also resolves private drafts.
    return {
        "tag_name": release.get("tagName"),
        "draft": release["isDraft"],
        "assets": release.get("assets"),
    }


def _verify_remote(lock: object, *, allow_draft: bool = False) -> None:
    if not isinstance(lock, dict) or not isinstance(lock.get("tag"), str):
        msg = "release preparation requires a tag-based texture lock; use --textures"
        raise TypeError(msg)
    # Validate before interpolating the tag into an API path.
    TexturePackSource.from_lock(lock)
    release = _release_inventory(_REPOSITORY, lock["tag"])
    validate_release_assets(lock, release)
    if release.get("draft") and not allow_draft:
        msg = "pinned textures are still private draft assets; publish their release first"
        raise ValueError(msg)


def _verify_renderer_remote(lock: object, *, allow_draft: bool = False) -> None:
    repository, tag, _ = release_target(lock)
    release = _release_inventory(repository, tag)
    validate_renderer_assets(lock, release)
    if release.get("draft") and not allow_draft:
        msg = "pinned renderer is still a private draft asset; publish its release first"
        raise ValueError(msg)


@app.command("verify")
def verify_assets() -> None:
    """Refuse PyPI publication unless the pinned renderer and textures are available."""
    try:
        _verify_remote(json.loads(_LOCK.read_text(encoding="utf-8")))
        _verify_renderer_remote(json.loads(_RENDERER_LOCK.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print("[green]All pinned renderer and texture assets match GitHub.[/]")


def _release_version(version: str | None) -> str:
    current = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    tags = _run("git", "tag", "--list", capture=True).splitlines()
    selected = version
    if selected is None:
        selected = (
            _run("cz", "bump", "--get-next", "--yes", capture=True)
            if f"v{current}" in tags
            else current
        )
    if not isinstance(selected, str) or _VERSION.fullmatch(selected) is None:
        msg = "expected a stable numeric release version, for example 1.0 or 1.1.0"
        raise ValueError(msg)
    if f"v{selected}" in tags:
        msg = f"tag v{selected} already exists; release tags are never overwritten"
        raise ValueError(msg)
    if selected != current:
        _run("cz", "bump", "--version-files-only", "--yes", selected)
    return selected


def _pack(version: str) -> tuple[Path, ...]:
    workspace = texture_workspace_directory(discover_game().game_dir)
    report = texture_pack.pack(
        workspace / UPSCALE_DIRECTORY,
        workspace / texture_pack_filename(version),
        version=version,
    )
    atomic_write(_LOCK, report.lock.read_bytes())
    return report.archives


@contextmanager
def _restore_metadata_on_error(paths: tuple[Path, ...]) -> Iterator[None]:
    """Undo local preparation on failure, before any release commit or tag exists."""
    original = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        yield
    except BaseException:
        for path, content in original.items():
            if content is None:
                path.unlink(missing_ok=True)
            elif not path.exists() or path.read_bytes() != content:
                atomic_write(path, content)
        console.print(
            "[yellow]Local release metadata restored; no release commit or tag created.[/]"
        )
        raise


def _release_notes(version: str) -> str:
    """Use only the selected version's conventional-commit changelog entry."""
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    entry = re.search(rf"(?ms)^## v{re.escape(version)}(?:[ \t][^\n]*)?\n.*?(?=^## |\Z)", changelog)
    if entry is None:
        msg = f"CHANGELOG.md has no release notes for v{version}"
        raise ValueError(msg)
    return entry[0].strip()


def _prepare(version: str | None, *, textures: bool, renderer: Path | None = None) -> str:
    if _run("git", "status", "--porcelain", capture=True):
        msg = "commit your work first: release preparation requires a clean worktree"
        raise ValueError(msg)
    branch = _run("git", "symbolic-ref", "--short", "HEAD", capture=True)
    _run("gh", "auth", "status", capture=True)
    # Validate an existing pack before changing the project version.
    if not textures:
        _verify_remote(json.loads(_LOCK.read_text(encoding="utf-8")))
    renderer_asset = inspect_dll(renderer) if renderer is not None else None
    if renderer_asset is None:
        _verify_renderer_remote(json.loads(_RENDERER_LOCK.read_text(encoding="utf-8")))
    paths = (Path("pyproject.toml"), Path("uv.lock"), _LOCK, _RENDERER_LOCK, Path("CHANGELOG.md"))
    with _restore_metadata_on_error(paths):
        selected = _release_version(version)
        archives = _pack(selected) if textures else ()
        if renderer_asset is not None:
            atomic_write(
                _RENDERER_LOCK,
                (json.dumps(renderer_asset.lock(f"v{selected}"), indent=2) + "\n").encode(),
            )
            archives += renderer_asset.uploads
        _run("uv", "lock")
        # Reuse the environment that launched us. Syncing after the version bump
        # would replace this running gk3hd.exe, which Windows keeps locked.
        _run("uv", "run", "--no-sync", "poe", "lint")
        _run("uv", "run", "--no-sync", "poe", "test")
        _run("uv", "build")
        if renderer_asset is not None:
            renderer_asset.verify_unchanged()
        notes = _release_notes(selected)
    _run("git", "add", "--", *(str(path) for path in paths if path.is_file()))
    if _run("git", "diff", "--cached", "--name-only", capture=True):
        _run("git", "commit", "-m", f"chore(release): v{selected}")
    tag = f"v{selected}"
    _run("git", "tag", "-a", tag, "-m", tag)
    _run("git", "push", "--atomic", "origin", branch, tag)
    _run(
        "gh",
        "release",
        "create",
        tag,
        "--repo",
        _REPOSITORY,
        "--draft",
        "--verify-tag",
        "--title",
        tag,
        "--notes",
        notes,
    )
    if archives:
        _run(
            "gh", "release", "upload", tag, "--repo", _REPOSITORY, *(str(path) for path in archives)
        )
    _verify_remote(json.loads(_LOCK.read_text(encoding="utf-8")), allow_draft=textures)
    _verify_renderer_remote(
        json.loads(_RENDERER_LOCK.read_text(encoding="utf-8")), allow_draft=renderer is not None
    )
    return tag


def _candidate(*, renderer: bool, dll: Path | None) -> Path | None:
    """Validate maintainer context and select an explicit or recorded build."""
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    if project.get("project", {}).get("name") != "gk3hd":
        msg = "run package draft from the gk3hd repository root"
        raise ValueError(msg)
    if renderer and dll is not None:
        msg = "choose --renderer or --dll, not both"
        raise ValueError(msg)
    return local_build().path if renderer else dll


@app.command("draft")
def prepare(
    version: Annotated[
        str | None, typer.Argument(help="Optional version; otherwise use conventional commits.")
    ] = None,
    *,
    textures: Annotated[bool, typer.Option(help="Build and attach a new texture pack.")] = False,
    renderer: Annotated[
        bool, typer.Option(help="Attach the last verified local renderer build.")
    ] = False,
    dll: Annotated[Path | None, typer.Option(help="Override the renderer build to attach.")] = None,
) -> None:
    """Check, commit, tag, push, and upload a gk3hd-version draft for review.

    Reuse published assets unless --textures or --renderer is supplied.
    Publishing the resulting GitHub draft triggers PyPI; this command does not.
    """
    try:
        candidate = _candidate(renderer=renderer, dll=dll)
        tag = _prepare(version, textures=textures, renderer=candidate)
    except (OSError, TypeError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(
        f"[green]Draft {tag} is ready.[/] Review it, then click Publish release on GitHub."
    )
