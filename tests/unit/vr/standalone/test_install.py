"""Installer ownership, status and CLI behavior without executing a game."""

from __future__ import annotations

import hashlib
import json
from io import StringIO
from queue import Empty, Queue
from typing import TYPE_CHECKING, Literal
from unittest.mock import MagicMock, Mock
from zipfile import ZipFile

import pytest
from typer.testing import CliRunner

from gk3hd.cli import app
from gk3hd.vr.standalone import install as installer
from gk3hd.vr.standalone.bundle import (
    REQUIRED_FILES,
    BundleManifest,
    BundleReceipt,
    build_bundle,
    component_bundle,
    inspect_bundle,
    read_bundle_manifest,
)
from gk3hd.vr.standalone.device import Broker, DeviceProbe

if TYPE_CHECKING:
    from pathlib import Path


def test_only_this_install_session_can_report_completion() -> None:
    record = {
        "stage": "complete",
        "completed": 1,
        "total": 1,
        "message": "Installed",
        "token": "current",
    }
    assert installer._status("I/GK3HDSetup: " + json.dumps(record), "old") is None
    report = installer._status("I/GK3HDSetup: " + json.dumps(record), "current")
    assert report is not None
    assert report.stage == "complete"
    assert installer._status("unrelated text", "current") is None
    assert installer._status('{"token":broken}', "current") is None


@pytest.mark.parametrize(
    "changes",
    [{"completed": -1}, {"completed": 12}, {"total": True}, {"stage": []}, {"message": 12}],
)
def test_bad_status_cannot_authorize_success(changes: dict[str, object]) -> None:
    record = {
        "token": "current",
        "stage": "complete",
        "completed": 1,
        "total": 1,
        "message": "Installed",
    }
    record.update(changes)
    with pytest.raises(RuntimeError, match="Malformed"):
        installer._status(json.dumps(record), "current")


def test_expanded_hd_progress_is_distinct_from_transfer_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(installer, "MAX_ARCHIVE_BYTES", 8 * 1024**3)
    monkeypatch.setattr(installer, "MAX_PAYLOAD_BYTES", 16 * 1024**3)
    record = {
        "token": "current",
        "stage": "extract",
        "completed": 9 * 1024**3,
        "total": 10 * 1024**3,
        "message": "Extracting verified HD resources",
    }
    report = installer._status(json.dumps(record), "current")
    assert report is not None
    assert report.completed == record["completed"]
    record["stage"] = "update"
    assert installer._status(json.dumps(record), "current") is not None
    record["stage"] = "verify"
    with pytest.raises(RuntimeError, match="archive bound"):
        installer._status(json.dumps(record), "current")


def test_device_space_requires_a_real_measurement() -> None:
    assert (
        installer._free_bytes(
            "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/data 900 100 800 11% /data"
        )
        == 800 * 1024
    )
    with pytest.raises(RuntimeError, match="free space"):
        installer._free_bytes("device disconnected")


def test_differently_signed_update_explains_that_android_kept_the_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = Mock(returncode=1, stdout="", stderr="Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]")
    run = Mock(return_value=result)
    monkeypatch.setattr(installer.subprocess, "run", run)

    with pytest.raises(RuntimeError, match=r"different signing key.*standalone backup"):
        installer._Adb("adb", "headset").run("install", "-r", "player.apk")

    assert run.call_args.args[0] == ["adb", "-s", "headset", "install", "-r", "player.apk"]


@pytest.mark.parametrize(
    ("detail", "hint"),
    [
        ("adb: error: device 'headset' not found", "reconnect its USB data cable"),
        ("Failure [INSTALL_FAILED_VERSION_DOWNGRADE]", "uvx gk3hd@latest vr standalone install"),
        ("Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]", "Free up headset storage"),
    ],
)
def test_install_failure_suggests_the_next_action(
    monkeypatch: pytest.MonkeyPatch, detail: str, hint: str
) -> None:
    result = Mock(returncode=1, stdout="", stderr=detail)
    monkeypatch.setattr(installer.subprocess, "run", Mock(return_value=result))
    with pytest.raises(RuntimeError, match=hint):
        installer._Adb("adb", "headset").run("install", "-r", "player.apk")


