"""Runtime failure is process death, not focus loss or slow frame delivery."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.vr import runtime_watch as watch
from gk3hd.vr.runtime import RuntimeSelection, RuntimeUnavailableError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def steamvr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[RuntimeSelection, Mock, Mock]:
    runtime = RuntimeSelection(tmp_path / "steamxr_win32.json", tmp_path / "bin/vrclient.dll")
    kernel = Mock()
    kernel.WaitForSingleObject.return_value = 258
    bind = Mock(return_value=123)
    monkeypatch.setattr(watch, "_WINDOWS", True)
    monkeypatch.setattr(watch, "_kernel", lambda: kernel)
    monkeypatch.setattr(watch, "_server", bind)
    return runtime, kernel, bind


def test_binding_is_deferred_until_established_frames(
    steamvr: tuple[RuntimeSelection, Mock, Mock], tmp_path: Path
) -> None:
    runtime, kernel, bind = steamvr
    with watch.RuntimeWatch(runtime, logs=tmp_path) as guard:
        bind.assert_not_called()
        kernel.WaitForSingleObject.assert_not_called()
        guard.check()
        guard.check()
        bind.assert_called_once_with(kernel, tmp_path / "bin/win64/vrserver.exe")
        assert kernel.WaitForSingleObject.call_count == 2
    kernel.CloseHandle.assert_called_once_with(123)


def test_terminated_identity_is_not_rebound_to_a_new_process(
    steamvr: tuple[RuntimeSelection, Mock, Mock], tmp_path: Path
) -> None:
    runtime, kernel, bind = steamvr
    kernel.WaitForSingleObject.side_effect = [258, 0]
    with watch.RuntimeWatch(runtime, logs=tmp_path) as guard:
        guard.check()
        with pytest.raises(RuntimeUnavailableError, match=r"restart SteamVR.*Unsaved.*Logs"):
            guard.check()
    bind.assert_called_once()
    kernel.CloseHandle.assert_called_once_with(123)


def test_runtime_lost_before_binding_is_actionable(
    steamvr: tuple[RuntimeSelection, Mock, Mock], tmp_path: Path
) -> None:
    runtime, kernel, bind = steamvr
    bind.return_value = None
    with (
        pytest.raises(RuntimeUnavailableError, match="SteamVR stopped"),
        watch.RuntimeWatch(runtime, logs=tmp_path) as guard,
    ):
        guard.check()
    kernel.WaitForSingleObject.assert_not_called()
    kernel.CloseHandle.assert_not_called()


@pytest.mark.parametrize("different", ["manifest", "library"])
def test_other_runtimes_do_not_watch_unrelated_steamvr(
    steamvr: tuple[RuntimeSelection, Mock, Mock], tmp_path: Path, different: str
) -> None:
    original, kernel, bind = steamvr
    runtime = RuntimeSelection(
        tmp_path / "other.json" if different == "manifest" else original.manifest,
        tmp_path / "other.dll" if different == "library" else original.library,
    )
    with watch.RuntimeWatch(runtime, logs=tmp_path) as guard:
        guard.check()
    bind.assert_not_called()
    kernel.WaitForSingleObject.assert_not_called()
    kernel.CloseHandle.assert_not_called()


def test_a_fresh_launch_binds_a_fresh_lifetime(
    steamvr: tuple[RuntimeSelection, Mock, Mock], tmp_path: Path
) -> None:
    runtime, kernel, bind = steamvr
    bind.side_effect = [123, 456]
    for _ in range(2):
        with watch.RuntimeWatch(runtime, logs=tmp_path) as guard:
            guard.check()
    assert [call.args for call in kernel.WaitForSingleObject.call_args_list] == [(123, 0), (456, 0)]
    assert [call.args for call in kernel.CloseHandle.call_args_list] == [(123,), (456,)]
