"""Local release-pack creation and exact installation round trips."""

from __future__ import annotations

import json
import threading
import zipfile
from importlib.resources import files
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import gk3hd.textures.install.conversion as texture_conversion
import gk3hd.textures.pack.build as texture_pack
from gk3hd.system.files import sha256_file
from gk3hd.system.ini import apply_custom_path, prepare_custom_path
from gk3hd.textures.install.journal import JOURNAL_FILENAME, TextureJournal, TextureJournalError
from gk3hd.textures.install.service import (
    PackInstallOptions,
    install_texture_pack,
    recover_texture_install,
    uninstall_texture_pack,
    verify_texture_pack,
)
from gk3hd.textures.model import TEXTURE_MANIFEST_SCHEMA_VERSION
from gk3hd.textures.native_bmp import encode_rgb565
from gk3hd.textures.pack.build import PackBuildReport, build_texture_pack
from gk3hd.textures.pack.format import TexturePackError
from gk3hd.textures.pack.source import TexturePackSource, discover_local_texture_pack
from gk3hd.textures.progress import TextureInstallProgress
from gk3hd.textures.upscale.fonts.button import FONT_BUTTON_SIZES
from gk3hd.textures.upscale.ui_art import STANDARD_BMP_UI_NAMES, UI_ART_SIZES
from gk3hd.textures.workspace import texture_pack_filename


@pytest.mark.parametrize(
    ("schema", "directory"),
    [
        (1, "gk3hd"),
        (2, "gk3hd/upscale"),
        (3, "gk3hd/textures"),
        (4, "gk3hd/textures/installed"),
    ],
)
@pytest.mark.parametrize("force", [False, True])
def test_obsolete_installation_cannot_authorize_file_or_ini_changes(
    tmp_path: Path, schema: int, directory: str, *, force: bool
) -> None:
    game = tmp_path / "game"
    target = game / directory
    target.mkdir(parents=True)
    texture = target / "ROOM.BMP"
    texture.write_bytes(b"managed by an obsolete design")
    ini = game / "GK3.ini"
    ini.write_bytes(b"CUSTOM PATHS = mods\n")
    change, installed_ini = prepare_custom_path(game, directory)
    apply_custom_path(game, change, installed_ini)
    state_path = game / ".gk3hd-textures.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": schema,
                "directory": directory,
                "files": [{"filename": texture.name, "sha256": sha256_file(texture)}],
                "ini": change.to_dict(),
                "manifest_sha256": "0" * 64,
                "pack_version": "obsolete",
            }
        ),
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in (texture, ini, state_path)}
    with pytest.raises(TexturePackError, match="invalid texture installation inventory"):
        verify_texture_pack(game)
    with pytest.raises(TexturePackError, match="invalid texture installation inventory"):
        uninstall_texture_pack(game, force=force)
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("schema", range(1, 6))
def test_obsolete_journal_cannot_authorize_recovery(tmp_path: Path, schema: int) -> None:
    game = tmp_path / "game"
    game.mkdir()
    staging = game / ".gk3hd-textures-old"
    staging.mkdir()
    texture = staging / "ROOM.BMP"
    texture.write_bytes(b"private")
    journal = game / JOURNAL_FILENAME
    journal.write_text(json.dumps({"schema_version": schema, "staging_name": staging.name}))
    with pytest.raises(TextureJournalError, match="unsupported schema"):
        recover_texture_install(game)
    assert texture.read_bytes() == b"private"
    assert journal.is_file()


def _write_pngs(directory: Path) -> None:
    directory.mkdir()
    Image.new("RGB", (2, 3), (10, 20, 30)).save(directory / "COLOR.PNG")
    Image.new("L", (3, 2), 127).save(directory / "ALPHA.PNG")


def _build_pack(source: Path, directory: Path) -> PackBuildReport:
    """Build the conventional v1.0 test pack in a chosen parent directory."""
    return build_texture_pack(
        source,
        directory / texture_pack_filename("1.0"),
        version="1.0",
    )


