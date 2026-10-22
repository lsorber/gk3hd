from collections.abc import Iterator, Sequence
from fractions import Fraction

import pytest
from PIL import Image

from gk3hd.videos.options import MovieUpscaleOptions
from gk3hd.videos.temporal import clip_frames_for_size, restore_frames, upscale_frames


@pytest.mark.parametrize(
    ("size", "maximum", "expected"),
    [
        ((320, 240), 17, 17),
        ((640, 480), 17, 5),
        ((320, 240), 33, 33),
        ((160, 120), 17, 17),
        ((640, 480), 5, 5),
        ((3840, 2160), 17, 5),
    ],
)
def test_large_sources_get_bounded_reproducible_temporal_context(
    size: tuple[int, int], maximum: int, expected: int
) -> None:
    assert clip_frames_for_size(size, maximum) == expected


@pytest.mark.parametrize(("size", "maximum"), [((0, 240), 17), ((320, 240), 16)])
def test_invalid_context_budget_is_rejected(size: tuple[int, int], maximum: int) -> None:
    with pytest.raises(ValueError, match="4n\\+1"):
        clip_frames_for_size(size, maximum)


class RecordingBackend:
    def __init__(self) -> None:
        self.clips: list[list[int]] = []

    def upscale(self, image: Image.Image) -> Image.Image:
        self.clips.append([image.tobytes()[0]])
        return image.resize((image.width * 4, image.height * 4))

    def upscale_clip(self, frames: Sequence[Image.Image]) -> list[Image.Image]:
        self.clips.append([frame.tobytes()[0] for frame in frames])
        return [frame.resize((frame.width * 4, frame.height * 4)) for frame in frames]


@pytest.mark.parametrize("rate", [Fraction(12), Fraction(15), Fraction(1000000, 66667)])
def test_low_cadence_never_mixes_moving_shapes_between_source_frames(rate: Fraction) -> None:
    class GhostingBackend(RecordingBackend):
        def upscale_clip(self, frames: Sequence[Image.Image]) -> list[Image.Image]:
            del frames
            pytest.fail("cross-frame temporal inference would introduce trails")

    frames = [Image.new("RGB", (8, 6), (i * 20, 40, 80)) for i in range(7)]
    pictures = list(restore_frames(frames, GhostingBackend(), MovieUpscaleOptions(), rate))
    assert [p.tobytes() for p in pictures] == [f.resize((32, 24)).tobytes() for f in frames]


def test_low_cadence_reuses_identical_holds_but_not_moving_frames() -> None:
    backend = RecordingBackend()
    frames = [Image.new("RGB", (8, 6), (i, 40, 80)) for i in (1, 1, 2, 2, 1)]
    pictures = list(restore_frames(frames, backend, MovieUpscaleOptions(), Fraction(15)))
    assert [p.tobytes()[0] for p in pictures] == [1, 1, 2, 2, 1]
    assert backend.clips == [[1], [2], [1]]


def test_normal_cadence_retains_joint_temporal_restoration() -> None:
    class JointBackend(RecordingBackend):
        def upscale(self, image: Image.Image) -> Image.Image:
            del image
            pytest.fail("normal-cadence frames should be restored jointly")

    backend = JointBackend()
    frames = [Image.new("RGB", (8, 6), (index, 40, 80)) for index in range(7)]
    result = list(restore_frames(frames, backend, MovieUpscaleOptions(), Fraction(30)))
    assert [frame.tobytes()[0] for frame in result] == list(range(7))


@pytest.mark.parametrize("count", [0, 1, 2, 4, 5, 6, 8, 9, 10, 17])
def test_stream_keeps_every_frame_once_in_order(count: int) -> None:
    backend = RecordingBackend()
    frames = [Image.new("RGB", (3, 2), (i, 0, 0)) for i in range(count)]
    progress: list[int] = []
    result = list(upscale_frames(frames, backend, progress=progress.append))
    assert len(result) == count
    assert [frame.tobytes()[0] for frame in result] == list(range(count))
    assert all(frame.size == (12, 8) for frame in result)
    assert progress == list(range(1, count + 1))
    assert all(len(clip) == 5 for clip in backend.clips)


def test_joint_clips_overlap_and_pad_only_the_tail() -> None:
    backend = RecordingBackend()
    list(upscale_frames((Image.new("RGB", (2, 2), (i, 0, 0)) for i in range(7)), backend))
    assert backend.clips == [[0, 1, 2, 3, 4], [4, 5, 6, 6, 6]]


def test_decoder_is_consumed_one_clip_at_a_time() -> None:
    decoded: list[int] = []

    def source() -> Iterator[Image.Image]:
        for index in range(1000):
            decoded.append(index)
            yield Image.new("RGB", (2, 2))

    stream = upscale_frames(source(), RecordingBackend())
    next(stream)
    assert len(decoded) == 5
    stream.close()


@pytest.mark.parametrize("count", [1, 16, 17, 18, 32, 33, 34, 49])
def test_long_context_keeps_frame_order_cadence_and_progress(count: int) -> None:
    frames = (Image.new("RGB", (2, 2), (index, 0, 0)) for index in range(count))
    progress: list[int] = []
    result = list(
        upscale_frames(frames, RecordingBackend(), clip_frames=17, progress=progress.append)
    )
    assert [frame.tobytes()[0] for frame in result] == list(range(count))
    assert progress == list(range(1, count + 1))


@pytest.mark.parametrize("count", [0, 1, 4, 6, 8])
def test_invalid_temporal_window_rejected(count: int) -> None:
    with pytest.raises(ValueError, match="4n\\+1"):
        list(upscale_frames([], RecordingBackend(), clip_frames=count))


