"""Explicit development-only VR commands, separate from ordinary installation."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves option annotations at runtime.
from typing import Annotated

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from gk3hd.cli.common import CLI_ERRORS, GameDirOption, _print_error, console
from gk3hd.vr import GAME_UNITS_PER_METER
from gk3hd.vr import build as builder
from gk3hd.vr import launch as launcher
from gk3hd.vr.process import PointingHand
from gk3hd.vr.service import VRService
from gk3hd.vr.status import TrackingStatus

app = typer.Typer(
    no_args_is_help=True,
    help="Development-only seated VR prototype. Not yet qualified for headset play.",
)


@app.callback()
def prototype() -> None:
    """Keep the unfinished prototype explicitly opt-in, not a flat-install feature."""
    console.print("[yellow]VR development prototype. Not ready for headset play.[/]")


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
    dll: Annotated[
        Path | None,
        typer.Option(help="Verified prototype DLL; defaults to the last local VR build."),
    ] = None,
    units_per_meter: Annotated[
        float,
        typer.Option(
            help="World scale override in game units per meter (default: 1 unit = 1 inch).",
            show_default=False,
        ),
    ] = GAME_UNITS_PER_METER,
) -> None:
    """Install an isolated GK3-VR.exe and private renderer; preserve flat play."""
    try:
        with Progress(
            SpinnerColumn("line"), TextColumn("{task.description}"), console=console
        ) as progress:
            progress.add_task("Compiling and verifying isolated VR player", total=None)
            VRService().install(game_dir=game_dir, dll=dll, units_per_meter=units_per_meter)
        console.print(
            "[green]VR prototype installed and verified.[/] Use gk3hd vr launch to start it."
        )
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def verify(game_dir: GameDirOption = None) -> None:
    """Verify owned files, renderer provenance and independently rebuilt player."""
    try:
        VRService().verify(game_dir=game_dir)
        console.print("[green]VR installation verified.[/] Headset acceptance remains unfinished.")
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
        VRService().uninstall(game_dir=game_dir)
        console.print(
            "[green]Owned VR player files removed.[/] Local builds and logs are retained."
        )
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error
