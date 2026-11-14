"""Build development Android/runtime components from pinned source, never install."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

from gk3hd.system.files import sha256_file
from gk3hd.vr.android.notices import COMPONENT_LICENSES
from gk3hd.vr.artifact import RECIPE as RENDERER_RECIPE
from gk3hd.vr.artifact import VRRendererAsset, inspect_vr_dll
from gk3hd.vr.build import build as build_renderer
from gk3hd.vr.standalone import sources
from gk3hd.vr.standalone.apk import MAX_APK_BYTES, player_components, require_player_apk
from gk3hd.vr.standalone.paths import APK_FILENAME, BUILD_RECORD, record_build, workspace
from gk3hd.vr.standalone.signing import ReleaseSigner, build_environment, release_keystore

RECIPE = Path(__file__).resolve().parents[1] / "android"
MAX_JOBS = 8
_CHECKS = frozenset(json.loads((RECIPE / "component-checks.json").read_text(encoding="utf-8")))
_OUTPUTS = {
    "openxr_wxr32.dll": 8 * 1024**2,
    "gk3hd-wine-launcher.exe": 8 * 1024**2,
    APK_FILENAME: MAX_APK_BYTES,
}
_SOURCE_SUFFIXES = {
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".patch",
    ".json",
    ".ps1",
    ".sh",
    ".py",
    ".vert",
    ".frag",
}


@dataclass(frozen=True, slots=True)
class Toolchain:
    """Android SDK, WSL compiler distribution and optional release variant."""

    android_sdk: Path | None = None
    wsl_distribution: str | None = None
    release: bool = False


def android_sdk(explicit: Path | None = None) -> Path:
    """Find a standard Android SDK, preserving explicit choices and env precedence."""
    candidate = explicit
    if candidate is None:
        configured = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if configured:
            candidate = Path(configured)
        elif executable := shutil.which("adb"):
            platform_tools = Path(executable).resolve().parent
            if platform_tools.name == "platform-tools":
                candidate = platform_tools.parent
    if candidate is None or not candidate.is_dir() or not (candidate / "platforms").is_dir():
        msg = (
            "Android SDK not found; set ANDROID_HOME or pass --android-sdk PATH. "
            "Android Platform Tools alone are insufficient for building."
        )
        raise ValueError(msg)
    return candidate.resolve()


def source_hashes() -> dict[str, str]:
    """Hash the shipped recipe/fixtures with the build's CRLF-independent policy."""
    return {
        path.relative_to(RECIPE).as_posix(): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for path in sorted(RECIPE.rglob("*"))
        if path.is_file() and (path.suffix in _SOURCE_SUFFIXES or path.name == "CMakeLists.txt")
    }


def inspect_components(directory: Path) -> Path:
    """Require current source/check provenance and unchanged development outputs.

    This is local build verification, not a signing trust root, physical headset
    qualification or a declaration that all upstream license obligations are met.
    """
    record = directory / BUILD_RECORD
    if not record.is_file() or record.stat().st_size > 512 * 1024:
        msg = "Missing or oversized standalone component build record"
        raise ValueError(msg)
    data = json.loads(record.read_text(encoding="utf-8"))
    pin = json.loads((RECIPE / "upstream.json").read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schema") != 1
        or data.get("kind") != "standalone-development-components"
        or data.get("upstream") != pin
        or data.get("inputs") != source_hashes()
        or not isinstance(data.get("checks"), list)
        or any(not isinstance(check, str) for check in data["checks"])
        or len(data["checks"]) != len(_CHECKS)
        or set(data["checks"]) != _CHECKS
        or not isinstance(data.get("outputs"), dict)
        or set(data["outputs"]) != set(_OUTPUTS)
    ):
        msg = "Standalone components do not match the current source/build checks; rebuild"
        raise ValueError(msg)
    for name, maximum in _OUTPUTS.items():
        path = directory / name
        if (
            not path.is_file()
            or not 0 < path.stat().st_size <= maximum
            or sha256_file(path) != data["outputs"][name]
        ):
            msg = f"Standalone component changed or is missing: {name}"
            raise ValueError(msg)
    require_player_apk(directory / APK_FILENAME)
    for name, expected in player_components(directory / APK_FILENAME).items():
        if data["outputs"][name] != expected:
            msg = "Standalone APK and guest components do not match; rebuild the player"
            raise ValueError(msg)
    return record


def _renderer(directory: Path) -> VRRendererAsset:
    pin = json.loads((RENDERER_RECIPE / "upstream.json").read_text(encoding="utf-8"))
    asset = inspect_vr_dll(directory / f"dxvk-sarek-{pin['version']}-xr-prototype.dll")
    # Native quad regressions compile the same action implementation as this
    # renderer. Do not trust mutable leftover sources just because its DLL passed.
    record = json.loads(asset.path.with_suffix(".json").read_text(encoding="utf-8"))
    for name, expected in record["openxr_inputs"].items():
        path = directory / "xr-source" / name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected
        ):
            msg = "The renderer build's native qualification sources changed; rebuild it"
            raise ValueError(msg)
    return asset


