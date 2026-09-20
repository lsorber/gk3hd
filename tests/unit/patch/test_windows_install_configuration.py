"""Hermetic tests for Windows registry and INI installation state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from gk3hd.patch.install.configuration import GraphicsBackend
from gk3hd.patch.install.windows import (
    _WINDOWS_UPDATE_REBOOT_KEYS,
    ConfigurationError,
    Gk3LaunchCompatibilityState,
    WindowsInstallConfiguration,
    local_graphics_proxy_dlls,
    required_gk3_appcompat_layers,
)
from gk3hd.patch.manifest import ExternalChange
from gk3hd.patch.model import PatchId
from gk3hd.renderer import distribution as d7vk
from gk3hd.renderer.distribution import CONFIG_NAME as D7VK_CONFIG_NAME
from gk3hd.renderer.distribution import config_bytes as d7vk_config_bytes
from gk3hd.renderer.state import STATE_FILENAME, RendererState

if TYPE_CHECKING:
    from pathlib import Path

_RESOLUTION_VALUE_COUNT = 5
_CONFIGURATION_REGISTRY_VALUE_COUNT = _RESOLUTION_VALUE_COUNT


@pytest.mark.parametrize("previous", [None, b"previous approved renderer"])
def test_renderer_transaction_uses_frozen_digest_and_restores_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, previous: bytes | None
) -> None:
    monkeypatch.setattr(d7vk, "cache_directory", lambda: tmp_path / "cache")
    candidate = tmp_path / "candidate.dll"
    candidate.write_bytes(b"new approved renderer")
    d7vk.retain_dll(candidate)
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    exe = tmp_path / "GK3.exe"
    dll = tmp_path / "ddraw.dll"
    if previous is not None:
        dll.write_bytes(previous)
        d7vk.retain_dll(dll)
    configuration = WindowsInstallConfiguration(MemoryRegistry())
    changes = tuple(
        change
        for change in configuration.prepare_renderer(exe=exe, digest=digest)
        if change.key == "ddraw.dll"
    )
    assert len(changes) == 1
    assert changes[0].installed == f"sha256:{digest}"
    configuration.apply(exe=exe, changes=changes)
    configuration.verify(exe=exe, changes=changes)
    assert dll.read_bytes() == candidate.read_bytes()
    configuration.restore(exe=exe, changes=changes, force=False)
    assert (dll.read_bytes() if dll.exists() else None) == previous


def test_installed_renderer_ownership_survives_cache_eviction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(d7vk, "cache_directory", lambda: tmp_path / "empty-cache")
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"game")
    dll = tmp_path / "ddraw.dll"
    dll.write_bytes(b"installed newer renderer")
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()
    changes = (
        ExternalChange("file:d7vk-binary", "ddraw.dll", None, f"sha256:{digest}"),
        ExternalChange("file", "dxvk.conf", None, "base64:"),
    )
    state = RendererState(changes, exe.name)
    exe.with_name(STATE_FILENAME).write_text(json.dumps(state.to_dict()), encoding="utf-8")
    assert local_graphics_proxy_dlls(tmp_path, allow_owned_d7vk=True) == ()
    dll.write_bytes(b"user replacement")
    assert local_graphics_proxy_dlls(tmp_path, allow_owned_d7vk=True) == (dll.name,)


@pytest.mark.parametrize("backend", list(GraphicsBackend))
def test_only_d7vk_requires_windows_rgb565_surfaces(backend: GraphicsBackend) -> None:
    previous = '{"type":1,"value":"~ WIN8RTM HIGHDPIAWARE"}'
    installed = required_gk3_appcompat_layers(previous, graphics_backend=backend)
    tokens = json.loads(installed)["value"].split()
    assert ("16BITCOLOR" in tokens) is (backend is GraphicsBackend.D7VK)
    assert tokens.count("HIGHDPIAWARE") == 1
    assert "WIN8RTM" in tokens
    assert "DWM8And16BitMitigation" in tokens
    assert required_gk3_appcompat_layers(installed, graphics_backend=backend) == installed


def test_d7vk_refuses_conflicting_256_color_policy() -> None:
    with pytest.raises(ConfigurationError, match="256-color"):
        required_gk3_appcompat_layers(
            '{"type":1,"value":"256COLOR"}', graphics_backend=GraphicsBackend.D7VK
        )


def test_d7vk_color_setting_is_transactional(tmp_path: Path) -> None:
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    previous = '{"type":1,"value":"~ HIGHDPIAWARE"}'
    registry = MemoryRegistry({str(exe.resolve()): previous})
    configuration = WindowsInstallConfiguration(registry)
    changes = configuration.prepare_renderer(exe=exe, digest="a" * 64)
    # Exercise the actual prepared AppCompat change without downloading a DLL.
    appcompat_changes = tuple(change for change in changes if change.key == str(exe.resolve()))
    assert len(appcompat_changes) == 1
    configuration.apply(exe=exe, changes=appcompat_changes)
    configuration.verify(exe=exe, changes=appcompat_changes)
    assert "16BITCOLOR" in registry.values[str(exe.resolve())]
    configuration.restore(exe=exe, changes=appcompat_changes, force=False)
    assert registry.values == {str(exe.resolve()): previous}


@pytest.mark.parametrize(
    "previous", [None, b"", b"# player\r\n[Other.exe]\r\nd3d9.presentInterval = 1"]
)
def test_d7vk_presentation_policy_restores_exact_original(
    tmp_path: Path, previous: bytes | None
) -> None:
    exe = tmp_path / "GK3.exe"
    config = tmp_path / D7VK_CONFIG_NAME
    if previous is not None:
        config.write_bytes(previous)
    configuration = WindowsInstallConfiguration(MemoryRegistry())
    changes = tuple(
        change
        for change in configuration.prepare_renderer(exe=exe, digest="a" * 64)
        if change.key == D7VK_CONFIG_NAME
    )
    assert len(changes) == 1
    configuration.apply(exe=exe, changes=changes)
    configuration.verify(exe=exe, changes=changes)
    installed = d7vk_config_bytes(executable_name=exe.name, previous=previous or b"")
    assert config.read_bytes() == installed
    config.write_bytes(installed + b"# changed after install\n")
    with pytest.raises(ConfigurationError, match="no longer matches"):
        configuration.restore(exe=exe, changes=changes, force=False)
    config.write_bytes(installed)
    configuration.restore(exe=exe, changes=changes, force=False)
    assert (config.read_bytes() if config.exists() else None) == previous


def test_launch_preflight_covers_both_windows_update_reboot_markers() -> None:
    """Feature-upgrade commits cannot hide behind the older missing marker."""
    assert len(_WINDOWS_UPDATE_REBOOT_KEYS) == 2
    assert any(key.endswith("RebootRequired") for key in _WINDOWS_UPDATE_REBOOT_KEYS)
    assert any(key.endswith("CommitRequired") for key in _WINDOWS_UPDATE_REBOOT_KEYS)


def test_launch_compatibility_state_reports_any_active_merge_blocker() -> None:
    """The merge flag is unsafe both during and after a pending restart."""
    assert (
        Gk3LaunchCompatibilityState(
            appcompat_merge_disabled=False,
            windows_update_reboot_required=True,
        ).blocker()
        is None
    )
    pending_update = Gk3LaunchCompatibilityState(
        appcompat_merge_disabled=True,
        windows_update_reboot_required=True,
    ).blocker()
    assert pending_update is not None
    assert "requires a restart" in pending_update
    stale_servicing = Gk3LaunchCompatibilityState(
        appcompat_merge_disabled=True,
        windows_update_reboot_required=False,
    ).blocker()
    assert stale_servicing is not None
    assert "DisableMergeSdbs=1" in stale_servicing


def test_graphics_proxy_discovery_is_case_specific_and_ordered(tmp_path: Path) -> None:
    """Native acceptance detects exactly the Windows proxy filenames it owns."""
    (tmp_path / "ddraw.dll").write_bytes(b"proxy")
    (tmp_path / "d3d9.dll").write_bytes(b"proxy")
    (tmp_path / "unrelated.dll").write_bytes(b"keep")

    assert local_graphics_proxy_dlls(tmp_path) == ("ddraw.dll", "d3d9.dll")


def test_modern_resolution_patch_does_not_install_a_graphics_backend(tmp_path: Path) -> None:
    """Mode exposure remains a self-contained GK3.exe capability."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    configuration = WindowsInstallConfiguration(
        MemoryRegistry(),
    )

    changes = configuration.prepare(
        exe=exe,
        width=3840,
        height=2160,
        patches=(PatchId("enable_modern_resolutions"),),
        graphics_backend=GraphicsBackend.NATIVE,
    )

    assert all(change.key not in {"ddraw.dll", D7VK_CONFIG_NAME} for change in changes)