def test_missed_transfer_progress_does_not_cancel_a_successful_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "private.zip"
    bundle.write_bytes(b"fixture")
    child = Mock(returncode=0)
    child.poll.side_effect = [None, None, 0, 0]
    process = MagicMock()
    process.__enter__.return_value = child
    monkeypatch.setattr(installer.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(installer.time, "sleep", Mock())
    run = Mock(side_effect=[RuntimeError("Headset command timed out"), "3"])
    monkeypatch.setattr(installer._Adb, "run", run)
    updates: list[installer.InstallProgress] = []

    installer._push(installer._Adb("adb", "headset"), bundle, "/owned.zip", updates.append)

    assert [update.completed for update in updates] == [0, 3, len(b"fixture")]
    child.kill.assert_not_called()


@pytest.mark.parametrize("completes", [True, False])
def test_large_usb_transfer_has_a_size_budget_but_never_waits_forever(
    monkeypatch: pytest.MonkeyPatch, *, completes: bool
) -> None:
    clock = [0.0]
    bundle = Mock()
    bundle.stat.return_value.st_size = 7 * 1024**3
    child = Mock(returncode=0)
    child.poll.side_effect = lambda: 0 if completes and clock[0] >= 1800 else None
    process = MagicMock()
    process.__enter__.return_value = child
    monkeypatch.setattr(installer.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(installer._Adb, "run", Mock(return_value=""))
    monkeypatch.setattr(installer.time, "monotonic", lambda: clock[0])

    def advance(_seconds: float) -> None:
        clock[0] += 600

    monkeypatch.setattr(installer.time, "sleep", advance)
    updates: list[installer.InstallProgress] = []
    if completes:
        installer._push(installer._Adb("adb", "headset"), bundle, "/owned.zip", updates.append)
        assert clock[0] == 1800
        assert updates[-1].completed == bundle.stat.return_value.st_size
        child.kill.assert_not_called()
    else:
        with pytest.raises(RuntimeError, match=r"transfer timed out.*USB data cable"):
            installer._push(installer._Adb("adb", "headset"), bundle, "/owned.zip", updates.append)
        assert 1800 < clock[0] <= 2400
        assert all(update.completed == 0 for update in updates)
        child.kill.assert_called_once()
        child.wait.assert_called_once()


def test_failed_push_does_not_report_transfer_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "private.zip"
    bundle.write_bytes(b"fixture")
    child = Mock(returncode=1)
    child.poll.return_value = 1
    child.stderr.read.return_value = "device disconnected"
    process = MagicMock()
    process.__enter__.return_value = child
    monkeypatch.setattr(installer.subprocess, "Popen", Mock(return_value=process))
    updates: list[installer.InstallProgress] = []
    with pytest.raises(RuntimeError, match="reconnect its USB data cable"):
        installer._push(installer._Adb("adb", "headset"), bundle, "/owned.zip", updates.append)
    assert [update.completed for update in updates] == [0]


def test_setup_accepts_progress_then_only_matching_completion() -> None:
    queue: Queue[str | None] = Queue()
    for token, stage, done, total in [
        ("old", "complete", 1, 1),
        ("current", "verify", 100, 200),
        ("current", "complete", 1, 1),
    ]:
        queue.put(
            json.dumps(
                {
                    "token": token,
                    "stage": stage,
                    "completed": done,
                    "total": total,
                    "message": stage,
                }
            )
        )
    updates: list[installer.InstallProgress] = []
    assert installer._consume_setup(queue, "current", updates.append, Mock()) == "complete"
    assert [update.stage for update in updates] == ["verify", "complete"]


@pytest.mark.parametrize("result_source", ["provider", "logcat"])
def test_live_but_silent_logcat_follows_the_persisted_install(
    monkeypatch: pytest.MonkeyPatch,
    result_source: str,
) -> None:
    queue: Queue[str | None] = Queue()
    clock = [0.0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    def status(token: str, stage: str) -> str:
        return json.dumps(
            {"token": token, "stage": stage, "completed": 1, "total": 2, "message": stage}
        )

    queue.put(status("current", "verify"))
    monkeypatch.setattr(installer.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(installer.time, "sleep", sleep)
    read_queue = queue.get

    def silent_read(*, timeout: float | None = None, block: bool = True) -> str | None:
        try:
            return read_queue(block=False)
        except Empty:
            if block:
                assert timeout is not None
                sleep(timeout)
            raise

    monkeypatch.setattr(queue, "get", silent_read)
    reads = 0

    def provider() -> str:
        nonlocal reads
        reads += 1
        if reads == 1:
            return status("old", "complete")
        if reads == 2:
            if result_source == "logcat":
                queue.put(status("current", "runtime"))
                queue.put(status("old", "complete"))
                queue.put(status("current", "complete"))
            return status("current", "verify")
        assert reads == 3
        assert result_source == "provider"
        return status("current", "complete")

    updates: list[installer.InstallProgress] = []
    assert installer._consume_setup(queue, "current", updates.append, provider) == "complete"
    assert [update.stage for update in updates] == ["verify", "complete"]


def test_installed_inventory_can_be_read_without_debug_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = json.dumps({"schema": 1, "files": {}})
    run = Mock(return_value=receipt)
    monkeypatch.setattr(installer._Adb, "run", run)

    assert installer._installed_receipt(installer._Adb("adb", "headset")) == receipt
    run.assert_called_once_with(
        "exec-out",
        "content",
        "read",
        "--uri",
        f"content://{installer.APPLICATION_ID}.setup/inventory",
        checked=False,
    )


@pytest.mark.parametrize("result", ["No content provider", "{éé}"])
def test_unavailable_provider_preserves_local_debug_receipt_access(
    monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    monkeypatch.setattr(installer, "_MAX_INSTALLED_RECEIPT", 5)
    run = Mock(side_effect=[result, "{}"])  # Four characters but six UTF-8 bytes.
    monkeypatch.setattr(installer._Adb, "run", run)

    assert installer._installed_receipt(installer._Adb("adb", "headset")) == "{}"
    assert run.call_args.args[:3] == ("shell", "run-as", installer.APPLICATION_ID)


@pytest.mark.parametrize("terminal", ["complete", "failed"])
def test_disconnected_progress_follows_the_same_native_installation(
    monkeypatch: pytest.MonkeyPatch, terminal: str
) -> None:
    queue: Queue[str | None] = Queue()
    queue.put(None)
    reports = [
        json.dumps({"token": token, "stage": stage, "completed": 1, "total": 2, "message": stage})
        for token, stage in [("old", "complete"), ("current", "extract"), ("current", terminal)]
    ]
    run = Mock(side_effect=["", RuntimeError("USB disconnected"), *reports])
    monkeypatch.setattr(installer._Adb, "run", run)
    monkeypatch.setattr(installer.time, "sleep", Mock())
    adb = installer._Adb("adb", "headset")

    def read() -> str:
        return installer._read_setup_status(adb)

    updates: list[installer.InstallProgress] = []
    if terminal == "failed":
        with pytest.raises(RuntimeError, match="failed"):
            installer._consume_setup(queue, "current", updates.append, read)
    else:
        assert installer._consume_setup(queue, "current", updates.append, read) == "complete"
    assert [update.stage for update in updates] == ["extract", terminal]
    provider_reads = [run.call_args_list[0], *run.call_args_list[2:]]
    assert all(call.args[:3] == ("exec-out", "content", "read") for call in provider_reads)
    assert run.call_args_list[1].args[:3] == ("exec-out", "run-as", installer.APPLICATION_ID)


@pytest.mark.parametrize("started", [False, True])
def test_disconnected_installer_retains_its_original_deadlines(
    monkeypatch: pytest.MonkeyPatch, started: bool
) -> None:
    queue: Queue[str | None] = Queue()
    if started:
        queue.put(
            json.dumps(
                {
                    "token": "current",
                    "stage": "verify",
                    "completed": 0,
                    "total": 1,
                    "message": "verify",
                }
            )
        )
    queue.put(None)
    clock = [0.0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(installer.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(installer.time, "sleep", sleep)
    monkeypatch.setattr(installer, "_FIRST_STATUS_SECONDS", 2)
    monkeypatch.setattr(installer, "_SETUP_SECONDS", 4)
    message = "did not report completion" if started else "did not report setup progress"
    with pytest.raises(RuntimeError, match=message):
        installer._consume_setup(queue, "current", Mock(), Mock(return_value=""))
    assert clock[0] <= 4


def test_silent_setup_fails_promptly(monkeypatch: pytest.MonkeyPatch) -> None:
    queue: Queue[str | None] = Queue()
    monkeypatch.setattr(installer.time, "monotonic", Mock(side_effect=[0, 0, 31, 31]))
    with pytest.raises(RuntimeError, match="did not report setup progress"):
        installer._consume_setup(queue, "current", Mock(), Mock())


def test_setup_import_does_not_open_a_headset_screen_or_stop_a_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = json.dumps(
        {
            "token": "current",
            "stage": "complete",
            "completed": 1,
            "total": 1,
            "message": "Installed",
        }
    )
    child = MagicMock()
    child.stdout = StringIO(output + "\n")
    child.poll.return_value = 0
    process = MagicMock()
    process.__enter__.return_value = child
    monkeypatch.setattr(installer.subprocess, "Popen", Mock(return_value=process))

    def response(*args: str, **_kwargs: object) -> str:
        if args[:4] == ("shell", "cmd", "package", "list"):
            return f"package:{installer.APPLICATION_ID} uid:10116"
        if args[:2] == ("shell", "ps"):
            return "UID NAME\n"
        if args == ("shell", "dumpsys", "activity", "activities"):
            return "ACTIVITY MANAGER ACTIVITIES (dumpsys activity activities)\n"
        if args[:3] == ("shell", "am", "start-foreground-service"):
            return "Starting service"
        message = f"Unexpected setup command: {args}"
        raise AssertionError(message)

    run = Mock(side_effect=response)
    monkeypatch.setattr(installer._Adb, "run", run)
    options = ("--es", "gk3hd_bundle", "/owned.zip", "--es", "gk3hd_bundle_sha256", "a" * 64)
    assert (
        installer._await_setup(installer._Adb("adb", "headset"), "current", options, Mock())
        == "Installed"
    )
    assert any(
        c.args[:3] == ("shell", "am", "start-foreground-service") for c in run.call_args_list
    )
    assert all("-S" not in c.args and "force-stop" not in c.args for c in run.call_args_list)


def test_native_preservation_error_is_not_masked() -> None:
    queue: Queue[str | None] = Queue()
    queue.put(
        json.dumps(
            {
                "token": "current",
                "stage": "failed",
                "completed": 0,
                "total": 0,
                "message": "Modified player preserved",
            }
        )
    )
    with pytest.raises(RuntimeError, match="Modified player preserved"):
        installer._consume_setup(queue, "current", Mock(), Mock())


@pytest.mark.parametrize("program", ["GK3-VR.exe", "gk3hd-wine-launcher.exe"])
def test_playing_session_is_preserved(monkeypatch: pytest.MonkeyPatch, program: str) -> None:
    run = Mock(
        side_effect=[f"package:{installer.APPLICATION_ID} uid:10116", f"UID NAME\n10116 {program}"]
    )
    monkeypatch.setattr(installer._Adb, "run", run)
    with pytest.raises(RuntimeError, match="running session was preserved"):
        installer._require_idle(installer._Adb("adb", "headset"))
    assert all("force-stop" not in call.args for call in run.call_args_list)


@pytest.mark.parametrize("starts_again", [False, True])
def test_check_after_quit_allows_android_to_retire_the_activity(
    monkeypatch: pytest.MonkeyPatch, *, starts_again: bool
) -> None:
    idle = "UID NAME\n10116 org.gk3hd.standalone"
    run = Mock(
        side_effect=[
            f"package:{installer.APPLICATION_ID} uid:10116",
            idle,
            f"  * Hist  #0: ActivityRecord{{123 u0 {installer.APPLICATION_ID}/.OpenXrActivity t1}}",
            "UID NAME\n10116 GK3-VR.exe" if starts_again else idle,
            "ACTIVITY MANAGER ACTIVITIES",
        ]
    )
    monkeypatch.setattr(installer._Adb, "run", run)
    monkeypatch.setattr(installer.time, "sleep", Mock())
    adb = installer._Adb("adb", "headset")
    if starts_again:
        with pytest.raises(RuntimeError, match="running session was preserved"):
            installer._require_idle(adb)
    else:
        installer._require_idle(adb)
    assert all("force-stop" not in call.args for call in run.call_args_list)


@pytest.mark.parametrize("program", ["GK3-VR.exe", "gk3hd-wine-launcher.exe"])
def test_other_apps_game_does_not_authorize_killing_it(
    monkeypatch: pytest.MonkeyPatch, program: str
) -> None:
    run = Mock(
        side_effect=[
            f"package:{installer.APPLICATION_ID} uid:10116",
            f"UID NAME\n10115 {program}\n10116 {installer.APPLICATION_ID}",
            (
                f"mLastPausedActivity: ActivityRecord{{123 u0 "
                f"{installer.APPLICATION_ID}/.StandaloneActivity t1}}\n"
                f"  * Hist  #0: ActivityRecord{{124 u0 "
                f"{installer.APPLICATION_ID}.probe/.ProbeActivity t2}}"
            ),
        ]
    )
    monkeypatch.setattr(installer._Adb, "run", run)
    installer._require_idle(installer._Adb("adb", "headset"))
    assert all("force-stop" not in call.args for call in run.call_args_list)


@pytest.mark.parametrize("probe_first", [False, True])
def test_related_package_does_not_hide_a_running_game(
    monkeypatch: pytest.MonkeyPatch, probe_first: bool
) -> None:
    packages = [
        f"package:{installer.APPLICATION_ID} uid:10116",
        f"package:{installer.APPLICATION_ID}.probe uid:10110",
    ]
    if probe_first:
        packages.reverse()
    run = Mock(side_effect=["\n".join(packages), "UID NAME\n10116 GK3-VR.exe"])
    monkeypatch.setattr(installer._Adb, "run", run)
    with pytest.raises(RuntimeError, match="running session was preserved"):
        installer._require_idle(installer._Adb("adb", "headset"))
    assert all("force-stop" not in call.args for call in run.call_args_list)


def test_cli_owns_progress_and_does_not_launch_game(monkeypatch: pytest.MonkeyPatch) -> None:
    install = Mock(
        return_value=installer.InstalledPlayer(
            "headset", "a" * 64, 58, "The same private player is already installed"
        )
    )
    monkeypatch.setattr(installer, "install", install)
    result = CliRunner().invoke(
        app, ["vr", "standalone", "install", "--apk", "player.apk", "--bundle", "private.zip"]
    )
    assert result.exit_code == 0, result.output
    assert "The same private player is already installed" in result.output
    assert "Open GK3HD VR in the headset" in result.output
    assert install.call_args.kwargs["apk"].name == "player.apk"
    assert callable(install.call_args.kwargs["on_progress"])


def test_cli_reports_preserved_player_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        installer, "install", Mock(side_effect=RuntimeError("Existing files were preserved"))
    )
    result = CliRunner().invoke(
        app, ["vr", "standalone", "install", "--apk", "player.apk", "--bundle", "private.zip"]
    )
    assert result.exit_code == 1
    assert "Existing files were preserved" in result.output


def test_preflight_refuses_wrong_apk_before_device_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = Mock(side_effect=ValueError("Wrong APK"))
    probe = Mock()
    monkeypatch.setattr(installer, "_freeze_apk", frozen)
    monkeypatch.setattr(installer, "probe", probe)
    with pytest.raises(ValueError, match="Wrong APK"):
        installer.install(
            apk=tmp_path / "wrong.apk", bundle=tmp_path / "private.zip", adb=tmp_path / "adb"
        )
    probe.assert_not_called()


@pytest.fixture
def android_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[DeviceProbe, Mock, list[installer.InstallProgress]]:
    """An explicit private import with no real device or package writes."""
    bundle = tmp_path / "private.zip"
    bundle.write_bytes(b"private fixture")
    headset = DeviceProbe("test-headset", {"api": "32", "abis": "arm64-v8a"}, None, (), ())
    monkeypatch.setattr(installer, "_freeze_apk", Mock())
    monkeypatch.setattr(installer.runtime_assets, "apk_runtime", Mock(return_value=None))
    monkeypatch.setattr(installer, "cache_directory", lambda: tmp_path / "cache")
    monkeypatch.setattr(installer, "require_player_components", Mock())
    monkeypatch.setattr(installer, "supports_component_update", Mock(return_value=False))
    monkeypatch.setattr(
        installer, "read_bundle_manifest", Mock(return_value=BundleManifest(bundle, {}, 20, 1))
    )
    monkeypatch.setattr(
        installer, "inspect_bundle", Mock(return_value=BundleReceipt(bundle, "a" * 64, 1, 20))
    )
    monkeypatch.setattr(installer, "probe", Mock(return_value=headset))
    command = Mock(return_value="")

    def run(_adb: installer._Adb, *args: str, **_kwargs: object) -> str:
        command(*args)
        if args[:3] == ("shell", "df", "-k"):
            return "/data 100000000 1 99999999 1% /data"
        return ""

    monkeypatch.setattr(installer._Adb, "run", run)
    monkeypatch.setattr(installer, "_push", Mock())
    monkeypatch.setattr(installer, "_await_setup", Mock(return_value="Installed private player"))
    return headset, command, []


@pytest.mark.parametrize("already_installed", [False, True])
def test_runtime_is_provisioned_once_and_setup_starts_after_transfer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    *,
    already_installed: bool,
) -> None:
    _headset, command, _updates = android_install
    runtime = tmp_path / "runtime.zip"
    runtime.write_bytes(b"verified Winlator runtime")
    marker = "c" * 64
    prepare = Mock(return_value=runtime)
    monkeypatch.setattr(installer.runtime_assets, "apk_runtime", Mock(return_value=marker))
    monkeypatch.setattr(installer.runtime_assets, "prepare_transfer", prepare)
    read_data = installer._read_setup_data

    def read(
        adb: installer._Adb, name: Literal["inventory", "status", "runtime"], limit: int
    ) -> str:
        if name == "runtime":
            return (
                json.dumps({"runtime": marker}, separators=(",", ":")) if already_installed else ""
            )
        return read_data(adb, name, limit)

    monkeypatch.setattr(installer, "_read_setup_data", read)
    install_events = Mock()
    monkeypatch.setattr(installer, "_push", install_events.transfer)
    install_events.setup.return_value = "Ready"
    monkeypatch.setattr(installer, "_await_setup", install_events.setup)

    installer.install(
        apk=tmp_path / "player.apk", bundle=tmp_path / "private.zip", adb=tmp_path / "adb"
    )

    assert prepare.call_count == (0 if already_installed else 1)
    assert [call.args[1] for call in install_events.transfer.call_args_list] == (
        [tmp_path / "private.zip"] if already_installed else [tmp_path / "private.zip", runtime]
    )
    assert install_events.mock_calls[-1][0] == "setup"
    cleanup = next(
        call.args for call in command.call_args_list if call.args[:3] == ("shell", "rm", "-f")
    )
    assert len(cleanup) == 5
    if not already_installed:
        assert install_events.transfer.call_args.args[2] in cleanup


@pytest.mark.parametrize("eligible", [True, False])
def test_install_transfers_the_selected_component_or_full_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    *,
    eligible: bool,
) -> None:
    headset, _command, updates = android_install
    full_path = tmp_path / "private.zip"
    component_path = tmp_path / "update.zip"
    component_path.write_bytes(b"update")
    component = BundleReceipt(component_path, "b" * 64, 1, 20, component_update=True)
    choose = Mock(return_value=component if eligible else None)
    transfer = Mock()
    monkeypatch.setattr(installer, "supports_component_update", Mock(return_value=True))
    monkeypatch.setattr(installer, "_installed_receipt", Mock(return_value="installed manifest"))
    monkeypatch.setattr(installer, "component_bundle", choose)
    monkeypatch.setattr(installer, "_push", transfer)
    checksum = Mock(wraps=installer.inspect_bundle)
    monkeypatch.setattr(installer, "inspect_bundle", checksum)
    result = installer.install(
        apk=tmp_path / "player.apk",
        bundle=full_path,
        adb=tmp_path / "adb",
        on_progress=updates.append,
    )
    assert result.device == headset.device
    assert result.bundle_sha256 == (component.sha256 if eligible else "a" * 64)
    assert choose.call_args.args[1] == "installed manifest"
    assert transfer.call_args.args[1] == (component_path if eligible else full_path)
    if eligible:
        checksum.assert_not_called()
    else:
        checksum.assert_called_once_with(full_path)
    assert any("smaller game component" in update.message for update in updates) == eligible


def test_an_older_apk_rejects_a_component_archive_before_transfer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
) -> None:
    _headset, command, _updates = android_install
    full_path = tmp_path / "private.zip"
    monkeypatch.setattr(
        installer,
        "read_bundle_manifest",
        Mock(return_value=BundleManifest(full_path, {}, 20, 2)),
    )
    transfer = Mock()
    monkeypatch.setattr(installer, "_push", transfer)
    with pytest.raises(ValueError, match="requires a full game bundle"):
        installer.install(apk=tmp_path / "player.apk", bundle=full_path, adb=tmp_path / "adb")
    transfer.assert_not_called()
    assert not any(call.args[0] == "install" for call in command.call_args_list)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param((True, 2, True), id="bounded"),
        pytest.param((True, 33, False), id="full-copy-fallback"),
        pytest.param((False, 2, False), id="legacy"),
    ],
)
def test_component_update_can_fit_without_room_for_another_game_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    case: tuple[bool, int, bool],
) -> None:
    bounded, changes, fits = case
    _headset, command, _updates = android_install
    base = {f"game/{name}": {"size": 1, "sha256": "a" * 64} for name in REQUIRED_FILES}
    base.update(
        {f"game/Data/part-{i}.brn": {"size": 512 * 1024**2, "sha256": "b" * 64} for i in range(8)}
    )
    files = {f"game/change-{i}.dll": b"replacement" for i in range(changes)}
    base.update({name: {"size": 1, "sha256": "c" * 64} for name in files})
    desired = base | {
        name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in files.items()
    }
    bundle = tmp_path / "components.zip"
    with ZipFile(bundle, "x") as archive:
        archive.writestr("bundle.json", json.dumps({"schema": 2, "files": desired}))
        for name, data in files.items():
            archive.writestr(name, data)

    monkeypatch.setattr(installer, "read_bundle_manifest", read_bundle_manifest)
    monkeypatch.setattr(installer, "inspect_bundle", inspect_bundle)
    monkeypatch.setattr(installer, "_free_bytes", Mock(return_value=3 * 1024**3))
    monkeypatch.setattr(
        installer,
        "_installed_receipt",
        Mock(return_value=json.dumps({"schema": 1, "bundle_sha256": "a" * 64, "files": base})),
    )
    monkeypatch.setattr(
        installer,
        "supports_component_update",
        Mock(side_effect=lambda _apk, *, additions=False, **_options: bounded or not additions),
    )
    transfer = Mock()
    monkeypatch.setattr(installer, "_push", transfer)
    if fits:
        result = installer.install(apk=tmp_path / "player.apk", bundle=bundle, adb=tmp_path / "adb")
        assert result.files == len(desired)
        assert transfer.call_args.args[1] == bundle
    else:
        with pytest.raises(RuntimeError, match=r"Free at least 3\.1 GiB more on the headset"):
            installer.install(apk=tmp_path / "player.apk", bundle=bundle, adb=tmp_path / "adb")
        transfer.assert_not_called()
        assert not any(call.args[0] == "install" for call in command.call_args_list)


