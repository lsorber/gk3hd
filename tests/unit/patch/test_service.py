"""New installations share one portable renderer, independent of the host OS."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from gk3hd.patch import service
from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.service import PatchRequest, PatchService
from gk3hd.system.display import DisplayMode
from tests.unit.patch.test_install_transaction import _prepared


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("auto", GraphicsBackend.D7VK),
        ("d7vk", GraphicsBackend.D7VK),
        ("native", GraphicsBackend.NATIVE),
    ],
)
def test_service_uses_d7vk_by_default_with_physical_desktop_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requested: str, expected: GraphicsBackend
) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"original")
    installer = Mock()
    installer.prepare.return_value = _prepared(exe, b"original", b"patched")
    monkeypatch.setattr(service, "Installer", Mock(return_value=installer))
    monkeypatch.setattr(
        service, "current_display_mode", Mock(return_value=DisplayMode(1280, 800, 90))
    )
    PatchService().prepare(PatchRequest(exe=exe, backend=requested))
    assert installer.prepare.call_args.kwargs["graphics_backend"] is expected
    assert installer.prepare.call_args.kwargs["width"] == 1280
    assert installer.prepare.call_args.kwargs["height"] == 800


@pytest.mark.parametrize("explicit", [False, True])
def test_update_keeps_resolution_without_needing_a_connected_display(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit: bool
) -> None:
    from gk3hd.patch.install.configuration import NoopConfiguration  # noqa: PLC0415
    from tests.unit.patch.test_install_transaction import PassingVerificationInstaller  # noqa: PLC0415

    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"original")
    plan = _prepared(exe, b"original", b"patched")
    PassingVerificationInstaller(
        configuration=NoopConfiguration(), process_probe=lambda: False
    ).apply(exe=exe, prepared=plan)
    installer = Mock()
    installer.prepare.return_value = plan
    monkeypatch.setattr(service, "Installer", Mock(return_value=installer))
    monkeypatch.setattr(service, "current_display_mode", Mock(side_effect=AssertionError))
    result = PatchService().prepare(
        PatchRequest(exe=exe, resolution=(1280, 800) if explicit else None)
    )
    expected = (1280, 800) if explicit else (1920, 1080)
    assert installer.prepare.call_args.kwargs["width"] == expected[0]
    assert installer.prepare.call_args.kwargs["height"] == expected[1]
    assert result.preserve_resolution is not explicit
