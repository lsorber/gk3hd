"""Verify local OpenXR prototypes without making them flat release artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from gk3hd.renderer.artifact import RendererAsset, inspect_recipe_dll

RECIPE = Path(__file__).resolve().parents[1] / "renderer"


def source_hashes() -> dict[str, str]:
    """Match the build's complete XR source/test inventory, independent of CRLF."""
    return {
        path.name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in sorted((RECIPE / "vr").iterdir())
        if path.is_file()
        and (path.suffix in {".cpp", ".h", ".patch"} or path.name == "CMakeLists.txt")
    }


@dataclass(frozen=True, slots=True)
class VRRendererAsset:
    """A locally tested prototype, deliberately without a release-lock method."""

    path: Path
    version: str
    dll_sha256: str
    dll_size: int
    companions: tuple[tuple[Path, str], ...]

    def verify_unchanged(self) -> None:
        """Detect substitution after preflight, including build records/notices."""
        RendererAsset(
            self.path, self.version, self.dll_sha256, self.dll_size, self.companions
        ).verify_unchanged()


def inspect_vr_dll(path: Path) -> VRRendererAsset:
    """Require a matching recipe, native/GPU tests and OpenXR/JsonCpp notices.

    This is local-build qualification, not real-headset acceptance. It does
    not execute the DLL or select a runtime, and cannot authorize publication.
    """
    return _inspect(path)


def inspect_installed_vr_dll(path: Path) -> VRRendererAsset:
    """Revalidate the private installed DLL with the same full prototype gate."""
    return _inspect(path, filename="ddraw.dll")


def _inspect(path: Path, *, filename: str | None = None) -> VRRendererAsset:
    pin = json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8"))
    inputs = source_hashes()
    if not inputs:
        msg = "OpenXR source inventory is empty"
        raise ValueError(msg)
    asset = inspect_recipe_dll(
        path,
        version=pin["version"] + "-xr-prototype",
        expected={
            "openxr_prototype": True,
            "openxr_inputs": inputs,
            "openxr_native_tests": "passed",
            "openxr_gpu_tests": "passed",
        },
        extra_notices=("OpenXR.txt", "JsonCpp.txt"),
        filename=filename,
    )
    return VRRendererAsset(
        asset.path, asset.version, asset.dll_sha256, asset.dll_size, asset.companions
    )