@pytest.mark.parametrize(
    "installed_state", ["base", "other", "already-applied", "interrupted", "interrupted-link"]
)
def test_explicit_component_update_checks_the_live_base_before_installing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    installed_state: str,
) -> None:
    _headset, command, _updates = android_install
    files = {}
    for index, name in enumerate([*sorted(REQUIRED_FILES), "Data/core.brn"]):
        source = tmp_path / f"fixture-{index}"
        source.write_bytes(name.encode())
        files[name] = source
    base = inspect_bundle(build_bundle(files, tmp_path / "base.zip").path)
    base_record = {"schema": 1, "bundle_sha256": base.sha256, "files": base.inventory}
    files["ddraw.dll"].write_bytes(b"current renderer")
    full = inspect_bundle(build_bundle(files, tmp_path / "full.zip").path)
    update = component_bundle(full, json.dumps(base_record), tmp_path / "update.zip")
    assert update is not None
    installed = base_record
    if installed_state == "other":
        files["Data/core.brn"].write_bytes(b"different original game data")
        other = inspect_bundle(build_bundle(files, tmp_path / "other.zip").path)
        installed = {"schema": 1, "bundle_sha256": other.sha256, "files": other.inventory}
    elif installed_state == "already-applied":
        installed = {"schema": 1, "bundle_sha256": update.sha256, "files": full.inventory}
    monkeypatch.setattr(installer, "read_bundle_manifest", read_bundle_manifest)
    monkeypatch.setattr(installer, "inspect_bundle", inspect_bundle)
    monkeypatch.setattr(installer, "supports_component_update", Mock(return_value=True))
    installed_record = json.dumps(installed)
    recovering = installed_state in {"interrupted", "interrupted-link"}
    post_recovery = [""] if installed_state == "interrupted-link" else []
    reads = Mock(
        side_effect=[installer._PENDING_INVENTORY, *post_recovery, installed_record]
        if recovering
        else None,
        return_value=installed_record,
    )
    monkeypatch.setattr(installer, "_installed_receipt", reads)
    monkeypatch.setattr(installer.time, "sleep", Mock())
    setup = Mock(return_value="Installed private player")
    monkeypatch.setattr(installer, "_await_setup", setup)
    transfer = Mock()
    monkeypatch.setattr(installer, "_push", transfer)
    if installed_state == "other":
        with pytest.raises(ValueError, match="does not match the installed player"):
            installer.install(apk=tmp_path / "player.apk", bundle=update.path, adb=tmp_path / "adb")
        transfer.assert_not_called()
        assert not any(call.args[0] == "install" for call in command.call_args_list)
    else:
        result = installer.install(
            apk=tmp_path / "player.apk", bundle=update.path, adb=tmp_path / "adb"
        )
        assert result.bundle_sha256 == update.sha256
        assert transfer.call_args.args[1] == update.path
        if recovering:
            setup_calls = setup.call_args_list
            assert len(setup_calls) == 2
            assert setup_calls[0].args[2] == ("--ez", "gk3hd_recover", "true")
            assert setup_calls[1].args[2][-1] == update.sha256
            assert reads.call_count == 2 + len(post_recovery)


