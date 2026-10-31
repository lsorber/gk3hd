"""Contextual inference cannot alter authored apertures or bake in eyeballs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from gk3hd.textures.model import PipelineOverride, TextureFeatures
from gk3hd.textures.routing import PipelineKind, plan_texture
from gk3hd.textures.upscale.face_layer import (
    face_layer_stamp,
    prepare_face_context,
    restore_face_layer,
)
from gk3hd.textures.upscale.generation import generation_stamp
from gk3hd.textures.upscale.pipeline import upscale_smooth_color
from gk3hd.textures.upscale.service import _is_resumable_png, _upscale_one

if TYPE_CHECKING:
    from pathlib import Path


def _sources(root: Path) -> Path:
    (root / "FACES.TXT").write_text(
        "[Eyes]\nEye_GreenX=4x4, DownSampleOnly\n[DEFAULT]\n"
        "Left Eye Name=Eye_GreenX\nRight Eye Name=Eye_GreenX\n"
        "Left Eye Offset=34,34\nRight Eye Offset=50,34\n[TEST]\n"
        "Eyelids Offset=32,32\nEyelids Alpha Channel=test_eyelids_alpha\n"
    )
    Image.new("RGB", (96, 96), (150, 110, 90)).save(root / "TEST_FACE.BMP")
    Image.new("RGB", (32, 32), (20, 160, 30)).save(root / "EYE_GREENX.BMP")
    art = Image.new("RGB", (32, 24), (150, 110, 90))
    art.paste((255, 0, 255), (8, 8, 12, 14))
    source = root / "TEST_EYELIDS.BMP"
    art.save(source)
    alpha = Image.new("L", art.size, 255)
    alpha.paste(0, (2, 2, 9, 7))
    alpha.paste(120, (13, 2, 20, 7))
    alpha.save(root / "TEST_EYELIDS_ALPHA.BMP")
    return source


class _ContextBackend:
    scale = 4

    def upscale(self, image: Image.Image) -> Image.Image:
        result = np.array(
            image.resize((image.width * 4, image.height * 4), Image.Resampling.BICUBIC)
        )
        result[::2, ::2] = np.minimum(result[::2, ::2].astype("int16") + 20, 255).astype("uint8")
        return Image.fromarray(result)


def test_context_uses_original_face_eyes_and_partial_opacity(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    context = prepare_face_context(source)
    assert context.image.size == (96, 96)
    assert context.origin == (32, 32)
    # A transparent eyelid texel reveals the separate eyeball in the input.
    assert context.image.getpixel((35, 35)) == (20, 160, 30)
    # Opaque eye-sheet surround must not replace untouched face outside the
    # expression footprint, even when the eye rectangle overlaps that area.
    Image.new("RGB", (64, 64), (20, 160, 30)).save(tmp_path / "EYE_GREENX.BMP")
    context = prepare_face_context(source)
    assert context.image.getpixel((41, 41)) == (150, 110, 90)
    assert 120 in context.coverage
    before = (tmp_path / "TEST_EYELIDS_ALPHA.BMP").read_bytes()
    restored = restore_face_layer(context, _ContextBackend())
    original = upscale_smooth_color(context.artwork, periodic=False, alphatest=True)
    mask = np.all(np.asarray(original) == (255, 0, 255), axis=2)
    np.testing.assert_array_equal(np.all(np.asarray(restored) == (255, 0, 255), axis=2), mask)
    # Partial opacity and uncovered pixels retain source shading, with no AI iris.
    coverage = np.asarray(
        Image.fromarray(context.coverage).resize(restored.size, Image.Resampling.NEAREST)
    )
    np.testing.assert_array_equal(
        np.asarray(restored)[coverage < 250], np.asarray(original)[coverage < 250]
    )
    assert not np.array_equal(
        np.asarray(restored)[coverage == 255], np.asarray(original)[coverage == 255]
    )
    assert (tmp_path / "TEST_EYELIDS_ALPHA.BMP").read_bytes() == before


def test_file_aware_generation_resumes_until_a_context_dependency_changes(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    choice = PipelineOverride.from_dict(
        {
            "pipeline": "ai",
            "variant": "face-layer",
            "status": "todo",
            "reason": "Contextual candidate.",
            "todo": "Review the composited animation.",
        }
    )
    features = TextureFeatures(
        source.name, eyelid_overlay=True, alphatest=True, pipeline_override=choice
    )
    plan = plan_texture(features)
    assert plan.kind is PipelineKind.FACE_LAYER_AI
    destination = tmp_path / "result.png"
    _upscale_one(source, destination, features, _ContextBackend())
    assert _is_resumable_png(source, destination, plan)
    stamp = generation_stamp(source, plan)
    Image.new("RGB", (32, 32), "blue").save(tmp_path / "EYE_GREENX.BMP")
    assert generation_stamp(source, plan) != stamp
    assert not _is_resumable_png(source, destination, plan)


def test_enlarged_override_coordinates_cannot_be_used_as_native_context(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    metadata = tmp_path / "FACES.TXT"
    metadata.write_text(
        metadata.read_text().replace("Eyelids Offset=32,32", "Eyelids Offset=128,128")
    )
    with pytest.raises(ValueError, match="coordinates exceed"):
        face_layer_stamp(source)


def test_authored_face_name_resolves_actor_texture_alias(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    metadata = tmp_path / "FACES.TXT"
    metadata.write_text(metadata.read_text().replace("[TEST]", "[ACTOR]\nFace Name=TEST_FACE"))
    assert prepare_face_context(source).origin == (32, 32)


def test_shared_face_uses_the_explicit_opacity_binding(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    metadata = tmp_path / "FACES.TXT"
    content = metadata.read_text().replace("[TEST]", "[ACTOR]\nFace Name=TEST_FACE")
    other = (
        "[OTHER]\nFace Name=TEST_FACE\nEyelids Offset=1,1\n"
        "Eyelids Alpha Channel=other_eyelids_alpha\n"
    )
    # Order cannot determine which character's mask and coordinates are used.
    for text in (content + other, other + content):
        metadata.write_text(text)
        context = prepare_face_context(source)
        assert context.origin == (32, 32)
        assert 120 in context.coverage


def test_shared_face_without_a_distinguishing_binding_is_rejected(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    metadata = tmp_path / "FACES.TXT"
    content = metadata.read_text().replace("[TEST]", "[ACTOR]\nFace Name=TEST_FACE")
    content = content.replace("test_eyelids_alpha", "actor_eyelids_alpha")
    metadata.write_text(content + "[OTHER]\nFace Name=TEST_FACE\nEyelids Offset=1,1\n")
    with pytest.raises(ValueError, match="ambiguous original face definition"):
        prepare_face_context(source)


def test_detail_refinement_preserves_apertures_and_partial_opacity(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    with Image.open(source) as image:
        artwork = image.convert("RGB")
    artwork.paste((60, 45, 30), (23, 13, 29, 21))
    artwork.save(source)
    context = prepare_face_context(source)

    class SoftDetailBackend:
        scale = 4

        def upscale(self, image: Image.Image) -> Image.Image:
            enlarged = image.resize((image.width * 4, image.height * 4))
            pixels = np.asarray(enlarged, dtype=np.float64)
            x = np.arange(enlarged.width)
            soft = np.sin(x * 0.31) * 15
            return Image.fromarray(np.clip(pixels + soft[None, :, None], 0, 255).astype("uint8"))

    backend = SoftDetailBackend()
    ordinary = np.asarray(restore_face_layer(context, backend))
    refined = np.asarray(restore_face_layer(context, backend, detail_sharpening=True))
    mask = np.all(ordinary == (255, 0, 255), axis=2)
    np.testing.assert_array_equal(np.all(refined == (255, 0, 255), axis=2), mask)
    coverage = np.asarray(
        Image.fromarray(context.coverage).resize((128, 96), Image.Resampling.NEAREST)
    )
    protected = (coverage < 250) | mask
    np.testing.assert_array_equal(refined[protected], ordinary[protected])
    assert np.any(refined[~protected] != ordinary[~protected])
    # Source scalar coverage stays an independent asset.
    assert prepare_face_context(source).coverage.tobytes() == context.coverage.tobytes()


def test_refinement_choice_is_reproducible_and_invalidates_the_old_output(tmp_path: Path) -> None:
    source = _sources(tmp_path)
    choice = PipelineOverride.from_dict(
        {"pipeline": "ai", "variant": "face-layer", "status": "final", "reason": "Reviewed detail."}
    )
    refined_choice = PipelineOverride.from_dict({**choice.to_dict(), "detail_sharpening": True})
    feature = TextureFeatures(source.name, eyelid_overlay=True, pipeline_override=choice)
    refined_feature = TextureFeatures(
        source.name,
        eyelid_overlay=True,
        pipeline_override=PipelineOverride.from_dict(refined_choice.to_dict()),
    )
    ordinary = tmp_path / "ordinary.png"
    refined = tmp_path / "refined.png"
    _upscale_one(source, ordinary, feature, _ContextBackend())
    assert not _is_resumable_png(source, ordinary, plan_texture(refined_feature))
    _upscale_one(source, refined, refined_feature, _ContextBackend())
    assert _is_resumable_png(source, refined, plan_texture(refined_feature))
    assert generation_stamp(source, plan_texture(feature)) != generation_stamp(
        source, plan_texture(refined_feature)
    )


@pytest.mark.parametrize("value", [1, "yes", None, []])
def test_detail_refinement_requires_an_explicit_boolean(value: object) -> None:
    with pytest.raises(TypeError, match="detail_sharpening"):
        PipelineOverride.from_dict(
            {
                "pipeline": "ai",
                "variant": "face-layer",
                "status": "final",
                "reason": "Reviewed detail.",
                "detail_sharpening": value,
            }
        )


def test_detail_refinement_cannot_be_applied_to_an_unrelated_route() -> None:
    with pytest.raises(ValueError, match="contextual face-layer"):
        PipelineOverride("ai", "color", "final", "Ordinary material.", detail_sharpening=True)
