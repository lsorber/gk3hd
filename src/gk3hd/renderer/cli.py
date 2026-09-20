"""Public renderer operations with explicit build and install boundaries."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves option annotations at runtime.
from typing import Annotated

import typer
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TextColumn

from gk3hd.cli.common import CLI_ERRORS, ExeOption, GameDirOption, _print_error, console
from gk3hd.renderer import build as builder
from gk3hd.renderer.service import RendererService
from gk3hd.renderer.service import download as download_renderer

app = typer.Typer(no_args_is_help=True, help="Build, download and manage the D7VK renderer.")


@app.command()
def download() -> None:
    """Download the latest verified renderer into the cache; do not modify GK3."""
    try:
        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), DownloadColumn()
        ) as progress:
            task = progress.add_task("Downloading renderer", total=None)
            path = download_renderer(
                progress=lambda done, total: progress.update(task, completed=done, total=total)
            )
        console.print(f"Renderer DLL: {path}")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command()
def install(
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    *,
    local: Annotated[bool, typer.Option(help="Use the last verified local build.")] = False,
    dll: Annotated[Path | None, typer.Option(help="Use an explicit local x86 D7VK DLL.")] = None,
) -> None:
    """Install or replace the renderer, keeping its original uninstall baseline."""
    try:
        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), DownloadColumn()
        ) as progress:
            task = progress.add_task("Installing renderer", total=None)
            RendererService().install(
                game_dir=game_dir,
                exe=exe,
                local=local,
                dll=dll,
                progress=lambda done, total: progress.update(task, completed=done, total=total),
            )
        console.print("[green]Renderer installed and verified.[/]")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command()
def build(
    game_dir: GameDirOption = None,
    *,
    output: Annotated[
        Path | None,
        typer.Option(help="Override the build directory under <GAME>/gk3hd/renderer/."),
    ] = None,
    jobs: Annotated[int, typer.Option(min=1, max=64, help="Parallel native build jobs.")] = 12,
) -> None:
    """Build and test modified D7VK on Windows; reuse a verified matching build."""
    try:
        asset = builder.build(game_dir=game_dir, output=output, jobs=jobs)
        console.print(f"Verified renderer: {asset.path}")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command()
def verify(game_dir: GameDirOption = None, exe: ExeOption = None) -> None:
    """Verify installed renderer files and platform settings."""
    try:
        state = RendererService().verify(game_dir=game_dir, exe=exe)
        console.print(f"[green]Renderer verified[/] ({state.digest[:12]}).")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command()
def uninstall(game_dir: GameDirOption = None, exe: ExeOption = None) -> None:
    """Remove the renderer after removing executable patches; restore original settings."""
    try:
        RendererService().uninstall(game_dir=game_dir, exe=exe)
        console.print("[green]Renderer removed.[/]")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