@pytest.mark.parametrize("post_recovery", [installer._PENDING_INVENTORY, ""])
def test_unresolved_recovery_stops_before_transfer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    post_recovery: str,
) -> None:
    _, command, _ = android_install
    monkeypatch.setattr(
        installer,
        "_installed_receipt",
        Mock(side_effect=[installer._PENDING_INVENTORY, *[post_recovery] * 3]),
    )
    monkeypatch.setattr(installer.time, "sleep", Mock())
    transfer = Mock()
    monkeypatch.setattr(installer, "_push", transfer)
    with pytest.raises(RuntimeError, match="Cannot verify the private player"):
        installer.install(
            apk=tmp_path / "player.apk", bundle=tmp_path / "private.zip", adb=tmp_path / "adb"
        )
    transfer.assert_not_called()
    assert not any(call.args[0] == "install" for call in command.call_args_list)


@pytest.mark.parametrize("apk_state", ["matching", "changed", "unreadable"])
def test_game_update_reuses_only_the_exact_installed_apk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    apk_state: str,
) -> None:
    _headset, command, updates = android_install
    payload = b"local APK bytes"
    digest = hashlib.sha256(payload).hexdigest()
    existing_apk = "/data/app/org.gk3hd.standalone/base.apk"
    ordinary_run = installer._Adb.run

    def freeze(_source: Path, destination: Path) -> None:
        destination.write_bytes(payload)

    def run(adb: installer._Adb, *args: str, timeout: int = 15, checked: bool = True) -> str:
        if args[:3] == ("shell", "pm", "path"):
            return f"package:{existing_apk}"
        if args == ("shell", "sha256sum", existing_apk):
            if apk_state == "unreadable":
                msg = "ADB shell cannot read the installed APK"
                raise RuntimeError(msg)
            return f"{digest if apk_state == 'matching' else '0' * 64}  {existing_apk}"
        return ordinary_run(adb, *args, timeout=timeout, checked=checked)

    setup = Mock(return_value="Updated private player")
    monkeypatch.setattr(installer, "_freeze_apk", freeze)
    monkeypatch.setattr(installer._Adb, "run", run)
    monkeypatch.setattr(installer, "_await_setup", setup)
    installer.install(
        apk=tmp_path / "player.apk",
        bundle=tmp_path / "private.zip",
        adb=tmp_path / "adb",
        on_progress=updates.append,
    )
    assert any(call.args[0] == "install" for call in command.call_args_list) == (
        apk_state != "matching"
    )
    assert any("Reusing the verified" in update.message for update in updates) == (
        apk_state == "matching"
    )
    setup.assert_called_once()


