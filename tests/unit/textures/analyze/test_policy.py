import ast
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from gk3hd.textures.analyze import classify
from gk3hd.textures.analyze.manifest import analyze_directory, load_feature_manifest, write_manifest
from gk3hd.textures.analyze.policy import POLICY_SCHEMA_VERSION, load_policy
from gk3hd.textures.bmp import inspect_bmp
from gk3hd.textures.model import PipelineOverride, TextureFeatures, TextureKind
from gk3hd.textures.routing import PipelineKind, plan_texture
from tests.unit.textures.analyze.test_manifest import _write_bmp24


def _policy(tmp_path: Path, **sections: object) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"schema_version": POLICY_SCHEMA_VERSION, **sections}))
    return path


def _decision(**changes: str) -> dict[str, object]:
    return {
        "textures": ["ART.BMP"],
        "pipeline": "resample",
        "variant": "color",
        "status": "todo",
        "reason": "Unverified candidate detail.",
        "todo": "Compare the material in its scene before promoting AI.",
        **changes,
    }


def test_pipeline_choice_does_not_lie_about_texture_features_and_survives_manifest(
    tmp_path: Path,
) -> None:
    _write_bmp24(tmp_path / "ART.BMP")
    policy = _policy(tmp_path, pipeline_overrides=[_decision()])
    report = analyze_directory(tmp_path, overrides=policy)
    feature = report.manifest.textures[0]
    assert feature.kind is TextureKind.COLOR
    assert not feature.exact_raster
    assert report.todos == (feature,)
    assert feature.pipeline_override is not None
    assert feature.pipeline_override.todo
    assert plan_texture(feature).kind is PipelineKind.COLOR_SMOOTH
    path = tmp_path / "analysis.json"
    write_manifest(report.manifest, path)
    assert load_feature_manifest(path)[feature.name] == feature
    serialized = json.loads(path.read_text())["textures"][0]
    assert "smooth_color" not in serialized
    assert serialized["pipeline_override"]["status"] == "todo"


def test_lady_howard_skin_uses_todo_bicubic_fallback(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "LH3_CHEST.BMP")
    report = analyze_directory(tmp_path)
    feature = report.manifest.textures[0]
    assert feature.pipeline_override is not None
    assert feature.pipeline_override.status == "todo"
    assert "skin" in feature.pipeline_override.reason
    assert feature.pipeline_override.todo
    assert plan_texture(feature).kind is PipelineKind.COLOR_SMOOTH
    path = tmp_path / "analysis.json"
    write_manifest(report.manifest, path)
    assert load_feature_manifest(path)[feature.name] == feature


def test_feature_correction_precedes_pipeline_choice(tmp_path: Path) -> None:
    _write_bmp24(tmp_path / "ART.BMP", top_left=(255, 0, 255))
    path = _policy(
        tmp_path,
        feature_overrides=[
            {"textures": ["ART.BMP"], "set": {"alphatest": False}, "reason": "Test."}
        ],
        pipeline_overrides=[_decision()],
    )
    feature = analyze_directory(tmp_path, overrides=path).manifest.textures[0]
    assert not feature.alphatest
    assert plan_texture(feature).kind is PipelineKind.COLOR_SMOOTH


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "maybe"},
        {"status": "final"},
        {"todo": " "},
        {"reason": ""},
        {"variant": "nonexistent"},
        {"pipeline": "nonexistent"},
        {"typo": "ignored?"},
    ],
)
def test_invalid_or_unactionable_pipeline_decisions_fail_early(
    tmp_path: Path, changes: dict[str, str]
) -> None:
    path = _policy(tmp_path, pipeline_overrides=[_decision(**changes)])
    with pytest.raises(ValueError, match=r"pipeline|override"):
        load_policy(path)


@pytest.mark.parametrize(
    "features",
    [
        TextureFeatures("ART.BMP", kind=TextureKind.DATA),
        TextureFeatures("ART.BMP", kind=TextureKind.ALPHA),
        TextureFeatures("ART.BMP", font_atlas=True),
        TextureFeatures("ART.BMP", native_size=True),
        TextureFeatures("ART.BMP", alphatest=True),
    ],
)
def test_explicit_choice_cannot_bypass_semantics(features: TextureFeatures) -> None:
    decision = PipelineOverride("resample", "color", "final", "Test.")
    with pytest.raises(ValueError, match="incompatible"):
        plan_texture(replace(features, pipeline_override=decision))


def test_override_can_enlarge_generic_retained_color_without_faking_features() -> None:
    feature = TextureFeatures("ART.BMP", exact_raster=True)
    assert plan_texture(feature).kind.keeps_native_size
    feature = replace(
        feature,
        pipeline_override=PipelineOverride("ai", "color", "final", "Reviewed smooth artwork."),
    )
    assert feature.exact_raster  # Analysis fact stays visible; explicit decision wins.
    assert plan_texture(feature).kind is PipelineKind.COLOR_AI


