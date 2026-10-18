"""Publication and interrupted recovery preserve flat play and external edits."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from gk3hd.system import locking
from gk3hd.system.files import json_bytes
from gk3hd.system.locking import ExclusiveFileLock, LockError, executable_lock_path
from gk3hd.vr import transaction
from gk3hd.vr.transaction import FILES, JOURNAL, VRTransaction

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    for name in ("GK3.exe", "ddraw.dll", "dxvk.conf", "GK3.ini", "save0001.gk3"):
        (root / name).write_bytes(f"flat {name}".encode())
    cache = tmp_path / "cache"
    monkeypatch.setattr(transaction, "cache_directory", lambda: cache)
    monkeypatch.setattr(locking, "cache_directory", lambda: cache)
    return root


def files(label: str | None) -> dict[str, bytes | None]:
    return {name: f"{label} {name}".encode() if label is not None else None for name in FILES}


def test_verified_rollback_content_remains_usable_without_another_disk_write(
    game: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"already durable original player"
    digest = VRTransaction._cache(payload)
    baseline = flat_files(game)
    with monkeypatch.context() as patch:
        patch.setattr(transaction, "atomic_write", Mock(side_effect=OSError("disk write failed")))
        assert VRTransaction._cache(payload) == digest
    assert VRTransaction._load(digest) == payload
    assert flat_files(game) == baseline


@pytest.mark.parametrize("damaged", [b"", b"different", b"original rollback datX"])
def test_damaged_rollback_content_is_repaired_before_reuse(game: Path, damaged: bytes) -> None:
    payload = b"original rollback data"
    digest = VRTransaction._cache(payload)
    cached = transaction.cache_directory() / "vr-transactions" / digest
    cached.write_bytes(damaged)
    baseline = flat_files(game)
    assert VRTransaction._cache(payload) == digest
    assert VRTransaction._load(digest) == payload
    assert flat_files(game) == baseline


def test_failed_repair_does_not_accept_a_matching_cache_filename(
    game: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"original rollback data"
    digest = VRTransaction._cache(payload)
    cached = transaction.cache_directory() / "vr-transactions" / digest
    cached.write_bytes(b"original rollback datX")
    baseline = flat_files(game)
    with monkeypatch.context() as patch:
        patch.setattr(transaction, "atomic_write", Mock(side_effect=OSError("disk write failed")))
        with pytest.raises(OSError, match="disk write failed"):
            VRTransaction._cache(payload)
    with pytest.raises(ValueError, match="VR recovery cache changed"):
        VRTransaction._load(digest)
    assert flat_files(game) == baseline


def read_files(game: Path) -> dict[str, bytes | None]:
    return {name: (game / name).read_bytes() if (game / name).exists() else None for name in FILES}


def publish(game: Path, payloads: dict[str, bytes | None]) -> None:
    for name, payload in payloads.items():
        if payload is not None:
            path = game / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)


def flat_files(game: Path) -> dict[str, bytes]:
    return {
        name: (game / name).read_bytes()
        for name in ("GK3.exe", "ddraw.dll", "dxvk.conf", "GK3.ini", "save0001.gk3")
    }


def interrupt(
    owner: VRTransaction,
    payloads: dict[str, bytes | None],
    monkeypatch: pytest.MonkeyPatch,
    index: int,
) -> None:
    """Leave a real, partially published journal as if the process vanished."""
    original = owner._publish
    calls = 0

    def interrupted(name: str, payload: bytes | None) -> None:
        nonlocal calls
        original(name, payload)
        calls += 1
        if calls == index + 1:
            raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(owner, "_publish", interrupted)
        patch.setattr(owner, "_recover", Mock(side_effect=[False, RuntimeError("process gone")]))
        with pytest.raises(KeyboardInterrupt):
            owner.commit(payloads, expected=owner.snapshot(), validate=lambda: None)


@pytest.mark.parametrize("initial", [None, "old"])
@pytest.mark.parametrize("replacement", [None, "new"])
def test_publish_and_remove_only_vr_owned_files(
    game: Path, initial: str | None, replacement: str | None
) -> None:
    baseline = flat_files(game)
    publish(game, files(initial))
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    expected = files(replacement)

    def validate() -> None:
        assert read_files(game) == expected

    owner.commit(expected, expected=owner.snapshot(), validate=validate)
    assert read_files(game) == expected
    assert not (game / JOURNAL).exists()
    assert not owner.recover()
    assert flat_files(game) == baseline


@pytest.mark.parametrize(("initial", "replacement"), [(None, "new"), ("old", "new"), ("old", None)])
@pytest.mark.parametrize("index", range(len(FILES)))
def test_interrupted_install_update_and_remove_restore_every_original_file(
    game: Path,
    monkeypatch: pytest.MonkeyPatch,
    initial: str | None,
    replacement: str | None,
    index: int,
) -> None:
    baseline = flat_files(game)
    publish(game, files(initial))
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    interrupt(owner, files(replacement), monkeypatch, index)
    assert (game / JOURNAL).exists()
    assert owner.recover()
    assert read_files(game) == files(initial)
    assert not (game / JOURNAL).exists()
    assert flat_files(game) == baseline


@pytest.mark.parametrize("error", [ValueError("invalid player"), KeyboardInterrupt()])
def test_failed_disk_validation_restores_original_generation(
    game: Path, error: BaseException
) -> None:
    publish(game, files("old"))
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    with pytest.raises(type(error)):
        owner.commit(files("new"), expected=owner.snapshot(), validate=Mock(side_effect=error))
    assert read_files(game) == files("old")
    assert not (game / JOURNAL).exists()


def test_committed_generation_survives_interruption_before_journal_cleanup(
    game: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    interrupt(owner, files("new"), monkeypatch, len(FILES) - 1)
    journal = game / JOURNAL
    content = json.loads(journal.read_bytes())
    content["phase"] = "committed"
    journal.write_bytes(json_bytes(content))
    assert owner.recover()
    assert read_files(game) == files("new")
    assert not journal.exists()


def test_external_edit_blocks_recovery_without_changing_any_files(
    game: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publish(game, files("old"))
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    interrupt(owner, files("new"), monkeypatch, 3)
    (game / FILES[-1]).write_bytes(b"external change")
    before = read_files(game)
    with pytest.raises(ValueError, match="outside the transaction"):
        owner.recover()
    assert read_files(game) == before
    assert (game / JOURNAL).exists()


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_recovery_validates_all_cached_originals_before_changing_any_file(
    game: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    publish(game, files("old"))
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    interrupt(owner, files("new"), monkeypatch, 3)
    journal = json.loads((game / JOURNAL).read_bytes())
    digest = journal["files"][FILES[-1]]["before"]
    cached = transaction.cache_directory() / "vr-transactions" / digest
    if damage == "missing":
        cached.unlink()
    else:
        cached.write_bytes(b"corrupt")
    before = read_files(game)
    with pytest.raises((ValueError, OSError)):
        owner.recover()
    assert read_files(game) == before
    assert (game / JOURNAL).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema", True), ("schema", 2), ("exe", "other.exe"), ("phase", []), ("phase", "other")],
)
def test_invalid_journal_is_retained_without_any_mutation(
    game: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    interrupt(owner, files("new"), monkeypatch, 2)
    journal = game / JOURNAL
    content = json.loads(journal.read_bytes())
    content[field] = value
    journal.write_bytes(json_bytes(content))
    before = read_files(game)
    with pytest.raises(ValueError, match="invalid VR recovery journal"):
        owner.recover()
    assert read_files(game) == before
    assert journal.exists()


@pytest.mark.parametrize("bad", ["../GK3.exe", "GK3.exe", "unknown"])
def test_journal_cannot_supply_additional_targets(
    game: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    interrupt(owner, files("new"), monkeypatch, 2)
    journal = game / JOURNAL
    content = json.loads(journal.read_bytes())
    content["files"][bad] = {"before": None, "after": None}
    journal.write_bytes(json_bytes(content))
    before = read_files(game)
    baseline = flat_files(game)
    with pytest.raises(ValueError, match="invalid VR recovery journal"):
        owner.recover()
    assert read_files(game) == before
    assert flat_files(game) == baseline
    assert journal.exists()


@pytest.mark.parametrize("identity", ["../path", "a" * 63, 123, []])
def test_journal_cannot_supply_invalid_cache_identities(
    game: Path, monkeypatch: pytest.MonkeyPatch, identity: object
) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    interrupt(owner, files("new"), monkeypatch, 2)
    journal = game / JOURNAL
    content = json.loads(journal.read_bytes())
    content["files"][FILES[0]]["before"] = identity
    journal.write_bytes(json_bytes(content))
    before = read_files(game)
    with pytest.raises(ValueError, match="invalid VR recovery identity"):
        owner.recover()
    assert read_files(game) == before
    assert journal.exists()


def test_stale_preparation_does_not_overwrite_external_changes(game: Path) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    expected = owner.snapshot()
    (game / FILES[0]).write_bytes(b"external player")
    before = read_files(game)
    with pytest.raises(ValueError, match="changed after preparation"):
        owner.commit(files("new"), expected=expected, validate=lambda: None)
    assert read_files(game) == before
    assert not (game / JOURNAL).exists()


def test_active_game_blocks_install_and_recovery(game: Path) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: True)
    with pytest.raises(RuntimeError, match="close GK3"):
        owner.commit(files("new"), expected=owner.snapshot(), validate=lambda: None)
    with pytest.raises(RuntimeError, match="close GK3"):
        owner.recover()
    assert read_files(game) == files(None)


def test_flat_and_vr_installers_share_exclusive_ownership(game: Path) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    with ExclusiveFileLock(executable_lock_path(game / "GK3.exe")), pytest.raises(LockError):
        owner.commit(files("new"), expected=owner.snapshot(), validate=lambda: None)
    assert read_files(game) == files(None)


@pytest.mark.parametrize("name", ["GK3-VR.exe", "gk3hd", JOURNAL])
def test_links_cannot_redirect_vr_mutations(game: Path, tmp_path: Path, name: str) -> None:
    target = tmp_path / "outside"
    is_directory = name == "gk3hd"
    if is_directory:
        target.mkdir()
    else:
        target.write_bytes(b"outside")
    try:
        (game / name).symlink_to(target, target_is_directory=is_directory)
    except OSError:
        pytest.skip("creating symlinks is not permitted on this test host")
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    operation = owner.recover if name == JOURNAL else owner.snapshot
    with pytest.raises(ValueError, match="links or junctions"):
        operation()
    if is_directory:
        assert not list(target.iterdir())
    else:
        assert target.read_bytes() == b"outside"


@pytest.mark.windows
def test_a_windows_junction_cannot_redirect_private_player_publication(
    game: Path, tmp_path: Path
) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    cmd = shutil.which("cmd")
    assert cmd is not None
    subprocess.run(  # noqa: S603 - fixed mklink operation, pytest-owned temporary paths only.
        [cmd, "/c", "mklink", "/J", str(game / "gk3hd"), str(target)],
        check=True,
        capture_output=True,
    )
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    with pytest.raises(ValueError, match="links or junctions"):
        owner.snapshot()
    assert not list(target.iterdir())


def test_failed_locked_preflight_leaves_no_journal_or_published_files(game: Path) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    with pytest.raises(ValueError, match="source changed"):
        owner.commit(
            files("new"),
            expected=owner.snapshot(),
            validate=lambda: None,
            preflight=Mock(side_effect=ValueError("source changed")),
        )
    assert read_files(game) == files(None)
    assert not (game / JOURNAL).exists()


def test_a_partial_generation_cannot_be_accepted_as_committed(
    game: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = VRTransaction(game / "GK3.exe", process_probe=lambda: False)
    interrupt(owner, files("new"), monkeypatch, 2)
    journal = game / JOURNAL
    content = json.loads(journal.read_bytes())
    content["phase"] = "committed"
    journal.write_bytes(json_bytes(content))
    before = read_files(game)
    with pytest.raises(ValueError, match="verified final state"):
        owner.recover()
    assert read_files(game) == before
    assert journal.exists()
