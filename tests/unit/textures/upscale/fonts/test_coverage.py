"""Coverage constraints are necessary invariants, not font-identity evidence."""

import numpy as np
import pytest

from gk3hd.textures.upscale.fonts.coverage import reconstruct_font_coverage


@pytest.mark.parametrize("shape", [(1, 1), (1, 13), (17, 1), (9, 15), (24, 33)])
@pytest.mark.parametrize("hinted", [False, True])
@pytest.mark.parametrize("bit_depth", [5, 8])
def test_exact_quantized_coverage_and_no_input_mutation(
    shape: tuple[int, int], hinted: bool, bit_depth: int
) -> None:
    maximum = (1 << bit_depth) - 1
    random = np.random.default_rng(124)
    source = random.integers(0, maximum + 1, shape, dtype=np.uint8)
    source.flat[0] = 0
    if source.size > 1:
        source.flat[-1] = maximum
    before = source.copy()
    hint = random.random((shape[0] * 4, shape[1] * 4)) if hinted else None
    previous_hint = hint.copy() if hint is not None else None
    first = reconstruct_font_coverage(source, edge_hint=hint, bit_depth=bit_depth)
    second = reconstruct_font_coverage(source, edge_hint=hint, bit_depth=bit_depth)
    assert first.dtype == np.uint8
    assert first.shape == (shape[0] * 4, shape[1] * 4)
    assert np.all(first <= maximum)
    blocks = first.reshape(shape[0], 4, shape[1], 4).transpose(0, 2, 1, 3)
    np.testing.assert_array_equal(blocks.sum(axis=(2, 3)), source.astype(np.int16) * 16)
    assert np.all(blocks[source == 0] == 0)
    assert np.all(blocks[source == maximum] == maximum)
    np.testing.assert_array_equal(source, before)
    np.testing.assert_array_equal(first, second)
    if hint is not None:
        np.testing.assert_array_equal(hint, previous_hint)


@pytest.mark.parametrize("value", [0, 1, 7, 15, 16, 30, 31])
def test_constant_and_single_pixel_coverage(value: int) -> None:
    source = np.full((1, 1), value, dtype=np.uint8)
    result = reconstruct_font_coverage(source)
    assert result.shape == (4, 4)
    assert result.sum() == value * 16


@pytest.mark.parametrize(
    "source",
    [
        np.zeros((0, 2), dtype=np.uint8),
        np.zeros(2, dtype=np.uint8),
        np.zeros((1, 1, 1), dtype=np.uint8),
        np.array([[32]], dtype=np.uint8),
        np.array([[256]], dtype=np.uint16),
        np.array([[0.5]]),
    ],
)
def test_invalid_coverage_is_rejected(source: np.ndarray) -> None:
    with pytest.raises(ValueError, match="font coverage requires"):
        reconstruct_font_coverage(source)


@pytest.mark.parametrize(
    "hint",
    [
        np.zeros((3, 4)),
        np.full((4, 4), np.nan),
        np.full((4, 4), np.inf),
        np.full((4, 4), -0.1),
        np.full((4, 4), 1.1),
    ],
)
def test_invalid_hint_is_rejected(hint: np.ndarray) -> None:
    with pytest.raises(ValueError, match="font edge hint requires"):
        reconstruct_font_coverage(np.array([[15]], dtype=np.uint8), edge_hint=hint)


def test_flat_hint_cannot_invent_an_edge_direction() -> None:
    source = np.array([[0, 4, 10], [0, 31, 10], [0, 10, 0]], dtype=np.uint8)
    np.testing.assert_array_equal(
        reconstruct_font_coverage(source),
        reconstruct_font_coverage(source, edge_hint=np.zeros((12, 12))),
    )


@pytest.mark.parametrize("bit_depth", [0, 1, 4, 6, 7, 9, 16])
def test_unverified_precision_is_rejected(bit_depth: int) -> None:
    with pytest.raises(ValueError, match="only five-bit or eight-bit"):
        reconstruct_font_coverage(np.array([[0]], dtype=np.uint8), bit_depth=bit_depth)


def test_default_precision_is_unchanged() -> None:
    source = np.array([[0, 4, 10], [0, 31, 10], [0, 10, 0]], dtype=np.uint8)
    np.testing.assert_array_equal(
        reconstruct_font_coverage(source), reconstruct_font_coverage(source, bit_depth=5)
    )
