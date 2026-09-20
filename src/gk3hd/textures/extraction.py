"""Extract the game's BMP inventory and decode its native image format."""

from __future__ import annotations

import os
import struct
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from gk3hd.system.discovery import discover_game
from gk3hd.textures.bmp import BmpError, inspect_bmp_bytes
from gk3hd.textures.brn import BarnArchive, BarnEntry, BrnError

TextureProgress = Callable[[int, int], None]

_GK3_BMP_HEADER = struct.Struct("<4sHH")

_BMP_FILE_HEADER = struct.Struct("<2sIHHI")

_BMP_INFO_HEADER = struct.Struct("<IiiHHIIiiII")

_BMP_PIXEL_OFFSET = _BMP_FILE_HEADER.size + _BMP_INFO_HEADER.size


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    """Concise counts returned after a successful extraction run."""

    extracted: int
    skipped: int
    copied_standard: int
    converted_proprietary: int


@dataclass(frozen=True, slots=True)
class _ExtractionWork:
    """One Barn entry and its prevalidated flat output path."""

    entry: BarnEntry
    destination: Path


def extract_bmps(
    data_directory: Path,
    output_directory: Path,
    *,
    overwrite: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> ExtractionReport:
    """Extract all catalogued BMPs, preserving or converting their payloads.

    Standard ``BM`` payloads are copied exactly through their declared file
    length. Proprietary ``61nM`` RGB565 payloads become uncompressed 24-bit
    bottom-up BMPs matching the corrected native extractor's conversion.
    """
    archive = BarnArchive.open(data_directory)
    target = output_directory.resolve()
    if target == archive.data_directory:
        msg = "output directory must differ from the GK3 data directory"
        raise BrnError(msg)
    if target.exists() and not target.is_dir():
        msg = f"output path is not a directory: {target}"
        raise BrnError(msg)

    entries = sorted(
        (entry for entry in archive.entries if entry.name.upper().endswith(".BMP")),
        # GK3 contains explicit DOS-style names such as FLOORT~1.BMP alongside
        # FLOORTILE.BMP. Create the explicit name first so NTFS gives the long
        # file a different generated 8.3 alias.
        key=lambda entry: ("~" not in entry.name, entry.name.casefold()),
    )
    if not entries:
        msg = f"no BMP entries found in {archive.data_directory / 'CORE.BRN'}"
        raise BrnError(msg)
    _validate_flat_unique_names(entries)
    target.mkdir(parents=True, exist_ok=True)
    total = len(entries)
    work, skipped = _plan_extraction(entries, target, overwrite=overwrite)
    if not work:
        _notify(progress, total, total)
        return ExtractionReport(0, skipped, 0, 0)

    completed = skipped
    _notify(progress, completed, total)
    explicit = [item for item in work if "~" in item.entry.name]
    regular = [item for item in work if "~" not in item.entry.name]
    copied = converted = 0
    with archive.reader() as read_entry:
        # Preserve real DOS-style names before NTFS allocates aliases for long
        # names. There are very few of these, so keeping this phase serial costs
        # little while making the following writes independently parallelizable.
        for item in explicit:
            proprietary = _extract_one(item, read_entry)
            copied += not proprietary
            converted += proprietary
            completed += 1
            _notify(progress, completed, total)

        workers = _worker_count(len(regular))
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="gk3hd-extract",
        ) as pool:
            futures = {pool.submit(_extract_one, item, read_entry): item for item in regular}
            for future in as_completed(futures):
                proprietary = future.result()
                copied += not proprietary
                converted += proprietary
                completed += 1
                _notify(progress, completed, total)
    return ExtractionReport(
        extracted=len(work),
        skipped=skipped,
        copied_standard=copied,
        converted_proprietary=converted,
    )


def _plan_extraction(
    entries: list[BarnEntry],
    target: Path,
    *,
    overwrite: bool,
) -> tuple[list[_ExtractionWork], int]:
    """Prevalidate every destination before workers mutate the output tree."""
    existing_names = {path.name.upper(): path.name for path in target.iterdir()}
    work: list[_ExtractionWork] = []
    skipped = 0
    for entry in entries:
        key = entry.name.upper()
        actual_name = existing_names.get(key)
        destination = target / (actual_name or entry.name)
        if actual_name is not None and not destination.is_file():
            msg = f"output destination is not a file: {destination}"
            raise BrnError(msg)
        if actual_name is not None and not overwrite:
            skipped += 1
            continue
        if actual_name is None and destination.exists():
            msg = (
                f"cannot create {entry.name}: it resolves to an NTFS short-name alias; "
                "use a fresh output directory"
            )
            raise BrnError(msg)
        existing_names[key] = destination.name
        work.append(_ExtractionWork(entry, destination))
    return work, skipped


