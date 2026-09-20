"""Use Proton's registry with the same transactional value policy as Windows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.install.windows import (
    ENGINE_KEY,
    HARDWARE_KEY,
    ConfigurationError,
    WindowsInstallConfiguration,
)
from gk3hd.patch.manifest import ExternalChange
from gk3hd.system.proton import ProtonContext, discover_proton

if TYPE_CHECKING:
    from pathlib import Path


_REGISTRY_TYPES = {"REG_SZ": 1, "REG_EXPAND_SZ": 2, "REG_DWORD": 4}


@dataclass(frozen=True, slots=True)
class ProtonRegistryBackend:
    """Read/write individual values through reg.exe, never rewrite user.reg."""

    context: ProtonContext
    key_path: str

    def read(self, name: str) -> str | None:
        """Read a typed value while distinguishing missing values from failures."""
        result = self.context.run(("reg.exe", "query", "HKCU\\" + self.key_path, "/v", name))
        if result.returncode:
            output = (result.stdout + result.stderr).casefold()
            if "unable to find" in output or "cannot find" in output:
                return None
            msg = f"Proton could not read registry value {name!r}: {result.stdout.strip()}"
            raise ConfigurationError(msg)
        match = re.search(
            r"^\s*" + re.escape(name) + r"\s+(REG_\w+)\s*(.*?)\r?$", result.stdout, re.MULTILINE
        )
        if match is None or match[1] not in _REGISTRY_TYPES:
            msg = f"unsupported Proton registry value {name!r}; refusing to replace it"
            raise ConfigurationError(msg)
        value = int(match[2], 0) if match[1] == "REG_DWORD" else match[2]
        return json.dumps(
            {"type": _REGISTRY_TYPES[match[1]], "value": value},
            sort_keys=True,
            separators=(",", ":"),
        )

    def write(self, name: str, value: str | None) -> None:
        """Modify one journaled value, preserving every unrelated prefix setting."""
        key = "HKCU\\" + self.key_path
        if value is None:
            if self.read(name) is None:
                return
            arguments = ("reg.exe", "delete", key, "/v", name, "/f")
        else:
            payload = json.loads(value)
            names = {number: text for text, number in _REGISTRY_TYPES.items()}
            kind = names.get(payload["type"])
            if kind is None:
                msg = f"unsupported saved Proton registry type for {name!r}"
                raise ConfigurationError(msg)
            arguments = (
                "reg.exe",
                "add",
                key,
                "/v",
                name,
                "/t",
                kind,
                "/d",
                str(payload["value"]),
                "/f",
            )
        result = self.context.run(arguments)
        if result.returncode:
            msg = f"Proton could not update registry value {name!r}: {result.stdout.strip()}"
            raise ConfigurationError(msg)


class ProtonInstallConfiguration(WindowsInstallConfiguration):
    """Journal a per-game native-DLL override alongside the shared settings."""

    def __init__(self, context: ProtonContext) -> None:
        """Bind every registry surface to one resolved Proton prefix."""
        super().__init__(
            ProtonRegistryBackend(context, ENGINE_KEY),
            ProtonRegistryBackend(context, HARDWARE_KEY),
        )
        self.context = context
        self.manage_appcompat = False

    def prepare_renderer(self, *, exe: Path, digest: str) -> tuple[ExternalChange, ...]:
        """Configure native D7VK only for this executable, not every Wine game."""
        changes = super().prepare_renderer(exe=exe, digest=digest)
        backend = self._dll_registry(exe)
        return (
            *changes,
            ExternalChange(
                surface="registry:HKCU\\" + backend.key_path,
                key="ddraw",
                previous=backend.read("ddraw"),
                installed=json.dumps(
                    {"type": 1, "value": "native,builtin"}, sort_keys=True, separators=(",", ":")
                ),
            ),
        )

    def _dll_registry(self, exe: Path) -> ProtonRegistryBackend:
        return ProtonRegistryBackend(
            self.context, rf"Software\Wine\AppDefaults\{exe.name}\DllOverrides"
        )

    def _read_value(self, *, exe: Path, change: ExternalChange) -> str | None:
        registry = self._dll_registry(exe)
        if change.surface == "registry:HKCU\\" + registry.key_path and change.key == "ddraw":
            return registry.read(change.key)
        return super()._read_value(exe=exe, change=change)

    def _write_value(self, *, exe: Path, change: ExternalChange, value: str | None) -> None:
        registry = self._dll_registry(exe)
        if change.surface == "registry:HKCU\\" + registry.key_path and change.key == "ddraw":
            registry.write(change.key, value)
        else:
            super()._write_value(exe=exe, change=change, value=value)


def proton_configuration(exe: Path) -> ProtonInstallConfiguration:
    """Reuse rollback/verification while omitting Windows-only AppCompat layers."""
    context = discover_proton(exe)
    return ProtonInstallConfiguration(context)
