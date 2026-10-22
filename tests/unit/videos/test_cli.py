"""The installed movie lifecycle must work without the optional AI/media stack."""

from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from typing import TYPE_CHECKING

import av
import pytest
from PIL import Image

from gk3hd.videos.options import MovieUpscaleOptions
from tests.unit.videos.test_technical import _make_rle_movie
from tests.unit.videos.test_temporal import RecordingBackend

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from tests.unit.videos.test_interpolation import LinearInterpolator


@pytest.mark.parametrize("strength", [None, 0.35])
def test_cli_uses_and_records_the_same_restoration_strength(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, strength: float | None
) -> None:
    from typer.testing import CliRunner  # noqa: PLC0415 - optional CLI test adapter.

    from gk3hd.cli import app, videos  # noqa: PLC0415 - CLI facade tested as installed.
    from tests.unit.videos.test_video import _make_movie  # noqa: PLC0415

    source, output = tmp_path / "source", tmp_path / "upscaled"
    source.mkdir()
    _make_movie(source / "intro.avi", audio=False)

    class Backend:
        device_description = "test device"

        @staticmethod
        def upscale_clip(frames: Sequence[Image.Image]) -> list[Image.Image]:
            return [
                Image.new("RGB", (frame.width * 4, frame.height * 4), (240, 40, 20))
                for frame in frames
            ]

    def create_backend(_device: str, _download: object, **options: object) -> Backend:
        del options
        return Backend()

    monkeypatch.setattr(videos, "create_backend", create_backend)
    arguments = ["videos", "upscale", str(source), str(output)]
    if strength is not None:
        arguments.extend(["--strength", str(strength)])
    result = CliRunner().invoke(app, arguments)
    assert result.exit_code == 0, result.output + repr(result.exception)
    receipt = json.loads((output / "intro.mkv.json").read_bytes())
    expected = MovieUpscaleOptions().restoration_strength if strength is None else strength
    assert receipt["restoration_strength"] == expected
    with (
        av.open(str(source / "intro.avi")) as original,
        av.open(str(output / "intro.mkv")) as generated,
    ):
        first = next(original.decode(video=0)).to_image().resize((64, 48), Image.Resampling.BICUBIC)
        wanted = Image.blend(first, Image.new("RGB", first.size, (240, 40, 20)), expected)
        actual = next(generated.decode(video=0)).to_image()
    assert max(abs(a - b) for a, b in zip(actual.tobytes(), wanted.tobytes(), strict=True)) <= 3
    assert receipt["model"] == "3b"


def test_movie_install_verify_uninstall_do_not_import_optional_dependencies(game: Path) -> None:
    from gk3hd.videos.pack import build_pack  # noqa: PLC0415 - prepare local fixture.

    build_pack(game, version="1.1.1")
    script = """
import importlib.abc
import json
import sys
from pathlib import Path

blocked = {'av', 'torch', 'diffusers', 'numpy', 'huggingface_hub', 'safetensors'}
class NoOptionalPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ImportError('optional package must not be imported: ' + fullname)

sys.meta_path.insert(0, NoOptionalPackages())
from gk3hd.cli import app
import gk3hd.videos.install as videos
import gk3hd.videos.runtime as runtime
from typer.testing import CliRunner
videos.is_gk3_running = lambda: False
runtime._pin = lambda: json.loads((Path(sys.argv[1]).parent / 'codec-pin.json').read_bytes())
runtime.cache_directory = lambda: Path(sys.argv[1]).parent / 'codec-cache'
for command in ['install', 'verify', 'uninstall']:
    arguments = ['videos', command, '--game-dir', sys.argv[1]]
    if command == 'install':
        arguments.append('--local')
    result = CliRunner().invoke(app, arguments)
    print(result.output)
    assert result.exit_code == 0, repr(result.exception)
assert not blocked.intersection(sys.modules)
"""
    result = subprocess.run(  # noqa: S603 - interpreter and generated fixture path, no shell.
        [sys.executable, "-c", script, str(game)],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Verified 1" in result.stdout
    assert "Removed 1" in result.stdout


@pytest.mark.parametrize("rate", [Fraction(15), Fraction(6389, 215)])
def test_cli_selects_cadence_from_media_not_a_specific_movie_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rate: Fraction,
    interpolator: LinearInterpolator,
) -> None:
    from typer.testing import CliRunner  # noqa: PLC0415 - invoke the public CLI.

    from gk3hd.cli import app, videos  # noqa: PLC0415 - facade tested as installed.
    from tests.unit.videos.test_video import _make_movie  # noqa: PLC0415

    source, output = tmp_path / "source", tmp_path / "generated"
    source.mkdir()
    _make_movie(source / "arbitrary-name.avi", audio=False, rate=rate)

    class Backend(RecordingBackend):
        device_description = "test device"

    monkeypatch.setattr(videos, "create_backend", lambda _device, _progress, **_options: Backend())
    result = CliRunner().invoke(app, ["videos", "upscale", str(source), str(output)])
    assert result.exit_code == 0, result.output + repr(result.exception)
    with av.open(str(output / "arbitrary-name.mkv")) as container:
        stream = container.streams.video[0]
        assert stream.average_rate == (60 if rate == 15 else rate)
        assert sum(1 for _ in container.decode(video=0)) == (28 if rate == 15 else 7)
    assert bool(interpolator.calls) == (rate == 15)


@pytest.mark.parametrize("cinematic", [False, True])
def test_non_ai_upscale_does_not_load_torch_or_download_models(
    tmp_path: Path, cinematic: bool
) -> None:
    from tests.unit.videos.test_video import _make_movie  # noqa: PLC0415

    source, output = tmp_path / "source", tmp_path / "generated"
    source.mkdir()
    if cinematic:
        _make_movie(source / "diagram.avi", audio=False, rate=Fraction(15))
    else:
        _make_rle_movie(source / "diagram.avi")
    script = """
import importlib.abc
import sys
blocked = {'torch', 'diffusers', 'huggingface_hub', 'safetensors'}
class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ImportError('non-AI upscale must not import ' + fullname)
sys.meta_path.insert(0, NoModels())
from gk3hd.cli import app
from typer.testing import CliRunner
arguments = ['videos', 'upscale', sys.argv[1], sys.argv[2]]
if sys.argv[3] == 'cinematic':
    arguments.extend(['--strength', '0'])
result = CliRunner().invoke(app, arguments)
print(result.output)
assert result.exit_code == 0, repr(result.exception)
assert 'AI device' not in result.output
assert not blocked.intersection(sys.modules)
"""
    result = subprocess.run(  # noqa: S603 - interpreter and generated fixture paths, no shell.
        [
            sys.executable,
            "-c",
            script,
            str(source),
            str(output),
            "cinematic" if cinematic else "technical",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (output / "diagram.mkv").is_file() == cinematic
    if not cinematic:
        assert "retained 1 original technical animations" in " ".join(result.stdout.split())
