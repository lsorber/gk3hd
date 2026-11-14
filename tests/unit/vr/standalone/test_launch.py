"""USB launch opens the same entry as the headset library, without installation."""

import subprocess
from unittest.mock import Mock, call

import pytest

from gk3hd.vr.standalone import device as discovery
from gk3hd.vr.standalone import install as service
from gk3hd.vr.standalone.apk import APPLICATION_ID


@pytest.mark.parametrize("installed", [False, True])
def test_launch_requires_an_installed_player_and_uses_its_library_entry(
    monkeypatch: pytest.MonkeyPatch, *, installed: bool
) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    listing = Mock(
        return_value=subprocess.CompletedProcess(
            ["adb", "devices", "-l"], 0, "List of devices attached\nquest device\n", ""
        )
    )
    monkeypatch.setattr(discovery, "_run", listing)
    run = Mock(side_effect=["package:/checked/player.apk" if installed else "", "Status: ok"])
    monkeypatch.setattr(service._Adb, "run", run)
    if installed:
        assert service.launch() == "quest"
        assert run.call_args == call(
            "shell", "am", "start", "-W", "-n", APPLICATION_ID + "/com.winlator.StandaloneActivity"
        )
    else:
        with pytest.raises(RuntimeError, match="not installed"):
            service.launch()
        assert run.call_count == 1
    listing.assert_called_once_with("adb", "devices", "-l")


@pytest.mark.parametrize("experiment", ["experimental_compressed", "experimental_eye_copy"])
def test_experiment_still_opens_the_checked_library_entry(
    monkeypatch: pytest.MonkeyPatch,
    experiment: str,
) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    monkeypatch.setattr(service, "select_device", Mock(return_value="headset"))
    run = Mock(side_effect=["package:/checked/player.apk", "Status: ok"])
    monkeypatch.setattr(service._Adb, "run", run)

    if experiment == "experimental_compressed":
        assert service.launch(experimental_compressed=True) == "headset"
    else:
        assert service.launch(experimental_eye_copy=True) == "headset"
    assert run.call_args == call(
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        APPLICATION_ID + "/com.winlator.StandaloneActivity",
        "--ez",
        "gk3hd_" + experiment,
        "true",
    )


def test_requested_eye_resolution_is_sent_only_to_the_selected_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    monkeypatch.setattr(service, "select_device", Mock(return_value="headset"))
    run = Mock(side_effect=["package:/checked/player.apk", "Status: ok"])
    monkeypatch.setattr(service._Adb, "run", run)

    assert service.launch(eye_resolution="2816x2880") == "headset"
    assert run.call_args.args[-3:] == ("--es", "gk3hd_eye_resolution", "2816x2880")


@pytest.mark.parametrize("value", ["", "2816", "2816x0", "4097x2048", "2816x2880 --ez flag"])
def test_invalid_eye_resolution_is_rejected_before_adb(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    adb = Mock()
    monkeypatch.setattr(service, "resolve_adb", adb)

    with pytest.raises(ValueError, match="WIDTHxHEIGHT"):
        service.launch(eye_resolution=value)
    adb.assert_not_called()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (
            (
                "Status: ok\nActivity: com.oculus.vrshell/.systemdialog.launchcheck."
                "LaunchCheckControllerRequiredDialogActivity\n"
            ),
            "Wake both headset controllers",
        ),
        ("Status: ok\nActivity: android/.PermissionPrompt\n", "system prompt"),
        (
            (
                "Activity: com.meta.pclinkservice.server/com.meta.link.ui.dialogs.available."
                "OculusLinkAvailableDialogActivity\n"
            ),
            "Dismiss the Quest Link connection prompt",
        ),
        (
            "Activity: com.oculus.firsttimenux/.FirstTimeNuxExclusiveSystemDialogActivity\n",
            "Finish headset setup",
        ),
        (
            "Activity: com.pimax.vrguardian/.activity.MainUnityActivity\n",
            "Check your play area",
        ),
        ("Error: Activity does not exist", "could not open"),
    ],
)
def test_launch_reports_system_interception_instead_of_success(
    monkeypatch: pytest.MonkeyPatch, response: str, error: str
) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    monkeypatch.setattr(service, "select_device", Mock(return_value="headset"))
    monkeypatch.setattr(
        service._Adb, "run", Mock(side_effect=["package:/checked/player.apk", response])
    )
    with pytest.raises(RuntimeError, match=error):
        service.launch()


@pytest.mark.parametrize("activity", ["StandaloneActivity", "OpenXrActivity", "CrystalActivity"])
def test_launch_accepts_this_apps_actual_activity(
    monkeypatch: pytest.MonkeyPatch, activity: str
) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    monkeypatch.setattr(service, "select_device", Mock(return_value="headset"))
    monkeypatch.setattr(
        service._Adb,
        "run",
        Mock(
            side_effect=[
                "package:/checked/player.apk",
                f"Status: ok\nActivity: {APPLICATION_ID}/com.winlator.{activity}\n",
            ]
        ),
    )
    assert service.launch() == "headset"


