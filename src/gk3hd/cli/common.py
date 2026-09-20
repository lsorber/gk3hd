"""Shared CLI options, error presentation and Rich progress rendering."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TaskID,
    TextColumn,
)
from rich.text import Text

from gk3hd.patch.binary.image import PEError
from gk3hd.patch.binary.operations import OperationError
from gk3hd.patch.builds import ProfileError
from gk3hd.patch.install.transaction import InstallError
from gk3hd.patch.install.windows import ConfigurationError
from gk3hd.patch.manifest import ManifestError
from gk3hd.patch.model import PatchCompilationError, PatchError
from gk3hd.patch.planner import PlanningError
from gk3hd.system.discovery import discover_game
from gk3hd.textures.workspace import texture_workspace_directory

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from rich.progress import Task

    from gk3hd.textures.progress import TextureInstallProgress

console = Console()

error_console = Console(stderr=True)

CLI_ERRORS = (
    OSError,
    RuntimeError,
    ValueError,
    ConfigurationError,
    InstallError,
    ManifestError,
    OperationError,
    PatchCompilationError,
    PatchError,
    PEError,
    PlanningError,
    ProfileError,
)

GameDirOption = Annotated[
    Path | None,
    typer.Option("--game-dir", help="GK3 game directory; normally discovered automatically."),
]

ExeOption = Annotated[
    Path | None,
    typer.Option("--exe", help="Exact GK3 executable; overrides --game-dir."),
]

ForceOption = Annotated[
    bool,
    typer.Option("--force", help="Override guards only for state owned by gk3hd."),
]


def _resolution(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    try:
        width_text, height_text = value.casefold().split("x", maxsplit=1)
        width, height = int(width_text), int(height_text)
    except ValueError as exc:
        msg = "resolution must use WIDTHxHEIGHT"
        raise typer.BadParameter(msg) from exc
    if width <= 0 or height <= 0:
        msg = "resolution dimensions must be positive"
        raise typer.BadParameter(msg)
    return width, height


def _print_error(exc: Exception) -> None:
    error_console.print("[bold red]Error:[/]", Text(str(exc)))


def _upscale_import_error(exc: ImportError) -> RuntimeError:
    """Preserve the failed import while giving an actionable extra-install command."""
    dependency = exc.name or "an upscaling dependency"
    message = (
        f"local upscaling could not load {dependency!r}: {exc}. "
        'Install the optional extra with uv tool install "gk3hd[upscale]" '
        "--torch-backend auto."
    )
    return RuntimeError(message)


class _UnitProgressColumn(ProgressColumn):
    """Render byte counts for downloads and item counts for local work."""

    def __init__(self) -> None:
        super().__init__()
        self._downloads = DownloadColumn()
        self._textures = MofNCompleteColumn()

    def render(self, task: Task) -> Text:
        """Choose the unit-aware Rich column for the current upscale phase."""
        column = self._downloads if task.fields.get("unit") == "bytes" else self._textures
        return column.render(task)


def _texture_stage(
    path: Path | None,
    stage: str,
    *,
    game_dir: Path | None,
    exe: Path | None,
) -> Path:
    """Resolve an explicit stage or its conventional discovered-game location."""
    if path is not None:
        return path.expanduser().resolve()
    target = discover_game(game_dir=game_dir, exe=exe)
    return texture_workspace_directory(target.game_dir) / stage


@contextmanager
def _texture_install_progress() -> Iterator[
    tuple[Progress, Callable[[TaskID, TextureInstallProgress], None]]
]:
    progress = Progress(
        SpinnerColumn("line"),
        TextColumn("{task.description}"),
        BarColumn(),
        _UnitProgressColumn(),
        console=console,
    )
    with progress:
        yield progress, lambda task, event: _update_texture_install(progress, task, event)


def _update_texture_install(
    progress: Progress,
    task: TaskID,
    event: TextureInstallProgress,
) -> None:
    progress.update(
        task,
        description=event.description,
        completed=event.completed,
        total=event.total,
        unit=event.unit,
    )