@pytest.mark.parametrize("program", ["GK3-VR.exe", "gk3hd-wine-launcher.exe", None])
def test_running_session_prevents_package_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    program: str | None,
) -> None:
    _headset, command, updates = android_install

    def run(_adb: installer._Adb, *args: str, **_kwargs: object) -> str:
        command(*args)
        if args[:4] == ("shell", "cmd", "package", "list"):
            return f"package:{installer.APPLICATION_ID} uid:10116"
        if args[:2] == ("shell", "ps"):
            return "UID NAME" if program is None else f"UID NAME\n10116 {program}"
        if args == ("shell", "dumpsys", "activity", "activities") and program is None:
            return (
                f"    * Hist  #0: ActivityRecord{{3fb5d13 u0 "
                f"{installer.APPLICATION_ID}/com.winlator.StandaloneActivity t2456}}"
            )
        return ""

    monkeypatch.setattr(installer._Adb, "run", run)
    with pytest.raises(RuntimeError, match="running session was preserved"):
        installer.install(
            apk=tmp_path / "player.apk",
            bundle=tmp_path / "private.zip",
            adb=tmp_path / "adb",
            on_progress=updates.append,
        )
    assert not any(call.args[0] == "install" for call in command.call_args_list)
    assert all("force-stop" not in call.args for call in command.call_args_list)
    assert not any(update.stage == "app" for update in updates)


