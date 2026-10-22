from PIL import Image

from gk3hd.videos.shots import tagged_frames


def test_gradual_brightness_change_does_not_fragment_a_shot() -> None:
    frames = [Image.new("RGB", (8, 6), (value,) * 3) for value in range(0, 140, 4)]
    result = list(tagged_frames(frames))
    assert [shot for shot, _ in result] == [0] * len(frames)
    assert [id(frame) for _, frame in result] == [id(frame) for frame in frames]


def test_dark_cut_is_detected_without_requiring_a_bright_frame() -> None:
    frames = [Image.new("RGB", (8, 6), (value,) * 3) for value in [10, 10, 10, 21, 21]]
    assert [shot for shot, _ in tagged_frames(frames)] == [0, 0, 0, 1, 1]
