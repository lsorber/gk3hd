"""Video inventory and local, temporally consistent restoration commands."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 - Typer resolves command annotations at runtime.
from typing import TYPE_CHECKING, Annotated

import typer
from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from gk3hd.cli.common import CLI_ERRORS, GameDirOption, _print_error, _UnitProgressColumn, console
from gk3hd.system.discovery import discover_game
from gk3hd.videos.backend import create_backend
from gk3hd.videos.catalog import MOVIE_EXTENSIONS, find_movies, movie_format, movie_workspace
from gk3hd.videos.install import MovieInstaller
from gk3hd.videos.pack import PackRequest, build_pack, install_pack

if TYPE_CHECKING:
    from collections.abc import Callable

    from gk3hd.videos.install import MovieInstallReport
    from gk3hd.videos.transaction import MovieProgress

app = typer.Typer(help="Restore the original videos at 4x resolution.", no_args_is_help=True)
VideoOption = Annotated[
    list[str] | None,
    typer.Option(
        "--video", "-v", help="Filename or glob, e.g. Sierra.avi or intro.bik; repeatable."
    ),
]


@app.command("list")
def videos_list(
    source: Annotated[
        Path | None, typer.Argument(help="Movie directory; defaults to GAME/Data.")
    ] = None,
    game_dir: GameDirOption = None,
) -> None:
    """List video files and distinguish recognized media from unknown headers."""
    try:
        directory = source or discover_game(game_dir=game_dir).data_dir
        paths = sorted(
            (
                p
                for p in directory.iterdir()
                if p.suffix.casefold() in MOVIE_EXTENSIONS and p.is_file()
            ),
            key=lambda p: p.name.casefold(),
        )
        table = Table("Movie", "Format", "Size", box=None)
        playable = 0
        for path in paths:
            kind = movie_format(path)
            playable += kind is not None
            table.add_row(
                path.name,
                kind or "[dim]Not a video header[/]",
                f"{path.stat().st_size / (1024 * 1024):.1f} MiB",
            )
        console.print(table)
        console.print(f"{playable} recognized videos; {len(paths) - playable} unrecognized files.")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command("upscale")
def videos_upscale(
    source: Annotated[
        Path | None, typer.Argument(help="Movie directory; defaults to GAME/Data.")
    ] = None,
    output: Annotated[
        Path | None, typer.Argument(help="Defaults to GAME/gk3hd/videos/upscaled.")
    ] = None,
    game_dir: GameDirOption = None,
    video: VideoOption = None,
    device: Annotated[str, typer.Option(help="AI device: auto, cuda, cpu, or cuda:1.")] = "auto",
    clip_frames: Annotated[
        int,
        typer.Option(
            min=5, help="Maximum context at 320x240: 5, 9, 13, 17, ...; shorter for larger videos."
        ),
    ] = 17,
    strength: Annotated[
        float,
        typer.Option(
            min=0,
            max=1,
            help="AI blend: 0 = bicubic only, 1 = full AI; lower stays closer to source.",
        ),
    ] = 1.0,
) -> None:
    """Restore selected videos with SeedVR2 and preserve original audio."""
    try:
        # Listing and installation do not need PyAV or Torch.
        from gk3hd.videos.service import (  # noqa: PLC0415 - optional video codecs.
            MovieUpscaleOptions,
            upscale_movies,
        )
        from gk3hd.videos.video import restoration_pipeline  # noqa: PLC0415 - optional codecs.

        options = MovieUpscaleOptions(clip_frames=clip_frames, restoration_strength=strength)
        source_path, output_path = _video_directories(source, output, game_dir)
        sources = find_movies(source_path, video or ())
        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            _UnitProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Preparing video restoration", total=None, unit="frames")

            def update(name: str, completed: int, total: int | None) -> None:
                progress.update(
                    task, description=escape(name), completed=completed, total=total, unit="frames"
                )

            def download(name: str, completed: int, total: int | None) -> None:
                progress.update(
                    task,
                    description=f"Downloading {escape(name)}",
                    completed=completed,
                    total=total,
                    unit="bytes",
                )

            backend = None
            if strength > 0 and any(restoration_pipeline(path) == "seedvr2" for path in sources):
                backend = create_backend(device, download)
                progress.console.print(f"AI device: {backend.device_description}")
                progress.console.print("Encoding: AV1 + FLAC (MKV)")
            report = upscale_movies(sources, output_path, backend, options=options, progress=update)
        console.print(
            f"Restored {report.generated} videos; reused {report.skipped} verified outputs; "
            f"retained {report.retained} original technical animations."
        )
        console.print(f"Video output: {report.output}")
    except ImportError as exc:
        message = (
            'Video upscaling needs the optional extra: uvx --from "gk3hd[upscale]" '
            "gk3hd videos upscale"
        )
        _print_error(RuntimeError(message))
        raise typer.Exit(1) from exc
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


def _video_directories(
    source: Path | None, output: Path | None, game_dir: Path | None
) -> tuple[Path, Path]:
    if source is not None and output is not None:
        return source.expanduser().resolve(), output.expanduser().resolve()
    target = discover_game(game_dir=game_dir)
    return (
        source.expanduser().resolve()
        if source is not None
        else (
            movie_workspace(target.game_dir) / "original"
            if (movie_workspace(target.game_dir) / "original").is_dir()
            else target.data_dir
        ),
        output.expanduser().resolve()
        if output is not None
        else movie_workspace(target.game_dir) / "upscaled",
    )


@app.command("install")
def videos_install(
    game_dir: GameDirOption = None,
    local: Annotated[
        bool,
        typer.Option(
            "--local", help="Install the pack in the current directory or game video workspace."
        ),
    ] = False,
    pack: Annotated[Path | None, typer.Option(help="Local video-pack lock or directory.")] = None,
    cache_dir: Annotated[
        Path | None, typer.Option(help="Downloaded-asset cache directory.")
    ] = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Use only hash-verified cached release assets.")
    ] = False,
) -> None:
    """Download and install the published video pack and private playback codecs."""
    try:
        target = discover_game(game_dir=game_dir)
        report = _file_action(
            "Preparing video installation",
            lambda progress: install_pack(
                target.game_dir,
                PackRequest(local=local, selection=pack, cache=cache_dir, offline=offline),
                progress=progress,
            ),
        )
        status = "Installed" if report.changed else "Already installed"
        console.print(f"{status}: {report.videos} videos in {report.directory}")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command("pack")
def videos_pack(
    source: Annotated[
        Path | None,
        typer.Argument(help="Verified MKV directory; defaults to GAME/gk3hd/videos/upscaled."),
    ] = None,
    output: Annotated[
        Path | None, typer.Argument(help="Versioned ZIP base; defaults inside GAME/gk3hd/videos.")
    ] = None,
    game_dir: GameDirOption = None,
) -> None:
    """Pack verified videos and the local player into release-ready ZIP parts."""
    try:
        from gk3hd import __version__  # noqa: PLC0415 - release version.

        target = discover_game(game_dir=game_dir)
        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            _UnitProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Packing videos", total=None, unit="bytes")
            archives = build_pack(
                target.game_dir,
                version=__version__,
                source=source,
                output=output,
                progress=lambda name, done, total: progress.update(
                    task, description=escape(name), completed=done, total=total
                ),
            )
        for archive in archives:
            console.print("Pack:", archive)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command("extract")
def videos_extract(
    output: Annotated[
        Path | None,
        typer.Argument(help="Original video directory; defaults to GAME/gk3hd/videos/original."),
    ] = None,
    game_dir: GameDirOption = None,
) -> None:
    """Copy the game's loose Bink/AVI originals into the video workspace."""
    try:
        from gk3hd.videos.catalog import extract  # noqa: PLC0415 - command operation.

        target = discover_game(game_dir=game_dir)
        destination = output or movie_workspace(target.game_dir) / "original"
        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            _UnitProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Extracting videos", total=None, unit="bytes")
            count = extract(
                target.data_dir,
                destination,
                progress=lambda name, done, total: progress.update(
                    task, description=escape(name), completed=done, total=total
                ),
            )
        console.print(f"Extracted {count} videos to {destination}")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command("build")
