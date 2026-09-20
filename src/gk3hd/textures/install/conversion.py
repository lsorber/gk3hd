"""Convert validated PNG archive members into game-ready BMPs in parallel."""

from __future__ import annotations

import hashlib
import os
import zipfile
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import ExitStack
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from PIL import Image

from gk3hd.textures.flat import actual_files, explicit_dos_name_first
from gk3hd.textures.native_bmp import PAIRED_UI_COLOR_SIZES, encode_rgb565
from gk3hd.textures.pack.format import PackManifest, PackTexture, TexturePackError, _texture_member
from gk3hd.textures.progress import report_install_progress
from gk3hd.textures.upscale.fingerprint import INVENTORY_FINGERPRINT_SIZES, WORKSTATION_PRINT_SIZES
from gk3hd.textures.upscale.fonts.atlas import FONT_ATLAS_COLOR_SIZES, font_atlas_recipe
from gk3hd.textures.upscale.fonts.bank import (
    font_bank_layout,
    font_row_bank_layout,
    has_font_row_bank,
    read_font_bank_flags,
)
from gk3hd.textures.upscale.fonts.button import FONT_BUTTON_SIZES
from gk3hd.textures.upscale.thumbnail_recipes import RGB565_THUMBNAIL_SIZES
from gk3hd.textures.upscale.ui_art import STANDARD_BMP_UI_NAMES, UI_ART_SIZES

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import BinaryIO

    from gk3hd.textures.progress import TextureInstallProgressCallback


@dataclass(frozen=True, slots=True)
class _ConversionWork:
    """One validated PNG member ready for independent BMP conversion."""

    archive: Path
    bundle: zipfile.ZipFile
    info: zipfile.ZipInfo
    filename: str
    entry: PackTexture


@dataclass(frozen=True, slots=True)
class _ConversionPool:
    """Bounded parallel conversion state shared by the ordered ZIP feeder."""

    staging: Path
    executor: ThreadPoolExecutor
    installed_by_name: dict[str, dict[str, str]]
    capacity: int
    total: int
    progress: TextureInstallProgressCallback | None


