"""Contract tests for declarative engine-patch definitions."""

from __future__ import annotations

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.operations import AssertBytes, ReplaceBytes
from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.engine import ENGINE_PATCHES
from gk3hd.patch.model import BuildContext, CompilationContext, PatchId
from tests.unit.patch.test_binary_operations import FakeExecutable

TEST_IMAGE_SIZE = 0x00710000


def _compilation_context(build: BuildContext, patch_id: PatchId) -> CompilationContext:
    """Wrap one isolated engine patch in the same context used by a real plan."""
    return CompilationContext(build=build, selected_patches=frozenset({patch_id}))


def _source_for(patch_id: PatchId) -> FakeExecutable:
    """Build an identity-addressed source containing one definition's exact sites."""
    source = FakeExecutable(bytearray(TEST_IMAGE_SIZE))
    build = BuildContext(build_id=GOG_BUILD.id)
    context = _compilation_context(build, patch_id)
    for operation in ENGINE_PATCHES[patch_id].build_operations(context):
        if isinstance(operation, (AssertBytes, ReplaceBytes)):
            source.write_bytes(operation.va, operation.expected)
    return source


def test_engine_definitions_have_canonical_ids_and_stable_ownership() -> None:
    """Generated claims agree across the two supported hash-bound profiles."""
    for definition in ENGINE_PATCHES.values():
        assert not definition.id.endswith(("_v1", "_v2", "_v3"))
        for build_id in definition.supported_builds:
            context = BuildContext(build_id=build_id)
            generated = frozenset(
                operation.claim
                for operation in definition.build_operations(
                    _compilation_context(context, definition.id)
                )
                if operation.payload is not None
            )
            assert generated == definition.ownership


def test_each_engine_definition_executes_from_pristine_sites() -> None:
    """Every operation set preflights, applies, and postchecks as one memory image."""
    context = BuildContext(build_id=GOG_BUILD.id)
    for patch_id, definition in ENGINE_PATCHES.items():
        source = _source_for(patch_id)
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
