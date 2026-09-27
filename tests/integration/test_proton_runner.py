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
        'if [ "$1" = getcompatpath ]; then\n'
        '  [ "$2" = "$STEAM_COMPAT_INSTALL_PATH" ] || exit 80\n'
        '  mkdir -p "$STEAM_COMPAT_DATA_PATH/pfx"\n'
        '  : > "$STEAM_COMPAT_DATA_PATH/pfx/system.reg"\n'
        "  exit 0\n"
        "fi\n"
        '[ "$1" = runinprefix ] && [ "$2" = reg.exe ] && [ "$3" = query ] || exit 81\n'
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


@pytest.mark.parametrize(("command_status", "flush_status"), [(0, 0), (7, 0), (0, 9)])
def test_registry_write_is_persisted_before_returning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command_status: int,
    flush_status: int,
) -> None:
    """Success means saved registry data, not just Wine's in-memory update."""
    root = tmp_path / "Steam with spaces"
    game = SteamGame(root, root, root / "steamapps/common/GK3")
    game.directory.mkdir(parents=True)
    executable = root / "Proton/proton"
    executable.parent.mkdir()
    executable.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = getcompatpath ]; then\n'
        '  mkdir -p "$STEAM_COMPAT_DATA_PATH/pfx"\n'
        '  : > "$STEAM_COMPAT_DATA_PATH/pfx/system.reg"\n'
        "  exit 0\n"
        "fi\n"
        f"[ {command_status} = 0 ] || exit {command_status}\n"
        'printf "pending setting" > "$STEAM_COMPAT_DATA_PATH/pfx/pending"\n'
    )
    server = executable.parent / "files/bin/wineserver"
    server.parent.mkdir(parents=True)
    server.write_text(
        '#!/bin/sh\n[ "$1" = -w ] || exit 80\n'
        f"[ {flush_status} = 0 ] || exit {flush_status}\n"
        'if [ -f "$WINEPREFIX/pending" ]; then\n'
        '  mv "$WINEPREFIX/pending" "$WINEPREFIX/persisted"\n'
        "fi\n"
    )
    runtime = root / "Runtime/_v2-entry-point"
    runtime.parent.mkdir()
    runtime.write_text('#!/bin/sh\nshift 2\nexec "$@"\n')
    for path in (executable, server, runtime):
        path.chmod(0o700)
    monkeypatch.delenv("GK3HD_WINESERVER", raising=False)
    result = ProtonContext(game, executable, runtime).run(
        ("reg.exe", "add", r"HKCU\Software\Test Space", "/v", "Gamma")
    )
    assert result.returncode == (flush_status or command_status)
    persisted = game.compatdata / "pfx/persisted"
    if command_status == flush_status == 0:
        assert persisted.read_text() == "pending setting"
    else:
        assert not persisted.exists()
    assert "GK3HD_WINESERVER" not in os.environ
