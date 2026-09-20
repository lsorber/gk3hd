"""Root commands and the public Typer application."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves command annotations at runtime.
from typing import Annotated

import typer
from rich.table import Table

import gk3hd.install as installation
import gk3hd.textures.install.service as texture_install
from gk3hd import __version__
from gk3hd.cli.common import (
    CLI_ERRORS,
    ExeOption,
    ForceOption,
    GameDirOption,
    _print_error,
    _resolution,
    _texture_install_progress,
    console,
)
from gk3hd.cli.patch import app as patch_app
from gk3hd.cli.textures import app as textures_app
from gk3hd.package import app as package_app
from gk3hd.patch.builds import ProfileError, profile_for_sha256
from gk3hd.patch.install.windows import local_graphics_proxy_dlls
from gk3hd.patch.service import PatchRequest, PatchService
from gk3hd.renderer.cli import app as renderer_app
from gk3hd.renderer.service import RendererService
from gk3hd.renderer.state import STATE_FILENAME as RENDERER_STATE_FILENAME
from gk3hd.system.discovery import discover_game
from gk3hd.system.display import current_display_mode
from gk3hd.system.files import sha256_file
from gk3hd.textures.install.service import STATE_FILENAME, TextureInstallRequest

app = typer.Typer(
    name="gk3hd",
    help="Modern widescreen patches and high-resolution textures for Gabriel Knight 3.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(patch_app, name="patch")
app.add_typer(textures_app, name="textures")
app.add_typer(renderer_app, name="renderer")
app.add_typer(package_app, name="package")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"gk3hd {__version__}")
        raise typer.Exit


@app.callback()
def root(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_callback, is_eager=True),
    ] = None,
) -> None:
    """Select a component command or install the complete modernization."""
    del version


@app.command()
def install(
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    texture_pack: Annotated[
        Path | None,
        typer.Option(
            help="Use a local pack name, ZIP part, or generated lock instead of downloading."
        ),
    ] = None,
    resolution: Annotated[
        str | None,
        typer.Option(help="Display mode as WIDTHxHEIGHT; defaults to the active display."),
    ] = None,
    group: Annotated[str, typer.Option(help="Patch group to install.")] = "recommended",
    cache_dir: Annotated[
        Path | None, typer.Option(help="Downloaded-asset cache directory.")
    ] = None,
    force: ForceOption = False,
    offline: Annotated[
        bool,
        typer.Option("--offline", help="Use only already verified texture assets from the cache."),
    ] = False,
) -> None:
    """Install recommended patches, the D7VK renderer and high-resolution textures."""
    try:
        with _texture_install_progress() as (progress, callback):
            task = progress.add_task(
                "Installing patches, renderer and textures",
                total=None,
                unit="items",
            )
            report = installation.install(
                PatchRequest(
                    game_dir=game_dir,
                    exe=exe,
                    group=group,
                    resolution=_resolution(resolution),
                ),
                TextureInstallRequest(
                    game_dir=game_dir,
                    exe=exe,
                    pack=texture_pack,
                    cache_dir=cache_dir,
                    force=force,
                    offline=offline,
                ),
                progress=lambda event: callback(task, event),
            )
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    verb = "Installed gk3hd" if report.changed else "gk3hd was already installed"
    console.print(f"[bold green]{verb}[/] - {report.patches} patches, {report.textures} textures")


@app.command()
def uninstall(
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    force: ForceOption = False,
) -> None:
    """Remove all verified gk3hd changes and restore prior state."""
    try:
        target = discover_game(game_dir=game_dir, exe=exe)
        installation.recover(exe=target.exe)
        texture_state = target.game_dir / STATE_FILENAME
        if texture_state.is_file():
            texture_install.uninstall(exe=target.exe, force=force)
        patch_status = PatchService.status(exe=target.exe)
        if patch_status.installed:
            PatchService().uninstall(exe=target.exe, force=force)
        RendererService().uninstall(exe=target.exe)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print("[bold green]Removed every managed gk3hd change.[/]")


@app.command()
def status(game_dir: GameDirOption = None, exe: ExeOption = None) -> None:
    """Show a fast summary of the resolved game and managed component state."""
    try:
        patch_status = PatchService.status(game_dir=game_dir, exe=exe)
        target = patch_status.target
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    table = Table(title="gk3hd status", show_header=False)
    table.add_column("Component", style="cyan")
    table.add_column("State")
    table.add_row("Game", target.game_dir.name)
    table.add_row("Patches", "installed" if patch_status.installed else "not installed")
    table.add_row(
        "Renderer",
        "installed" if (target.game_dir / RENDERER_STATE_FILENAME).is_file() else "not installed",
    )
    table.add_row(
        "Textures",
        "installed" if (target.game_dir / STATE_FILENAME).is_file() else "not installed",
    )
    console.print(table)


@app.command()
def verify(game_dir: GameDirOption = None, exe: ExeOption = None) -> None:
    """Verify all three installed components without upgrading them."""
    try:
        target = discover_game(game_dir=game_dir, exe=exe)
        PatchService().verify(exe=target.exe)
        RendererService().verify(exe=target.exe)
        texture_install.verify(exe=target.exe)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print("[green]Patches, renderer and textures verified.[/]")


@app.command()
def doctor(game_dir: GameDirOption = None, exe: ExeOption = None) -> None:
    """Perform read-only target, build, data, INI, display, and proxy checks."""
    try:
        target = discover_game(game_dir=game_dir, exe=exe)
        digest = sha256_file(target.exe)
        try:
            build = profile_for_sha256(digest).label
        except ProfileError:
            build = "patched or unsupported"
        display = current_display_mode()
        proxies = local_graphics_proxy_dlls(target.game_dir, allow_owned_d7vk=True)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    table = Table(title="gk3hd doctor")
    table.add_column("Check")
    table.add_column("Result")
    table.add_row("Executable", target.exe.name)
    table.add_row("Build", build)
    table.add_row("Data", "found" if target.data_dir.is_dir() else "missing")
    table.add_row("INI", target.ini.name if target.ini is not None else "will create GK3.ini")
    table.add_row("Display", f"{display.width}x{display.height} @ {display.refresh_hz} Hz")
    table.add_row("Graphics proxies", ", ".join(proxies) if proxies else "none")
    console.print(table)
