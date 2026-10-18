"""Runtime selection is x86-aware, explicit and never changes global defaults."""

from __future__ import annotations

import json
import struct
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

import pytest

from gk3hd.vr import runtime

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dll = bytearray(128)
    dll[:2] = b"MZ"
    struct.pack_into("<I", dll, 0x3C, 64)
    dll[64:68] = b"PE\0\0"
    for offset, value in ((68, 0x14C), (86, 0x2000), (88, 0x10B)):
        struct.pack_into("<H", dll, offset, value)
    (tmp_path / "runtime.dll").write_bytes(dll)
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "file_format_version": "1.0.0",
                "runtime": {"library_path": "runtime.dll"},
            }
        )
    )
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(runtime, "_registered_runtime", Mock(return_value=path))
    return path


def test_registered_selection_is_validated_and_not_a_headset_claim(manifest: Path) -> None:
    selected = runtime.selected_runtime()
    assert selected.manifest == manifest
    assert selected.library == manifest.parent / "runtime.dll"
    assert runtime.os.environ == {}


def test_explicit_selection_precedes_environment_and_registry(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lookup = Mock()
    monkeypatch.setattr(runtime, "_registered_runtime", lookup)
    runtime.os.environ["XR_RUNTIME_JSON"] = "missing.json"
    assert runtime.selected_runtime(manifest=manifest).manifest == manifest
    lookup.assert_not_called()


def test_environment_override_precedes_registry(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lookup = Mock()
    monkeypatch.setattr(runtime, "_registered_runtime", lookup)
    runtime.os.environ["XR_RUNTIME_JSON"] = str(manifest)
    assert runtime.selected_runtime().manifest == manifest
    lookup.assert_not_called()


@pytest.mark.parametrize(("offset", "value"), [(68, 0x8664), (86, 0), (88, 0x20B)])
def test_incompatible_runtime_images_are_rejected(manifest: Path, offset: int, value: int) -> None:
    library = manifest.parent / "runtime.dll"
    data = bytearray(library.read_bytes())
    struct.pack_into("<H", data, offset, value)
    library.write_bytes(data)
    with pytest.raises(runtime.RuntimeUnavailableError, match="32-bit"):
        runtime.selected_runtime()


@pytest.mark.parametrize("damage", ["missing", "truncated", "header"])
def test_missing_or_invalid_library_cannot_be_selected(manifest: Path, damage: str) -> None:
    library = manifest.parent / "runtime.dll"
    if damage == "missing":
        library.unlink()
    elif damage == "truncated":
        library.write_bytes(b"MZ")
    else:
        data = bytearray(library.read_bytes())
        struct.pack_into("<I", data, 0x3C, 0xFFFFFFF0)
        library.write_bytes(data)
    with pytest.raises(runtime.RuntimeUnavailableError, match=r"cannot read|PE image|PE header"):
        runtime.selected_runtime()


@pytest.mark.parametrize("data", [[], {}, {"runtime": []}, {"file_format_version": "2.0.0"}])
def test_invalid_runtime_manifest_is_rejected(manifest: Path, data: object) -> None:
    manifest.write_text(json.dumps(data))
    with pytest.raises(runtime.RuntimeUnavailableError, match="invalid library declaration"):
        runtime.selected_runtime()


def test_missing_x86_registration_uses_installed_steamvr_only_for_this_process(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steam_manifest = manifest.with_name("steamxr_win32.json")
    steam_manifest.write_bytes(manifest.read_bytes())
    monkeypatch.setattr(runtime, "_registered_runtime", Mock(return_value=None))
    monkeypatch.setattr(runtime, "steam_roots", Mock(return_value=(manifest.parent,)))
    monkeypatch.setattr(runtime, "steam_libraries", Mock(return_value=(manifest.parent,)))
    lookup = Mock(return_value=manifest.parent)
    monkeypatch.setattr(runtime, "installed_app", lookup)
    assert runtime.selected_runtime().manifest == steam_manifest
    lookup.assert_called_once_with(manifest.parent, "250820")
    assert runtime.os.environ == {}


@pytest.mark.usefixtures("manifest")
def test_missing_runtime_has_an_actionable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_registered_runtime", Mock(return_value=None))
    monkeypatch.setattr(runtime, "steam_roots", Mock(return_value=()))
    with pytest.raises(runtime.RuntimeUnavailableError, match="install SteamVR"):
        runtime.selected_runtime()


def test_other_platforms_do_not_claim_windows_runtime_support(
    manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name="posix", environ={}))
    with pytest.raises(runtime.RuntimeUnavailableError, match="Windows OpenXR only"):
        runtime.selected_runtime(manifest=manifest)


def test_native_registration_uses_the_32_bit_view_from_any_python_architecture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime, "os", SimpleNamespace(name="nt", environ={}))
    registry = MagicMock(HKEY_LOCAL_MACHINE=1, KEY_READ=2, KEY_WOW64_32KEY=0x200, REG_SZ=1)
    registry.QueryValueEx.return_value = (str(tmp_path / "runtime.json"), 1)
    monkeypatch.setattr(runtime, "winreg", registry, raising=False)
    assert runtime._registered_runtime() == tmp_path / "runtime.json"
    registry.OpenKey.assert_called_once_with(1, r"SOFTWARE\Khronos\OpenXR\1", 0, 0x202)
    registry.SetValueEx.assert_not_called()
