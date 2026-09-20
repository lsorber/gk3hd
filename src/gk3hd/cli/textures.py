"""Typer commands for texture analysis, generation and installation."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves command annotations at runtime.
from typing import Annotated

import typer
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

import gk3hd.textures.analyze.manifest as texture_analyze
import gk3hd.textures.extraction as texture_extract
import gk3hd.textures.install.service as texture_install
import gk3hd.textures.pack.build as texture_pack
import gk3hd.textures.upscale.service as texture_upscale
from gk3hd import __version__
from gk3hd.cli.common import (
    CLI_ERRORS,
    ExeOption,
    ForceOption,
    GameDirOption,
    _print_error,
    _texture_install_progress,
    _texture_stage,
    _UnitProgressColumn,
    _upscale_import_error,
    console,
)
from gk3hd.system.discovery import discover_game
from gk3hd.textures.install.service import TextureInstallRequest
from gk3hd.textures.review import review
from gk3hd.textures.upscale.service import UpscaleOptions, UpscaleProgress
from gk3hd.textures.workspace import (
    PACK_LOCK_FILENAME,
    SOURCE_DIRECTORY,
    UPSCALE_DIRECTORY,
    adjacent_stage,
    analysis_file,
    texture_pack_filename,
    texture_workspace_directory,
)

app = typer.Typer(help="Extract, upscale, package, install, or remove textures.")
app.command("review")(review)


@app.command("extract")
def textures_extract(
    output: Annotated[
        Path | None,
        typer.Argument(help="Output directory; defaults to GAME/gk3hd/textures/original."),
    ] = None,
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace existing BMP outputs."),
    ] = False,
) -> None:
    """Extract and normalize BMP textures from GK3's BRN archives."""
    try:
        target = discover_game(game_dir=game_dir, exe=exe)
        destination = (
            output.expanduser().resolve()
            if output is not None
            else texture_workspace_directory(target.game_dir) / SOURCE_DIRECTORY
        )
        with Progress(
            SpinnerColumn("line"), TextColumn("{task.description}"), BarColumn(), console=console
        ) as progress:
            task = progress.add_task("Extracting BRN textures", total=None)
            report = texture_extract.extract(
                destination,
                exe=target.exe,
                overwrite=overwrite,
                progress=lambda completed, total: progress.update(
                    task, completed=completed, total=total
                ),
            )
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print(
        f"[bold green]Extracted[/] {report.extracted} textures "
        f"({report.converted_proprietary} converted, {report.skipped} skipped)"
    )
    console.print("[dim]Texture folder:[/]", destination)


@app.command("analyze")
def textures_analyze(
    source: Annotated[
        Path | None,
        typer.Argument(help="BMP directory; defaults to GAME/gk3hd/textures/original."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(help="Manifest path; defaults inside the texture folder."),
    ] = None,
    overrides: Annotated[
        Path | None,
        typer.Option(help="Complete replacement texture policy (features and pipelines)."),
    ] = None,
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
) -> None:
    """Analyze BMP semantics and select the correct pipeline for each texture."""
    try:
        source_path = _texture_stage(
            source,
            SOURCE_DIRECTORY,
            game_dir=game_dir,
            exe=exe,
        )
        manifest_path = analysis_file(source_path, output)
        with Progress(
            SpinnerColumn("line"), TextColumn("{task.description}"), BarColumn(), console=console
        ) as progress:
            task = progress.add_task("Analyzing textures", total=None)
            report = texture_analyze.analyze(
                source_path,
                manifest_path,
                overrides=overrides,
                data_directory=(
                    discover_game(game_dir=game_dir, exe=exe).data_dir
                    if game_dir is not None or exe is not None
                    else None
                ),
                progress=lambda completed, total: progress.update(
                    task, completed=completed, total=total
                ),
            )
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    methods = report.pipelines
    texture_count = len(report.manifest.textures)
    texture_label = "texture" if texture_count == 1 else "textures"
    console.print(
        f"[bold green]Analyzed {texture_count:,} {texture_label}[/]: "
        + ", ".join(f"{count:,} {method.value}" for method, count in methods.items() if count)
        + (f"; {len(report.todos):,} texture todos" if report.todos else "")
    )
    console.print("[dim]Analysis file:[/]", manifest_path)


@app.command("upscale")
def textures_upscale(
    source: Annotated[
        Path | None,
        typer.Argument(help="BMP directory; defaults to GAME/gk3hd/textures/original."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Argument(help="PNG directory; defaults to GAME/gk3hd/textures/upscaled."),
    ] = None,
    features: Annotated[Path | None, typer.Option(help="Existing feature manifest.")] = None,
    fonts: Annotated[
        Path | None,
        typer.Option(help="Font directory for verified partial outline reconstruction."),
    ] = None,
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            help="Replace existing outputs instead of safely resuming.",
        ),
    ] = False,
    device: Annotated[
        str,
        typer.Option(help="Compute device: auto, cuda, cpu, or a specific device such as cuda:1."),
    ] = "auto",
) -> None:
    """Apply the property-aware 4x pipeline and write release-ready PNGs."""
    try:
        source_path = _texture_stage(
            source,
            SOURCE_DIRECTORY,
            game_dir=game_dir,
            exe=exe,
        )
        output_path = (
            output.expanduser().resolve()
            if output is not None
            else adjacent_stage(source_path, UPSCALE_DIRECTORY)
        )
        manifest_path = analysis_file(source_path, features)
        generated_analysis = features is None and not manifest_path.is_file()
        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            _UnitProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Upscaling textures", total=None, unit="textures")

            def update(completed: int, total: int) -> None:
                progress.update(
                    task,
                    description="Upscaling textures",
                    completed=completed,
                    total=total,
                    unit="textures",
                )

            def update_download(filename: str, completed: int, total: int | None) -> None:
                progress.update(
                    task,
                    description=f"Downloading {filename}",
                    completed=completed,
                    total=total,
                    unit="bytes",
                )

            def show_backend(description: str, is_cpu: bool) -> None:
                style = "yellow" if is_cpu else "green"
                suffix = " (slow fallback)" if is_cpu else ""
                progress.console.print(f"[dim]AI device:[/] [{style}]{description}{suffix}[/]")

            report = texture_upscale.upscale(
                source_path,
                output_path,
                options=UpscaleOptions(
                    features=features,
                    overwrite=overwrite,
                    device=device,
                    fonts=fonts,
                ),
                progress=UpscaleProgress(
                    textures=update,
                    downloads=update_download,
                    backend=show_backend,
                ),
            )
    except ImportError as exc:
        _print_error(_upscale_import_error(exc))
        raise typer.Exit(1) from exc
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print(
        f"[bold green]Upscale complete[/] - {report.created} created, "
        f"{report.skipped} resumed, {report.excluded} semantic assets left untouched "
        f"({report.textures} total)"
    )
    if generated_analysis:
        console.print("[dim]Created analysis:[/]", manifest_path)
    if report.font_outlined_glyphs or report.font_retained_glyphs:
        console.print(
            f"[dim]Supplied-font coverage:[/] {report.font_outlined_glyphs:,} reconstructed, "
            f"{report.font_retained_glyphs:,} cells preserve original artwork"
        )
    console.print("[dim]PNG folder:[/]", output_path)