@pytest.mark.parametrize("section", ["feature_overrides", "pipeline_overrides"])
@pytest.mark.parametrize("condition", [{"size": [2, 2]}, {"color_key": 1}, {"color_key": None}])
def test_invalid_conditions_are_rejected(
    tmp_path: Path, section: str, condition: dict[str, object]
) -> None:
    rule = (
        {"textures": ["ART.BMP"], "set": {"tiled": True}, "reason": "Test."}
        if section == "feature_overrides"
        else _decision()
    )
    rule["when"] = condition
    path = _policy(
        tmp_path,
        **{section: [rule]},
    )
    with pytest.raises((TypeError, ValueError), match="policy"):
        load_policy(path)


@pytest.mark.parametrize(
    "names", [[], ["X.PNG"], ["../X.BMP"], ["dir\\X.BMP"], ["C:X.BMP"], ["X.BMP", "x.bmp"]]
)
def test_texture_names_are_portable_and_unique(tmp_path: Path, names: list[str]) -> None:
    path = _policy(
        tmp_path, feature_overrides=[{"textures": names, "set": {"tiled": True}, "reason": "Test."}]
    )
    with pytest.raises(ValueError, match=r"textures|duplicate"):
        load_policy(path)


def test_group_matching_and_overlap_detection(tmp_path: Path) -> None:
    rule = {
        "textures": ["ART.BMP", "OTHER.BMP"],
        "set": {"tiled": True},
        "reason": "Test.",
    }
    path = _policy(tmp_path, feature_overrides=[rule])
    policy = load_policy(path)
    feature = TextureFeatures("ART.BMP")
    source = tmp_path / feature.name
    _write_bmp24(source)
    info = inspect_bmp(source)
    assert policy.apply(feature, info).tiled
    assert policy.apply(replace(feature, name="other.bmp"), info).tiled
    assert not policy.apply(replace(feature, name="UNLISTED.BMP"), info).tiled
    assert policy.apply(feature, replace(info, width=99)).tiled
    path = _policy(tmp_path, feature_overrides=[rule, rule])
    with pytest.raises(ValueError, match="overlapping feature"):
        load_policy(path).apply(feature, info)
    path = _policy(tmp_path, pipeline_overrides=[_decision(), _decision()])
    with pytest.raises(ValueError, match="overlapping pipeline"):
        load_policy(path).apply(feature, info)


def test_legacy_and_unknown_fields_are_not_silently_ignored(tmp_path: Path) -> None:
    path = _policy(tmp_path, textures=[])
    with pytest.raises(ValueError, match="unsupported"):
        load_policy(path)
    path = _policy(tmp_path, schema_version=7)
    with pytest.raises(ValueError, match="schema_version"):
        load_policy(path)
    path = _policy(
        tmp_path,
        feature_overrides=[
            {"textures": ["ART.BMP"], "set": {"smooth_color": True}, "reason": "Not a feature."}
        ],
    )
    with pytest.raises(ValueError, match="supported texture features"):
        load_policy(path)


def test_packaged_todos_cover_unresolved_and_partial_font_work() -> None:
    policy = load_policy()
    decisions = {
        name: rule.decision
        for rule in policy.pipeline_rules
        for name in rule.names
        if rule.decision is not None
    }
    assert decisions["CANDLE.BMP"].status == "final"
    for name in ("F_GPS_L.BMP", "F_TIMES_B_I_12A.BMP", "F_CAPTION_GOUDY18.BMP", "F_TOOLTIP.BMP"):
        assert decisions[name].status == "todo"
        assert decisions[name].todo


def test_analysis_heuristics_do_not_embed_named_texture_exceptions() -> None:
    tree = ast.parse(inspect.getsource(classify))
    names = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.upper().endswith(".BMP")
        and node.value != ".BMP"
    ]
    assert not names


def test_pipeline_override_can_select_an_available_resource_recipe() -> None:
    feature = TextureFeatures("C_FPBRUSH.BMP", exact_raster=True)
    choice = PipelineOverride("reconstruct", "ui-artwork", "final", "Verified frame layout.")
    assert (
        plan_texture(replace(feature, pipeline_override=choice)).kind is PipelineKind.UI_SOURCE_4X
    )
    with pytest.raises(ValueError, match="incompatible"):
        plan_texture(replace(feature, name="UNSUPPORTED.BMP", pipeline_override=choice))


def test_disjoint_feature_groups_validate_together_and_ignore_group_order(tmp_path: Path) -> None:
    groups = [
        {"textures": ["ART.BMP"], "set": {"kind": "alpha"}, "reason": "Scalar semantics."},
        {"textures": ["ART.BMP"], "set": {"alphatest": False}, "reason": "Not a binary color key."},
    ]
    feature = TextureFeatures("ART.BMP", alphatest=True)
    source = tmp_path / feature.name
    _write_bmp24(source, top_left=(255, 0, 255))
    info = inspect_bmp(source)
    first = load_policy(_policy(tmp_path, feature_overrides=groups)).apply(feature, info)
    second = load_policy(_policy(tmp_path, feature_overrides=list(reversed(groups)))).apply(
        feature, info
    )
    assert first == second
    assert first.kind is TextureKind.ALPHA
    assert not first.alphatest
