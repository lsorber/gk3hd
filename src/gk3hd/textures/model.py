"""Typed texture feature manifest model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


# The revision also invalidates cached analysis when packaged routing changes.
TEXTURE_MANIFEST_SCHEMA_VERSION = 166


class TextureKind(StrEnum):
    """Meaning of a texture's pixel values."""

    COLOR = "color"
    ALPHA = "alpha"
    DATA = "data"


@dataclass(frozen=True, slots=True)
class TextureFeatures:
    """Analyzed facts plus a separately recorded explicit processing decision."""

    name: str
    kind: TextureKind = TextureKind.COLOR
    tiled: bool = False
    alphatest: bool = False
    exact_raster: bool = False
    font_atlas: bool = False
    native_size: bool = False
    constant_color: bool = False
    alpha_silhouette: bool = False
    pipeline_override: PipelineOverride | None = None

    def __post_init__(self) -> None:
        """Reject combinations that have no defined pipeline meaning."""
        if self.alpha_silhouette and self.kind is not TextureKind.ALPHA:
            msg = f"{self.name}: alpha_silhouette requires scalar opacity"
            raise ValueError(msg)
        if self.kind is not TextureKind.COLOR and self.alphatest:
            msg = f"{self.name}: alphatest is valid only for color textures"
            raise ValueError(msg)
        if self.kind is not TextureKind.COLOR and self.exact_raster:
            msg = f"{self.name}: exact_raster is valid only for color textures"
            raise ValueError(msg)
        if self.kind is TextureKind.DATA and self.font_atlas:
            msg = f"{self.name}: font_atlas is invalid for data textures"
            raise ValueError(msg)
        if self.exact_raster and self.font_atlas:
            msg = f"{self.name}: exact_raster and font_atlas are mutually exclusive"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, object]:
        """Return an explicit, stable JSON representation."""
        result: dict[str, object] = {
            "name": self.name,
            "kind": self.kind.value,
            "tiled": self.tiled,
            "alphatest": self.alphatest,
            "exact_raster": self.exact_raster,
            "font_atlas": self.font_atlas,
            "native_size": self.native_size,
            "constant_color": self.constant_color,
            "alpha_silhouette": self.alpha_silhouette,
        }
        if self.pipeline_override is not None:
            result["pipeline_override"] = self.pipeline_override.to_dict()
        return result

    def with_overrides(self, values: Mapping[str, object]) -> TextureFeatures:
        """Return a validated copy with explicitly supplied feature overrides."""
        kind_value = values.get("kind", self.kind)
        try:
            kind = kind_value if isinstance(kind_value, TextureKind) else TextureKind(kind_value)
        except (TypeError, ValueError) as exc:
            msg = f"{self.name}: invalid kind {kind_value!r}"
            raise ValueError(msg) from exc
        return TextureFeatures(
            name=self.name,
            kind=kind,
            tiled=_bool_override(values, "tiled", default=self.tiled, name=self.name),
            alphatest=_bool_override(values, "alphatest", default=self.alphatest, name=self.name),
            exact_raster=_bool_override(
                values,
                "exact_raster",
                default=self.exact_raster,
                name=self.name,
            ),
            font_atlas=_bool_override(
                values,
                "font_atlas",
                default=self.font_atlas,
                name=self.name,
            ),
            native_size=_bool_override(
                values,
                "native_size",
                default=self.native_size,
                name=self.name,
            ),
            constant_color=_bool_override(
                values, "constant_color", default=self.constant_color, name=self.name
            ),
            alpha_silhouette=_bool_override(
                values, "alpha_silhouette", default=self.alpha_silhouette, name=self.name
            ),
            pipeline_override=self.pipeline_override,
        )


def _bool_override(
    values: Mapping[str, object],
    key: str,
    *,
    default: bool,
    name: str,
) -> bool:
    """Read one strict boolean override instead of accepting truthy values."""
    value = values.get(key, default)
    if not isinstance(value, bool):
        msg = f"{name}: {key} must be true or false"
        raise TypeError(msg)
    return value


@dataclass(frozen=True, slots=True)
class TextureManifest:
    """Versioned collection of texture features."""

    textures: tuple[TextureFeatures, ...]
    schema_version: int = TEXTURE_MANIFEST_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        """Return the complete JSON-compatible manifest payload."""
        return {
            "schema_version": self.schema_version,
            "texture_count": len(self.textures),
            "textures": [texture.to_dict() for texture in self.textures],
        }


@dataclass(frozen=True, slots=True)
class PipelineOverride:
    """A justified current route, optionally recording unfinished improvement work."""

    pipeline: str
    variant: str
    status: str
    reason: str
    todo: str | None = None

    def __post_init__(self) -> None:
        """Require an explanation and actionable work for temporary decisions."""
        if self.status not in {"final", "todo"}:
            msg = "pipeline override status must be final or todo"
            raise ValueError(msg)
        if not all(
            isinstance(v, str) and v.strip() for v in (self.pipeline, self.variant, self.reason)
        ):
            msg = "pipeline override requires pipeline, variant and reason"
            raise ValueError(msg)
        if self.status == "todo" and not (isinstance(self.todo, str) and self.todo.strip()):
            msg = "temporary pipeline override requires an actionable todo"
            raise ValueError(msg)
        if self.status == "final" and self.todo is not None:
            msg = "final pipeline override must not contain a todo"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, str]:
        """Serialize status and rationale without mixing them into feature flags."""
        result = {
            "pipeline": self.pipeline,
            "variant": self.variant,
            "status": self.status,
            "reason": self.reason,
        }
        if self.todo is not None:
            result["todo"] = self.todo
        return result

    @classmethod
    def from_dict(cls, value: object) -> PipelineOverride:
        """Reject misspelled fields and ill-typed decisions in policy or analysis."""
        if not isinstance(value, dict) or set(value) - {
            "pipeline",
            "variant",
            "status",
            "reason",
            "todo",
        }:
            msg = "invalid pipeline override fields"
            raise ValueError(msg)
        if not {"pipeline", "variant", "status", "reason"} <= set(value) or not all(
            isinstance(v, str) for v in value.values()
        ):
            msg = "pipeline override requires string pipeline, variant, status and reason"
            raise ValueError(msg)
        return cls(
            value["pipeline"], value["variant"], value["status"], value["reason"], value.get("todo")
        )
