"""Source patches must apply when developers build inside another Git checkout."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

from gk3hd.vr.android.wine.build import source_environment

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_source_patch_applies_inside_an_enclosing_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = shutil.which("git")
    assert git is not None
    parent = tmp_path / "outer checkout"
    parent.mkdir()
    subprocess.run([git, "init", "--quiet", str(parent)], check=True)  # noqa: S603 - resolved Git and literal arguments
    sentinel = parent / "registry.c"
    sentinel.write_text("parent file must stay untouched\n")
    source = parent / "generated/source/wine"
    source.mkdir(parents=True)
    registry = source / "registry.c"
    registry.write_bytes(b"before\n")
    # A caller may have exported repository selection and line-ending options.
    monkeypatch.setenv("GIT_DIR", str(parent / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(parent))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    patch = b"--- a/registry.c\n+++ b/registry.c\n@@ -1 +1 @@\n-before\n+after\n"
    subprocess.run(  # noqa: S603 - resolved Git, fixed operation, fixture patch on stdin
        [git, "apply", "--whitespace=nowarn"],
        input=patch,
        cwd=source,
        env=source_environment(source, parent / "generated/build"),
        check=True,
        capture_output=True,
    )
    assert registry.read_bytes() == b"after\n"
    assert sentinel.read_text() == "parent file must stay untouched\n"
