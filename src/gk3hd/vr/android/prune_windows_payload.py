"""Omit Windows payloads outside the standalone game's release configuration."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory


def _optional_patch(path: str) -> bool:
    parts = PurePosixPath(path.casefold()).parts
    return (
        parts[:1] == ("home",)
        and parts[2:5] == (".wine", "drive_c", "windows")
        and (parts[5:6] == ("fonts",) or parts[5:] == ("syswow64", "mfc42.dll"))
    )


_UNUSED_WRAPPERS = ("cnc-ddraw-", "d7vk-", "d8vk-", "dxvk-")


def unused_wrapper(name: str) -> bool:
    """Identify upstream wrapper families replaced by the private game renderer."""
    return name.casefold().startswith(_UNUSED_WRAPPERS)


def prune(assets: Path, *, release: bool = False) -> None:
    """Preserve Wine's built-in components and exclude the optional native overlays."""
    if not release:
        _prune_debug_overlay(assets)
    # The upstream registry code still reads wincomponents.json.
    for overlay in (assets / "wincomponents").glob("*.tzst"):
        overlay.unlink()
    if release:
        (assets / "pulseaudio.tzst").unlink(missing_ok=True)
        (assets / "soundfont/SONiVOX-EAS-GM-Wavetable.sf2").unlink(missing_ok=True)
        for path in (assets / "dxwrapper").rglob("*"):
            family = path.relative_to(assets / "dxwrapper").parts[0]
            if unused_wrapper(family) and (path.is_file() or path.is_symlink()):
                path.unlink()


def _prune_debug_overlay(assets: Path) -> None:
    """Keep the bundled debug overlay sanitized before compilation."""
    patches = assets / "rootfs_patches.tzst"
    with TemporaryDirectory(dir=assets) as staging:
        output = Path(staging) / patches.name
        with (
            tarfile.open(patches, "r|zst") as source,
            tarfile.open(output, "w|zst") as target,
        ):
            for member in source:
                if _optional_patch(member.name):
                    continue
                if not member.isfile():
                    target.addfile(member)
                    continue
                payload = source.extractfile(member)
                if payload is None:
                    message = f"Missing runtime archive data for {member.name}"
                    raise ValueError(message)
                with payload:
                    target.addfile(member, payload)
        output.replace(patches)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    prune(args.assets, release=args.release)
