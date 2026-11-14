"""Verify portable build records without compiling or executing fixture binaries."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from gk3hd.system.files import json_bytes, sha256_file
from gk3hd.vr.standalone import build as builder
from gk3hd.vr.standalone import sources
from gk3hd.vr.standalone.apk import COMPONENT_ASSET
from tests.unit.vr.standalone.test_apk import binary_manifest


@pytest.fixture
def components(tmp_path: Path) -> Path:
    for name in ("openxr_wxr32.dll", "gk3hd-wine-launcher.exe"):
        (tmp_path / name).write_bytes(b"non-executable fixture")
    with ZipFile(tmp_path / "gk3hd-standalone.apk", "w") as archive:
        archive.writestr("AndroidManifest.xml", binary_manifest())
        archive.writestr(
            COMPONENT_ASSET,
            "".join(
                f"{hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()}  {name}\n"
                for name in ("openxr_wxr32.dll", "gk3hd-wine-launcher.exe")
            ),
        )
    outputs = {
        name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        for name in (
            "openxr_wxr32.dll",
            "gk3hd-wine-launcher.exe",
            "gk3hd-standalone.apk",
        )
    }
    (tmp_path / "standalone-components.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "kind": "standalone-development-components",
                "upstream": json.loads(
                    (builder.RECIPE / "upstream.json").read_text(encoding="utf-8")
                ),
                "inputs": builder.source_hashes(),
                "outputs": outputs,
                "checks": sorted(builder._CHECKS),
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_current_build_record_accepts_unchanged_outputs(components: Path) -> None:
    assert builder.inspect_components(components) == components / "standalone-components.json"


@pytest.mark.parametrize(
    "problem", ["", "wrong build", "missing recipe", "wrong source", "wrong wine"]
)
def test_release_source_attachment_belongs_to_the_selected_build(
    components: Path, problem: str
) -> None:
    record = builder.inspect_components(components)
    data = json.loads(record.read_bytes())
    archive = components / "gk3hd-vr-sources.zip"
    standalone = components / "standalone.zip"
    wine = b"fixture Wine source"
    pins = json_bytes(
        {name: {"sha256": hashlib.sha256(wine).hexdigest()} for name in ("wine", "staging")}
    )
    data["inputs"] = {
        "wine/upstream.json": hashlib.sha256(pins).hexdigest(),
        "winlator.patch": hashlib.sha256(b"source changes").hexdigest(),
    }
    with ZipFile(archive, "w") as bundle:
        bundle.writestr(record.name, json_bytes(data))
        bundle.writestr(
            "SOURCES.txt", (builder.RECIPE.parent / "SOURCES.txt").read_text(encoding="utf-8")
        )
        for name in ("winlator", "vortek", "wxr"):
            snapshot = BytesIO()
            with ZipFile(snapshot, "w") as git_archive:
                git_archive.comment = (
                    "0" * 40
                    if name == "wxr" and problem == "wrong source"
                    else data["upstream"][name]["commit"]
                ).encode()
                git_archive.writestr("source.c", "fixture")
            bundle.writestr(f"upstream/{name}.zip", snapshot.getvalue())
        bundle.writestr(
            "upstream/wine.tar.gz", b"different Wine" if problem == "wrong wine" else wine
        )
        bundle.writestr("upstream/staging.tar.gz", wine)
        bundle.writestr("gk3hd/src/gk3hd/vr/android/wine/upstream.json", pins)
        if problem != "missing recipe":
            bundle.writestr("gk3hd/src/gk3hd/vr/android/winlator.patch", "source changes")
    data["source_archive_sha256"] = sha256_file(archive)
    if problem == "wrong build":
        data["outputs"]["gk3hd-standalone.apk"] = "a" * 64
    with ZipFile(standalone, "w") as binaries:
        binaries.writestr(record.name, json_bytes(data))

    if problem:
        with pytest.raises(ValueError, match="does not match the signed component build"):
            sources.attachment(components, standalone, name="verified.zip")
        assert not (components / "verified.zip").exists()
    else:
        attached = sources.attachment(components, standalone, name="verified.zip")
        assert attached.read_bytes() == archive.read_bytes()


def test_build_record_must_include_the_native_draw_watchdog_check(components: Path) -> None:
    receipt = components / "standalone-components.json"
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["checks"].remove("native-draw-progress-java")
    receipt.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="current source/build checks"):
        builder.inspect_components(components)


def test_valid_outputs_cannot_pair_an_apk_with_another_runtime(components: Path) -> None:
    runtime = components / "openxr_wxr32.dll"
    runtime.write_bytes(b"another independently built runtime")
    receipt = components / "standalone-components.json"
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["outputs"][runtime.name] = hashlib.sha256(runtime.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="APK and guest components do not match"):
        builder.inspect_components(components)


@pytest.mark.parametrize("name", ["openxr_wxr32.dll", "gk3hd-wine-launcher.exe"])
def test_changed_or_missing_component_cannot_pass(components: Path, name: str) -> None:
    (components / name).write_bytes(b"substituted output")
    with pytest.raises(ValueError, match="component changed"):
        builder.inspect_components(components)
    (components / name).unlink()
    with pytest.raises(ValueError, match="component changed"):
        builder.inspect_components(components)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema", 2),
        ("kind", "release-qualified"),
        ("inputs", {}),
        ("upstream", {}),
        ("checks", ["wine-messages"]),
        ("checks", [{"unhashable": True}]),
        ("outputs", {"../foreign.dll": "not an output"}),
    ],
)
def test_incomplete_or_stale_provenance_is_rejected(
    components: Path, key: str, value: object
) -> None:
    record = components / "standalone-components.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data[key] = value
    record.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="current source/build checks"):
        builder.inspect_components(components)


def test_matching_hash_does_not_authorize_another_apps_apk(components: Path) -> None:
    apk = components / "gk3hd-standalone.apk"
    with ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", binary_manifest("com.example.personal"))
    record = components / "standalone-components.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["outputs"][apk.name] = hashlib.sha256(apk.read_bytes()).hexdigest()
    record.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="other apps were preserved"):
        builder.inspect_components(components)


def test_record_does_not_encode_builders_absolute_paths(components: Path) -> None:
    record = components / "standalone-components.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    assert all(not name.startswith(("/", "\\")) and ":" not in name for name in data["inputs"])
    assert str(components) not in record.read_text(encoding="utf-8")


def test_build_fails_before_any_source_download_without_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder.shutil, "which", lambda _name: None)
    output = tmp_path / "new build"
    with pytest.raises(ValueError, match="Windows and PowerShell"):
        builder.build(toolchain=builder.Toolchain(tmp_path), output=output)
    assert not output.exists()


def test_wrong_wsl_compiler_explains_how_to_select_another_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(builder.shutil, "which", Mock(return_value="wsl.exe"))
    run = Mock(return_value=Mock(returncode=0, stdout="0.0.0\n"))
    monkeypatch.setattr(builder.subprocess, "run", run)

    with pytest.raises(ValueError, match=r"requires WSL GCC .+found 0\.0\.0.+--wsl-distribution"):
        builder._check_wine_compiler("Fixture Linux")

    assert run.call_args.args[0][1:3] == ["-d", "Fixture Linux"]


def test_failed_compilation_keeps_diagnostics_outside_the_game_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "temporary build"
    scratch.mkdir()
    output = tmp_path / "game library" / "gk3hd" / "vr" / "standalone" / "candidate"
    monkeypatch.setattr(builder, "_build_tools", Mock(return_value=("pwsh", tmp_path)))
    monkeypatch.setattr(builder, "_renderer", Mock())
    monkeypatch.setattr(builder, "mkdtemp", Mock(return_value=str(scratch)))

    def fail(command: list[str], **_options: object) -> Mock:
        native_output = Path(command[command.index("-OutputRoot") + 1])
        native_output.mkdir()
        (native_output / "failure.log").write_text("toolchain failed", encoding="utf-8")
        return Mock(returncode=1)

    monkeypatch.setattr(builder.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="Intermediate files are in"):
        builder.build(toolchain=builder.Toolchain(tmp_path), output=output, renderer_build=tmp_path)
    assert list(output.iterdir()) == []
    assert len(list(scratch.rglob("failure.log"))) == 1


@pytest.fixture
def sdk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    monkeypatch.setattr(builder.shutil, "which", Mock(return_value=None))
    (tmp_path / "platforms").mkdir()
    return tmp_path


@pytest.mark.parametrize("variable", ["ANDROID_HOME", "ANDROID_SDK_ROOT"])
def test_standard_sdk_environment_is_respected(
    sdk: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, str(sdk))
    assert builder.android_sdk() == sdk.resolve()


def test_sdk_can_be_discovered_from_platform_tools(
    sdk: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        builder.shutil, "which", Mock(return_value=str(sdk / "platform-tools/adb.exe"))
    )
    assert builder.android_sdk() == sdk.resolve()


def test_explicit_sdk_takes_precedence_over_environment(
    sdk: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANDROID_HOME", str(sdk / "missing"))
    assert builder.android_sdk(sdk) == sdk.resolve()


def test_invalid_explicit_sdk_does_not_fall_back(
    sdk: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    with pytest.raises(ValueError, match="Android SDK not found"):
        builder.android_sdk(sdk / "missing")


def test_platform_tools_alone_are_not_a_build_sdk(sdk: Path) -> None:
    with pytest.raises(ValueError, match="Platform Tools alone"):
        builder.android_sdk(sdk / "platform-tools")