@pytest.mark.parametrize("interrupted_transfer", [True, False])
def test_update_keeps_current_player_when_transfer_is_interrupted_or_play_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    *,
    interrupted_transfer: bool,
) -> None:
    _headset, command, updates = android_install
    transfer = Mock(
        side_effect=RuntimeError("Transfer interrupted") if interrupted_transfer else None
    )
    idle = Mock(side_effect=None if interrupted_transfer else [None, RuntimeError("Playing")])
    monkeypatch.setattr(installer, "_push", transfer)
    monkeypatch.setattr(installer, "_require_idle", idle)
    with pytest.raises(
        RuntimeError, match="Transfer interrupted" if interrupted_transfer else "Playing"
    ):
        installer.install(
            apk=tmp_path / "player.apk",
            bundle=tmp_path / "private.zip",
            adb=tmp_path / "adb",
            on_progress=updates.append,
        )

    remote = transfer.call_args.args[2]
    assert any(
        call.args[:3] == ("shell", "rm", "-f") and remote in call.args[3:]
        for call in command.call_args_list
    )
    assert not any(call.args[0] == "install" for call in command.call_args_list)
    assert not any(update.stage == "app" for update in updates)


@pytest.mark.parametrize("transfer_intact", [True, False])
def test_retry_after_apk_update_recovers_the_game_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    *,
    transfer_intact: bool,
) -> None:
    _headset, command, updates = android_install
    run = installer._Adb.run
    transfer = Mock()
    installs = 0
    disconnected = False
    removed = []

    def adb(adb: installer._Adb, *args: str, timeout: int = 15, checked: bool = True) -> str:
        nonlocal installs, disconnected
        if args[:2] == ("install", "-r"):
            installs += 1
            disconnected = True
            return "Success"
        if disconnected:
            msg = "USB disconnected"
            raise RuntimeError(msg)
        if args[:4] == ("shell", "stat", "-c", "%s"):
            assert args[4] == transfer.call_args.args[2]
            return str((tmp_path / "private.zip").stat().st_size)
        if args[:2] == ("shell", "sha256sum"):
            assert args[2] == transfer.call_args.args[2]
            return "a" * 64 if transfer_intact else "b" * 64
        if args[:3] == ("shell", "rm", "-f"):
            removed.append(args[3])
        return run(adb, *args, timeout=timeout, checked=checked)

    monkeypatch.setattr(installer._Adb, "run", adb)
    monkeypatch.setattr(installer, "_push", transfer)
    monkeypatch.setattr(installer, "_installed_apk_matches", lambda *_args: installs == 1)

    def install() -> installer.InstalledPlayer:
        return installer.install(
            apk=tmp_path / "player.apk",
            bundle=tmp_path / "private.zip",
            adb=tmp_path / "adb",
            on_progress=updates.append,
        )

    with pytest.raises(RuntimeError, match="USB disconnected"):
        install()
    remote = transfer.call_args.args[2]
    assert removed == []
    disconnected = False

    assert install().message == "Installed private player"
    assert installs == 1
    assert transfer.call_count == (1 if transfer_intact else 2)
    assert removed[0] == remote
    assert len(removed) == (1 if transfer_intact else 2)
    assert not list((tmp_path / "cache").rglob("*.json"))
    assert not any("force-stop" in call.args for call in command.call_args_list)


