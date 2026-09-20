"""Dependency, conflict, build-support, and ownership planning."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gk3hd.patch.model import (
    BuildContext,
    PatchDefinition,
    PatchId,
    PatchPlan,
    PatchProfile,
    PatchRegistry,
    ProfileId,
    ProfileRegistry,
    ResourceClaim,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


class PlanningError(Exception):
    """Report an invalid registry or an unresolvable user selection."""

    @classmethod
    def invalid(cls, detail: str) -> PlanningError:
        """Build an error for invalid registry metadata."""
        return cls(f"invalid patch registry: {detail}")

    @classmethod
    def selection(cls, detail: str) -> PlanningError:
        """Build an error for an invalid requested selection."""
        return cls(f"cannot build patch plan: {detail}")


class PatchPlanner:
    """Validate one registry and resolve deterministic patch plans from it."""

    def __init__(self, patches: PatchRegistry, profiles: ProfileRegistry) -> None:
        """Validate and retain immutable copies of both registries."""
        self._patches = dict(patches)
        self._profiles = dict(profiles)
        self._validate_registry()

    @property
    def patches(self) -> tuple[PatchDefinition, ...]:
        """Return definitions in canonical ID order for user-facing listing."""
        return tuple(self._patches[key] for key in sorted(self._patches))

    @property
    def profiles(self) -> tuple[PatchProfile, ...]:
        """Return the recommended profile first, followed by canonical ID order."""
        keys = sorted(self._profiles, key=lambda key: (key != "recommended", key))
        return tuple(self._profiles[key] for key in keys)

    def plan_profile(self, profile_id: ProfileId, build: BuildContext) -> PatchPlan:
        """Resolve one named profile and all of its transitive dependencies."""
        profile = self._profiles.get(profile_id)
        if profile is None:
            detail = f"unknown profile {profile_id!r}"
            raise PlanningError.selection(detail)
        return self._plan(profile.patches, build=build, profile=profile.id)

    def plan_explicit(self, requested: Iterable[PatchId], build: BuildContext) -> PatchPlan:
        """Resolve an explicit minimal selection and its dependencies."""
        return self._plan(frozenset(requested), build=build, profile=None)

    def profile_patch_ids(self, profile_id: ProfileId) -> tuple[PatchId, ...]:
        """List a group's complete selection, including dependencies, without a game."""
        profile = self._profiles.get(profile_id)
        if profile is None:
            detail = f"unknown profile {profile_id!r}"
            raise PlanningError.selection(detail)
        return tuple(sorted(self._resolve_dependencies(profile.patches)))

    def _plan(
        self,
        requested: frozenset[PatchId],
        *,
        build: BuildContext,
        profile: ProfileId | None,
    ) -> PatchPlan:
        selected = self._resolve_dependencies(requested)

        for patch_id in sorted(selected):
            definition = self._patches[patch_id]
            if definition.supported_builds and build.build_id not in definition.supported_builds:
                detail = f"patch {patch_id!r} does not support build {build.build_id!r}"
                raise PlanningError.selection(detail)
            active_conflicts = definition.conflicts & selected
            if active_conflicts:
                conflicts = ", ".join(sorted(active_conflicts))
                detail = f"patch {patch_id!r} conflicts with {conflicts}"
                raise PlanningError.selection(detail)

        ordered = self._topological_order(selected)
        self._validate_selected_ownership(ordered)
        return PatchPlan(
            build=build,
            profile=profile,
            definitions=tuple(self._patches[patch_id] for patch_id in ordered),
        )

    def _resolve_dependencies(self, requested: frozenset[PatchId]) -> set[PatchId]:
        """Share dependency expansion between group listings and actual installs."""
        selected: set[PatchId] = set()

        def select(patch_id: PatchId) -> None:
            definition = self._patches.get(patch_id)
            if definition is None:
                detail = f"unknown patch {patch_id!r}"
                raise PlanningError.selection(detail)
            if patch_id in selected:
                return
            selected.add(patch_id)
            for dependency in sorted(definition.requires):
                select(dependency)

        for patch_id in sorted(requested):
            select(patch_id)
        return selected

    def _topological_order(self, selected: set[PatchId]) -> tuple[PatchId, ...]:
        visiting: set[PatchId] = set()
        visited: set[PatchId] = set()
        ordered: list[PatchId] = []

        def visit(patch_id: PatchId) -> None:
            if patch_id in visited:
                return
            if patch_id in visiting:
                detail = f"dependency cycle includes {patch_id!r}"
                raise PlanningError.invalid(detail)
            visiting.add(patch_id)
            for dependency in sorted(self._patches[patch_id].requires):
                if dependency in selected:
                    visit(dependency)
            visiting.remove(patch_id)
            visited.add(patch_id)
            ordered.append(patch_id)

        for patch_id in sorted(selected):
            visit(patch_id)
        return tuple(ordered)

    def _validate_selected_ownership(self, ordered: tuple[PatchId, ...]) -> None:
        owners: dict[ResourceClaim, PatchId] = {}
        for patch_id in ordered:
            for claim in self._patches[patch_id].ownership:
                existing = owners.get(claim)
                if existing is not None and existing != patch_id:
                    detail = (
                        f"patches {existing!r} and {patch_id!r} both own {claim.kind}:{claim.key}"
                    )
                    raise PlanningError.selection(detail)
                owners[claim] = patch_id

    def _validate_registry(self) -> None:
        for key, definition in self._patches.items():
            self._validate_definition(key, definition)

        self._topological_order(set(self._patches))

        for key, profile in self._profiles.items():
            self._validate_profile(key, profile)

    def _validate_definition(self, key: PatchId, definition: PatchDefinition) -> None:
        """Validate one patch's identity, documentation, and relationships."""
        if key != definition.id:
            detail = f"key {key!r} does not match definition {definition.id!r}"
            raise PlanningError.invalid(detail)
        if not key or key.endswith(("_v1", "_v2", "_v3")):
            detail = f"noncanonical patch ID {key!r}"
            raise PlanningError.invalid(detail)
        if not definition.name:
            detail = f"patch {key!r} needs a display name"
            raise PlanningError.invalid(detail)
        if not definition.description or not definition.description.endswith("."):
            detail = f"patch {key!r} needs a sentence description"
            raise PlanningError.invalid(detail)
        unknown = (definition.requires | definition.conflicts) - self._patches.keys()
        if unknown:
            names = ", ".join(sorted(unknown))
            detail = f"patch {key!r} refers to unknown patches: {names}"
            raise PlanningError.invalid(detail)

    def _validate_profile(self, key: ProfileId, profile: PatchProfile) -> None:
        """Validate one profile's identity, documentation, and patch references."""
        if key != profile.id:
            detail = f"profile key {key!r} does not match {profile.id!r}"
            raise PlanningError.invalid(detail)
        if not profile.name:
            detail = f"profile {key!r} needs a display name"
            raise PlanningError.invalid(detail)
        if not profile.description or not profile.description.endswith("."):
            detail = f"profile {key!r} needs a sentence description"
            raise PlanningError.invalid(detail)
        unknown = profile.patches - self._patches.keys()
        if unknown:
            names = ", ".join(sorted(unknown))
            detail = f"profile {key!r} refers to unknown patches: {names}"
            raise PlanningError.invalid(detail)
