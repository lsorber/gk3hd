"""Opt-in supervised VR launching with child-only settings and explicit failures."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.install.windows import is_gk3_running, required_gk3_appcompat_layers
from gk3hd.system.discovery import discover_game
from gk3hd.system.locking import ExclusiveFileLock, executable_lock_path
from gk3hd.vr.process import PointingHand, VRProcess
from gk3hd.vr.runtime import RuntimeSelection, RuntimeUnavailableError, selected_runtime
from gk3hd.vr.runtime_watch import RuntimeWatch
from gk3hd.vr.service import VRService
from gk3hd.vr.status import TRACKING_FILE, TrackingFeedback, TrackingStatus
from gk3hd.vr.transaction import PLAYER

if TYPE_CHECKING:
    from collections.abc import Callable

_STARTUP_SECONDS = 30
_RUNTIME_ERRORS = (
    "GK3HD OpenXR initialization:",
    "GK3HD OpenXR session ended:",
    "GK3HD OpenXR Vulkan instance:",
    "GK3HD OpenXR GPU selection:",
    "GK3HD OpenXR Vulkan device:",
    "GK3HD OpenXR renderer session:",
)
_RENDER_ERRORS = (
    "GK3HD: XR frame bridge:",
    "GK3HD: XR panel bridge:",
    "GK3HD: XR scene bridge:",
    "GK3HD: unknown XR frame bridge failure",
    "GK3HD: unknown XR panel bridge failure",
    "GK3HD: unknown XR scene bridge failure",
    "GK3HD: XR native interface has no render target",
    "GK3HD: XR native interface upload failed:",
)


def child_environment(game_dir: Path, runtime: RuntimeSelection, *, logs: Path) -> dict[str, str]:
    """Discard stale development controls without mutating the caller's settings."""
    values = {
        name.upper(): value
        for name, value in os.environ.items()
        if not name.upper().startswith(("XR_", "GK3HD_XR_", "DXVK_", "D7VK_"))
        and name.upper() != "__COMPAT_LAYER"
    }
    layer = json.loads(required_gk3_appcompat_layers(None, graphics_backend=GraphicsBackend.D7VK))
    values.update(
        XR_RUNTIME_JSON=str(runtime.manifest),
        GK3HD_XR_PROTOTYPE="1",
        DXVK_CONFIG_FILE=str(game_dir / PLAYER / "dxvk.conf"),
        DXVK_LOG_PATH=str(logs),
        D7VK_LOG_PATH=str(logs),
        GK3HD_XR_TRACKING_STATUS=str(logs / TRACKING_FILE),
        __COMPAT_LAYER=layer["value"],
    )
    return values


def _logs(game_dir: Path) -> Path:
    root = game_dir / "gk3hd/vr/logs"
    for part in (root, *root.parents):
        if part == game_dir:
            break
        if part.is_symlink() or part.is_junction():
            msg = "VR log directory must not traverse links or junctions"
            raise ValueError(msg)
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="launch-", dir=root))


def _runtime_error(logs: Path) -> str | None:
    path = logs / "GK3-VR_ddraw.log"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(("err:", "error:")) and any(
            marker in line for marker in (*_RUNTIME_ERRORS, *_RENDER_ERRORS)
        ):
            return line.strip()
    return None


def _check_runtime(logs: Path) -> None:
    failure = _runtime_error(logs)
    if failure is not None:
        if any(marker in failure for marker in _RUNTIME_ERRORS):
            msg = (
                f"VR runtime/headset unavailable: {failure}. "
                f"Start SteamVR, reconnect the headset and launch VR again. Logs: {logs}"
            )
            raise RuntimeUnavailableError(msg)
        raise _rendering_failed(failure, logs)


def _rendering_failed(failure: str, logs: Path) -> RuntimeUnavailableError:
    msg = (
        f"VR rendering failed: {failure}. Unsaved progress may be lost. "
        "Launch VR again; if this repeats, include these logs when reporting it: "
        f"{logs}"
    )
    return RuntimeUnavailableError(msg)


def launch(
    *,
    game_dir: Path | None = None,
    runtime_manifest: Path | None = None,
    pointing_hand: PointingHand = PointingHand.RIGHT,
    on_tracking: Callable[[TrackingStatus], None] | None = None,
) -> int:
    """Run the verified player until exit; never substitute ordinary flat play.

    Startup requires submitted VR frames, not merely a registered runtime.
    This does not establish headset comfort or release acceptance.
    """
    hand = PointingHand(pointing_hand)
    target = discover_game(game_dir=game_dir)
    with ExclusiveFileLock(executable_lock_path(target.exe)):
        if is_gk3_running():
            msg = "close GK3 and its VR player before launching VR"
            raise RuntimeError(msg)
        program = VRService().verify(game_dir=target.game_dir)
        runtime = selected_runtime(manifest=runtime_manifest)
        logs = _logs(target.game_dir)
        environment = child_environment(target.game_dir, runtime, logs=logs)
        feedback = TrackingFeedback(logs, on_tracking) if on_tracking is not None else None
        with (
            RuntimeWatch(runtime, logs=logs) as watch,
            VRProcess(
                target.game_dir / "GK3-VR.exe", program, environment=environment, pointing_hand=hand
            ) as child,
        ):
            deadline = time.monotonic() + _STARTUP_SECONDS
            submitted = False
            while child.poll() is None:
                _check_runtime(logs)
                failure = child.render_failure(program)
                if failure is not None:
                    raise _rendering_failed(failure, logs)
                if not submitted:
                    submitted = child.has_submitted_frames(program)
                    if not submitted and time.monotonic() >= deadline:
                        msg = (
                            f"no VR frames submitted within {_STARTUP_SECONDS:g} seconds; "
                            "check the headset and logs, then relaunch VR. "
                            f"Logs: {logs}"
                        )
                        raise RuntimeUnavailableError(msg)
                if submitted:
                    watch.check()
                if feedback is not None:
                    feedback.poll(time.monotonic())
                time.sleep(0.05)
            code = child.wait(timeout=0)
            # The child may exit between the last poll and a terminal XR log
            # write. Do not mistake an error followed by exit code zero for a
            # healthy native Quit.
            _check_runtime(logs)
        if not submitted or code != 0:
            msg = f"VR player exited with code {code}; submitted frames={submitted}. Logs: {logs}"
            raise RuntimeUnavailableError(msg)
        return code