def test_game_opened_during_apk_check_survives_an_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
) -> None:
    _headset, command, updates = android_install
    bundle = tmp_path / "private.zip"
    installed_apk = "/data/app/gk3hd/base.apk"
    original_run = installer._Adb.run
    playing = False
    start_on_digest = True

    def run(adb: installer._Adb, *args: str, timeout: int = 15, checked: bool = True) -> str:
        nonlocal playing, start_on_digest
        response = original_run(adb, *args, timeout=timeout, checked=checked)
        if args[:5] == ("shell", "cmd", "package", "list", "packages"):
            return f"package:{installer.APPLICATION_ID} uid:10116"
        if args == ("shell", "pm", "path", installer.APPLICATION_ID):
            return f"package:{installed_apk}"
        if args[:4] == ("shell", "stat", "-c", "%s"):
            return str(bundle.stat().st_size)
        if args[:2] == ("shell", "sha256sum"):
            checking_apk = args[2] == installed_apk
            if checking_apk and start_on_digest:
                playing = True
                start_on_digest = False
            digest = ("b" if checking_apk else "a") * 64
            return f"{digest}  {args[2]}"
        if args[:2] == ("shell", "ps") and playing:
            return "UID NAME\n10116 GK3-VR.exe"
        return response

    monkeypatch.setattr(installer._Adb, "run", run)
    monkeypatch.setattr(installer, "_freeze_apk", lambda _, frozen: frozen.write_bytes(b"fixture"))

    def install() -> installer.InstalledPlayer:
        return installer.install(
            apk=tmp_path / "player.apk",
            bundle=bundle,
            adb=tmp_path / "adb",
            on_progress=updates.append,
        )

    with pytest.raises(RuntimeError, match="running session was preserved"):
        install()

    assert playing
    assert not any(call.args[0] == "install" for call in command.call_args_list)
    assert not any("force-stop" in call.args for call in command.call_args_list)
    playing = False
    assert install().message == "Installed private player"
    assert any("Reusing the verified transfer" in update.message for update in updates)


