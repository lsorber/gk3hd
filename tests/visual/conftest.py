"""Session-scoped captures reused by parametrized visual checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.visual.support.catalog import Scene, SuiteSize, scenes
from tests.visual.support.runs import comparison_run


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Give every authored camera a stable pytest ID and individual result."""
    if "scene" in metafunc.fixturenames:
        selected = scenes(SuiteSize(metafunc.config.getoption("--suite")))
        metafunc.parametrize("scene", selected, ids=[scene.name for scene in selected])


@pytest.fixture(scope="session")
def visual_run(pytestconfig: pytest.Config) -> Path:
    """Keep each run's diagnostic images in ignored repository output."""
    resume = pytestconfig.getoption("--resume")
    run = comparison_run(resume=Path(resume) if resume else None)
    run.mkdir(parents=True, exist_ok=resume is not None)
    return run


@pytest.fixture(scope="session")
def verified_game(pytestconfig: pytest.Config) -> Path:
    """Require a complete installation; visual tests never install missing components."""
    from gk3hd.patch.service import PatchService  # noqa: PLC0415
    from gk3hd.renderer.service import RendererService  # noqa: PLC0415
    from gk3hd.system.discovery import discover_game  # noqa: PLC0415
    from gk3hd.textures.install.service import verify  # noqa: PLC0415

    game = pytestconfig.getoption("--game-dir")
    target = discover_game(game_dir=Path(game) if game else None)
    PatchService().verify(exe=target.exe)
    RendererService().verify(exe=target.exe)
    verify(exe=target.exe)
    return target.game_dir


@pytest.fixture(scope="session")
def camera_captures(request: pytest.FixtureRequest, visual_run: Path, verified_game: Path) -> Path:
    """Capture only cameras surviving pytest selection, once per quality mode."""
    from tests.visual.support import scenario  # noqa: PLC0415 - Win32 only after opt-in.

    selected = []
    for item in request.session.items:
        if isinstance(item, pytest.Function) and hasattr(item, "callspec"):
            scene = item.callspec.params.get("scene")
            if isinstance(scene, Scene) and scene.kind != "special":
                selected.append(scene)
    scenario.capture(
        game_dir=verified_game,
        size=SuiteSize(request.config.getoption("--suite")),
        resolution=request.config.getoption("--visual-resolution"),
        resume=visual_run,
        selected=tuple(selected),
    )
    return visual_run


@pytest.fixture(scope="session")
def interaction_captures(
    request: pytest.FixtureRequest, visual_run: Path, verified_game: Path
) -> Path:
    """Keep stateful UI sequences together and reuse their report across checks."""
    from tests.visual.support import special  # noqa: PLC0415 - Win32 only after opt-in.

    special.capture(
        game_dir=verified_game,
        resolution=request.config.getoption("--visual-resolution"),
        resume=visual_run,
        selected=tuple(
            scene.name
            for item in request.session.items
            if isinstance(item, pytest.Function)
            and hasattr(item, "callspec")
            and isinstance(scene := item.callspec.params.get("scene"), Scene)
            and scene.kind == "special"
        ),
    )
    return visual_run
