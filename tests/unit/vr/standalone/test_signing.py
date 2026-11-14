"""Require the configured release certificate and disallow debug builds."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from gk3hd.vr.android import runtime_assets
from gk3hd.vr.standalone import signing
from gk3hd.vr.standalone.paths import APK_FILENAME
from tests.unit.vr.standalone.test_build import components

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["components"]


def test_unconfigured_certificate_fails_before_sdk_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GK3HD_VR_SIGNER_SHA256", raising=False)
    with pytest.raises(ValueError, match="GK3HD_VR_SIGNER_SHA256"):
        signing.ReleaseSigner.configured(tmp_path)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("assets/wincomponents/wmdecoder.tzst", "optional upstream Windows archive"),
        ("lib/arm64-v8a/libpulseaudio.so", "unused upstream audio library"),
        ("assets/dxwrapper/d7vk-1.11.tzst", "unused upstream graphics wrapper"),
        (
            "assets/dxwrapper/cnc-ddraw-6.6/Shaders/bilinear.glsl",
            "unused upstream graphics wrapper",
        ),
    ],
)
def test_release_rejects_unused_upstream_payloads(
    components: Path, name: str, message: str
) -> None:
    apk = components / APK_FILENAME
    with ZipFile(apk, "a") as archive:
        archive.writestr(name, b"optional payload")
    signer = signing.ReleaseSigner("a" * 64, "java", components)
    with pytest.raises(ValueError, match=message):
        signer.verify(apk)


@pytest.mark.parametrize("entry", [None, b"unrelated notice"])
def test_release_rejects_a_missing_or_changed_commons_notice(
    components: Path, entry: bytes | None
) -> None:
    apk = components / APK_FILENAME
    if entry is not None:
        with ZipFile(apk, "a") as archive:
            archive.writestr("META-INF/NOTICE.txt", entry)
    signer = signing.ReleaseSigner("a" * 64, "java", components)
    with pytest.raises(ValueError, match=r"third-party notice: META-INF/NOTICE\.txt"):
        signer.verify(apk)


@pytest.mark.parametrize(
    ("apk_signer", "manifest", "error"),
    [
        ("b" * 64, "", "configured Android release signer"),
        ("a" * 64, "application-debuggable\n", "debuggable standalone APK"),
        ("a" * 64, "", ""),
    ],
)
def test_verify_requires_a_nondebuggable_apk_from_the_approved_signer(
    components: Path, monkeypatch: pytest.MonkeyPatch, apk_signer: str, manifest: str, error: str
) -> None:
    run = Mock(side_effect=[f"Signer #1 certificate SHA-256 digest: {apk_signer}\n", manifest])
    monkeypatch.setattr(signing, "_run", run)
    monkeypatch.setattr(signing.notices, "verify", Mock())
    with ZipFile(components / APK_FILENAME, "a") as archive:
        archive.writestr("assets/gk3hd-runtime.json", runtime_assets._manifest())
    signer = signing.ReleaseSigner("a" * 64, "java", components)
    if error:
        with pytest.raises(ValueError, match=error):
            signer.verify(components / APK_FILENAME)
    else:
        signer.verify(components / APK_FILENAME)
