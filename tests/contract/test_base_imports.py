"""A development environment must not hide accidental optional CLI dependencies."""

import subprocess
import sys
from pathlib import Path


def test_base_cli_imports_without_any_upscaling_dependency() -> None:
    script = """
import importlib.abc
import runpy
import sys
import tempfile
from pathlib import Path

class NoUpscalingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in {
            'numpy', 'scipy', 'torch', 'diffusers', 'einops', 'huggingface_hub',
            'safetensors', 'rotary_embedding_torch', 'freetype',
        }:
            raise ModuleNotFoundError('unexpected optional import: ' + fullname)
        return None

sys.meta_path.insert(0, NoUpscalingImports())
from gk3hd.cli import app
from typer.testing import CliRunner
for command in (
    ['--version'], ['install', '--help'], ['patch', 'list'], ['textures', 'install', '--help'],
):
    result = CliRunner().invoke(app, command)
    assert result.exit_code == 0, (command, result.output, result.exception)
workflow = runpy.run_path(sys.argv[1])['test_texture_pack_install_verify_and_uninstall_commands']
with tempfile.TemporaryDirectory() as directory:
    workflow(Path(directory))

# Resource-driven analysis needs the ordinary LZO decoder, not the AI extra.
from PIL import Image
import gk3hd.textures.analyze.manifest as texture_analyze
from tests.unit.textures.test_extraction import _write_barn_fixture
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    _write_barn_fixture(root / 'Data', core_assets=[
        ('ATLAS.BMP', b'catalog entry', 0),
        ('CUSTOM.FON', b'Bitmap Name=atlas', 2),
    ])
    source = root / 'original'
    source.mkdir()
    Image.new('RGB', (2, 2)).save(source / 'ATLAS.BMP')
    report = texture_analyze.analyze(source)
    assert report.manifest.textures[0].font_atlas
"""
    workflow_test = Path(__file__).resolve().parents[1] / "integration/test_cli.py"
    result = subprocess.run(  # noqa: S603 - fixed interpreter and hermetic test program.
        [sys.executable, "-c", script, str(workflow_test)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr or result.stdout
