"""Discovery never fabricates support or changes an attached Android device."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from gk3hd.cli import app
from gk3hd.vr.standalone import device as standalone


@pytest.mark.parametrize(
    ("listing", "selected", "error"),
    [
        ("List of devices attached\n", None, "No Android headset"),
        ("device-a\tunauthorized\n", None, "unauthorized"),
        ("device-a\toffline\n", None, "offline"),
        ("device-a\tdevice\ndevice-b\tdevice\n", None, "Multiple Android devices"),
        ("device-a\tdevice\n", "missing", "not connected"),
    ],
)
def test_unavailable_device_is_actionable(listing: str, selected: str | None, error: str) -> None:
    with pytest.raises(RuntimeError, match=error):
        standalone._select_device(listing, selected)


def test_explicit_selection_does_not_touch_another_device() -> None:
    listing = "List of devices attached\ndevice-a\tdevice product:phone\ndevice-b\tdevice\n"
    assert standalone._select_device(listing, "device-b") == "device-b"


def test_multiple_devices_show_options_to_select_each_headset() -> None:
    listing = "crystal\tdevice model:Pimax_Crystal\nquest\tunauthorized model:Quest_3\n"
    with pytest.raises(RuntimeError) as caught:
        standalone._select_device(listing, None)
    assert "Pimax Crystal (device)  --device crystal" in str(caught.value)
    assert "Quest 3 (unauthorized)  --device quest" in str(caught.value)


def test_sdk_platform_tools_work_without_changing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    platform_tools = tmp_path / "platform-tools"
    platform_tools.mkdir()
    executable = platform_tools / ("adb.exe" if os.name == "nt" else "adb")
    executable.touch()
    monkeypatch.setattr(standalone.shutil, "which", lambda _: None)
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))

    assert standalone.resolve_adb(None) == str(executable)


@pytest.mark.parametrize(
    ("response", "code", "status"),
    [
        ("Row: 0 package_name=com.example.xr, so_filename=libruntime.so", 0, "runtime advertised"),
        ("SecurityException: Permission Denial", 1, "query denied"),
        ("No result found.", 0, "no accessible runtime"),
        ("Could not find provider", 0, "no accessible runtime"),
        ("package_name=broken", 0, "no accessible runtime"),
    ],
)
def test_broker_discovery_is_not_runtime_qualification(
    response: str, code: int, status: str
) -> None:
    assert standalone._broker_status(response, code).startswith(status)


def test_probe_collects_facts_without_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def run(executable: str, *args: str) -> subprocess.CompletedProcess[str]:
        assert executable == "adb"
        calls.append(args)
        if args == ("devices", "-l"):
            output = "List of devices attached\nheadset\tdevice\n"
        else:
            assert args[:3] == ("-s", "headset", "shell")
            command = args[3:]
            if command == ("getprop",):
                output = (
                    "[ro.product.model]: [Crystal]\n[ro.build.version.sdk]: [29]\n"
                    "[ro.product.cpu.abilist]: [arm64-v8a,armeabi-v7a]\n"
                    "[unrelated.private.setting]: [do-not-export]\n"
                )
            elif command == ("cat", "/proc/meminfo"):
                output = "MemTotal:       6291456 kB\n"
            elif command[0] == "content":
                output = "No result found."
            else:
                assert command[0] == "ls"
                output = "/system/lib64/libpxrunityxrcore.pi.so\n"
        return subprocess.CompletedProcess([], 0, output, "")

    monkeypatch.setattr(standalone.shutil, "which", lambda _: "adb")
    monkeypatch.setattr(standalone, "_run", run)
    report = standalone.probe()
    assert report.properties["model"] == "Crystal"
    assert report.properties["manufacturer"] == "unknown"
    assert report.memory_mib == 6144
    assert "do-not-export" not in str(report)
    assert report.pimax_library_paths == ("/system/lib64/libpxrunityxrcore.pi.so",)
    assert all("not established" in b.status for b in report.brokers)
    assert len(calls) == 6


def test_query_timeout_is_bounded_and_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Mock(side_effect=subprocess.TimeoutExpired("adb", 10))
    monkeypatch.setattr(standalone.subprocess, "run", runner)
    with pytest.raises(RuntimeError, match="timed out"):
        standalone._run("adb", "devices", "-l")
    assert runner.call_args.kwargs["timeout"] == 10
    assert "shell" not in runner.call_args.kwargs


def test_probe_cli_does_not_install_or_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Mock(side_effect=RuntimeError("No Android headset is visible"))
    monkeypatch.setattr(standalone, "probe", probe)
    result = CliRunner().invoke(app, ["vr", "standalone", "doctor", "--adb", "adb-custom"])
    assert result.exit_code == 1
    assert "No Android headset" in result.output
    probe.assert_called_once_with(adb=Path("adb-custom"), device=None)