@dataclass(slots=True)
class MemoryRegistry:
    """Store serialized registry values without accessing the live registry."""

    values: dict[str, str] = field(default_factory=dict)
    fail_on_write: int | None = None
    writes: int = 0

    def read(self, name: str) -> str | None:
        """Read one in-memory value."""
        return self.values.get(name)

    def write(self, name: str, value: str | None) -> None:
        """Write one value, with an optional deterministic fault."""
        self.writes += 1
        if self.writes == self.fail_on_write:
            msg = "injected registry failure"
            raise OSError(msg)
        if value is None:
            self.values.pop(name, None)
        else:
            self.values[name] = value


def test_configuration_apply_verify_and_restore_are_exact(tmp_path: Path) -> None:
    """Registry values round-trip while patching leaves texture INI state alone."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    ini = tmp_path / "GK3.ini"
    original_ini = b"[Paths]\r\nCUSTOM PATHS = gk3hd\r\n"
    ini.write_bytes(original_ini)
    registry = MemoryRegistry()
    configuration = WindowsInstallConfiguration(registry)

    changes = configuration.prepare(exe=exe, width=1920, height=1080)
    configuration.apply(exe=exe, changes=changes)
    configuration.verify(exe=exe, changes=changes)

    assert ini.read_bytes() == original_ini
    assert len(registry.values) == _CONFIGURATION_REGISTRY_VALUE_COUNT
    # Renderer installation owns compatibility flags; patching only sets the
    # requested resolution here and must not change presentation independently.
    assert str(exe.resolve()) not in registry.values

    configuration.restore(exe=exe, changes=changes, force=False)
    assert ini.read_bytes() == original_ini
    assert registry.values == {}


def test_rendering_quality_patch_owns_explicit_maximum_hardware_profile(
    tmp_path: Path,
) -> None:
    """Saved Medium/full-redraw preferences cannot override the quality patch."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    engine = MemoryRegistry()
    hardware = MemoryRegistry(
        {
            "Incremental Rendering": '{"type":4,"value":0}',
            "Surface Quality": '{"type":1,"value":"Medium"}',
        }
    )
    appcompat = MemoryRegistry()
    original_hardware = dict(hardware.values)
    configuration = WindowsInstallConfiguration(
        engine,
        hardware=hardware,
        appcompat=appcompat,
    )

    changes = configuration.prepare(
        exe=exe,
        width=3840,
        height=2160,
        patches=(PatchId("maximize_graphics_quality"),),
        graphics_backend=GraphicsBackend.NATIVE,
    )
    configuration.apply(exe=exe, changes=changes)
    configuration.verify(exe=exe, changes=changes)

    assert hardware.values == {
        "Incremental Rendering": '{"type":4,"value":0}',
        "Mip Mapping": '{"type":4,"value":1}',
        "Interpolation": '{"type":4,"value":1}',
        "Trilinear Filtering": '{"type":4,"value":1}',
        "Lod": '{"type":4,"value":100}',
        "Max Anisotropy Level": '{"type":4,"value":4294967295}',
        "Gamma": '{"type":1,"value":"1.000000"}',
        "Surface Quality": '{"type":1,"value":"High"}',
    }
    assert sum("\\Hardware" in change.surface for change in changes) == 8

    configuration.restore(exe=exe, changes=changes, force=False)
    assert engine.values == {}
    assert hardware.values == original_hardware
    assert appcompat.values == {}