@pytest.mark.integration
def test_geometric_png_pack_installs_native_colors_and_uninstalls_exactly(tmp_path: Path) -> None:
    """Portable PNG transport preserves each geometric resource's original format."""
    source = tmp_path / "png"
    source.mkdir()
    expected = {}
    catalog = UI_ART_SIZES | FONT_BUTTON_SIZES
    source_sizes = {
        name: catalog[name]
        for name in (
            "INV_HIGHLIGHT.BMP",
            "RC_SO_SAVE_STD.BMP",
            "S_BOX_SIDE.BMP",
            "C_WAIT_ALPHA.BMP",
        )
    }
    for name, (width, height) in source_sizes.items():
        image = (
            Image.new("L", (width * 4, height * 4), 192)
            if name.endswith("_ALPHA.BMP")
            else Image.new("RGB", (width * 4, height * 4), (180, 125, 0))
        )
        image.save(source / f"{Path(name).stem}.PNG")
        if name in STANDARD_BMP_UI_NAMES:
            stream = BytesIO()
            image.save(stream, format="BMP")
            expected[name] = stream.getvalue()
        else:
            expected[name] = encode_rgb565(image)
    report = _build_pack(source, tmp_path / "release")
    game = tmp_path / "game"
    game.mkdir()
    original_ini = b"[Paths]\r\nCUSTOM PATHS = mods\r\n"
    (game / "gk3.ini").write_bytes(original_ini)
    installed = install_texture_pack(
        game,
        TexturePackSource.local(report.archives[0]),
        PackInstallOptions(cache_dir=tmp_path / "cache"),
    )
    assert installed.textures == len(source_sizes)
    for name, payload in expected.items():
        assert (game / "gk3hd" / "textures" / "installed" / name).read_bytes() == payload
    assert verify_texture_pack(game).textures == len(source_sizes)
    uninstall_texture_pack(game)
    assert not (game / "gk3hd").exists()
    assert (game / "gk3.ini").read_bytes() == original_ini


@pytest.mark.integration
def test_pack_build_is_deterministic(tmp_path: Path) -> None:
    """Identical PNG input produces one byte-identical manifest-first archive."""
    source = tmp_path / "png"
    _write_pngs(source)
    first = _build_pack(source, tmp_path / "first")
    second = _build_pack(source, tmp_path / "second")

    assert first.archives[0].read_bytes() == second.archives[0].read_bytes()
    assert first.lock.read_bytes() == second.lock.read_bytes()
    with zipfile.ZipFile(first.archives[0]) as bundle:
        assert bundle.namelist() == [
            "texture-pack-manifest.json",
            "upscaled/ALPHA.PNG",
            "upscaled/COLOR.PNG",
        ]