@pytest.mark.parametrize("finished", [False, True])
def test_retry_follows_setup_already_running_or_finished_on_the_headset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    *,
    finished: bool,
) -> None:
    _headset, _command, _updates = android_install
    run = installer._Adb.run
    setup = Mock(side_effect=[RuntimeError("USB disconnected"), "Updated private player"])
    transfer = Mock()
    active = False

    def adb(adb: installer._Adb, *args: str, timeout: int = 15, checked: bool = True) -> str:
        if active and args[:3] == ("exec-out", "content", "read") and args[-1].endswith("/status"):
            token = setup.call_args_list[0].args[1]
            return json.dumps(
                {
                    "token": token,
                    "stage": "complete" if finished else "update",
                    "completed": 2,
                    "total": 3,
                    "message": "Updated private player" if finished else "Updating game files",
                }
            )
        if active and args[:4] == ("shell", "dumpsys", "activity", "services"):
            return f"* ServiceRecord{{1 u0 {installer._SETUP}}}"
        return run(adb, *args, timeout=timeout, checked=checked)

    monkeypatch.setattr(installer._Adb, "run", adb)
    monkeypatch.setattr(installer, "_push", transfer)
    monkeypatch.setattr(installer, "_await_setup", setup)
    monkeypatch.setattr(installer, "_installed_apk_matches", lambda *_args: active)

    def install() -> installer.InstalledPlayer:
        return installer.install(
            apk=tmp_path / "player.apk", bundle=tmp_path / "private.zip", adb=tmp_path / "adb"
        )

    with pytest.raises(RuntimeError, match="USB disconnected"):
        install()
    active = True

    assert install().message == "Updated private player"
    transfer.assert_called_once()
    if finished:
        setup.assert_called_once()
    else:
        assert setup.call_args.kwargs == {"start": False}
        assert setup.call_args.args[1] == setup.call_args_list[0].args[1]
    assert not list((tmp_path / "cache").rglob("*.json"))


@pytest.mark.parametrize("advertised", [True, False])
def test_openxr_player_import_does_not_require_vendor_libraries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    *,
    advertised: bool,
) -> None:
    headset, command, updates = android_install
    status = (
        "runtime advertised; session not tested"
        if advertised
        else "query denied; runtime availability unknown"
    )
    headset = DeviceProbe(
        headset.device, headset.properties, None, (Broker("test-broker", status, ""),), ()
    )
    monkeypatch.setattr(installer, "probe", Mock(return_value=headset))
    result = installer.install(
        apk=tmp_path / "player.apk",
        bundle=tmp_path / "private.zip",
        adb=tmp_path / "adb",
        on_progress=updates.append,
    )
    assert result.device == headset.device
    assert any(call.args[0] == "install" for call in command.call_args_list)
    assert any(update.stage == "warning" for update in updates) is not advertised
    assert all("android.permission.CAMERA" not in call.args for call in command.call_args_list)


@pytest.mark.parametrize(
    ("api", "abis"),
    [
        ("25", "arm64-v8a"),
        ("unknown", "arm64-v8a"),
        ("32", "armeabi-v7a"),
        ("32", "arm64-v8a-extra"),
    ],
)
def test_incompatible_android_player_is_rejected_before_device_changes(
    tmp_path: Path,
    android_install: tuple[DeviceProbe, Mock, list[installer.InstallProgress]],
    api: str,
    abis: str,
) -> None:
    headset, command, _updates = android_install
    headset.properties.update(api=api, abis=abis)
    with pytest.raises(RuntimeError, match="requires Android API 26"):
        installer.install(
            apk=tmp_path / "player.apk", bundle=tmp_path / "private.zip", adb=tmp_path / "adb"
        )
    command.assert_not_called()
