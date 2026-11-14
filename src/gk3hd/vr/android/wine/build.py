"""Build only the compatible standalone Wine server from pinned Linux source."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

RECIPE = Path(__file__).resolve().parent
MAX_ARCHIVE = 64 * 1024**2
MAX_EXPANDED = 800 * 1024**2
MAX_SERVER = 2 * 1024**2
ELF_HEADER = 64
MAX_JOBS = 8
OPTIONS = (
    "--enable-win64",
    "--disable-tests",
    "--without-x",
    "--without-wayland",
    "--without-freetype",
    "--without-gnutls",
)


def digest(path: Path) -> str:
    """Hash a source/build input without loading the whole archive."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive(output: Path, name: str, pin: dict[str, str]) -> Path:
    """Allow a verified preseeded archive, never replace an unexpected input."""
    path = output / f"{name}.tar.gz"
    if not pin["url"].startswith("https://codeload.github.com/"):
        msg = "Wine source requires the pinned HTTPS archive host"
        raise ValueError(msg)
    if not path.exists():
        partial = path.with_suffix(".partial")
        # The recipe fixes the HTTPS host above; content must also match SHA-256.
        with urllib.request.urlopen(pin["url"], timeout=60) as source, partial.open("xb") as target:  # noqa: S310
            size = 0
            while block := source.read(1024**2):
                size += len(block)
                if size > MAX_ARCHIVE:
                    msg = "Wine source archive exceeds its bound"
                    raise ValueError(msg)
                target.write(block)
        partial.rename(path)
    if path.is_symlink() or path.stat().st_size > MAX_ARCHIVE or digest(path) != pin["sha256"]:
        msg = "Wine source archive does not match its pin; existing input preserved"
        raise ValueError(msg)
    return path


def extract(path: Path, output: Path) -> None:
    """Expand a bounded source archive with Python's safe data filter."""
    with tarfile.open(path) as source:
        if sum(member.size for member in source.getmembers()) > MAX_EXPANDED:
            msg = "Expanded Wine source exceeds its bound"
            raise ValueError(msg)
        source.extractall(output, filter="data")


def _tool(name: str) -> str:
    program = shutil.which(name)
    if program is None:
        msg = f"Missing Wine server build tool: {name}"
        raise FileNotFoundError(msg)
    return program


def _record(package: Path, source: Path, compiler: str, patches: dict[str, str]) -> None:
    files = {"wineserver": digest(package / "wineserver")}
    for name in ("registry-save.patch", "private-temp.patch", "upstream.json"):
        target = package / name
        target.write_bytes((RECIPE / name).read_bytes().replace(b"\r\n", b"\n"))
        files[name] = digest(target)
    shutil.copyfile(source / "COPYING.LIB", package / "COPYING.LIB")
    files["COPYING.LIB"] = digest(package / "COPYING.LIB")
    record = {
        "schema": 1,
        "kind": "standalone-wine-registry-server",
        "upstream": json.loads((RECIPE / "upstream.json").read_text()),
        "patches": patches,
        "compiler": compiler,
        "configure": OPTIONS,
        "registry_source_sha256": digest(source / "server/registry.c"),
        "protocol_sha256": digest(source / "server/protocol.def"),
        "files": files,
        "default_async_registry": True,
        "default_versioned_dirty_tracking": True,
    }
    (package / "server-build.json").write_text(json.dumps(record, indent=2) + "\n")


def source_environment(source: Path, compiled: Path) -> dict[str, str]:
    """Apply archive patches independently of an enclosing checkout or Git settings."""
    environment = dict(os.environ)
    for name in (
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_CONFIG_PARAMETERS",
    ):
        environment.pop(name, None)
    # Wine Staging's patch backend delegates to `git apply`. Inside a parent
    # checkout Git can silently skip archive paths outside its current prefix.
    environment["GIT_CEILING_DIRECTORIES"] = str(source.parent)
    environment["GIT_CONFIG_COUNT"] = "1"
    environment["GIT_CONFIG_KEY_0"] = "core.autocrlf"
    environment["GIT_CONFIG_VALUE_0"] = "false"
    environment["CFLAGS"] = (
        f"-O2 -g0 -ffile-prefix-map={source}=wine-source -ffile-prefix-map={compiled}=wine-build"
    )
    environment["SOURCE_DATE_EPOCH"] = "1749168000"
    return environment


def build(output: Path, jobs: int) -> None:
    """Keep failures/logs in this fresh workspace and emit a bounded server package."""
    pin = json.loads((RECIPE / "upstream.json").read_text())
    if not 1 <= jobs <= MAX_JOBS:
        msg = "Wine server builds require one to eight jobs"
        raise ValueError(msg)
    compiler = subprocess.check_output([_tool("gcc"), "-dumpfullversion"], text=True).strip()  # noqa: S603 - resolved compiler, fixed argument
    if compiler != pin["gcc"]:
        msg = f"Wine server builds require GCC {pin['gcc']} (found {compiler})"
        raise ValueError(msg)
    output.mkdir(parents=True, exist_ok=True)
    source_root = output / "source"
    source_root.mkdir()
    for name in ("wine", "staging"):
        extract(archive(output, name, pin[name]), source_root)
    source = source_root / pin["wine"]["directory"]
    staging = source_root / pin["staging"]["directory"]
    compiled = output / "build"
    compiled.mkdir()
    environment = source_environment(source, compiled)
    patches = {}
    with (output / "build.log").open("xb") as log:

        def run(arguments: list[str], cwd: Path) -> None:
            arguments[0] = _tool(arguments[0])
            subprocess.run(  # noqa: S603 - pinned source tools, separate arguments, no shell
                arguments,
                cwd=cwd,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )

        run(
            [
                sys.executable,
                str(staging / "staging/patchinstall.py"),
                "--backend=patch",
                "--destdir=" + str(source),
                pin["staging"]["patchset"],
            ],
            source,
        )
        if digest(source / "server/registry.c") != pin["registry_base_sha256"]:
            msg = "Wine Staging registry base differs from the qualified source"
            raise ValueError(msg)
        if digest(source / "server/protocol.def") != pin["protocol_sha256"]:
            msg = "Wine server protocol differs from the installed client"
            raise ValueError(msg)
        for name in ("registry-save.patch", "private-temp.patch"):
            patch = output / name
            patch.write_bytes((RECIPE / name).read_bytes().replace(b"\r\n", b"\n"))
            run(["git", "apply", "--check", str(patch)], source)
            run(["git", "apply", str(patch)], source)
            patches[name] = digest(patch)
        run([str(source / "configure"), *OPTIONS], compiled)
        run(["make", f"-j{jobs}", "server/wineserver"], compiled)
        package = output / "package"
        package.mkdir()
        server = package / "wineserver"
        run(["strip", "-o", str(server), str(compiled / "server/wineserver")], compiled)
    image = server.read_bytes()
    if (
        not ELF_HEADER <= len(image) <= MAX_SERVER
        or image[:6] != b"\x7fELF\x02\x01"
        or image[18:20] != b"\x3e\x00"
    ):
        msg = "The built Wine server is not a bounded x86-64 ELF"
        raise ValueError(msg)
    _record(package, source, compiler, patches)


if __name__ == "__main__":
    build(Path(sys.argv[1]).resolve(), int(sys.argv[2]))
