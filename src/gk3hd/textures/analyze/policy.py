"""Reviewed feature corrections and explicit final/temporary pipeline choices."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from importlib.resources import files
from typing import TYPE_CHECKING

from gk3hd.textures.model import PipelineOverride
from gk3hd.textures.routing import pipeline_kind, plan_texture

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from gk3hd.textures.bmp import BmpInfo
    from gk3hd.textures.model import TextureFeatures

POLICY_SCHEMA_VERSION = 9
FEATURE_FIELDS = frozenset(
    {
        "kind",
        "tiled",
        "alphatest",
        "exact_raster",
        "font_atlas",
        "native_size",
        "constant_color",
        "alpha_silhouette",
    }
)


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """One group of named exceptions sharing the same correction or decision."""

    names: frozenset[str]
    features: Mapping[str, object]
    decision: PipelineOverride | None = None
    color_key: bool | None = None

    def matches(self, name: str, info: BmpInfo) -> bool:
        """Keep opaque-only artwork corrections away from transparent variants."""
        return name.upper() in self.names and (
            self.color_key is None or self.color_key == info.has_color_key
        )


@dataclass(frozen=True, slots=True)
class TexturePolicy:
    """Ordered corrections followed by independent processing decisions."""

    feature_rules: tuple[PolicyRule, ...]
    pipeline_rules: tuple[PolicyRule, ...]

    @property
    def names(self) -> frozenset[str]:
        """Return the entire explicit inventory for unused-entry reporting."""
        return frozenset(
            n for rule in (*self.feature_rules, *self.pipeline_rules) for n in rule.names
        )

    def apply(self, features: TextureFeatures, info: BmpInfo) -> TextureFeatures:
        """Correct features first, then attach and validate the selected override."""
        corrections: dict[str, object] = {}
        for rule in self.feature_rules:
            if rule.matches(features.name, info):
                if corrections.keys() & rule.features.keys():
                    msg = f"{features.name}: overlapping feature overrides"
                    raise ValueError(msg)
                corrections.update(rule.features)
        features = features.with_overrides(corrections)
        choices = [r.decision for r in self.pipeline_rules if r.matches(features.name, info)]
        if len(choices) > 1:
            msg = f"{features.name}: overlapping pipeline overrides"
            raise ValueError(msg)
        if choices:
            features = replace(features, pipeline_override=choices[0])
        plan_texture(features)
        return features


def load_policy(path: Path | None = None) -> TexturePolicy:
    """Read the packaged policy, or a complete explicit replacement policy."""
    resource = path if path is not None else files("gk3hd").joinpath("assets/texture-policy.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != POLICY_SCHEMA_VERSION:
        msg = f"texture policy requires schema_version {POLICY_SCHEMA_VERSION}"
        raise ValueError(msg)
    if set(payload) - {"schema_version", "feature_overrides", "pipeline_overrides"}:
        msg = "unsupported texture policy field"
        raise ValueError(msg)
    return TexturePolicy(
        _rules(payload.get("feature_overrides", []), pipeline=False),
        _rules(payload.get("pipeline_overrides", []), pipeline=True),
    )


def _rules(entries: object, *, pipeline: bool) -> tuple[PolicyRule, ...]:
    """Validate groups before matching, including entries absent from this game."""
    if not isinstance(entries, list):
        msg = "policy overrides must be arrays"
        raise TypeError(msg)
    return tuple(_rule(entry, pipeline=pipeline) for entry in entries)


def _rule(entry: object, *, pipeline: bool) -> PolicyRule:
    """Decode a single feature correction or pipeline override group."""
    fields = (
        {"textures", "when", "pipeline", "variant", "status", "reason", "todo"}
        if pipeline
        else {"textures", "when", "set", "reason"}
    )
    if not isinstance(entry, dict) or set(entry) - fields:
        msg = "unsupported policy override field"
        raise ValueError(msg)
    names = _names(entry.get("textures"))
    color_key = _color_key_condition(entry.get("when", {}))
    if pipeline:
        decision = PipelineOverride.from_dict(
            {k: v for k, v in entry.items() if k not in {"textures", "when"}}
        )
        pipeline_kind(decision.pipeline, decision.variant)
        return PolicyRule(names, {}, decision, color_key=color_key)
    values = entry.get("set")
    if not isinstance(values, dict) or not values or set(values) - FEATURE_FIELDS:
        msg = "feature override set must contain supported texture features"
        raise ValueError(msg)
    if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
        msg = "feature override requires a reason"
        raise ValueError(msg)
    if any(not isinstance(v, bool) for k, v in values.items() if k != "kind") or (
        "kind" in values
        and (
            not isinstance(values["kind"], str) or values["kind"] not in {"color", "alpha", "data"}
        )
    ):
        msg = "feature overrides require boolean flags or a valid kind"
        raise ValueError(msg)
    return PolicyRule(names, values, color_key=color_key)


def _color_key_condition(value: object) -> bool | None:
    """Decode the one supported distinction between opaque and keyed artwork."""
    if not isinstance(value, dict) or set(value) - {"color_key"}:
        msg = "policy when supports only color_key"
        raise ValueError(msg)
    if "color_key" not in value:
        return None
    color_key = value["color_key"]
    if not isinstance(color_key, bool):
        msg = "policy color_key must be boolean"
        raise TypeError(msg)
    return color_key


def _names(value: object) -> frozenset[str]:
    """Reject duplicates and paths consistently on Windows and Linux."""
    if (
        not isinstance(value, list)
        or not value
        or not all(
            isinstance(n, str) and n.upper().endswith(".BMP") and not any(c in n for c in "/\\:")
            for n in value
        )
    ):
        msg = "textures must be a nonempty array of BMP basenames"
        raise ValueError(msg)
    names = frozenset(n.upper() for n in value)
    if len(names) != len(value):
        msg = "duplicate texture in policy group"
        raise ValueError(msg)
    return names