class _HashingWriter:
    """Hash the sequential BMP bytes Pillow writes without reading them again."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()

    def write(self, payload: bytes) -> int:
        """Write and hash one sequential output block."""
        written = self.stream.write(payload)
        self.digest.update(payload[:written])
        return written

    def flush(self) -> None:
        """Flush the wrapped stream when requested by Pillow."""
        self.stream.flush()


def _convert_archives(
    archives: tuple[Path, ...],
    part_manifests: tuple[PackManifest, ...],
    manifest: PackManifest,
    staging: Path,
    *,
    progress: TextureInstallProgressCallback | None = None,
) -> list[dict[str, str]]:
    """Verify and convert every PNG with bounded parallel image workers."""
    expected = {item["filename"].casefold(): item for item in manifest["textures"]}
    installed_by_name: dict[str, dict[str, str]] = {}
    total = manifest["texture_count"]
    report_install_progress(progress, "Converting textures", 0, total)
    try:
        with ExitStack() as stack:
            bundles = {
                archive: stack.enter_context(zipfile.ZipFile(archive)) for archive in archives
            }
            work = _conversion_work(
                archives,
                part_manifests,
                bundles,
                expected,
            )
            explicit_names = [item for item in work if "~" in item.filename]
            regular_names = [item for item in work if "~" not in item.filename]
            for item in explicit_names:
                installed = _convert_member(item, staging, _verified_png_payload(item))
                installed_by_name[item.filename.casefold()] = installed
                report_install_progress(
                    progress, "Converting textures", len(installed_by_name), total
                )
            workers = _worker_count(len(regular_names))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gk3hd-bmp") as pool:
                _convert_regular_members(
                    regular_names,
                    _ConversionPool(
                        staging,
                        pool,
                        installed_by_name,
                        workers,
                        total,
                        progress,
                    ),
                )
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        msg = f"cannot read texture pack: {exc}"
        raise TexturePackError(msg) from exc
    actual = actual_files(staging, suffix=".bmp")
    expected_bmps = {f"{Path(name).stem}.BMP".casefold() for name in expected}
    if set(actual) != expected_bmps or len(installed_by_name) != manifest["texture_count"]:
        msg = f"installed {len(installed_by_name)} textures, expected {manifest['texture_count']}"
        raise TexturePackError(msg)
    return [installed_by_name[item["filename"].casefold()] for item in manifest["textures"]]


def _conversion_work(
    archives: tuple[Path, ...],
    part_manifests: tuple[PackManifest, ...],
    bundles: Mapping[Path, zipfile.ZipFile],
    expected: Mapping[str, PackTexture],
) -> tuple[_ConversionWork, ...]:
    """Validate unique archive membership before starting parallel writes."""
    work: list[_ConversionWork] = []
    seen: set[str] = set()
    for archive, part_manifest in zip(archives, part_manifests, strict=True):
        bundle = bundles[archive]
        for declared in part_manifest["part_textures"]:
            info = bundle.getinfo(_texture_member(declared))
            member = info.filename
            filename = PurePosixPath(member).name
            if member != _texture_member(filename):
                msg = f"unsafe texture-pack member: {member!r}"
                raise TexturePackError(msg)
            key = filename.casefold()
            entry = expected.get(key)
            if entry is None:
                msg = f"unexpected texture in {archive.name}: {member}"
                raise TexturePackError(msg)
            if key in seen:
                msg = f"texture occurs more than once in pack: {filename}"
                raise TexturePackError(msg)
            seen.add(key)
            work.append(_ConversionWork(archive, bundle, info, filename, entry))
    if seen != set(expected):
        msg = f"texture-pack parts contain {len(seen)} textures, expected {len(expected)}"
        raise TexturePackError(msg)
    return tuple(sorted(work, key=lambda item: explicit_dos_name_first(item.filename)))


def _verified_png_payload(item: _ConversionWork) -> bytes:
    """Read one stored member in archive order and verify its release hash."""
    payload = item.bundle.read(item.info)
    if hashlib.sha256(payload).hexdigest() != item.entry["png_sha256"]:
        msg = f"texture hash does not match manifest: {item.filename}"
        raise TexturePackError(msg)
    return payload


def _convert_regular_members(
    items: list[_ConversionWork],
    conversion: _ConversionPool,
) -> None:
    """Feed ordered ZIP reads into a bounded pool of image conversion workers."""
    pending: dict[Future[dict[str, str]], _ConversionWork] = {}
    iterator = iter(items)
    exhausted = False
    while pending or not exhausted:
        while not exhausted and len(pending) < conversion.capacity:
            try:
                item = next(iterator)
            except StopIteration:
                exhausted = True
                break
            payload = _verified_png_payload(item)
            pending[
                conversion.executor.submit(
                    _convert_member,
                    item,
                    conversion.staging,
                    payload,
                )
            ] = item
        if not pending:
            continue
        completed, _remaining = wait(pending, return_when=FIRST_COMPLETED)
        for future in completed:
            item = pending.pop(future)
            conversion.installed_by_name[item.filename.casefold()] = future.result()
            report_install_progress(
                conversion.progress,
                "Converting textures",
                len(conversion.installed_by_name),
                conversion.total,
            )


def _convert_member(
    item: _ConversionWork,
    staging: Path,
    payload: bytes,
) -> dict[str, str]:
    """Decode and convert one already verified PNG payload."""
    with Image.open(BytesIO(payload)) as image:
        image.load()
        _verify_png(image, item.entry, member=item.filename)
        destination = staging / f"{Path(item.filename).stem}.BMP"
        digest = _save_bmp(image, destination, mode=item.entry["mode"])
    return {"filename": destination.name, "sha256": digest}


def _worker_count(work: int) -> int:
    """Use enough codec workers for modern CPUs without flooding the disk."""
    return min(work or 1, 16, max(4, os.cpu_count() or 1))


def _verify_png(image: Image.Image, entry: PackTexture, *, member: str) -> None:
    if image.format != "PNG":
        msg = f"texture is not a PNG: {member}"
        raise TexturePackError(msg)
    if image.size != (entry["width"], entry["height"]) or image.mode != entry["mode"]:
        msg = f"texture metadata does not match manifest: {member}"
        raise TexturePackError(msg)


def _save_bmp(image: Image.Image, destination: Path, *, mode: str) -> str:
    """Write one BMP and return its hash without a second disk read."""
    if mode in {"RGB", "RGBA"}:
        output = image.convert("RGB")
    elif mode == "L":
        output = image.convert("L")
    elif mode == "P":
        output = image.copy()
    else:
        msg = f"unsupported texture mode: {mode}"
        raise TexturePackError(msg)
    bank_layout = font_bank_layout(destination.name)
    padded_font = False
    if bank_layout is not None and output.size == bank_layout.image_size:
        if read_font_bank_flags(output, bank_layout) is None:
            msg = f"invalid padded font metadata: {destination.name}"
            raise TexturePackError(msg)
        padded_font = True
    row_layout = font_row_bank_layout(destination.name)
    recipe = font_atlas_recipe(destination.name)
    row_font = (
        row_layout is not None
        and output.size == row_layout.image_size
        and recipe is not None
        and not recipe.alpha
    )
    if row_font and not has_font_row_bank(output):
        msg = f"invalid row font metadata: {destination.name}"
        raise TexturePackError(msg)
    with destination.open("wb") as stream:
        writer = _HashingWriter(stream)
        name = destination.name.upper()
        native_size = (
            UI_ART_SIZES.get(name)
            or INVENTORY_FINGERPRINT_SIZES.get(name)
            or WORKSTATION_PRINT_SIZES.get(name)
            or RGB565_THUMBNAIL_SIZES.get(name)
            or PAIRED_UI_COLOR_SIZES.get(name)
            or FONT_BUTTON_SIZES.get(name)
            or FONT_ATLAS_COLOR_SIZES.get(name)
        )
        if row_font or (
            output.mode == "RGB"
            and native_size is not None
            and name not in STANDARD_BMP_UI_NAMES
            and (output.size == (native_size[0] * 4, native_size[1] * 4) or padded_font)
        ):
            # These verified source families were RGB565 in the BRNs. PNG is
            # still the portable transport; install their original game format
            # to avoid a second quantization through the 24-bit bitmap loader.
            writer.write(encode_rgb565(output))
        else:
            output.save(cast("BinaryIO", writer), format="BMP")
        writer.flush()
    return writer.digest.hexdigest()
