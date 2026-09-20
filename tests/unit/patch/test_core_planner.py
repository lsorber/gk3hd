"""Unit tests for deterministic patch planning and registry validation."""

from __future__ import annotations

import pytest

from gk3hd.patch.binary.operations import ReplaceBytes
from gk3hd.patch.model import (
    AddressSpan,
    BuildContext,
    BuildId,
    CompilationContext,
    DisplayMode,
    PatchCompilationError,
    PatchDefinition,
    PatchId,
    PatchProfile,
    ProfileId,
    ResourceClaim,
    ResourceKind,
)
from gk3hd.patch.planner import PatchPlanner, PlanningError

TEST_BUILD = BuildId("test")


def test_build_context_requires_an_executable_identity() -> None:
    """Anonymous executable state cannot enter patch planning."""
    with pytest.raises(ValueError, match="requires a build ID"):
        BuildContext(build_id=BuildId(""))


@pytest.mark.parametrize(("width", "height"), [(0, 768), (1024, 0), (-1, 768)])
def test_display_mode_rejects_invalid_dimensions(width: int, height: int) -> None:
    """Invalid external display state cannot enter an installation."""
    with pytest.raises(ValueError, match="dimensions must be positive"):
        DisplayMode(width=width, height=height)


def test_resource_claims_and_address_spans_must_identify_real_ranges() -> None:
    """Empty ownership keys and empty ranges fail at domain construction."""
    with pytest.raises(ValueError, match="key must be nonempty"):
        ResourceClaim(ResourceKind.HOOK, "")
    with pytest.raises(ValueError, match="invalid address span"):
        AddressSpan(4, 4)


def _operations(_context: CompilationContext) -> tuple[()]:
    return ()


def _definition(
    name: str,
    *,
    requires: frozenset[PatchId] = frozenset(),
    conflicts: frozenset[PatchId] = frozenset(),
    ownership: frozenset[ResourceClaim] = frozenset(),
) -> PatchDefinition:
    return PatchDefinition(
        id=PatchId(name),
        name=name.title(),
        description=f"Apply {name}.",
        build_operations=_operations,
        requires=requires,
        conflicts=conflicts,
        supported_builds=frozenset({TEST_BUILD}),
        ownership=ownership,
    )


def test_planner_resolves_dependencies_deterministically() -> None:
    """Dependencies precede dependents regardless of registry insertion order."""
    base = _definition("base")
    dependent = _definition("dependent", requires=frozenset({base.id}))
    planner = PatchPlanner(
        {dependent.id: dependent, base.id: base},
        {
            ProfileId("recommended"): PatchProfile(
                id=ProfileId("recommended"),
                name="Recommended",
                description="Apply all tested fixes.",
                patches=frozenset({dependent.id}),
            )
        },
    )

    plan = planner.plan_profile(
        ProfileId("recommended"),
        BuildContext(build_id=TEST_BUILD),
    )

    assert plan.patch_ids == (base.id, dependent.id)
    assert planner.profile_patch_ids(ProfileId("recommended")) == (base.id, dependent.id)


def test_group_listing_rejects_unknown_profile() -> None:
    planner = PatchPlanner({}, {})
    with pytest.raises(PlanningError, match="unknown profile"):
        planner.profile_patch_ids(ProfileId("missing"))


def test_planner_rejects_conflicting_selection() -> None:
    """A plan cannot contain a declared conflicting pair."""
    left = _definition("left", conflicts=frozenset({PatchId("right")}))
    right = _definition("right")
    planner = PatchPlanner({left.id: left, right.id: right}, {})

    with pytest.raises(PlanningError, match="conflicts"):
        planner.plan_explicit(
            {left.id, right.id},
            BuildContext(build_id=TEST_BUILD),
        )


def test_planner_rejects_duplicate_resource_ownership() -> None:
    """Two selected patches cannot own the same exclusive hook."""
    claim = ResourceClaim(ResourceKind.HOOK, "final_blitter")
    left = _definition("left", ownership=frozenset({claim}))
    right = _definition("right", ownership=frozenset({claim}))
    planner = PatchPlanner({left.id: left, right.id: right}, {})

    with pytest.raises(PlanningError, match="both own"):
        planner.plan_explicit(
            {left.id, right.id},
            BuildContext(build_id=TEST_BUILD),
        )


def test_registry_rejects_versioned_ids() -> None:
    """Historical implementation versions do not belong in public IDs."""
    legacy = _definition("legacy_v1")

    with pytest.raises(PlanningError, match="noncanonical"):
        PatchPlanner({legacy.id: legacy}, {})


def test_registry_rejects_dependency_cycles() -> None:
    """Registry construction rejects cycles before user planning begins."""
    left_id = PatchId("left")
    right_id = PatchId("right")
    left = _definition("left", requires=frozenset({right_id}))
    right = _definition("right", requires=frozenset({left_id}))

    with pytest.raises(PlanningError, match="cycle"):
        PatchPlanner({left.id: left, right.id: right}, {})


def test_compilation_rejects_an_operation_for_a_foreign_owner() -> None:
    """A factory cannot attach mutations to another patch's identity."""
    patch_id = PatchId("owner")
    claim = ResourceClaim(ResourceKind.BYTE_RANGE, "0x00000001:1")

    def foreign(_context: CompilationContext) -> tuple[ReplaceBytes, ...]:
        return (ReplaceBytes(PatchId("foreign"), "foreign.site", 1, b"\0", b"\1"),)

    definition = PatchDefinition(
        id=patch_id,
        name="Own byte",
        description="Own one exact byte.",
        build_operations=foreign,
        supported_builds=frozenset({TEST_BUILD}),
        ownership=frozenset({claim}),
    )
    plan = PatchPlanner({patch_id: definition}, {}).plan_explicit(
        {patch_id},
        BuildContext(build_id=TEST_BUILD),
    )

    with pytest.raises(PatchCompilationError, match="foreign owner"):
        plan.compile_operations()


def test_compilation_rejects_an_undeclared_mutation_claim() -> None:
    """A factory cannot bypass registry ownership and conflict checks."""
    patch_id = PatchId("owner")

    def undeclared(_context: CompilationContext) -> tuple[ReplaceBytes, ...]:
        return (ReplaceBytes(patch_id, "owner.site", 1, b"\0", b"\1"),)

    definition = PatchDefinition(
        id=patch_id,
        name="Attempt undeclared byte",
        description="Attempt one undeclared byte.",
        build_operations=undeclared,
        supported_builds=frozenset({TEST_BUILD}),
    )
    plan = PatchPlanner({patch_id: definition}, {}).plan_explicit(
        {patch_id},
        BuildContext(build_id=TEST_BUILD),
    )

    with pytest.raises(PatchCompilationError, match="undeclared mutation claim"):
        plan.compile_operations()
