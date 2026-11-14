"""Sign and verify standalone release APKs using the Android SDK."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from gk3hd.system.files import is_sha256
from gk3hd.vr.android import notices
from gk3hd.vr.android.prune_windows_payload import unused_wrapper
from gk3hd.vr.android.runtime_assets import apk_runtime
from gk3hd.vr.standalone.apk import require_player_apk

_KEYSTORE_UNLOCK_ENV = "GK3HD_VR_KEYSTORE_PASSWORD"
_CERTIFICATE = "GK3HD_VR_SIGNER_SHA256"
_UNUSED_AUDIO = frozenset(
    json.loads(
        (Path(__file__).resolve().parents[1] / "android/release-audio-exclusions.json").read_bytes()
    )
)


def _run(tool: list[str], purpose: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - SDK tools with explicit arguments.
            tool,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        message = f"Android SDK timed out while attempting to {purpose}"
        raise RuntimeError(message) from error
    if result.returncode:
        message = f"Android SDK could not {purpose}: {result.stderr.strip()[-1500:]}"
        raise ValueError(message)
    return result.stdout


@dataclass(frozen=True, slots=True)
class ReleaseSigner:
    """Require one approved certificate and a non-debuggable player APK."""

    certificate: str
    java: str
    tools: Path

    @classmethod
    def configured(cls, sdk: Path) -> ReleaseSigner:
        """Read the persistent certificate fingerprint from release configuration."""
        certificate = os.environ.get(_CERTIFICATE, "").strip().lower()
        if not is_sha256(certificate):
            message = f"Set {_CERTIFICATE} to the expected Android release certificate SHA-256"
            raise ValueError(message)
        java = shutil.which("java")
        # Launch the SDK's signer without a platform shell.
        tools = sdk / "build-tools" / "35.0.1"
        aapt = tools / ("aapt2.exe" if os.name == "nt" else "aapt2")
        if java is None or not (tools / "lib/apksigner.jar").is_file() or not aapt.is_file():
            message = "Android release signing requires Java and Android SDK Build Tools 35.0.1"
            raise ValueError(message)
        return cls(certificate, java, tools)

    def _apksigner(self, *args: str) -> list[str]:
        return [self.java, "-jar", str(self.tools / "lib/apksigner.jar"), *args]

    def verify(self, apk: Path) -> None:
        """Check the APK's actual signature and manifest before publication."""
        require_player_apk(apk)
        with ZipFile(apk) as archive:
            for name in archive.namelist():
                if name.startswith("lib/") and name.rsplit("/", 1)[-1] in _UNUSED_AUDIO:
                    message = f"The release APK includes an unused upstream audio library: {name}"
                    raise ValueError(message)
                normalized = name.casefold()
                if normalized.startswith("assets/wincomponents/") and normalized.endswith(".tzst"):
                    message = (
                        f"The release APK includes an optional upstream Windows archive: {name}"
                    )
                    raise ValueError(message)
                family = normalized.removeprefix("assets/dxwrapper/").split("/", 1)[0]
                if normalized.startswith("assets/dxwrapper/") and unused_wrapper(family):
                    message = (
                        f"The release APK includes an unused upstream graphics wrapper: {name}"
                    )
                    raise ValueError(message)
            notices.verify(archive)
        apk_runtime(apk, required=True)
        report = _run(
            self._apksigner("verify", "--print-certs", str(apk)), "verify the release APK signature"
        )
        certificates = re.findall(r"(?m)^Signer #\d+ certificate SHA-256 digest: (\S+)$", report)
        if certificates != [self.certificate]:
            message = "The APK does not have the configured Android release signer"
            raise ValueError(message)
        aapt = self.tools / ("aapt2.exe" if os.name == "nt" else "aapt2")
        manifest = _run(
            [str(aapt), "dump", "badging", str(apk)], "inspect the release APK manifest"
        )
        if "application-debuggable" in manifest.splitlines():
            message = "A debuggable standalone APK cannot be published as a release"
            raise ValueError(message)

    def sign(self, unsigned: Path, destination: Path, keystore: Path) -> None:
        """Sign a Gradle-aligned release APK and verify the signed result."""
        _run(
            self._apksigner(
                "sign",
                "--ks",
                str(keystore),
                "--ks-pass",
                f"env:{_KEYSTORE_UNLOCK_ENV}",
                "--key-pass",
                f"env:{_KEYSTORE_UNLOCK_ENV}",
                "--v4-signing-enabled",
                "false",
                "--out",
                str(destination),
                str(unsigned),
            ),
            "sign the standalone release APK",
        )
        self.verify(destination)


def release_keystore() -> Path:
    """Find the release keystore before starting a native build."""
    configured = os.environ.get("GK3HD_VR_KEYSTORE")
    if not configured or not os.environ.get(_KEYSTORE_UNLOCK_ENV) or not Path(configured).is_file():
        message = f"Configure GK3HD_VR_KEYSTORE and {_KEYSTORE_UNLOCK_ENV} for release signing"
        raise ValueError(message)
    return Path(configured).resolve()


def build_environment() -> dict[str, str]:
    """Keep the keystore password out of the Android component build."""
    return {name: value for name, value in os.environ.items() if name != _KEYSTORE_UNLOCK_ENV}
