"""New installations share one portable renderer, independent of the host OS."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from gk3hd.patch import service
from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.service import PatchRequest, PatchService
from gk3hd.system.display import DisplayMode


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("auto", GraphicsBackend.D7VK),
        ("d7vk", GraphicsBackend.D7VK),
        ("native", GraphicsBackend.NATIVE),
    ],
)
def test_service_uses_d7vk_by_default_with_physical_desktop_resolution(
    monkeypatch: pytest.MonkeyPatch, requested: str, expected: GraphicsBackend
) -> None:
    installer = Mock()
    monkeypatch.setattr(service, "Installer", Mock(return_value=installer))
    monkeypatch.setattr(service, "discover_game", Mock(return_value=Mock(exe=Path("GK3.exe"))))
    monkeypatch.setattr(
        service, "current_display_mode", Mock(return_value=DisplayMode(1280, 800, 90))
    )
    PatchService().prepare(PatchRequest(backend=requested))
    assert installer.prepare.call_args.kwargs["graphics_backend"] is expected
    assert installer.prepare.call_args.kwargs["width"] == 1280
    assert installer.prepare.call_args.kwargs["height"] == 800
