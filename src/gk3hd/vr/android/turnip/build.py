"""Build the private Linux/ARM64 guest driver from pinned source and dependencies."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

CLI_ARGUMENTS = 2


def fetch(url: str, target: Path, expected: str, maximum: int) -> None:
    """Fetch one bounded, pinned build input into a fresh owned output."""
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(url, timeout=40) as response, target.open("xb") as output:  # noqa: S310
        while block := response.read(1024**2):
            total += len(block)
            if total > maximum:
                msg = "Source dependency exceeds its pinned size"
                raise ValueError(msg)
            digest.update(block)
            output.write(block)
    if digest.hexdigest() != expected:
        msg = f"Source dependency hash mismatch: {target.name}"
        raise ValueError(msg)


def build(output: Path) -> None:
    """Create an isolated sysroot and clean Mesa build, never install a driver."""
    recipe = Path(__file__).resolve().parent
    programs: dict[str, str] = {}
    for program in (
        "git",
        "tar",
        "zstd",
        "ninja",
        "pkg-config",
        "dpkg-deb",
        "aarch64-linux-gnu-gcc",
        "sh",
    ):
        executable = shutil.which(program)
        if executable is None:
            msg = f"Missing Linux build tool: {program}"
            raise RuntimeError(msg)
        programs[program] = executable
    output.mkdir()
    pin = json.loads((recipe / "upstream.json").read_text())
    archive = output / "mesa.tar.xz"
    fetch(pin["mesa"]["url"], archive, pin["mesa"]["sha256"], pin["mesa"]["bytes"])
    packages = output / "packages"
    packages.mkdir()

    def dependency(row: dict[str, str | int]) -> Path:
        target = packages / (str(row["name"]) + ".deb")
        fetch(str(row["url"]), target, str(row["sha256"]), int(row["bytes"]))
        return target

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        archives = list(pool.map(dependency, pin["packages"]))
    sysroot = output / "sysroot"
    sysroot.mkdir()
    for package in archives:
        subprocess.run([programs["dpkg-deb"], "-x", str(package), str(sysroot)], check=True)  # noqa: S603
    # These packages were pinned from the signed Ubuntu ARM64 index. Never add
    # target packages to the host or let pkg-config select host x86 libraries.
    wrapper = output / "pkg-config"
    wrapper.write_text(
        "#!/bin/sh\nexport PKG_CONFIG_LIBDIR="
        + shlex.quote(str(sysroot / "usr/lib/aarch64-linux-gnu/pkgconfig"))
        + ":"
        + shlex.quote(str(sysroot / "usr/share/pkgconfig"))
        + "\nexport PKG_CONFIG_SYSROOT_DIR="
        + shlex.quote(str(sysroot))
        + '\nexec /usr/bin/pkg-config "$@"\n'
    )
    wrapper.chmod(0o700)
    cross = output / "cross.ini"
    target_libraries = sysroot / "usr/lib/aarch64-linux-gnu"
    # Let Meson recognize the pinned target libraries as compiler search paths.
    # Otherwise it adds their build-machine location to the ELF string table.
    compiler_prefix = f"-B{target_libraries}/"
    cross.write_text(
        "[binaries]\n"
        f"c = ['aarch64-linux-gnu-gcc', {compiler_prefix!r}]\n"
        f"cpp = ['aarch64-linux-gnu-g++', {compiler_prefix!r}]\n"
        "ar = 'aarch64-linux-gnu-ar'\nstrip = 'aarch64-linux-gnu-strip'\n"
        f"pkg-config = {str(wrapper)!r}\n"
        "[host_machine]\nsystem = 'linux'\ncpu_family = 'aarch64'\n"
        "cpu = 'armv8-a'\nendian = 'little'\n[properties]\nneeds_exe_wrapper = true\n"
        "[built-in options]\n"
        f"c_link_args = ['-Wl,-rpath-link,{target_libraries}']\n"
        f"cpp_link_args = ['-Wl,-rpath-link,{target_libraries}']\n"
    )
    tools = output / "host-tools"
    subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(tools)], check=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [str(tools / "bin/python"), "-m", "pip", "install", "--no-cache-dir", "meson==1.9.0"],
        check=True,
    )
    environment = dict(os.environ, PATH=str(tools / "bin") + os.pathsep + os.environ["PATH"])
    subprocess.run(  # noqa: S603
        [
            programs["sh"],
            str(recipe / "build-player.sh"),
            str(archive),
            str(cross),
            str(sysroot),
            str(output / "driver"),
        ],
        env=environment,
        check=True,
    )
    # Retain the exact source dependency catalog beside the compiled payload.
    shutil.copyfile(recipe / "upstream.json", output / "driver/package/source-inputs.json")


if __name__ == "__main__":
    if len(sys.argv) != CLI_ARGUMENTS:
        msg = "Usage: build.py NEW_OUTPUT_DIRECTORY"
        raise SystemExit(msg)
    build(Path(sys.argv[1]).resolve())
