"""Current pack contracts reject malformed evidence before installation."""

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from gk3hd.textures.pack.build import build_texture_pack
from gk3hd.textures.pack.format import PACK_MANIFEST_FILENAME, TexturePackError, _load_pack_set
from gk3hd.textures.pack.source import TexturePackSource


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("schema_version", True),
        ("scale", True),
        ("scale", 2),
        ("texture_count", True),
        ("part_index", True),
        ("part_count", True),
        ("part_textures", ["../IMAGE.PNG"]),
    ],
)
def test_invalid_pack_header_fails_closed(tmp_path: Path, field: str, value: object) -> None:
    source = tmp_path / "png"
    source.mkdir()
    Image.new("RGB", (2, 2)).save(source / "IMAGE.PNG")
    report = build_texture_pack(source, tmp_path / "gk3hd-texture-pack-v1.0.zip", version="1.0")
    archive = report.archives[0]
    with zipfile.ZipFile(archive) as bundle:
        members = {name: bundle.read(name) for name in bundle.namelist()}
    manifest = json.loads(members[PACK_MANIFEST_FILENAME])
    manifest[field] = value
    members[PACK_MANIFEST_FILENAME] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    with pytest.raises(TexturePackError):
        _load_pack_set((archive,))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"archive_url": "https://example.com/pack.zip", "archive_sha256": "0" * 64},
        {"archives": None},
        {"archives": {}},
        {"archives": [{"filename": "pack.zip", "size": 1, "sha256": "0" * 64}]},
    ],
)
def test_locks_require_explicit_current_archive_list(payload: object) -> None:
    with pytest.raises(TexturePackError):
        TexturePackSource.from_lock(payload)


@pytest.mark.parametrize("name", ["../pack.zip", "..\\pack.zip", "NUL.zip", "x:y.zip"])
def test_lock_names_are_portable(name: str) -> None:
    with pytest.raises(TexturePackError):
        TexturePackSource.from_lock(
            {"tag": "v1.0", "archives": [{"filename": name, "size": 1, "sha256": "0" * 64}]}
        )


def test_empty_archive_set_is_an_explicit_error() -> None:
    with pytest.raises(TexturePackError, match="no archive parts"):
        _load_pack_set(())