@app.command("pack")
def textures_pack(
    source: Annotated[
        Path | None,
        typer.Argument(help="PNG directory; defaults to GAME/gk3hd/textures/upscaled."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Pack base ZIP; defaults to "
                f"GAME/gk3hd/textures/{texture_pack_filename(__version__)}."
            )
        ),
    ] = None,
    features: Annotated[
        Path | None,
        typer.Option(help="Texture analysis; defaults beside the PNG folder."),
    ] = None,
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
) -> None:
    """Build a deterministic versioned texture pack and source lock."""
    try:
        source_path = _texture_stage(
            source,
            UPSCALE_DIRECTORY,
            game_dir=game_dir,
            exe=exe,
        )
        output_path = (
            output.expanduser().resolve()
            if output is not None
            else adjacent_stage(source_path, texture_pack_filename(__version__))
        )
        with console.status("[bold cyan]Building deterministic texture pack...", spinner="line"):
            report = texture_pack.pack(
                source_path,
                output_path,
                version=__version__,
                features=features,
            )
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    part_label = "archive" if len(report.archives) == 1 else "archive parts"
    console.print(
        f"[bold green]Built[/] {report.textures} textures in {len(report.archives)} {part_label}"
    )
    for archive in report.archives:
        console.print(f"[dim]Pack part:[/] {archive}")
    console.print(f"[dim]Generated lock:[/] {report.lock}")
    console.print(
        f"Commit {PACK_LOCK_FILENAME}, create/push v{__version__}, and upload every pack part."
    )


@app.command("install")
def textures_install(
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    local: Annotated[
        bool,
        typer.Option(
            "--local",
            help="Use the pack in the current directory or the game texture workspace.",
        ),
    ] = False,
    pack: Annotated[
        Path | None,
        typer.Option(help="Local pack name, ZIP part, directory, or generated lock."),
    ] = None,
    cache_dir: Annotated[
        Path | None, typer.Option(help="Downloaded-asset cache directory.")
    ] = None,
    force: ForceOption = False,
    offline: Annotated[
        bool,
        typer.Option("--offline", help="Use only already verified release assets from the cache."),
    ] = False,
) -> None:
    """Download or read a texture pack, convert it to BMP, and install it."""
    try:
        with _texture_install_progress() as (progress, callback):
            task = progress.add_task("Preparing texture pack", total=None, unit="items")
            report = texture_install.install(
                TextureInstallRequest(
                    game_dir=game_dir,
                    exe=exe,
                    pack=pack,
                    local=local,
                    cache_dir=cache_dir,
                    force=force,
                    offline=offline,
                ),
                progress=lambda event: callback(task, event),
            )
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print(
        f"[bold green]Installed[/] {report.textures} textures under gk3hd/textures/installed/"
    )


@app.command("verify")
def textures_verify(game_dir: GameDirOption = None, exe: ExeOption = None) -> None:
    """Hash-verify installed BMPs and the managed GK3 INI edit."""
    try:
        with console.status("[bold cyan]Verifying installed textures...", spinner="line"):
            report = texture_install.verify(game_dir=game_dir, exe=exe)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print(f"[bold green]Verified[/] {report.textures} installed textures")


@app.command("uninstall")
def textures_uninstall(
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    force: ForceOption = False,
) -> None:
    """Remove managed BMPs and restore the exact prior INI bytes."""
    try:
        texture_install.uninstall(game_dir=game_dir, exe=exe, force=force)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print("[bold green]Textures removed.[/]")
