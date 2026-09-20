"""Exercise the Linux subprocess boundary without requiring Steam or Wine."""

import json
import os
from pathlib import Path

import pytest

from gk3hd.patch.install.proton import ProtonRegistryBackend
from gk3hd.system.proton import ProtonContext
from gk3hd.system.steam import SteamGame

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.name != "posix", reason="POSIX runner"),
]


def test_runtime_handoff_and_registry_output_are_captured(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "Steam with spaces"
    game = SteamGame(root, root, root / "steamapps/common/GK3")
    game.directory.mkdir(parents=True)
    executable = root / "Proton/proton"
    executable.parent.mkdir()
    executable.write_text(
        "#!/bin/sh\n"
        '[ "$1" = run ] && [ "$2" = reg.exe ] && [ "$3" = query ] || exit 81\n'
        '[ "$4" = "HKCU\\Software\\Test Space" ] && [ "$5" = /v ] && [ "$6" = Gamma ] || exit 82\n'
        '[ "$PROTON_LOG" = 0 ] && [ "$WINEDEBUG" = -all ] || exit 83\n'
        '[ "$STEAM_COMPAT_APP_ID" = 497360 ] || exit 84\n'
        '[ -d "$STEAM_COMPAT_DATA_PATH" ] || exit 85\n'
        'printf "diagnostics belong in the captured pipe\\n" >&2\n'
        'printf "    Gamma    REG_SZ    1.000000\\n"\n'
    )
    runtime = root / "Runtime/_v2-entry-point"
    runtime.parent.mkdir()
    runtime.write_text(
        '#!/bin/sh\n[ "$1" = --verb=run ] && [ "$2" = -- ] || exit 86\nshift 2\nexec "$@"\n'
    )
    executable.chmod(0o700)
    runtime.chmod(0o700)
    monkeypatch.setenv("PROTON_LOG", "1")
    context = ProtonContext(game, executable, runtime)
    value = ProtonRegistryBackend(context, r"Software\Test Space").read("Gamma")
    assert json.loads(value or "null") == {"type": 1, "value": "1.000000"}
    assert capfd.readouterr() == ("", "")
    assert os.environ["PROTON_LOG"] == "1"