@pytest.mark.parametrize(
    ("activities", "message"),
    [
        (
            (
                "topResumedActivity=ActivityRecord{abc u0 "
                "com.oculus.firsttimenux/.FirstTimeNuxExclusiveSystemDialogActivity t12}"
            ),
            "Finish headset setup",
        ),
        (
            (
                "mResumedActivity=ActivityRecord{abc u0 "
                "com.oculus.guardian/.GuardianDialogActivity t12}"
            ),
            "Check your play area",
        ),
        (
            (
                "topResumedActivity=ActivityRecord{abc u0 com.oculus.vrshell/"
                ".LaunchCheckControllerRequiredDialogActivity t12}"
            ),
            "Wake both headset controllers",
        ),
        (
            (
                "mLastPausedActivity=ActivityRecord{abc u0 "
                "com.oculus.firsttimenux/.FirstTimeNuxExclusiveSystemDialogActivity t12}\n"
                f"topResumedActivity=ActivityRecord{{def u0 {APPLICATION_ID}/.OpenXrActivity t13}}"
            ),
            "not confirmed",
        ),
        (
            (
                "mResumedActivity: ActivityRecord{abc u0 "
                "com.pimax.vrguardian/.activity.MainUnityActivity t12}"
            ),
            "Check your play area",
        ),
        (
            (
                "mLastPausedActivity: ActivityRecord{abc u0 "
                "com.pimax.vrguardian/.activity.MainUnityActivity t12}\n"
                f"ResumedActivity: ActivityRecord{{def u0 {APPLICATION_ID}/.CrystalActivity t13}}"
            ),
            "not confirmed",
        ),
        (
            (
                "mFocusedApp=ActivityRecord{abc u0 com.meta.pclinkservice.server/"
                "com.meta.link.ui.dialogs.available.OculusLinkAvailableDialogActivity t12}\n"
            ),
            "Dismiss the Quest Link connection prompt",
        ),
        (
            (
                "topResumedActivity=ActivityRecord{abc u0 com.meta.pclinkservice.server/"
                "com.meta.link.ui.dialogs.available.OculusLinkAvailableDialogActivity t12}\n"
                "mFocusedApp=ActivityRecord{def u0 com.oculus.vrshell/.HomeActivity t13}\n"
                "mFocusedApp=null\n"
            ),
            "not confirmed",
        ),
        (RuntimeError("Diagnostic query unavailable"), "not confirmed"),
    ],
)
def test_launch_timeout_explains_current_prompts_without_relaunch_or_termination(
    monkeypatch: pytest.MonkeyPatch, activities: str | RuntimeError, message: str
) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    monkeypatch.setattr(service, "select_device", Mock(return_value="headset"))
    timeout = RuntimeError("Headset command timed out")
    timeout.__cause__ = subprocess.TimeoutExpired(["adb", "shell", "am", "start"], 15)
    run = Mock(
        side_effect=[
            "package:/checked/player.apk",
            timeout,
            activities,
            RuntimeError("No power report"),
        ]
    )
    monkeypatch.setattr(service._Adb, "run", run)
    with pytest.raises(RuntimeError, match=message):
        service.launch()
    assert sum(args.args[:3] == ("shell", "am", "start") for args in run.call_args_list) == 1
    assert all("force-stop" not in args.args for args in run.call_args_list)


def test_android_timeout_with_successful_exit_checks_for_a_current_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    monkeypatch.setattr(service, "select_device", Mock(return_value="headset"))
    run = Mock(
        side_effect=[
            "package:/checked/player.apk",
            f"Status: timeout\nActivity: {APPLICATION_ID}/.StandaloneActivity\nComplete",
            (
                "mResumedActivity: ActivityRecord{abc u0 "
                "com.pimax.vrguardian/.activity.MainUnityActivity t12}"
            ),
        ]
    )
    monkeypatch.setattr(service._Adb, "run", run)
    with pytest.raises(RuntimeError, match="Check your play area"):
        service.launch()
    assert sum(args.args[:3] == ("shell", "am", "start") for args in run.call_args_list) == 1
    assert all("force-stop" not in args.args for args in run.call_args_list)


@pytest.mark.parametrize("state", ["STANDBY", "HEADSET_UNMOUNTED", "WAITING_FOR_SLEEP_MSG"])
def test_unconfirmed_launch_explains_current_headset_power_state(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    monkeypatch.setattr(service, "select_device", Mock(return_value="headset"))
    timeout = RuntimeError("Launch observation expired")
    timeout.__cause__ = subprocess.TimeoutExpired(["adb", "shell", "am", "start"], 15)
    run = Mock(
        side_effect=[
            "package:/checked/player.apk",
            timeout,
            "mFocusedApp=ActivityRecord{abc u0 com.oculus.vrshell/.HomeActivity t12}",
            f"State: {state}\nEvent log:\n  older state: HEADSET_MOUNTED\n",
        ]
    )
    monkeypatch.setattr(service._Adb, "run", run)
    with pytest.raises(RuntimeError, match="Wake it and put it on"):
        service.launch()
    assert sum(args.args[:3] == ("shell", "am", "start") for args in run.call_args_list) == 1
    assert all(
        "force-stop" not in args.args and "setprop" not in args.args for args in run.call_args_list
    )


@pytest.mark.parametrize(
    "report",
    [
        "State: HEADSET_MOUNTED\nEvent log:\n  older state: HEADSET_UNMOUNTED\n",
        "Can't find service: vrpowermanager\n",
        "State: UNKNOWN\n",
        "Event log:\n  State: HEADSET_UNMOUNTED\n",
    ],
)
def test_launch_does_not_infer_sleep_from_history_or_an_unknown_power_report(report: str) -> None:
    adb = Mock(spec=service._Adb)
    adb.run.side_effect = ["", report]
    assert service._launch_timeout_message(adb) == (
        "GK3HD VR launch was not confirmed. Check the headset before trying again"
    )


def test_launch_preserves_other_device_command_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "resolve_adb", Mock(return_value="adb"))
    monkeypatch.setattr(service, "select_device", Mock(return_value="headset"))
    failure = RuntimeError("Selected device disconnected")
    run = Mock(side_effect=["package:/checked/player.apk", failure])
    monkeypatch.setattr(service._Adb, "run", run)
    with pytest.raises(RuntimeError, match="Selected device disconnected") as raised:
        service.launch()
    assert raised.value is failure
    assert run.call_count == 2
