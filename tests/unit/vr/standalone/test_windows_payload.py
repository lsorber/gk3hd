"""Keep the standalone runtime overlay free of optional Windows payloads."""

from __future__ import annotations

import io
import sys
import tarfile
from typing import TYPE_CHECKING

import pytest

from gk3hd.vr.android.prune_windows_payload import prune

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.skipif(sys.version_info < (3, 14), reason="Android builds require Python 3.14")
@pytest.mark.parametrize("release", [False, True])
def test_omit_optional_windows_files_and_preserve_required_overlays(
    tmp_path: Path, *, release: bool
) -> None:
    wincomponents = tmp_path / "wincomponents"
    wincomponents.mkdir()
    (wincomponents / "wmdecoder.tzst").write_bytes(b"optional archive")
    metadata = wincomponents / "wincomponents.json"
    metadata.write_bytes(b"{}")
    patches = tmp_path / "rootfs_patches.tzst"
    guest_windows = "./home/guest/.wine/drive_c/windows"
    audio = "./usr/lib/alsa-lib/libasound_module_pcm_android_aserver.so"
    alternatives = [
        tmp_path / "dxwrapper/cnc-ddraw-6.6/Shaders/interpolation/bilinear.glsl",
        tmp_path / "dxwrapper/d7vk-1.11.tzst",
        tmp_path / "dxwrapper/d8vk-1.0.tzst",
        tmp_path / "dxwrapper/dxvk-2.4.1.tzst",
    ]
    vkd3d = tmp_path / "dxwrapper/vkd3d-2.14.1.tzst"
    optional_audio = [
        tmp_path / "pulseaudio.tzst",
        tmp_path / "soundfont/SONiVOX-EAS-GM-Wavetable.sf2",
    ]
    for path in [*alternatives, vkd3d, *optional_audio]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"payload")
    with tarfile.open(patches, "w|zst") as archive:
        for path in (
            f"{guest_windows}/Fonts/arial.ttf",
            f"{guest_windows}/syswow64/mfc42.dll",
            audio,
        ):
            entry = tarfile.TarInfo(path)
            entry.size = 4
            archive.addfile(entry, io.BytesIO(b"data"))

    prune(tmp_path, release=release)

    assert all(path.is_file() is not release for path in (*alternatives, *optional_audio))
    assert vkd3d.read_bytes() == b"payload"
    assert list(wincomponents.iterdir()) == [metadata]
    assert metadata.read_bytes() == b"{}"
    with tarfile.open(patches, "r|zst") as archive:
        names = []
        for entry in archive:
            names.append(entry.name)
            if entry.name == audio:
                payload = archive.extractfile(entry)
                assert payload is not None
                with payload:
                    assert payload.read() == b"data"
    assert names == (
        [f"{guest_windows}/Fonts/arial.ttf", f"{guest_windows}/syswow64/mfc42.dll", audio]
        if release
        else [audio]
    )
