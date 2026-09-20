"""Compact patch previews without discovering, compiling or installing a game."""

from io import StringIO
from unittest.mock import Mock

import pytest
from rich.console import Console
from typer.testing import CliRunner

from gk3hd.cli import app, patch
from gk3hd.patch.builds import SUPPORTED_BUILDS
from gk3hd.patch.catalog import PLANNER
from gk3hd.patch.model import BuildContext, PatchId


def test_dry_run_lists_the_resolved_plan_without_installing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = PLANNER.plan_explicit(
        {PatchId("scale_fixed_interfaces")},
        BuildContext(build_id=next(iter(SUPPORTED_BUILDS))),
    )
    service = Mock()
    service.prepare.return_value = Mock(plan=plan, display_mode=Mock(width=3840, height=2160))
    monkeypatch.setattr(patch, "PatchService", lambda: service)
    output = StringIO()
    monkeypatch.setattr(patch, "console", Console(file=output, width=80, color_system=None))
    result = CliRunner().invoke(
        app, ["patch", "install", "--dry-run", "--patch", "scale_fixed_interfaces"]
    )
    assert result.exit_code == 0, result.output
    assert "Would install 4 patches for 3840x2160" in output.getvalue()
    for patch_id in plan.patch_ids:
        assert patch_id in output.getvalue()
    assert "skip_all_movies" not in output.getvalue()
    service.install.assert_not_called()
    service.prepare.assert_called_once()


@pytest.mark.parametrize("width", [60, 80, 120])
def test_patch_list_fits_terminal_without_ellipsis(
    monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    output = StringIO()
    monkeypatch.setattr(patch, "console", Console(file=output, width=width, color_system=None))
    result = CliRunner().invoke(app, ["patch", "list"])
    assert result.exit_code == 0, result.output
    assert "…" not in output.getvalue()
    assert all(len(line) <= width for line in output.getvalue().splitlines())
    compact = "".join(output.getvalue().split())
    for definition in patch.PatchService.patches():
        assert definition.id in compact
