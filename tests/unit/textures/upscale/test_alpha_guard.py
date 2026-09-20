import json

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.model import TextureFeatures, TextureKind
from gk3hd.textures.upscale.alpha_guard import alpha_rejection_reasons, alpha_result_method
from gk3hd.textures.upscale.generation import ALPHA_STAMP
from gk3hd.textures.upscale.pipeline import is_current_alpha_output, upscale_texture


def _mask() -> Image.Image:
    image = Image.new("L", (32, 32))
    image.paste(255, (4, 4, 28, 28))
    image.paste(0, (12, 12, 20, 20))
    return image


def test_exact_enlargement_preserves_topology_and_coverage() -> None:
    original = _mask()
    candidate = original.resize((128, 128), Image.Resampling.NEAREST)
    assert not alpha_rejection_reasons(original, candidate, 4)
    assert alpha_rejection_reasons(original, original, 4) == ("invalid-dimensions",)


@pytest.mark.parametrize("value", [80, 150, 255])
def test_new_parts_are_rejected_at_multiple_opacity_thresholds(value: int) -> None:
    original = _mask()
    candidate = original.resize((128, 128), Image.Resampling.NEAREST)
    candidate.putpixel((2, 2), value)
    reasons = alpha_rejection_reasons(original, candidate, 4)
    assert "contour-shift" in reasons
    assert "changed-holes-or-parts" in reasons


def test_filling_holes_and_shrinking_silhouettes_are_rejected() -> None:
    original = _mask()
    candidate = original.resize((128, 128), Image.Resampling.NEAREST)
    candidate.paste(255, (48, 48, 80, 80))
    assert "changed-holes-or-parts" in alpha_rejection_reasons(original, candidate, 4)
    candidate.paste(0, (0, 0, 64, 128))
    assert "area-change" in alpha_rejection_reasons(original, candidate, 4)


def test_coverage_loss_without_binary_contour_changes_is_rejected() -> None:
    original = _mask()
    candidate = original.resize((128, 128), Image.Resampling.NEAREST)
    candidate = candidate.point(lambda value: min(value, 200))
    assert alpha_rejection_reasons(original, candidate, 4) == ("coverage-change",)


@pytest.mark.parametrize("accepted", [True, False])
def test_guard_records_grayscale_ai_or_exact_lanczos_and_validates_cache(accepted: bool) -> None:
    class Backend:
        scale = 4

        def upscale(self, image: Image.Image) -> Image.Image:
            size = (image.width * 4, image.height * 4)
            return (
                image.resize(size, Image.Resampling.NEAREST)
                if accepted
                else Image.new("RGB", size, "white")
            )

    original = _mask()
    feature = TextureFeatures("X_OP.BMP", kind=TextureKind.ALPHA, alpha_silhouette=True)
    output = upscale_texture(original, feature, upscaler=Backend())
    assert output.mode == "P"
    rgb = np.asarray(output.convert("RGB"))
    np.testing.assert_array_equal(rgb[:, :, 0], rgb[:, :, 1])
    np.testing.assert_array_equal(rgb[:, :, 0], rgb[:, :, 2])
    assert alpha_result_method(output) == ("ai" if accepted else "lanczos")
    assert is_current_alpha_output(original, output, periodic=False)
    if not accepted:
        expected = upscale_texture(original, feature.with_overrides({"alpha_silhouette": False}))
        assert output.tobytes() == expected.tobytes()
        assert json.loads(output.info[ALPHA_STAMP])["reasons"]
    output.putpixel((0, 0), 255)
    assert not is_current_alpha_output(original, output, periodic=False)


@pytest.mark.parametrize("metadata", ["", "null", "{}", '{"version":0,"method":"ai"}'])
def test_unknown_guard_metadata_requires_regeneration(metadata: str) -> None:
    image = _mask()
    image.info[ALPHA_STAMP] = metadata
    assert alpha_result_method(image) is None