def test_native_quality_policy_retains_the_identity_gamma_curve(tmp_path: Path) -> None:
    """Color policy remains identical across presentation backends."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    hardware = MemoryRegistry()
    configuration = WindowsInstallConfiguration(
        MemoryRegistry(),
        hardware=hardware,
        appcompat=MemoryRegistry(),
    )

    changes = configuration.prepare(
        exe=exe,
        width=1920,
        height=1080,
        patches=(PatchId("maximize_graphics_quality"),),
        graphics_backend=GraphicsBackend.NATIVE,
    )
    configuration.apply(exe=exe, changes=changes)

    assert hardware.values["Gamma"] == '{"type":1,"value":"1.000000"}'


@pytest.mark.parametrize("original", [b"CUSTOM PATHS = mods\n", b"[Paths]\n"])
def test_patch_configuration_never_owns_texture_paths(tmp_path: Path, original: bytes) -> None:
    """The executable component cannot claim the texture component's INI surface."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    ini = tmp_path / "GK3.ini"
    ini.write_bytes(original)
    (tmp_path / "gk3hd").mkdir()
    registry = MemoryRegistry()
    configuration = WindowsInstallConfiguration(registry)

    changes = configuration.prepare(exe=exe, width=1920, height=1080)
    configuration.apply(exe=exe, changes=changes)

    assert ini.read_bytes() == original
    assert all(change.key != ini.name for change in changes)
    configuration.restore(exe=exe, changes=changes, force=False)
    assert ini.read_bytes() == original