def videos_build(game_dir: GameDirOption = None) -> None:
    """Build the AV1 player in GAME/gk3hd/videos/player (Windows toolchain required)."""
    try:
        from gk3hd.videos.runtime import build_player  # noqa: PLC0415 - developer operation.

        target = discover_game(game_dir=game_dir)
        directory = build_player(target.game_dir)
        console.print(f"Video player build: {directory}")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command("verify")
def videos_verify(game_dir: GameDirOption = None) -> None:
    """Verify installed video hashes and their original source identities."""
    try:
        target = discover_game(game_dir=game_dir)
        report = _file_action(
            "Verifying videos",
            lambda progress: MovieInstaller.verify(target.game_dir, progress=progress),
        )
        console.print(f"Verified {report.videos} installed videos.")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


@app.command("uninstall")
def videos_uninstall(game_dir: GameDirOption = None) -> None:
    """Remove owned video replacements; keep originals and generated outputs."""
    try:
        target = discover_game(game_dir=game_dir)
        report = _file_action(
            "Verifying videos before removal",
            lambda progress: MovieInstaller().uninstall(target.game_dir, progress=progress),
        )
        console.print(f"Removed {report.videos} video replacements; originals are unchanged.")
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc


def _file_action(
    description: str, action: Callable[[MovieProgress], MovieInstallReport]
) -> MovieInstallReport:
    with Progress(
        SpinnerColumn("line"),
        TextColumn("{task.description}"),
        BarColumn(),
        _UnitProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(description, total=None, unit="bytes")

        def update(name: str, completed: int, total: int) -> None:
            progress.update(task, description=escape(name), completed=completed, total=total)

        return action(update)
