from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.analyze.alpha_shape import is_alpha_silhouette
from gk3hd.textures.analyze.classify import classify_texture
from gk3hd.textures.bmp import inspect_bmp_bytes
from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, plan_texture


def _mask() -> np.ndarray:
    result = np.zeros((24, 24), dtype=np.uint8)
    result[3:21, 3:21] = 128
    result[4:20, 4:20] = 255
    return result


def _classify(mask: np.ndarray) -> bool:
    return is_alpha_silhouette(tuple(row.tobytes() for row in mask))


@pytest.mark.parametrize("interior", [0, 1, 2, 3, 8])
def test_gray_interior_tolerance_is_not_a_pixel_edit(interior: int) -> None:
    mask = _mask()
    mask[10, 6 : 6 + interior] = 128
    before = mask.copy()
    assert _classify(mask) == (interior <= 2)
    np.testing.assert_array_equal(before, mask)


def test_internal_holes_and_clipped_silhouettes_qualify() -> None:
    mask = _mask()
    mask[8:16, 8:16] = 128
    mask[9:15, 9:15] = 0
    assert _classify(mask)
    mask[8:16, :4] = 255
    assert _classify(mask)


def test_opaque_exterior_and_no_opaque_core_are_not_silhouettes() -> None:
    mask = _mask()
    assert not _classify(255 - mask)
    mask[mask == 255] = 128
    assert not _classify(mask)


@pytest.mark.parametrize("rows", [(), (b"",), (b"\0", b"\0\0"), (b"\0",), (b"\xff",)])
def test_degenerate_masks_do_not_qualify(rows: tuple[bytes, ...]) -> None:
    assert not is_alpha_silhouette(rows)


def test_analysis_decodes_palette_and_does_not_classify_visible_gray_as_opacity() -> None:
    mask = _mask()[:, :-1]  # BMP stride has padding; reverse palette index meaning.
    image = Image.fromarray(255 - mask).convert("P")
    image.putpalette([v for i in range(256) for v in (255 - i,) * 3])
    stream = BytesIO()
    image.save(stream, format="BMP")
    info = inspect_bmp_bytes(stream.getvalue())
    assert info.alpha_silhouette
    features = classify_texture("ANY_NAME_OP.BMP", info, {})
    assert features.alpha_silhouette
    assert plan_texture(features).kind is PipelineKind.ALPHA_AI
    assert not classify_texture("VISIBLE.BMP", info, {}).alpha_silhouette


def test_feature_roundtrip_force_resampling_and_priority() -> None:
    feature = TextureFeatures("X_OP.BMP", kind=TextureKind.ALPHA, alpha_silhouette=True)
    assert feature.with_overrides(feature.to_dict()) == feature
    assert plan_texture(feature.with_overrides({"alpha_silhouette": False})).kind is (
        PipelineKind.ALPHA_SMOOTH
    )
    assert plan_texture(feature.with_overrides({"native_size": True})).kind.keeps_native_size
    with pytest.raises(ValueError, match="requires scalar opacity"):
        TextureFeatures("X.BMP", alpha_silhouette=True)
    with pytest.raises(TypeError, match="must be true or false"):
        feature.with_overrides({"alpha_silhouette": "yes"})
