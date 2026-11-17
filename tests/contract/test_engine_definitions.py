"""Contract tests for engine-patch definitions."""

from __future__ import annotations

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.operations import AssertBytes
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.engine import ENGINE_PATCHES
from gk3hd.patch.model import BuildContext, CompilationContext, PatchId
from tests.unit.patch.test_complete_compilation import _source


def _compilation_context(build: BuildContext, patch_id: PatchId) -> CompilationContext:
    """Wrap one isolated engine patch in the same context used by a real plan."""
    return CompilationContext(build=build, selected_patches=frozenset({patch_id}))


def test_engine_definitions_have_canonical_ids_and_stable_ownership() -> None:
    """Generated mutation claims agree across all supported builds."""
    for definition in ENGINE_PATCHES.values():
        assert not definition.id.endswith(("_v1", "_v2", "_v3"))
        for build_id in definition.supported_builds:
            context = BuildContext(build_id=build_id)
            generated = frozenset(
                operation.claim
                for operation in definition.build_operations(
                    _compilation_context(context, definition.id)
                )
                if operation.is_mutation
            )
            assert generated == definition.ownership


def test_each_engine_definition_executes_from_pristine_sites() -> None:
    """Every operation set preflights, applies, and postchecks as one memory image."""
    context = BuildContext(build_id=GOG_BUILD.id)
    for patch_id, definition in ENGINE_PATCHES.items():
        source = _source(GOG_BUILD)
        output = OperationExecutor().execute(
            source,
            definition.build_operations(_compilation_context(context, patch_id)),
        )
        assert output.data != source.data


def test_modern_modes_preserve_safe_missing_configuration_fallback() -> None:
    """Mode exposure must not assume that an arbitrary display supports 1080p."""
    patch_id = PatchId("enable_modern_resolutions")
    context = BuildContext(build_id=GOG_BUILD.id)
    operations = ENGINE_PATCHES[patch_id].build_operations(_compilation_context(context, patch_id))
    fallback = next(
        operation for operation in operations if operation.symbol == "resolution.fallback"
    )
    assert isinstance(fallback, AssertBytes)
