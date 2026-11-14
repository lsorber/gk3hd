"""Install, launch and maintain the opt-in PC VR player."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves option annotations at runtime.
from typing import Annotated

import typer
from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from gk3hd.cli.common import CLI_ERRORS, GameDirOption, _print_error, console
from gk3hd.vr import build as builder
from gk3hd.vr import distribution, shortcut
from gk3hd.vr import launch as launcher
from gk3hd.vr.process import PointingHand
from gk3hd.vr.service import VRService
from gk3hd.vr.standalone.cli import app as standalone_app
from gk3hd.vr.status import TrackingStatus

app = typer.Typer(
    no_args_is_help=True,
    help="Experimental PC and standalone VR. Not yet qualified for headset play.",
)
app.add_typer(standalone_app, name="standalone")


@app.command()
def build(
    game_dir: GameDirOption = None,
    *,
    output: Annotated[
        Path | None, typer.Option(help="Override <GAME>/gk3hd/vr/renderer/ build output.")
    ] = None,
    jobs: Annotated[int, typer.Option(min=1, max=64, help="Parallel native build jobs.")] = 12,
) -> None:
    """Build/test the pinned OpenXR renderer; do not install or launch it."""
    try:
        asset = builder.build(game_dir=game_dir, output=output, jobs=jobs)
        console.print(f"Verified VR prototype: {asset.path}")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def install(
    game_dir: GameDirOption = None,
    *,
    local: Annotated[
        bool, typer.Option(help="Use the last local renderer build instead of downloading.")
    ] = False,
    dll: Annotated[
        Path | None,
        typer.Option(help="Override the prebuilt or local verified VR renderer."),
    ] = None,
    units_per_meter: Annotated[
        float | None,
        typer.Option(
            help="Override world scale; updates preserve it. New installs use 1 unit = 1 inch.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Install an isolated GK3-VR.exe and private renderer; preserve flat play."""
    published = dll is None and not local
    try:
        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Finding compatible VR components", total=None)
            if published:
                components = distribution.components(
                    kind=distribution.AssetKind.RENDERER,
                    progress=lambda done, total: progress.update(
                        task, description="Downloading VR renderer", total=total, completed=done
                    ),
                )
                dll = distribution.renderer_path(components)
            progress.reset(
                task, description="Compiling and verifying isolated VR player", total=None
            )
            VRService().install(game_dir=game_dir, dll=dll, units_per_meter=units_per_meter)
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error
    linked = False
    try:
        linked = shortcut.install(game_dir)
    except CLI_ERRORS as error:
        console.print(f"[yellow]{escape(str(error))}[/]")
    command = "uvx gk3hd@latest" if published else "gk3hd"
    launch_hint = "Open GK3HD VR from Start." if linked else f"Run {command} vr launch."
    console.print(f"[green]VR player installed and verified.[/] {launch_hint}")


@app.command()
def verify(game_dir: GameDirOption = None) -> None:
    """Verify owned files, renderer provenance and independently rebuilt player."""
    try:
        VRService().verify(game_dir=game_dir)
        console.print("[green]PC VR files verified.[/]")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def launch(
    game_dir: GameDirOption = None,
    *,
    runtime: Annotated[
        Path | None, typer.Option(help="Override the discovered 32-bit OpenXR runtime manifest.")
    ] = None,
    hand: Annotated[
        PointingHand,
        typer.Option(
            help="Preferred pointing controller; the other takes over if tracking is lost."
        ),
    ] = PointingHand.RIGHT,
    start_menu: Annotated[bool, typer.Option(hidden=True)] = False,
) -> None:
    """Launch verified VR with child-only settings; supervise it until exit."""
    try:
        launcher.launch(
            game_dir=game_dir,
            runtime_manifest=runtime,
            pointing_hand=hand,
            on_tracking=_tracking_feedback,
        )
    except CLI_ERRORS as error:
        _print_error(error)
        if start_menu:
            shortcut.show_launch_error(str(error))
        raise typer.Exit(1) from error


def _tracking_feedback(tracked: TrackingStatus) -> None:
    if tracked is TrackingStatus.AVAILABLE:
        console.print(
            "[green]Headset tracking available.[/] Release held controls before interacting."
        )
    else:
        console.print(
            "[yellow]Headset tracking unavailable.[/] Check that the headset is awake "
            "and can track its surroundings. VR controller input is paused."
        )


@app.command()
def uninstall(game_dir: GameDirOption = None) -> None:
    """Remove unchanged owned VR files; preserve flat play and externally edited files."""
    try:
        game = VRService().uninstall(game_dir=game_dir)
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error
    try:
        shortcut.uninstall(game)
    except CLI_ERRORS as error:
        console.print(f"[yellow]{escape(str(error))}[/]")
    console.print("[green]Owned VR player files removed.[/] Local builds and logs are retained.")