@pytest.mark.parametrize("cut", [1, 4, 5, 8, 16, 17])
def test_hard_cut_is_not_inferred_or_blended_across(cut: int) -> None:
    backend = RecordingBackend()
    colors = [0] * cut + [220] * 6
    frames = [Image.new("RGB", (2, 2), (value,) * 3) for value in colors]
    progress: list[int] = []
    result = list(upscale_frames(frames, backend, clip_frames=17, progress=progress.append))
    assert [frame.tobytes()[0] for frame in result] == colors
    assert progress == list(range(1, len(colors) + 1))
    assert all(len(set(clip)) == 1 for clip in backend.clips)


def test_single_frame_flash_keeps_both_boundaries_separate() -> None:
    backend = RecordingBackend()
    colors = [0] * 6 + [255] + [0] * 6
    result = list(
        upscale_frames([Image.new("RGB", (2, 2), (value,) * 3) for value in colors], backend)
    )
    assert [frame.tobytes()[0] for frame in result] == colors
    assert all(len(set(clip)) == 1 for clip in backend.clips)


def test_short_tail_uses_only_the_temporal_padding_it_needs() -> None:
    backend = RecordingBackend()
    frames = [Image.new("RGB", (2, 2), (value, 0, 0)) for value in range(18)]
    result = list(upscale_frames(frames, backend, clip_frames=17))
    assert len(result) == len(frames)
    assert [len(clip) for clip in backend.clips] == [17, 5]
    assert backend.clips[-1] == [16, 17, 17, 17, 17]


@pytest.mark.parametrize("strength", [0.0, 0.35, 0.8, 1.0])
@pytest.mark.parametrize("count", [1, 5, 6, 9, 17, 18])
def test_strength_blends_each_decoded_frame_once_including_held_boundaries(
    strength: float, count: int
) -> None:
    frames = [Image.new("RGB", (3, 2), (index * 2, 50, 80)) for index in range(count)]

    class ConstantBackend:
        calls = 0

        def upscale_clip(self, frames: Sequence[Image.Image]) -> list[Image.Image]:
            self.calls += 1
            return [Image.new("RGB", (12, 8), (200, 120, 20)) for _ in frames]

    backend = ConstantBackend()
    progress: list[int] = []
    pictures = list(
        upscale_frames(frames, backend, restoration_strength=strength, progress=progress.append)
    )
    assert len(pictures) == count
    assert progress == list(range(1, count + 1))
    for before, after in zip(frames, pictures, strict=True):
        source = before.resize((12, 8), Image.Resampling.BICUBIC)
        expected = Image.blend(source, Image.new("RGB", (12, 8), (200, 120, 20)), strength)
        assert after.tobytes() == expected.tobytes()
    assert bool(backend.calls) == bool(strength)


def test_bicubic_only_mode_needs_no_backend_and_keeps_source_order() -> None:
    frames = [Image.new("RGB", (2, 3), (index, 80, 120)) for index in range(6)]
    pictures = list(upscale_frames(frames, None, restoration_strength=0))
    assert [picture.tobytes() for picture in pictures] == [
        frame.resize((8, 12), Image.Resampling.BICUBIC).tobytes() for frame in frames
    ]


@pytest.mark.parametrize("strength", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_output_strength_is_rejected(strength: float) -> None:
    with pytest.raises(ValueError, match="restoration_strength"):
        list(upscale_frames([], RecordingBackend(), restoration_strength=strength))


def test_positive_strength_requires_backend_before_consuming_source() -> None:
    def source() -> Iterator[Image.Image]:
        pytest.fail("missing backend should be reported before decoding")
        yield Image.new("RGB", (2, 2))

    with pytest.raises(ValueError, match="temporal AI backend"):
        list(upscale_frames(source(), None, restoration_strength=0.35))


def test_shared_boundary_is_source_anchored_after_combining_temporal_predictions() -> None:
    class ContextBackend:
        calls = 0

        def upscale_clip(self, frames: Sequence[Image.Image]) -> list[Image.Image]:
            self.calls += 1
            return [Image.new("RGB", (8, 8), (self.calls * 100,) * 3) for _ in frames]

    source = [Image.new("RGB", (2, 2), (20,) * 3) for _ in range(9)]
    result = list(upscale_frames(source, ContextBackend(), restoration_strength=0.35))
    predictions = [100] * 4 + [150] + [200] * 4
    for frame, value in zip(result, predictions, strict=True):
        expected = Image.blend(
            Image.new("RGB", (8, 8), (20,) * 3),
            Image.new("RGB", (8, 8), (value,) * 3),
            0.35,
        )
        assert frame.tobytes() == expected.tobytes()


def test_source_blend_keeps_predictions_on_opposite_sides_of_cut_separate() -> None:
    class ShotBackend:
        @staticmethod
        def upscale_clip(frames: Sequence[Image.Image]) -> list[Image.Image]:
            color = 70 if frames[0].tobytes()[0] == 0 else 180
            return [Image.new("RGB", (8, 8), (color,) * 3) for _ in frames]

    values = [0] * 6 + [220] * 6
    source = [Image.new("RGB", (2, 2), (value,) * 3) for value in values]
    result = list(upscale_frames(source, ShotBackend(), restoration_strength=0.35))
    for value, frame in zip(values, result, strict=True):
        prediction = 70 if value == 0 else 180
        expected = Image.blend(
            Image.new("RGB", (8, 8), (value,) * 3),
            Image.new("RGB", (8, 8), (prediction,) * 3),
            0.35,
        )
        assert frame.tobytes() == expected.tobytes()