def _copy_components(child: Path, target: Path, signing: tuple[ReleaseSigner, Path] | None) -> None:
    record = inspect_components(child)
    for name in (*_OUTPUTS, *COMPONENT_LICENSES):
        if name == APK_FILENAME and signing is not None:
            signer, keystore = signing
            signer.sign(child / name, target / name, keystore)
        else:
            shutil.copyfile(child / name, target / name)
    if signing is None:
        shutil.copyfile(record, target / record.name)
    else:
        data = json.loads(record.read_text(encoding="utf-8"))
        data["outputs"][APK_FILENAME] = sha256_file(target / APK_FILENAME)
        data["android_release_signer_sha256"] = signing[0].certificate
        (target / record.name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _build_tools(toolchain: Toolchain, jobs: int) -> tuple[str, Path]:
    shell = shutil.which("pwsh")
    if os.name != "nt" or not shell:
        msg = "Standalone component builds currently require Windows and PowerShell 7"
        raise ValueError(msg)
    if sys.version_info < (3, 14):
        msg = "Standalone component builds require Python 3.14 or newer"
        raise ValueError(msg)
    if not 1 <= jobs <= MAX_JOBS:
        msg = "Standalone build jobs must be between 1 and 8"
        raise ValueError(msg)
    sdk = android_sdk(toolchain.android_sdk)
    _check_wine_compiler(toolchain.wsl_distribution)
    return shell, sdk


def _check_wine_compiler(distribution: str | None) -> None:
    """Reject an incompatible WSL toolchain before compiling the VR renderer."""
    wsl = shutil.which("wsl")
    if wsl is None:
        msg = "Standalone builds require WSL with the pinned Wine server compiler"
        raise ValueError(msg)
    expected = json.loads((RECIPE / "wine/upstream.json").read_text(encoding="utf-8"))["gcc"]
    selection = ("-d", distribution) if distribution else ()
    try:
        compiler = subprocess.run(  # noqa: S603 - resolved WSL, fixed compiler query.
            [wsl, *selection, "--exec", "gcc", "-dumpfullversion"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        msg = "Cannot start the Wine compiler in WSL. Check --wsl-distribution."
        raise ValueError(msg) from error
    found = compiler.stdout.strip() if compiler.returncode == 0 else "unavailable"
    if found != expected:
        msg = f"Wine requires WSL GCC {expected} (found {found}). Check --wsl-distribution."
        raise ValueError(msg)


def build(
    *,
    toolchain: Toolchain,
    game_dir: Path | None = None,
    output: Path | None = None,
    renderer_build: Path | None = None,
    jobs: int = 4,
) -> Path:
    """Build a separate private APK/runtime/helper and verified renderer.

    Requires the Windows C++/Android toolchains. An explicit verified renderer
    build can be reused; otherwise the existing pinned VR renderer builder runs.
    No game files, headset apps, global environment or release assets are changed.
    """
    shell, sdk = _build_tools(toolchain, jobs)
    signing = (ReleaseSigner.configured(sdk), release_keystore()) if toolchain.release else None
    if output is None:
        directory = workspace(game_dir)
        target = directory / "build" / uuid4().hex
    else:
        directory = None
        target = output.resolve()
    if target.exists():
        msg = "Standalone build output already exists; choose a fresh --output directory"
        raise FileExistsError(msg)
    before = source_hashes()
    asset = _renderer(renderer_build.resolve()) if renderer_build else None
    target.mkdir(parents=True)
    if asset is None:
        asset = build_renderer(game_dir=game_dir, jobs=jobs)
        asset = _renderer(asset.path.parent)
    # MSBuild and Gradle create deep paths beneath their build root. Keep that
    # root independent of the length of the game's Steam or GOG library path.
    scratch = Path(mkdtemp(prefix="gk3vr-"))
    child = scratch / "build"
    completed = subprocess.run(  # noqa: S603 - fixed first-party recipe and separate arguments.
        [
            shell,
            "-NoProfile",
            "-File",
            str(RECIPE / "build-components.ps1"),
            "-OutputRoot",
            str(child),
            "-RendererBuild",
            str(asset.path.parent),
            "-AndroidSdk",
            str(sdk),
            "-Python",
            sys.executable,
            "-Jobs",
            str(jobs),
            *(
                ["-WslDistribution", toolchain.wsl_distribution]
                if toolchain.wsl_distribution
                else []
            ),
            *(["-Release"] if signing else []),
        ],
        env=build_environment(),
        check=False,
    )
    if completed.returncode:
        msg = f"Standalone component build failed. Intermediate files are in {scratch}"
        raise RuntimeError(msg)
    asset.verify_unchanged()
    if source_hashes() != before:
        msg = "Standalone source changed during compilation; no component set was published"
        raise ValueError(msg)
    _copy_components(child, target, signing)
    for path in [asset.path, *(path for path, _ in asset.companions)]:
        shutil.copyfile(path, target / path.name)
    record = inspect_components(target)
    inspect_vr_dll(target / asset.path.name)
    if signing is not None:
        sources.stage(child, target)
    if directory is not None:
        record_build(directory, record, release=toolchain.release)
    shutil.rmtree(scratch, ignore_errors=True)
    return target
