"""Protect existing saves and verify a backup before reporting success."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from gk3hd.vr.standalone import saves

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO


@pytest.mark.parametrize("entry", ["save0001.gk3", "other.txt", "../save0001.gk3"])
def test_only_native_save_slots_can_be_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    path = tmp_path / "my-saves.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(entry, b"a saved game")
    device = Mock()
    device.run.side_effect = ["", "Result: Bundle[{restored=1}]", ""]
    connect = Mock(return_value=device)
    monkeypatch.setattr(saves, "_connect", connect)
    if entry == "save0001.gk3":
        assert saves.restore(path) == 1
        assert device.run.call_args_list[0].args[:3] == ("push", "-q", str(path))
        assert device.run.call_args_list[1].args[:3] == ("shell", "content", "call")
        assert device.run.call_args_list[2].args[:3] == ("shell", "rm", "-f")
    else:
        with pytest.raises(ValueError, match="unexpected"):
            saves.restore(path)
        connect.assert_not_called()


@pytest.mark.parametrize("valid", [True, False])
def test_backup_publishes_only_a_verified_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, valid: bool
) -> None:
    device = Mock()
    monkeypatch.setattr(saves, "_connect", Mock(return_value=device))

    def read(_command: list[str], *, stdout: BinaryIO, **_kwargs: object) -> Mock:
        if valid:
            with ZipFile(stdout, "w") as archive:
                archive.writestr("save0001.gk3", b"a saved game")
        else:
            stdout.write(b"truncated")
        return Mock(returncode=0)

    monkeypatch.setattr(saves.subprocess, "run", read)
    target = tmp_path / "my-saves.zip"
    if valid:
        assert saves.backup(target) == (target, 1)
        assert target.is_file()
    else:
        with pytest.raises(ValueError, match="valid ZIP"):
            saves.backup(target)
        assert not target.exists()
    assert not list(tmp_path.glob(".gk3hd-saves-*"))