def _extract_one(
    item: _ExtractionWork,
    read_entry: Callable[[BarnEntry], bytes],
) -> bool:
    """Decode and atomically publish one independent texture."""
    payload = read_entry(item.entry)
    bitmap, proprietary = _decode_bmp_payload(payload, name=item.entry.name)
    _atomic_write(item.destination, bitmap)
    return proprietary


def _worker_count(work: int) -> int:
    """Use enough workers for PNG/Barn codecs without flooding the disk."""
    return min(work or 1, 16, max(4, os.cpu_count() or 1))


def _notify(progress: Callable[[int, int], None] | None, completed: int, total: int) -> None:
    """Publish optional extraction progress without complicating the hot loop."""
    if progress is not None:
        progress(completed, total)


def _validate_flat_unique_names(entries: list[BarnEntry]) -> None:
    """Ensure flattening cannot traverse directories or overwrite case aliases."""
    names: dict[str, str] = {}
    for entry in entries:
        if Path(entry.name).name != entry.name or "/" in entry.name or "\\" in entry.name:
            msg = f"unsafe BMP catalog name: {entry.name!r}"
            raise BrnError(msg)
        key = entry.name.upper()
        previous = names.get(key)
        if previous is not None:
            msg = f"duplicate BMP catalog name: {previous!r} and {entry.name!r}"
            raise BrnError(msg)
        names[key] = entry.name


def _decode_bmp_payload(payload: bytes, *, name: str) -> tuple[bytes, bool]:
    """Return a standard BMP plus whether proprietary conversion was required."""
    if payload.startswith(b"61nM"):
        return _convert_rgb565(payload, name=name), True
    if payload.startswith(b"BM"):
        return _copy_standard_bmp(payload, name=name), False
    msg = f"{name}: unknown BMP payload header {payload[:4]!r}"
    raise BrnError(msg)


def _copy_standard_bmp(payload: bytes, *, name: str) -> bytes:
    """Validate a standard BMP and retain precisely its declared file bytes."""
    try:
        info = inspect_bmp_bytes(payload, source=name)
    except BmpError as exc:
        raise BrnError(str(exc)) from exc
    (declared_size,) = struct.unpack_from("<I", payload, 2)
    if declared_size == 0:
        pixel_offset = struct.unpack_from("<I", payload, 10)[0]
        row_size = ((info.bits_per_pixel * info.width + 31) // 32) * 4
        declared_size = pixel_offset + row_size * info.height
    if declared_size < _BMP_PIXEL_OFFSET or declared_size > len(payload):
        msg = f"{name}: invalid BMP file size {declared_size}"
        raise BrnError(msg)
    return payload[:declared_size]


def _convert_rgb565(payload: bytes, *, name: str) -> bytes:
    """Convert GK3's top-down, row-padded RGB565 image to a 24-bit BMP."""
    if len(payload) < _GK3_BMP_HEADER.size:
        msg = f"{name}: truncated 61nM header"
        raise BrnError(msg)
    magic, height, width = _GK3_BMP_HEADER.unpack_from(payload)
    if magic != b"61nM" or width == 0 or height == 0:
        msg = f"{name}: invalid 61nM header"
        raise BrnError(msg)
    source_row_size = (width + (width & 1)) * 2
    expected_size = _GK3_BMP_HEADER.size + source_row_size * height
    if len(payload) != expected_size:
        msg = f"{name}: 61nM payload is {len(payload)} bytes, expected {expected_size}"
        raise BrnError(msg)

    output_row_size = ((24 * width + 31) // 32) * 4
    image_size = output_row_size * height
    file_size = _BMP_PIXEL_OFFSET + image_size
    # Pillow's native raw decoder performs the exact floor-scaled RGB565
    # conversion previously implemented by the per-pixel Python loop. Its raw
    # encoder also emits the required padded, bottom-up BGR rows in native code.
    image = Image.frombytes(
        "RGB",
        (width, height),
        payload[_GK3_BMP_HEADER.size :],
        "raw",
        "BGR;16",
        source_row_size,
        1,
    )
    pixels = image.tobytes("raw", "BGR", output_row_size, -1)

    file_header = _BMP_FILE_HEADER.pack(b"BM", file_size, 0, 0, _BMP_PIXEL_OFFSET)
    info_header = _BMP_INFO_HEADER.pack(
        _BMP_INFO_HEADER.size,
        width,
        height,
        1,
        24,
        0,
        image_size,
        0,
        0,
        0,
        0,
    )
    return file_header + info_header + pixels


def _atomic_write(destination: Path, data: bytes) -> None:
    """Replace one output only after its complete contents reach disk."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def extract(
    output: Path,
    *,
    game_dir: Path | None = None,
    exe: Path | None = None,
    overwrite: bool = False,
    progress: TextureProgress | None = None,
) -> ExtractionReport:
    """Extract the complete BMP catalog from the discovered data directory."""
    target = discover_game(game_dir=game_dir, exe=exe)
    return extract_bmps(
        target.data_dir,
        output,
        overwrite=overwrite,
        progress=progress,
    )
