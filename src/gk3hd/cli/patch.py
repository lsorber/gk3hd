"""Typer commands for executable patch management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer
from rich.table import Table

from gk3hd.cli.common import (
    CLI_ERRORS,
    ExeOption,
    ForceOption,
    GameDirOption,
    _print_error,
    _resolution,
    console,
)
from gk3hd.patch.model import ProfileId
from gk3hd.patch.service import PatchRequest, PatchService

if TYPE_CHECKING:
    from gk3hd.patch.model import PatchDefinition

app = typer.Typer(help="Install, inspect, verify, or remove executable patches.")


def _patch_table(definitions: tuple[PatchDefinition, ...]) -> Table:
    """Show only the selectable identity and a compact benefit, without truncation."""
    table = Table(box=None, pad_edge=False)
    table.add_column("Patch ID", style="cyan", no_wrap=True)
    table.add_column("Benefit", overflow="fold")
    for definition in definitions:
        table.add_row(definition.id, definition.description)
    return table


@app.command("list")
def patch_list() -> None:
    """List groups with their complete patch selection and compact benefits."""
    groups = Table(title="Groups (--group)", box=None, pad_edge=False)
    groups.add_column("Group", style="cyan")
    groups.add_column("Installs", overflow="fold")
    recommended = set(PatchService.profile_patch_ids(ProfileId("recommended")))
    for profile in PatchService.profiles():
        selected = PatchService.profile_patch_ids(profile.id)
        members = ", ".join(selected)
        if profile.id != "recommended" and recommended <= set(selected):
            members = "recommended + " + ", ".join(sorted(set(selected) - recommended))
        groups.add_row(
            profile.id,
            f"{profile.description}\n{members}",
        )
    console.print(groups)
    console.print()
    console.print(_patch_table(PatchService.patches()))
    console.print(
        "\n[dim]Select with --group GROUP or --patch PATCH_ID (repeatable).\n"
        "Dependencies are included automatically.[/]"
    )


@app.command("install")
def patch_install(
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    group: Annotated[str | None, typer.Option(help="Named patch group.")] = "recommended",
    patch: Annotated[
        list[str] | None,
        typer.Option("--patch", help="Install one patch; may be repeated and replaces --group."),
    ] = None,
    resolution: Annotated[str | None, typer.Option(help="WIDTHxHEIGHT display mode.")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Compile and verify without changing disk.")
    ] = False,
) -> None:
    """Install a patch group or explicit patches transactionally."""
    if patch and group == "recommended":
        group = None
    try:
        service = PatchService()
        request = PatchRequest(
            game_dir=game_dir,
            exe=exe,
            group=group,
            patches=tuple(patch or ()),
            resolution=_resolution(resolution),
        )
        with console.status("[bold cyan]Compiling and verifying patches...", spinner="line"):
            prepared = service.prepare(request) if dry_run else service.install(request)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    verb = "Would install" if dry_run else "Installed"
    console.print(
        f"[bold green]{verb}[/] {len(prepared.plan.patch_ids)} patches for "
        f"{prepared.display_mode.width}x{prepared.display_mode.height}"
    )
    if dry_run:
        console.print(_patch_table(prepared.plan.definitions))


@app.command("verify")
def patch_verify(game_dir: GameDirOption = None, exe: ExeOption = None) -> None:
    """Rebuild and byte-verify the complete installed patch plan."""
    try:
        with console.status("[bold cyan]Rebuilding installed patch plan...", spinner="line"):
            report = PatchService().verify(game_dir=game_dir, exe=exe)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print(f"[bold green]Verified[/] {len(report.patches)} executable patches")


@app.command("uninstall")
def patch_uninstall(
    game_dir: GameDirOption = None,
    exe: ExeOption = None,
    force: ForceOption = False,
) -> None:
    """Restore the exact pristine executable and prior configuration."""
    try:
        PatchService().uninstall(game_dir=game_dir, exe=exe, force=force)
    except CLI_ERRORS as exc:
        _print_error(exc)
        raise typer.Exit(1) from exc
    console.print("[bold green]Executable patches removed.[/]")
