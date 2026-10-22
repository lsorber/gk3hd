"""Atomic, resumable generation of videos with reproducible source identities."""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from gk3hd.system.files import sha256_file
from gk3hd.system.locking import ExclusiveFileLock, executable_lock_path
from gk3hd.videos.interpolation import INTERPOLATION_RECIPE, cinematic_rate
from gk3hd.videos.manifest import GENERATION_RECIPE, GENERATION_SCHEMA, read_json
from gk3hd.videos.options import MovieUpscaleOptions
from gk3hd.videos.publication import (
    GenerationSnapshot,
    pending_path,
    publish,
    record,
    recover_publication,
)
from gk3hd.videos.temporal import FRAMEWISE_RECIPE, clip_frames_for_size, framewise_restoration
from gk3hd.videos.video import convert, probe, restoration_pipeline

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from gk3hd.videos.temporal import ClipUpscaler


@dataclass(frozen=True, slots=True)
class MovieUpscaleReport:
    """Generated/reused cinematics and technical originals left unchanged."""

    generated: int
    skipped: int
    output: Path
    retained: int = 0


def upscale_movies(
    sources: Sequence[Path],
    output: Path,
    backend: ClipUpscaler | None = None,
    *,
    options: MovieUpscaleOptions | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> MovieUpscaleReport:
    """Resume only matching, hash-verified videos; publish each movie atomically."""
    options = options or MovieUpscaleOptions()
    output.mkdir(parents=True, exist_ok=True)
    with ExclusiveFileLock(executable_lock_path(output / ".movie-generation")):
        return _upscale_unlocked(sources, output, backend, options, progress)


def _upscale_unlocked(
    sources: Sequence[Path],
    output: Path,
    backend: ClipUpscaler | None,
    options: MovieUpscaleOptions,
    progress: Callable[[str, int, int], None] | None,
) -> MovieUpscaleReport:
    generated = skipped = retained = 0
    for source in sources:
        pipeline = restoration_pipeline(source)
        if pipeline == "retain":
            retained += 1
            continue
        destination = output / f"{source.stem}.mkv"
        state = destination.with_suffix(destination.suffix + ".json")
        if destination.resolve() == source.resolve():
            msg = f"output directory would overwrite an original movie: {source.name}"
            raise ValueError(msg)
        source_hash = sha256_file(source)
        recover_publication(destination, source_name=source.name, source_sha256=source_hash)
        info = probe(source)
        clip_frames = clip_frames_for_size((info.width, info.height), options.clip_frames)
        identity = {
            "schema_version": GENERATION_SCHEMA,
            "recipe": GENERATION_RECIPE,
            "pipeline": pipeline,
            "codec": "libaom-av1",
            "model": "3b",
            "encoding": "av1-444-10bit-crf24-rgb-lossless-flac-v2",
            **asdict(options),
            "clip_frames": clip_frames,
            "source_name": source.name,
            "source_sha256": source_hash,
            "interpolation": None,
        }
        if options.restoration_strength > 0 and framewise_restoration(info.rate):
            identity["recipe"] = FRAMEWISE_RECIPE
            identity["clip_frames"] = 1
        if options.restoration_strength > 0 and cinematic_rate(info.rate) != info.rate:
            identity["interpolation"] = {"recipe": INTERPOLATION_RECIPE, "rate": [60, 1]}
        if _verified_output(destination, state, identity):
            skipped += 1
            continue
        _generate(
            source,
            destination,
            identity=identity,
            backend=backend,
            options=replace(options, clip_frames=clip_frames),
            progress=progress,
        )
        generated += 1
    return MovieUpscaleReport(generated, skipped, output, retained)


def _verified_output(destination: Path, state: Path, identity: Mapping[str, object]) -> bool:
    GenerationSnapshot.capture(destination)
    if not destination.exists():
        return False
    payload = record(destination, read_json(state))
    return all(payload.get(key) == value for key, value in identity.items())


def _generate(  # noqa: PLR0913 - bind one complete per-movie generation transaction.
    source: Path,
    destination: Path,
    *,
    identity: Mapping[str, object],
    backend: ClipUpscaler | None,
    options: MovieUpscaleOptions,
    progress: Callable[[str, int, int], None] | None,
) -> None:
    before = GenerationSnapshot.capture(destination)
    original = probe(source)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.stem}-", suffix=destination.suffix, dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        if progress is not None:
            progress(source.name, 0, original.frames)
        info = convert(
            source,
            temporary,
            backend,
            options=options,
            progress=(lambda done, total: progress(source.name, done, total))
            if progress is not None
            else None,
        )
        encoded = probe(temporary)
        if encoded != info:
            differences = ", ".join(
                f"{key}: expected {value!r}, got {asdict(encoded)[key]!r}"
                for key, value in asdict(info).items()
                if asdict(encoded)[key] != value
            )
            msg = f"encoded movie does not preserve expected media: {source.name} ({differences})"
            raise ValueError(msg)
        metadata = asdict(info)
        metadata["rate"] = [info.rate.numerator, info.rate.denominator]
        source_metadata = asdict(original)
        source_metadata["rate"] = [original.rate.numerator, original.rate.denominator]
        payload = {
            **identity,
            "output_sha256": sha256_file(temporary),
            "media": metadata,
            "source_media": source_metadata,
        }
        if sha256_file(source) != identity["source_sha256"]:
            msg = f"original movie changed during restoration: {source.name}"
            raise ValueError(msg)
        publish(destination, temporary, payload, before)
    finally:
        if not pending_path(destination).exists():
            temporary.unlink(missing_ok=True)