def test_configuration_leaves_ini_without_path_line_unchanged_when_no_hd_roots(
    tmp_path: Path,
) -> None:
    """A texture-path edit is not owned when the installation has no HD roots."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    ini = tmp_path / "GK3.ini"
    original = b"[Paths]\n"
    ini.write_bytes(original)
    configuration = WindowsInstallConfiguration(MemoryRegistry())

    changes = configuration.prepare(exe=exe, width=1920, height=1080)

    assert all(change.surface != "file" for change in changes)
    assert ini.read_bytes() == original


def test_configuration_preserves_unrelated_appcompat_tokens(tmp_path: Path) -> None:
    """Required GK3 layers are merged without discarding user compatibility policy."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    key = str(exe.resolve())
    original = '{"type":1,"value":"WINXPSP3 DWM8And16BitMitigation"}'
    registry = MemoryRegistry({key: original})
    configuration = WindowsInstallConfiguration(registry)

    changes = tuple(
        change
        for change in configuration.prepare_renderer(exe=exe, digest="a" * 64)
        if change.key == key
    )
    configuration.apply(exe=exe, changes=changes)

    assert registry.values[key] == (
        '{"type":1,"value":"WINXPSP3 DWM8And16BitMitigation HIGHDPIAWARE 16BITCOLOR"}'
    )
    configuration.restore(exe=exe, changes=changes, force=False)
    assert registry.values[key] == original


def test_required_appcompat_policy_is_idempotent() -> None:
    """Temporary captures and durable installs converge on one token set."""
    original = '{"type":1,"value":"WINXPSP3 DWM8And16BitMitigation HIGHDPIAWARE"}'

    assert required_gk3_appcompat_layers(original) == original


def test_restore_protects_post_install_user_changes(tmp_path: Path) -> None:
    """A normal restore refuses to overwrite a setting edited after apply."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    registry = MemoryRegistry()
    configuration = WindowsInstallConfiguration(registry)
    changes = configuration.prepare(exe=exe, width=1920, height=1080)
    configuration.apply(exe=exe, changes=changes)
    registry.values["Game Width"] = '{"type":4,"value":1280}'

    with pytest.raises(ConfigurationError, match="no longer matches"):
        configuration.restore(exe=exe, changes=changes, force=False)

    configuration.restore(exe=exe, changes=changes, force=True)
    assert registry.values == {}


def test_failed_configuration_apply_rolls_back_completed_values(tmp_path: Path) -> None:
    """A mid-transaction registry failure restores every completed write."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    registry = MemoryRegistry(fail_on_write=3)
    configuration = WindowsInstallConfiguration(registry)
    changes = configuration.prepare(exe=exe, width=1920, height=1080)

    with pytest.raises(OSError, match="injected registry failure"):
        configuration.apply(exe=exe, changes=changes)

    assert registry.values == {}


def test_failed_forced_restore_preserves_exact_user_values(tmp_path: Path) -> None:
    """A write fault cannot replace post-install edits with stale defaults."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    registry = MemoryRegistry()
    configuration = WindowsInstallConfiguration(registry)
    changes = configuration.prepare(exe=exe, width=1920, height=1080)
    configuration.apply(exe=exe, changes=changes)
    registry.values["Game Width"] = '{"type":4,"value":1280}'
    registry.values["Game Height"] = '{"type":4,"value":720}'
    entry = dict(registry.values)
    registry.fail_on_write = registry.writes + 3

    with pytest.raises(OSError, match="injected registry failure"):
        configuration.restore(exe=exe, changes=changes, force=True)

    assert registry.values == entry


def test_interrupted_apply_recovery_accepts_only_known_states(tmp_path: Path) -> None:
    """Recovery handles partial writes but protects unrelated later edits."""
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(b"fixture")
    registry = MemoryRegistry()
    configuration = WindowsInstallConfiguration(registry)
    changes = configuration.prepare(exe=exe, width=1920, height=1080)
    registry.values["Game Width"] = changes[0].installed
    registry.values["Game Height"] = changes[1].installed

    configuration.recover_interrupted_apply(exe=exe, changes=changes)
    assert registry.values == {}

    registry.values["Game Width"] = '{"type":4,"value":1280}'
    with pytest.raises(ConfigurationError, match="changed outside"):
        configuration.recover_interrupted_apply(exe=exe, changes=changes)
    assert registry.values["Game Width"] == '{"type":4,"value":1280}'


@pytest.mark.parametrize(
    "change",
    [
        ExternalChange(
            "registry:HKCU\\Software\\Sierra On-Line\\Gabriel Knight 3\\Engine",
            "Unowned Value",
            None,
            '{"type":4,"value":1}',
        ),
        ExternalChange("file", "GK3.exe", None, "base64:dGFtcGVyZWQ="),
    ],
)
def test_configuration_rejects_manifest_targets_it_does_not_own(
    tmp_path: Path,
    change: ExternalChange,
) -> None:
    """Even a forced restore cannot turn manifest data into an arbitrary write."""
    exe = tmp_path / "GK3.exe"
    original = b"synthetic executable"
    exe.write_bytes(original)
    registry = MemoryRegistry()
    configuration = WindowsInstallConfiguration(registry)

    with pytest.raises(ConfigurationError, match="unsupported external configuration target"):
        configuration.restore(exe=exe, changes=(change,), force=True)

    assert exe.read_bytes() == original
    assert registry.values == {}
    assert registry.writes == 0
