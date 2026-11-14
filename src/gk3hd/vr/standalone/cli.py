"""Build, pack and install the shared Android standalone VR player."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path  # noqa: TC003 - Typer resolves option annotations at runtime.
from typing import Annotated

import typer
from rich.filesize import decimal
from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from gk3hd.cli.common import CLI_ERRORS, GameDirOption, _print_error, console
from gk3hd.patch.model import ProfileId
from gk3hd.vr.standalone import build as builder
from gk3hd.vr.standalone import device as devices
from gk3hd.vr.standalone import install as installer
from gk3hd.vr.standalone import pack as packer
from gk3hd.vr.standalone import prepare as preparation
from gk3hd.vr.standalone import saves
from gk3hd.vr.standalone.paths import install_inputs, recorded_build, workspace

app = typer.Typer(
    no_args_is_help=True, help="Build, pack and install standalone VR for Android headsets."
)


@app.command()
def backup(
    output: Annotated[Path | None, typer.Argument(help="Save ZIP filename.")] = None,
    *,
    adb: Annotated[Path | None, typer.Option(help="ADB executable outside PATH.")] = None,
    device: Annotated[
        str | None, typer.Option(help="Headset serial when several are connected.")
    ] = None,
) -> None:
    """Back up saves from the headset to a ZIP over USB."""
    try:
        path, count = saves.backup(output, adb=adb, device=device)
        console.print(f"[green]Saved {count} game saves.[/] {escape(str(path))}")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def restore(
    backup_file: Annotated[Path, typer.Argument(help="ZIP created by standalone backup.")],
    *,
    adb: Annotated[Path | None, typer.Option(help="ADB executable outside PATH.")] = None,
    device: Annotated[
        str | None, typer.Option(help="Headset serial when several are connected.")
    ] = None,
) -> None:
    """Restore backed-up saves over USB, preserving existing saves."""
    try:
        count = saves.restore(backup_file, adb=adb, device=device)
        console.print(f"[green]Restored {count} missing game saves.[/]")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def launch(
    *,
    adb: Annotated[
        Path | None, typer.Option(help="Path to ADB if it isn't found automatically.")
    ] = None,
    device: Annotated[
        str | None, typer.Option(help="Headset serial when multiple devices are connected.")
    ] = None,
    experimental_compressed: Annotated[
        bool,
        typer.Option(
            "--experimental-compressed", help="Try compressed stereo for one standalone launch."
        ),
    ] = False,
    experimental_eye_copy: Annotated[
        bool, typer.Option(help="Try the faster eye copy for one Pimax launch.")
    ] = False,
    eye_resolution: Annotated[
        str | None,
        typer.Option(metavar="WIDTHxHEIGHT", help="Test a per-eye resolution for one launch."),
    ] = None,
) -> None:
    """Open the installed game; you can also use GK3HD VR in the headset library."""
    try:
        installer.launch(
            adb=adb,
            device=device,
            experimental_compressed=experimental_compressed,
            experimental_eye_copy=experimental_eye_copy,
            eye_resolution=eye_resolution,
        )
        console.print("[green]GK3HD VR launch requested.[/] Continue in the headset.")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def doctor(
    *,
    adb: Annotated[
        Path | None, typer.Option(help="Path to ADB if it isn't found automatically.")
    ] = None,
    device: Annotated[
        str | None, typer.Option(help="Headset serial when multiple devices are connected.")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Print the discovery report as JSON.")
    ] = False,
) -> None:
    """Check connected headset and runtime capabilities over USB."""
    try:
        report = devices.probe(adb=adb, device=device)
        if json_output:
            console.print_json(data=asdict(report))
            return
        table = Table(title="Standalone VR device")
        table.add_column("Check", style="cyan")
        table.add_column("Result")
        table.add_row("Device", escape(report.device))
        for key, value in report.properties.items():
            table.add_row(key.capitalize(), escape(value))
        table.add_row("Memory", f"{report.memory_mib} MiB" if report.memory_mib else "unknown")
        for broker in report.brokers:
            table.add_row(escape(broker.authority), escape(broker.status))
        table.add_row(
            "Pimax adapter libraries", "found" if report.pimax_library_paths else "absent"
        )
        console.print(table)
        console.print("[yellow]Discovery only; runtime and gameplay still need device testing.[/]")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def build(
    game_dir: GameDirOption = None,
    *,
    android_sdk: Annotated[
        Path | None,
        typer.Option(help="Android SDK; defaults to ANDROID_HOME or SDK found via ADB."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(help="Fresh output; defaults to <GAME>/gk3hd/vr/standalone/build/."),
    ] = None,
    renderer_build: Annotated[
        Path | None,
        typer.Option(help="Reuse a verified VR renderer build; otherwise compile it too."),
    ] = None,
    wsl_distribution: Annotated[
        str | None,
        typer.Option(help="WSL distribution with the ARM64 compiler; defaults to WSL's default."),
    ] = None,
    jobs: Annotated[int, typer.Option(min=1, max=8, help="Maximum concurrent build jobs.")] = 4,
    release: Annotated[
        bool, typer.Option(help="Build a non-debuggable APK with the configured release signer.")
    ] = False,
) -> None:
    """Build and test the Android player, runtime and VR renderer."""
    try:
        directory = builder.build(
            toolchain=builder.Toolchain(android_sdk, wsl_distribution, release),
            game_dir=game_dir,
            output=output,
            renderer_build=renderer_build,
            jobs=jobs,
        )
        kind = "release" if release else "development"
        console.print(f"Standalone {kind} components: {directory}")
        if output is None:
            command = "package draft --vr" if release else "vr standalone install --local"
            console.print(f"Next: gk3hd {command}")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def pack(
    game_dir: GameDirOption = None,
    *,
    build_dir: Annotated[
        Path | None,
        typer.Option(help="Component directory; defaults to the latest development build."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(help="Override <GAME>/gk3hd/vr/standalone/gk3hd-standalone.zip."),
    ] = None,
    testing: Annotated[
        bool,
        typer.Option(help="Skip ALL movies for bounded developer tests, including story videos."),
    ] = False,
    textures: Annotated[
        bool,
        typer.Option(
            help="Include the verified HD textures; disable only for diagnostic controls."
        ),
    ] = True,
    videos: Annotated[
        bool,
        typer.Option(
            help="Include the verified HD videos and player; disable only for diagnostic controls."
        ),
    ] = True,
    backend: Annotated[
        packer.GraphicsBackend,
        typer.Option(help="Graphics transport: private Turnip driver or system Vulkan driver."),
    ] = packer.GraphicsBackend.TURNIP,
) -> None:
    """Package a private player with game data, HD textures and HD videos."""
    try:
        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Compiling and verifying standalone player", total=None)

            def update(done: int, total: int) -> None:
                progress.update(
                    task, description="Packaging private game data", total=total, completed=done
                )

            receipt = packer.pack(
                game_dir=game_dir,
                build_dir=build_dir,
                output=output,
                options=packer.PreparationOptions(
                    profile=ProfileId("testing" if testing else "recommended"),
                    textures=textures,
                    videos=videos,
                    backend=backend,
                ),
                on_progress=update,
            )
        console.print(f"Private standalone bundle: {receipt.path}")
        if testing:
            console.print("[yellow]Testing bundle skips all movies. Not for normal gameplay.[/]")
        if not textures or not videos:
            console.print("[yellow]Diagnostic bundle: original assets, reduced quality.[/]")
        console.print("[yellow]Keep this bundle private: it contains purchased game data.[/]")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error


@app.command()
def install(
    game_dir: GameDirOption = None,
    *,
    local: Annotated[
        bool, typer.Option(help="Use the latest development build and locally installed HD packs.")
    ] = False,
    build_dir: Annotated[
        Path | None, typer.Option(help="Use this verified local component build.")
    ] = None,
    apk: Annotated[
        Path | None, typer.Option(help="Override the APK from the local component build.")
    ] = None,
    bundle: Annotated[
        Path | None, typer.Option(help="Override the private game bundle from standalone pack.")
    ] = None,
    adb: Annotated[
        Path | None, typer.Option(help="Path to ADB if it isn't found automatically.")
    ] = None,
    device: Annotated[
        str | None, typer.Option(help="Headset serial if multiple devices are connected.")
    ] = None,
) -> None:
    """Install or update standalone VR over USB, preserving saves and preferences."""
    try:
        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("{task.fields[detail]}"),
            console=console,
        ) as progress:
            task = progress.add_task("Checking standalone installation", total=None, detail="")
            current_stage = ("", "")

            def update(event: installer.InstallProgress) -> None:
                nonlocal current_stage
                if event.stage in {"failed", "complete"}:
                    return
                if event.stage == "warning":
                    console.print(f"[yellow]{escape(event.message)}[/]")
                    return
                total = event.total
                stage = (event.stage, event.message)
                if stage != current_stage:
                    progress.reset(task, total=total)
                    current_stage = stage
                detail = ""
                if total:
                    detail = (
                        f"{decimal(event.completed)} / {decimal(total)}"
                        if event.unit == "bytes"
                        else f"{event.completed:,} / {total:,}"
                    )
                progress.update(
                    task,
                    description=escape(event.message),
                    total=total,
                    completed=event.completed if total else 0,
                    detail=detail,
                )

            if apk is not None or bundle is not None:
                apk_path, bundle_path = install_inputs(
                    game_dir=game_dir, build_dir=build_dir, apk=apk, bundle=bundle
                )
            else:
                if local and build_dir is None:
                    build_dir = recorded_build(workspace(game_dir))
                apk_path, bundle_path, device = preparation.prepare(
                    game_dir=game_dir,
                    adb=adb,
                    device=device,
                    on_progress=update,
                    build_dir=build_dir,
                )
            installed = installer.install(
                apk=apk_path, bundle=bundle_path, adb=adb, device=device, on_progress=update
            )
        console.print(f"[green]{escape(installed.message.rstrip('.'))}.[/]")
        console.print("Open GK3HD VR in the headset.")
    except CLI_ERRORS as error:
        _print_error(error)
        raise typer.Exit(1) from error
