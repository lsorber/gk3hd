"""ADB installation of the explicitly supplied standalone development player."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from gk3hd.system.files import atomic_write, cache_directory, is_sha256, json_bytes, sha256_file
from gk3hd.system.locking import ExclusiveFileLock
from gk3hd.vr.android import runtime_assets
from gk3hd.vr.standalone.apk import (
    APPLICATION_ID,
    MAX_APK_BYTES,
    require_player_apk,
    require_player_components,
    supports_component_update,
)
from gk3hd.vr.standalone.bundle import (
    MAX_ARCHIVE_BYTES,
    MAX_PAYLOAD_BYTES,
    BundleManifest,
    BundleReceipt,
    component_bundle,
    inspect_bundle,
    read_bundle_manifest,
    require_component_base,
    staging_payload_bytes,
)
from gk3hd.vr.standalone.device import (
    USB_RETRY,
    probe,
    require_install_platform,
    resolve_adb,
    select_device,
    usb_problem,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO

_SETUP = f"{APPLICATION_ID}/com.winlator.ManagedSetupService"
_SETUP_DATA = f"content://{APPLICATION_ID}.setup"
_STAGES = frozenset(
    {"runtime", "verify", "extract", "container", "update", "configure", "complete", "failed"}
)
_RESERVE = 2 * 1024**3
_SETUP_SECONDS = 600
_PUSH_SECONDS = 600
_MAX_EYE_AXIS = 4096
_FIRST_STATUS_SECONDS = 30
_POLL_SECONDS = 0.25
_ACTIVITY_RETIRE_SECONDS = 2
_STATUS_POLL_SECONDS = 1
_MAX_QUEUED_STATUS = 32
_DF_COLUMNS = 6
_MAX_INSTALLED_RECEIPT = 2 * 1024**2 + 512
_MAX_SETUP_STATUS = 64 * 1024
_MAX_TRANSFER_RECORD = 4096
_PENDING_INVENTORY = '{"component_update_pending":true}'
_SETUP_BUSY = "The headset is still installing GK3HD VR. Wait for it to finish, then try again."


@dataclass(frozen=True, slots=True)
class InstallProgress:
    """One CLI-owned progress update; no raw library or ADB output."""

    stage: str
    message: str
    completed: int = 0
    total: int | None = None
    unit: Literal["bytes", "items"] = "bytes"


@dataclass(frozen=True, slots=True)
class InstalledPlayer:
    """Verified private import, not hardware/gameplay acceptance."""

    device: str
    bundle_sha256: str
    files: int
    message: str


@dataclass(frozen=True, slots=True)
class _Transfer:
    token: str
    archive_sha256: str
    inventory_sha256: str

    @property
    def remote(self) -> str:
        return f"/sdcard/Download/gk3hd-standalone-{self.token}.zip"

    @property
    def runtime_remote(self) -> str:
        return f"/sdcard/Download/gk3hd-runtime-{self.token}.zip"

    def write(self, path: Path) -> None:
        atomic_write(
            path,
            json_bytes(
                {
                    "token": self.token,
                    "archive": self.archive_sha256,
                    "inventory": self.inventory_sha256,
                }
            ),
        )

    @classmethod
    def read(cls, path: Path) -> _Transfer | None:
        if not path.exists():
            return None
        if path.stat().st_size <= _MAX_TRANSFER_RECORD:
            try:
                values = json.loads(path.read_bytes())
            except (UnicodeDecodeError, json.JSONDecodeError):
                values = None
            if isinstance(values, dict):
                token, archive, inventory = (
                    values.get(key) for key in ("token", "archive", "inventory")
                )
                if (
                    isinstance(token, str)
                    and re.fullmatch(r"[0-9a-f]{32}", token)
                    and is_sha256(archive)
                    and is_sha256(inventory)
                ):
                    return cls(token, archive, inventory)
        msg = f"The previous transfer record is invalid. Move this file aside and retry.\n{path}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _Adb:
    executable: str
    device: str

    def command(self, *args: str) -> list[str]:
        return [self.executable, "-s", self.device, *args]

    def run(self, *args: str, timeout: int = 15, checked: bool = True) -> str:
        try:
            result = subprocess.run(  # noqa: S603 - explicit arguments, no host shell.
                self.command(*args),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            msg = f"The headset stopped responding over USB. {USB_RETRY}"
            raise RuntimeError(msg) from error
        if checked and result.returncode:
            detail = (result.stderr or result.stdout).strip()[-2000:]
            problem = usb_problem(detail)
            if problem is None and args[:2] == ("install", "-r"):
                problem = _apk_install_problem(detail)
            raise RuntimeError(problem or f"Headset command failed.\n{detail}")
        return result.stdout.strip()


def _apk_install_problem(detail: str) -> str | None:
    if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in detail:
        return (
            "The installed GK3HD VR app uses a different signing key. "
            "Android kept the existing app and its data. "
            "Use a release signed with the same key. "
            "Before switching builds, run gk3hd vr standalone backup and check the ZIP."
        )
    if "INSTALL_FAILED_VERSION_DOWNGRADE" in detail:
        return (
            "The headset already has a newer GK3HD VR app. "
            "Run uvx gk3hd@latest vr standalone install to use the latest public release."
        )
    if "INSTALL_FAILED_INSUFFICIENT_STORAGE" in detail:
        return "The headset is out of space for the app. Free up headset storage and retry."
    return None


def _launch_prompt(activity: str) -> str | None:
    """Explain known headset prompts without dismissing them or changing policy."""
    if "OculusLinkAvailableDialogActivity" in activity:
        return "Dismiss the Quest Link connection prompt in the headset, then open GK3HD VR again"
    if "LaunchCheckControllerRequiredDialogActivity" in activity:
        return "Wake both headset controllers and choose Continue in the headset to open GK3HD VR"
    if "FirstTimeNuxExclusiveSystemDialogActivity" in activity:
        return "Finish headset setup in the headset, then open GK3HD VR again"
    if "GuardianDialogActivity" in activity or activity.startswith("com.pimax.vrguardian/"):
        return "Check your play area and complete the boundary prompt in the headset"
    return None


def _current_prompt(adb: _Adb) -> str | None:
    """Inspect current prompts once; paused activity names are not evidence."""
    try:
        activities = adb.run("shell", "dumpsys", "activity", "activities", timeout=3, checked=False)
    except RuntimeError:
        activities = ""
    # Quest keeps resumed panels on several displays after focus moves away.
    # Prefer the actual focused app so a retained Link dialog does not become
    # advice to dismiss a prompt the user has already closed.
    focused = re.findall(r"(?m)^\s*mFocusedApp=.*?\s([\w.]+/[\w.$]+)", activities)
    current = focused or re.findall(
        r"(?m)^\s*(?:topResumedActivity|mResumedActivity|ResumedActivity)\s*[:=].*?\s([\w.]+/[\w.$]+)",
        activities,
    )
    for activity in current:
        message = _launch_prompt(activity)
        if message is not None:
            return message
    return None


def _launch_timeout_message(adb: _Adb) -> str:
    """A launch timeout does not prove a USB failure."""
    prompt = _current_prompt(adb)
    if prompt is not None:
        return prompt
    try:
        power = adb.run("shell", "dumpsys", "vrpowermanager", timeout=3, checked=False)
    except RuntimeError:
        power = ""
    state = re.search(r"(?m)^State:\s*(\w+)\s*$", power)
    if state is not None and state[1] in {"STANDBY", "HEADSET_UNMOUNTED", "WAITING_FOR_SLEEP_MSG"}:
        return (
            "GK3HD VR launch was not confirmed while the headset reports standby or no wearer. "
            "Wake it and put it on, then open GK3HD VR from its Library"
        )
    return "GK3HD VR launch was not confirmed. Check the headset before trying again"


def _launch_graphics_args(
    *, experimental_compressed: bool, experimental_eye_copy: bool, eye_resolution: str | None
) -> list[str]:
    arguments = []
    if experimental_compressed:
        arguments.extend(("--ez", "gk3hd_experimental_compressed", "true"))
    if experimental_eye_copy:
        arguments.extend(("--ez", "gk3hd_experimental_eye_copy", "true"))
    if eye_resolution is not None:
        match = re.fullmatch(r"([1-9][0-9]{0,3})x([1-9][0-9]{0,3})", eye_resolution)
        if match is None or max(map(int, match.groups())) > _MAX_EYE_AXIS:
            msg = f"Eye resolution must be WIDTHxHEIGHT, with dimensions from 1 to {_MAX_EYE_AXIS}"
            raise ValueError(msg)
        arguments.extend(("--es", "gk3hd_eye_resolution", eye_resolution))
    return arguments


def launch(
    *,
    adb: Path | None = None,
    device: str | None = None,
    experimental_compressed: bool = False,
    experimental_eye_copy: bool = False,
    eye_resolution: str | None = None,
) -> str:
    """Open the same checked app entry as the headset library, without reinstalling."""
    graphics_args = _launch_graphics_args(
        experimental_compressed=experimental_compressed,
        experimental_eye_copy=experimental_eye_copy,
        eye_resolution=eye_resolution,
    )
    executable = resolve_adb(adb)
    selected = _Adb(executable, select_device(executable, device))
    if not selected.run("shell", "pm", "path", APPLICATION_ID).startswith("package:"):
        msg = (
            "GK3HD VR is not installed on this headset. Run uvx gk3hd@latest vr standalone install."
        )
        raise RuntimeError(msg)
    arguments = [
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        f"{APPLICATION_ID}/com.winlator.StandaloneActivity",
        *graphics_args,
    ]
    try:
        result = selected.run(*arguments)
    except RuntimeError as error:
        if not isinstance(error.__cause__, subprocess.TimeoutExpired):
            raise
        raise RuntimeError(_launch_timeout_message(selected)) from error
    if "Error:" in result or "Exception" in result:
        msg = f"Headset could not open GK3HD VR: {result[-2000:]}"
        raise RuntimeError(msg)
    activity = re.search(r"^Activity:\s*(\S+)", result, re.MULTILINE)
    if activity is not None and not activity[1].startswith(f"{APPLICATION_ID}/"):
        msg = _launch_prompt(activity[1]) or (
            "The headset opened a system prompt instead of GK3HD VR; continue in the headset"
        )
        raise RuntimeError(msg)
    if re.search(r"(?m)^Status:[ \t]*timeout[ \t]*$", result):
        raise RuntimeError(_launch_timeout_message(selected))
    return selected.device


def _free_bytes(output: str) -> int:
    for line in reversed(output.splitlines()):
        columns = line.split()
        if len(columns) >= _DF_COLUMNS and columns[3].isdecimal():
            return int(columns[3]) * 1024
    msg = "Cannot establish headset free space; installation has not started"
    raise RuntimeError(msg)


def require_player_closed(*, adb: Path | None, device: str) -> None:
    """Check the selected headset before starting download and preparation."""
    _require_idle(_Adb(resolve_adb(adb), device))


def _require_idle(adb: _Adb) -> None:
    package = adb.run("shell", "cmd", "package", "list", "packages", "-U", APPLICATION_ID)
    match = re.search(rf"^package:{re.escape(APPLICATION_ID)} uid:(\d+)$", package, re.MULTILINE)
    if match is None:
        return
    msg = "Close GK3HD VR before installing; its running session was preserved"
    # The library launcher and recovery dialog can be open before Wine starts.
    # Look at task entries to exclude cached processes and past focus records.
    player_activity = re.compile(
        r"(?m)^[ \t]*\*[ \t]+Hist[ \t]+#\d+:[ \t]+ActivityRecord\{"
        rf"[^\n]*[ \t]{re.escape(APPLICATION_ID)}/",
    )
    guest_processes = {(match[1], "GK3-VR.exe"), (match[1], "gk3hd-wine-launcher.exe")}
    deadline = time.monotonic() + _ACTIVITY_RETIRE_SECONDS
    while True:
        processes = adb.run("shell", "ps", "-A", "-o", "UID,NAME")
        if any(tuple(line.split()) in guest_processes for line in processes.splitlines()):
            raise RuntimeError(msg)
        activities = adb.run("shell", "dumpsys", "activity", "activities")
        if not player_activity.search(activities):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(msg)
        # Android can retain the activity briefly after an ordinary game Quit.
        # Recheck both witnesses in case the launcher starts a new guest.
        time.sleep(_POLL_SECONDS)


def _read_setup_data(adb: _Adb, name: Literal["inventory", "status", "runtime"], limit: int) -> str:
    try:
        record = adb.run(
            "exec-out", "content", "read", "--uri", f"{_SETUP_DATA}/{name}", checked=False
        )
    except RuntimeError:
        return ""
    return record if record.startswith("{") and len(record.encode("utf-8")) <= limit else ""


def _installed_receipt(adb: _Adb) -> str:
    if receipt := _read_setup_data(adb, "inventory", _MAX_INSTALLED_RECEIPT):
        return receipt
    # Earlier local development APKs have no setup metadata provider.
    command = (
        "set -- files/rootfs/home/xuser-*/.wine/drive_c/gk3hd-vr/.gk3hd-standalone.json; "
        '[ "$#" = 1 ] && [ -f "$1" ] && [ ! -L "$1" ] && '
        f'head -c {_MAX_INSTALLED_RECEIPT + 1} "$1"'
    )
    try:
        receipt = adb.run(
            "shell", "run-as", APPLICATION_ID, "sh", "-c", shlex.quote(command), checked=False
        )
    except RuntimeError:
        return ""
    return receipt if len(receipt) <= _MAX_INSTALLED_RECEIPT else ""


def _transfer_bundle(
    adb: _Adb,
    apk: Path,
    manifest: BundleManifest,
    staging: Path,
    notify: Callable[[InstallProgress], None],
) -> tuple[BundleReceipt, int]:
    installed = _installed_receipt(adb)
    if installed == _PENDING_INVENTORY:
        _await_setup(adb, uuid4().hex, ("--ez", "gk3hd_recover", "true"), notify)
        installed = _installed_receipt(adb)
        # Recovery may finish just as USB drops or the metadata provider
        # restarts. Retry the read without running recovery or transferring again.
        for _ in range(2):
            if installed:
                break
            time.sleep(_POLL_SECONDS)
            installed = _installed_receipt(adb)
        if installed == _PENDING_INVENTORY or not installed:
            msg = "Cannot verify the private player after recovering its interrupted update"
            raise RuntimeError(msg)
    if not supports_component_update(
        apk, verification_only=manifest.verification_only, additions=manifest.component_additions
    ):
        if manifest.component_update:
            msg = "This GK3HD VR app requires a full game bundle"
            raise ValueError(msg)
        receipt = inspect_bundle(manifest.path)
        return receipt, receipt.payload_bytes
    bounded_components = supports_component_update(apk, additions=True)
    if manifest.component_update:
        receipt = inspect_bundle(manifest.path)
        require_component_base(receipt, installed)
    else:
        candidate = component_bundle(
            manifest,
            installed,
            staging / "update.zip",
            allow_verification=supports_component_update(apk, verification_only=True),
            allow_additions=bounded_components,
        )
        receipt = candidate if candidate is not None else inspect_bundle(manifest.path)
    return receipt, staging_payload_bytes(receipt, installed, bounded_components=bounded_components)


def _status(line: str, token: str) -> InstallProgress | None:
    start = line.find("{")
    if start < 0:
        return None
    try:
        record = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict) or record.get("token") != token:
        return None
    stage, done, total, message = (
        record.get(key) for key in ("stage", "completed", "total", "message")
    )
    if (
        not isinstance(stage, str)
        or stage not in _STAGES
        or type(done) is not int
        or type(total) is not int
        or not 0 <= done <= total <= MAX_PAYLOAD_BYTES
        or not isinstance(message, str)
    ):
        msg = "Malformed private installer status; no success is assumed"
        raise RuntimeError(msg)
    if stage == "verify" and total > MAX_ARCHIVE_BYTES:
        msg = "Installer transfer verification exceeds its archive bound"
        raise RuntimeError(msg)
    return InstallProgress(stage, message, done, total or None)


def _read_lines(stream: TextIO, queue: Queue[str | None]) -> None:
    try:
        for line in stream:
            queue.put(line)
    finally:
        queue.put(None)


def _push(
    adb: _Adb,
    bundle: Path,
    remote: str,
    notify: Callable[[InstallProgress], None],
    *,
    label: str = "private game bundle",
) -> None:
    total = bundle.stat().st_size
    started = time.monotonic()
    # A full HD bundle can exceed ten minutes over USB 2. Budget for 4 MiB/s
    # plus setup, retaining a finite deadline even if the progress probe stalls.
    seconds = max(_PUSH_SECONDS, total / (4 * 1024**2) + 60)
    description = f"Transferring the {label}"
    notify(InstallProgress("transfer", description, 0, total))
    with subprocess.Popen(  # noqa: S603 - generated safe remote name, no host shell.
        adb.command("push", "-q", "-Z", str(bundle), remote),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as child:
        try:
            while child.poll() is None:
                if time.monotonic() - started > seconds:
                    msg = f"{label.capitalize()} transfer timed out. {USB_RETRY}"
                    raise RuntimeError(msg)
                try:
                    size = adb.run("shell", "stat", "-c", "%s", remote, checked=False)
                except RuntimeError:
                    # A busy USB link can delay a separate shell query while
                    # push continues. That observation neither fails the push
                    # nor authorizes success: require its exit and native hash
                    # verification before installing any private player files.
                    size = ""
                if size.isdecimal():
                    notify(
                        InstallProgress(
                            "transfer",
                            description,
                            min(int(size), total),
                            total,
                        )
                    )
                time.sleep(1)
            if child.returncode:
                detail = child.stderr.read().strip()[-2000:] if child.stderr is not None else ""
                msg = usb_problem(detail) or f"{label.capitalize()} transfer failed.\n{detail}"
                raise RuntimeError(msg)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
    notify(InstallProgress("transfer", description, total, total))


def _setup_line(
    queue: Queue[str | None],
    read_status: Callable[[], str],
    *,
    polling: bool,
    streaming: bool,
) -> str | None:
    if not polling:
        try:
            return queue.get(timeout=_POLL_SECONDS)
        except Empty:
            return ""
    if not streaming:
        time.sleep(_STATUS_POLL_SECONDS)
    try:
        return read_status()
    except RuntimeError:
        # USB may reconnect before the existing setup deadline.
        return ""


def _queued_setup_result(queue: Queue[str | None], token: str) -> InstallProgress | None:
    # Persisted progress can be newer than buffered log messages. Only accept
    # the matching terminal result from this stream after switching to polling.
    for _ in range(_MAX_QUEUED_STATUS):
        try:
            line = queue.get_nowait()
        except Empty:
            break
        if line is None:
            break
        status = _status(line, token)
        if status is not None and status.stage in {"complete", "failed"}:
            return status
    return None


def _consume_setup(
    queue: Queue[str | None],
    token: str,
    notify: Callable[[InstallProgress], None],
    read_status: Callable[[], str],
) -> str:
    started = time.monotonic()
    deadline = started + _SETUP_SECONDS
    first_deadline = started + _FIRST_STATUS_SECONDS
    next_status_poll = started + _STATUS_POLL_SECONDS
    streaming = True
    last_status: InstallProgress | None = None
    while (now := time.monotonic()) < deadline:
        if last_status is None and now >= first_deadline:
            msg = (
                "The headset did not report setup progress. "
                "Reconnect USB and run the same install command again."
            )
            raise RuntimeError(msg)
        polling = not streaming or now >= next_status_poll
        if polling:
            next_status_poll = now + _STATUS_POLL_SECONDS
        status = None if streaming else _queued_setup_result(queue, token)
        if status is None:
            line = _setup_line(queue, read_status, polling=polling, streaming=streaming)
            if line is None:
                streaming = False
                continue
            status = _status(line, token)
        if status is None:
            continue
        # Once a matching persisted status is available, follow it without
        # replaying older queued lines.
        streaming = not polling
        next_status_poll = time.monotonic() + _STATUS_POLL_SECONDS
        if status == last_status:
            continue
        last_status = status
        notify(status)
        if status.stage == "failed":
            raise RuntimeError(status.message)
        if status.stage == "complete":
            return status.message
    msg = (
        "The headset did not report completion. "
        "Reconnect USB and run the same install command again."
    )
    raise RuntimeError(msg)


def _read_setup_status(adb: _Adb) -> str:
    if status := _read_setup_data(adb, "status", _MAX_SETUP_STATUS):
        return status
    return adb.run(
        "exec-out", "run-as", APPLICATION_ID, "cat", "files/gk3hd-setup.json", checked=False
    )


def _await_setup(
    adb: _Adb,
    token: str,
    options: tuple[str, ...],
    notify: Callable[[InstallProgress], None],
    *,
    start: bool = True,
) -> str:
    queue: Queue[str | None] = Queue()
    with subprocess.Popen(  # noqa: S603 - constant log filters, no host shell.
        adb.command("logcat", "-T", "1", "-v", "brief", "-s", "GK3HDSetup:I", "*:S"),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as logs:
        if logs.stdout is None:
            msg = "Cannot observe the private installer"
            raise RuntimeError(msg)
        reader = threading.Thread(target=_read_lines, args=(logs.stdout, queue), daemon=True)
        reader.start()
        try:
            if start:
                _require_idle(adb)
                launched = adb.run(
                    "shell",
                    "am",
                    "start-foreground-service",
                    "-n",
                    _SETUP,
                    "--es",
                    "gk3hd_install_id",
                    token,
                    *options,
                )
                if re.search(r"Error:|Error type|Exception|Permission Denial", launched):
                    msg = f"Cannot start the private installer: {launched[-2000:]}"
                    raise RuntimeError(msg)
            return _consume_setup(queue, token, notify, lambda: _read_setup_status(adb))
        finally:
            if logs.poll() is None:
                logs.terminate()
            logs.wait(timeout=10)
            reader.join(timeout=2)


def _freeze_apk(source: Path, destination: Path) -> None:
    total = 0
    with source.open("rb") as incoming, destination.open("xb") as output:
        while block := incoming.read(128 * 1024):
            total += len(block)
            if total > MAX_APK_BYTES:
                msg = "Standalone APK exceeds its size limit"
                raise ValueError(msg)
            output.write(block)
    require_player_apk(destination)


def _installed_apk_matches(adb: _Adb, frozen: Path) -> bool:
    """Reuse a single installed APK only after verifying the exact bytes."""
    try:
        paths = adb.run("shell", "pm", "path", APPLICATION_ID).splitlines()
        if len(paths) != 1 or not paths[0].startswith("package:/"):
            return False
        path = paths[0].removeprefix("package:")
        if not path.endswith(".apk"):
            return False
        digest = adb.run("shell", "sha256sum", shlex.quote(path)).split(maxsplit=1)
    except RuntimeError:
        return False
    return bool(digest and digest[0] == sha256_file(frozen))


def _discard_transfer(
    adb: _Adb, journal: Path, transfer: _Transfer, notify: Callable[[InstallProgress], None]
) -> bool:
    try:
        adb.run("shell", "rm", "-f", transfer.remote, transfer.runtime_remote)
    except RuntimeError:
        notify(
            InstallProgress("warning", "Reconnect USB and rerun install to clean up the transfer")
        )
        return False
    journal.unlink()
    return True


def _require_discard(
    adb: _Adb, journal: Path, transfer: _Transfer, notify: Callable[[InstallProgress], None]
) -> None:
    if not _discard_transfer(adb, journal, transfer, notify):
        msg = "Could not clear the previous transfer. Reconnect USB and run install again."
        raise RuntimeError(msg)


def _previous_setup(
    adb: _Adb, transfer: _Transfer, notify: Callable[[InstallProgress], None]
) -> InstallProgress | None:
    """Follow the owned setup across disconnects without restarting an active import."""
    status = _status(_read_setup_status(adb), transfer.token)
    if status is not None and status.stage in {"complete", "failed"}:
        return status
    if not _setup_running(adb):
        return status
    if status is None:
        raise RuntimeError(_SETUP_BUSY)
    message = _await_setup(adb, transfer.token, (), notify, start=False)
    return InstallProgress("complete", message, 1, 1)


def _setup_running(adb: _Adb) -> bool:
    services = adb.run("shell", "dumpsys", "activity", "services", _SETUP)
    return re.search(r"\bServiceRecord\{[^\n]*\b" + re.escape(_SETUP) + r"\b", services) is not None


def _require_setup_idle(adb: _Adb) -> None:
    if _setup_running(adb):
        raise RuntimeError(_SETUP_BUSY)


def _reuse_transfer(adb: _Adb, transfer: _Transfer, receipt: BundleReceipt) -> bool:
    if transfer.archive_sha256 != receipt.sha256:
        return False
    size = adb.run("shell", "stat", "-c", "%s", transfer.remote, checked=False)
    if not size.isdecimal() or int(size) != receipt.path.stat().st_size:
        return False
    digest = adb.run("shell", "sha256sum", transfer.remote, timeout=_SETUP_SECONDS).split()
    return bool(digest and digest[0] == receipt.sha256)


def _require_transfer_space(adb: _Adb, needed: int) -> None:
    available = min(
        _free_bytes(adb.run("shell", "df", "-k", mount)) for mount in ("/data", "/sdcard")
    )
    if available < needed:
        additional = math.ceil((needed - available) * 10 / 1024**3) / 10
        msg = (
            f"Free at least {additional:.1f} GiB more on the headset, "
            "then run the same command again."
        )
        raise RuntimeError(msg)


def _prepare_runtime(
    adb: _Adb, apk: Path, notify: Callable[[InstallProgress], None]
) -> Path | None:
    identity = runtime_assets.apk_runtime(apk)
    if identity is None:
        return None
    status = _read_setup_data(adb, "runtime", 256)
    if status == f'{{"runtime":"{identity}"}}':
        return None
    return runtime_assets.prepare_transfer(
        apk.with_name("runtime.zip"),
        progress=lambda done, total: notify(
            InstallProgress("download", "Downloading the Winlator runtime", done, total)
        ),
    )


def _install_apk(adb: _Adb, apk: Path, notify: Callable[[InstallProgress], None]) -> None:
    if _installed_apk_matches(adb, apk):
        notify(InstallProgress("app", "Reusing the verified GK3HD VR app"))
    else:
        notify(InstallProgress("app", "Installing the separate GK3HD VR app"))
        # Android replaces the app process during installation. Check again
        # in case the player launched while the APK was being verified.
        _require_idle(adb)
        adb.run("install", "-r", str(apk), timeout=120)
    for permission in ("READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE"):
        adb.run("shell", "pm", "grant", APPLICATION_ID, f"android.permission.{permission}")


def _install_selected(
    selected: _Adb,
    frozen: Path,
    manifest: BundleManifest,
    journal: Path,
    notify: Callable[[InstallProgress], None],
) -> InstalledPlayer:
    _require_idle(selected)
    desired = hashlib.sha256(json_bytes(manifest.inventory)).hexdigest()
    previous = _Transfer.read(journal)
    if previous is not None:
        status = _previous_setup(selected, previous, notify)
        if (
            status is not None
            and status.stage == "complete"
            and previous.inventory_sha256 == desired
            and _installed_apk_matches(selected, frozen)
        ):
            _discard_transfer(selected, journal, previous, notify)
            return InstalledPlayer(
                selected.device, previous.archive_sha256, len(manifest.inventory), status.message
            )
        if status is not None:
            _require_discard(selected, journal, previous, notify)
            previous = None
    _require_setup_idle(selected)
    receipt, staged_bytes = _transfer_bundle(selected, frozen, manifest, frozen.parent, notify)
    require_player_components(frozen, receipt.path)
    if receipt.component_update:
        notify(
            InstallProgress(
                "preflight",
                "Checking existing game files on the headset"
                if receipt.verification_only
                else "Using a smaller game component update",
            )
        )
    resumed = (
        previous is not None
        and previous.inventory_sha256 == desired
        and _reuse_transfer(selected, previous, receipt)
    )
    if previous is not None and not resumed:
        _require_discard(selected, journal, previous, notify)
    copies = 1 if resumed else 2
    runtime = _prepare_runtime(selected, frozen, notify)
    runtime_bytes = 0 if runtime is None else 2 * runtime.stat().st_size
    _require_transfer_space(
        selected, receipt.path.stat().st_size * copies + staged_bytes + runtime_bytes + _RESERVE
    )
    if resumed and previous is not None:
        transfer = previous
        notify(InstallProgress("transfer", "Reusing the verified transfer on the headset"))
        _require_idle(selected)
    else:
        transfer = _Transfer(uuid4().hex, receipt.sha256, desired)
        transfer.write(journal)
        try:
            _push(selected, receipt.path, transfer.remote, notify)
            _require_idle(selected)
        except (RuntimeError, OSError, KeyboardInterrupt):
            _discard_transfer(selected, journal, transfer, notify)
            raise
    if runtime is not None:
        _push(selected, runtime, transfer.runtime_remote, notify, label="Winlator runtime")
        _require_idle(selected)
    _require_setup_idle(selected)
    _install_apk(selected, frozen, notify)
    options = (
        "--es",
        "gk3hd_bundle",
        transfer.remote,
        "--es",
        "gk3hd_bundle_sha256",
        receipt.sha256,
    )
    message = _await_setup(selected, transfer.token, options, notify)
    _discard_transfer(selected, journal, transfer, notify)
    return InstalledPlayer(selected.device, receipt.sha256, receipt.files, message)


def install(
    *,
    apk: Path,
    bundle: Path,
    adb: Path | None = None,
    device: str | None = None,
    on_progress: Callable[[InstallProgress], None] | None = None,
) -> InstalledPlayer:
    """Install a trusted explicit APK and private bundle, without launching play.

    This development entry deliberately does not download unpublished binaries,
    rebuild a renderer silently, copy another prefix or delete existing saves.
    """
    notify = on_progress or (lambda _event: None)
    executable = resolve_adb(adb)
    notify(InstallProgress("preflight", "Checking the standalone APK and private game bundle"))
    with TemporaryDirectory(prefix="gk3hd-standalone-") as staging:
        frozen = Path(staging) / "gk3hd.apk"
        _freeze_apk(apk, frozen)
        manifest = read_bundle_manifest(bundle.resolve())
        require_player_components(frozen, manifest.path)
        headset = probe(adb=Path(executable), device=device)
        require_install_platform(headset)
        if not headset.pimax_library_paths and not any(
            broker.status == "runtime advertised; session not tested" for broker in headset.brokers
        ):
            # Shell queries can be denied even when the app's OpenXR loader can
            # discover a runtime. Installation is not headset qualification.
            notify(
                InstallProgress(
                    "warning", "VR runtime availability must still be checked in the headset player"
                )
            )
        selected = _Adb(executable, headset.device)
        key = hashlib.sha256(headset.device.encode()).hexdigest()
        journal = cache_directory() / "vr" / "standalone" / f"{key}.json"
        with ExclusiveFileLock(journal.with_suffix(".lock")):
            return _install_selected(selected, frozen, manifest, journal, notify)