@pytest.mark.integration
def test_pack_excludes_untouched_semantic_assets_even_if_stale_pngs_exist(
    tmp_path: Path,
) -> None:
    """The release boundary cannot reintroduce outputs from an older upscale run."""
    textures = tmp_path / "textures"
    source = textures / "upscaled"
    source.mkdir(parents=True)
    Image.new("RGB", (8, 8), (10, 20, 30)).save(source / "COLOR.PNG")
    Image.new("L", (8, 8), 127).save(source / "ROOMWLKBNDS.PNG")
    Image.new("RGB", (8, 8), (255, 0, 255)).save(source / "FONT.PNG")
    (textures / "texture-analysis.json").write_text(
        json.dumps(
            {
                "schema_version": TEXTURE_MANIFEST_SCHEMA_VERSION,
                "texture_count": 3,
                "textures": [
                    {
                        "name": "COLOR.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    },
                    {
                        "name": "ROOMWLKBNDS.BMP",
                        "kind": "data",
                        "tiled": False,
                        "alphatest": False,
                        "exact_raster": False,
                        "font_atlas": False,
                    },
                    {
                        "name": "FONT.BMP",
                        "kind": "color",
                        "tiled": False,
                        "alphatest": True,
                        "exact_raster": False,
                        "font_atlas": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output = textures / texture_pack_filename("1.0")

    report = texture_pack.pack(
        source,
        output,
        version="1.0",
    )

    assert report.textures == 1
    with zipfile.ZipFile(output) as bundle:
        assert bundle.namelist() == ["texture-pack-manifest.json", "upscaled/COLOR.PNG"]


@pytest.mark.integration
def test_local_pack_installs_leftmost_and_uninstalls_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release PNGs become BMPs under gk3hd/textures/installed and round-trip the INI."""
    source = tmp_path / "png"
    _write_pngs(source)
    report = _build_pack(source, tmp_path / "release")
    game = tmp_path / "game"
    game.mkdir()
    original_ini = b"[Paths]\r\nCUSTOM PATHS = mods; GK3HD/TEXTURES/INSTALLED\r\n"
    (game / "gk3.ini").write_bytes(original_ini)
    updates: list[TextureInstallProgress] = []
    staging_paths: list[Path] = []
    worker_names: set[str] = set()
    original_write = TextureJournal.write
    original_convert = texture_conversion._convert_member

    def record_journal(journal: TextureJournal) -> None:
        staging_paths.append(journal.staging)
        original_write(journal)

    def record_worker(
        item: texture_conversion._ConversionWork,
        staging: Path,
        payload: bytes,
    ) -> dict[str, str]:
        worker_names.add(threading.current_thread().name)
        return original_convert(item, staging, payload)

    monkeypatch.setattr(TextureJournal, "write", record_journal)
    monkeypatch.setattr(texture_conversion, "_convert_member", record_worker)

    installed = install_texture_pack(
        game,
        TexturePackSource.local(report.archives[0]),
        PackInstallOptions(cache_dir=tmp_path / "cache", progress=updates.append),
    )

    assert installed.textures == 2
    assert {path.name for path in (game / "gk3hd" / "textures" / "installed").iterdir()} == {
        "ALPHA.BMP",
        "COLOR.BMP",
        "FACES.TXT",
    }
    assert (game / "gk3hd" / "textures" / "installed" / "FACES.TXT").read_bytes() == files(
        "gk3hd"
    ).joinpath("assets/FACES.TXT").read_bytes()
    assert (game / "gk3.ini").read_bytes() == (
        b"[Paths]\r\nCUSTOM PATHS = gk3hd/textures/installed; mods\r\n"
    )
    assert {update.description for update in updates} == {
        "Preparing texture pack",
        "Validating texture pack",
        "Converting textures",
        "Installing textures",
        "Finalizing installation",
    }
    assert updates[-1] == TextureInstallProgress("Finalizing installation", 3, 3)
    assert staging_paths[0].parent == game / "gk3hd" / "textures"
    assert worker_names
    assert all(name.startswith("gk3hd-bmp") for name in worker_names)
    verified = verify_texture_pack(game)
    assert verified.textures == 2

    uninstall_texture_pack(game)

    assert not (game / "gk3hd").exists()
    assert not (game / ".gk3hd-textures.json").exists()
    assert (game / "gk3.ini").read_bytes() == original_ini


@pytest.mark.integration
def test_pack_installs_explicit_dos_name_before_its_conflicting_long_name(
    tmp_path: Path,
) -> None:
    """Fresh staging preserves both real GK3 resources on an 8.3-enabled volume."""
    source = tmp_path / "png"
    source.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(source / "FLOORT~1.PNG")
    Image.new("RGB", (8, 8), (10, 20, 30)).save(source / "FLOORTILE.PNG")
    report = _build_pack(source, tmp_path / "release")
    with zipfile.ZipFile(report.archives[0]) as bundle:
        assert bundle.namelist() == [
            "texture-pack-manifest.json",
            "upscaled/FLOORT~1.PNG",
            "upscaled/FLOORTILE.PNG",
        ]
    game = tmp_path / "game"
    game.mkdir()

    installed = install_texture_pack(game, TexturePackSource.local(report.archives[0]))

    assert installed.textures == 2
    destination = game / "gk3hd" / "textures" / "installed"
    assert {path.name.casefold() for path in destination.iterdir()} == {
        "faces.txt",
        "floort~1.bmp",
        "floortile.bmp",
    }
    with Image.open(destination / "FLOORT~1.BMP") as image:
        assert image.getpixel((0, 0)) == (1, 2, 3)
    with Image.open(destination / "FLOORTILE.BMP") as image:
        assert image.getpixel((0, 0)) == (10, 20, 30)
    uninstall_texture_pack(game)


@pytest.mark.integration
def test_offline_remote_install_uses_only_verified_cache(tmp_path: Path) -> None:
    """The remote source path can install without network when every locked asset is cached."""
    source = tmp_path / "png"
    _write_pngs(source)
    report = _build_pack(source, tmp_path / "release")
    lock = json.loads(report.lock.read_text(encoding="utf-8"))
    asset = lock["archives"][0]
    cache = tmp_path / "cache"
    archive_cache = cache / "textures" / asset["sha256"] / report.archives[0].name
    archive_cache.parent.mkdir(parents=True)
    archive_cache.write_bytes(report.archives[0].read_bytes())
    game = tmp_path / "game"
    game.mkdir()

    installed = install_texture_pack(
        game,
        TexturePackSource.from_lock(lock),
        PackInstallOptions(cache_dir=cache, offline=True),
    )

    assert installed.textures == 2
    uninstall_texture_pack(game)


@pytest.mark.integration
def test_multi_part_pack_installs_as_one_logical_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generated lock makes every release part one local install input."""
    source = tmp_path / "png"
    source.mkdir()
    for index in range(4):
        image = Image.effect_noise((64, 64), 100).convert("RGB")
        image.save(source / f"NOISE{index}.PNG")
    monkeypatch.setattr("gk3hd.textures.pack.build.GITHUB_ASSET_LIMIT", 18_000)

    report = _build_pack(source, tmp_path / "release")

    assert len(report.archives) == 4
    assert all(archive.stat().st_size < 18_000 for archive in report.archives)
    lock = json.loads(report.lock.read_text(encoding="utf-8"))
    assert [entry["filename"] for entry in lock["archives"]] == [
        archive.name for archive in report.archives
    ]
    game = tmp_path / "game"
    game.mkdir()
    installed = install_texture_pack(game, TexturePackSource.local(report.lock))
    assert installed.textures == 4
    assert verify_texture_pack(game).textures == 4


@pytest.mark.integration
def test_multi_part_pack_can_be_selected_by_any_part_or_logical_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One part or the unsplit pack name selects every adjacent archive part."""
    source = tmp_path / "png"
    source.mkdir()
    for index in range(2):
        Image.effect_noise((64, 64), 100).convert("RGB").save(source / f"NOISE{index}.PNG")
    monkeypatch.setattr("gk3hd.textures.pack.build.GITHUB_ASSET_LIMIT", 18_000)
    report = _build_pack(source, tmp_path / "release")
    game = tmp_path / "game"
    game.mkdir()

    from_part = TexturePackSource.local(report.archives[-1])
    assert tuple(asset.archive_path for asset in from_part.assets) == report.archives
    from_name = discover_local_texture_pack(
        Path(texture_pack_filename("1.0")),
        search_directories=(report.lock.parent,),
    )
    installed = install_texture_pack(game, from_name)

    assert installed.textures == 2


@pytest.mark.integration
def test_multi_part_pack_still_requires_every_discovered_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Automatic discovery does not permit an incomplete logical pack."""
    source = tmp_path / "png"
    source.mkdir()
    for index in range(2):
        Image.effect_noise((64, 64), 100).convert("RGB").save(source / f"NOISE{index}.PNG")
    monkeypatch.setattr("gk3hd.textures.pack.build.GITHUB_ASSET_LIMIT", 18_000)
    report = _build_pack(source, tmp_path / "release")
    selected = TexturePackSource.local(report.archives[0])
    report.archives[-1].unlink()
    game = tmp_path / "game"
    game.mkdir()

    with pytest.raises(TexturePackError, match="does not exist"):
        install_texture_pack(game, selected)


@pytest.mark.integration
def test_install_and_uninstall_leave_local_upscale_pngs_separate(tmp_path: Path) -> None:
    """The dedicated installed BMP directory never claims local upscale PNG output."""
    source = tmp_path / "png"
    _write_pngs(source)
    report = _build_pack(source, tmp_path / "release")
    game = tmp_path / "game"
    upscale = game / "gk3hd" / "textures" / "upscaled"
    upscale.mkdir(parents=True)
    local_png = upscale / "LOCAL.PNG"
    Image.new("RGB", (1, 1), (1, 2, 3)).save(local_png)

    install_texture_pack(
        game,
        TexturePackSource.local(report.archives[0]),
        PackInstallOptions(cache_dir=tmp_path / "cache"),
    )

    assert local_png.is_file()
    installed = game / "gk3hd" / "textures" / "installed"
    assert {path.suffix for path in installed.iterdir()} == {".BMP", ".TXT"}
    assert verify_texture_pack(game).textures == 2
    uninstall_texture_pack(game)
    assert {path.name for path in upscale.iterdir()} == {"LOCAL.PNG"}
    assert not installed.exists()
    assert not (game / ".gk3hd-textures.json").exists()
    assert not (game / "GK3.ini").exists()


@pytest.mark.integration
def test_install_rejects_unowned_dedicated_texture_directory(tmp_path: Path) -> None:
    """An existing install directory is never silently overwritten or adopted."""
    game = tmp_path / "game"
    target = game / "gk3hd" / "textures" / "installed"
    target.mkdir(parents=True)
    (target / "USER.BMP").write_bytes(b"user")

    with pytest.raises(TexturePackError, match="exists but is not owned"):
        install_texture_pack(game, TexturePackSource.local(tmp_path / "missing.zip"))


@pytest.mark.integration
def test_interrupted_texture_commit_rolls_back_directory_and_ini(tmp_path: Path) -> None:
    """A durable pre-state journal restores an interrupted directory/INI commit."""
    game = tmp_path / "game"
    game.mkdir()
    ini = game / "GK3.ini"
    original = b"CUSTOM PATHS = mods\n"
    ini.write_bytes(original)
    staging = game / "gk3hd" / "textures" / ".install-fixture"
    staging.mkdir(parents=True)
    (staging / "ROOM.BMP").write_bytes(b"fixture")
    change, installed = prepare_custom_path(game, "gk3hd/textures/installed")
    staged_texture = staging / "ROOM.BMP"
    journal = TextureJournal.create(
        game,
        staging,
        change,
        [{"filename": staged_texture.name, "sha256": sha256_file(staged_texture)}],
    )
    journal.write()
    upscale = game / "gk3hd" / "textures" / "upscaled"
    upscale.mkdir(parents=True)
    local_png = upscale / "LOCAL.PNG"
    local_png.write_bytes(b"local")
    target = game / "gk3hd" / "textures" / "installed"
    staging.replace(target)
    apply_custom_path(game, change, installed)

    recover_texture_install(game)

    assert ini.read_bytes() == original
    assert not target.exists()
    assert {path.name for path in upscale.iterdir()} == {local_png.name}
    assert not journal.path.exists()


@pytest.mark.integration
def test_uninstall_protects_modified_texture(tmp_path: Path) -> None:
    """A later texture edit blocks ordinary uninstall but permits explicit force."""
    source = tmp_path / "png"
    _write_pngs(source)
    report = _build_pack(source, tmp_path / "release")
    game = tmp_path / "game"
    game.mkdir()
    install_texture_pack(
        game,
        TexturePackSource.local(report.archives[0]),
        PackInstallOptions(cache_dir=tmp_path / "cache"),
    )
    (game / "gk3hd" / "textures" / "installed" / "COLOR.BMP").write_bytes(b"user edit")

    with pytest.raises(TexturePackError, match="changed after installation"):
        uninstall_texture_pack(game)

    uninstall_texture_pack(game, force=True)
    assert not (game / "gk3hd").exists()
