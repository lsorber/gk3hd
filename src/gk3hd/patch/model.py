"""Immutable domain models shared by the patch registry and planner."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NewType, Protocol

BuildId = NewType("BuildId", str)
PatchId = NewType("PatchId", str)
ProfileId = NewType("ProfileId", str)


class ResourceKind(StrEnum):
    """Kinds of executable resources that require exclusive ownership."""

    BYTE_RANGE = "byte_range"
    HOOK = "hook"
    FEATURE_POLICY = "feature_policy"
    SECTION = "section"


@dataclass(frozen=True, slots=True, order=True)
class ResourceClaim:
    """One exclusive logical mutation surface claimed by a patch."""

    kind: ResourceKind
    key: str

    def __post_init__(self) -> None:
        """Reject ownership claims that cannot identify a resource."""
        if not self.key:
            message = "resource claim key must be nonempty"
            raise ValueError(message)


@dataclass(frozen=True, slots=True, order=True)
class AddressSpan:
    """One fixed half-open virtual-address range."""

    start: int
    end: int

    def __post_init__(self) -> None:
        """Require one nonempty, nonnegative half-open range."""
        if self.start < 0 or self.end <= self.start:
            message = f"invalid address span [{self.start}, {self.end})"
            raise ValueError(message)

    def overlaps(self, other: AddressSpan) -> bool:
        """Return whether two address ranges overlap."""
        return self.start < other.end and other.start < self.end


class MutableExecutable(Protocol):
    """Executable-image behavior required by patch operations."""

    def va_to_offset(self, va: int) -> int:
        """Translate one virtual address to its file offset."""

    def read_bytes(self, offset: int, size: int) -> bytes:
        """Read an exact byte range from the image."""

    def write_bytes(self, offset: int, payload: bytes) -> None:
        """Overwrite an exact byte range in the image."""


class PatchOperation(ABC):
    """Self-validating executable mutation compiled by a patch definition."""

    owner: PatchId
    symbol: str

    @property
    @abstractmethod
    def is_mutation(self) -> bool:
        """Return whether the operation changes executable state."""

    @property
    @abstractmethod
    def claim(self) -> ResourceClaim:
        """Return the mutation surface owned by this operation."""

    @property
    @abstractmethod
    def span(self) -> AddressSpan | None:
        """Return a fixed address range, or none for a new section/assertion."""

    @property
    @abstractmethod
    def payload(self) -> bytes | None:
        """Return fixed replacement bytes when overlap comparison is possible."""

    @abstractmethod
    def validate_source(self, image: MutableExecutable) -> None:
        """Validate the pristine input without mutating it."""

    @abstractmethod
    def apply(self, image: MutableExecutable) -> None:
        """Apply the mutation to an in-memory image."""

    @abstractmethod
    def verify(self, image: MutableExecutable) -> None:
        """Verify the operation's complete installed postcondition."""


@dataclass(frozen=True, slots=True)
class BuildContext:
    """Recognized executable-build identity available during compilation."""

    build_id: BuildId

    def __post_init__(self) -> None:
        """Require a named executable build."""
        if not self.build_id:
            message = "build context requires a build ID"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class DisplayMode:
    """Validated external display configuration for one installation."""

    width: int
    height: int

    def __post_init__(self) -> None:
        """Require usable positive display dimensions."""
        if self.width <= 0 or self.height <= 0:
            message = f"display mode dimensions must be positive, got {self.width}x{self.height}"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CompilationContext:
    """Build inputs and complete immutable patch selection for compilation."""

    build: BuildContext
    selected_patches: frozenset[PatchId]


type OperationFactory = Callable[[CompilationContext], tuple[PatchOperation, ...]]


@dataclass(frozen=True, slots=True)
class PatchDefinition:
    """Authoritative identity, relationships, ownership, and implementation."""

    id: PatchId
    name: str
    description: str
    build_operations: OperationFactory
    requires: frozenset[PatchId] = field(default_factory=frozenset)
    conflicts: frozenset[PatchId] = field(default_factory=frozenset)
    supported_builds: frozenset[BuildId] = field(default_factory=frozenset)
    ownership: frozenset[ResourceClaim] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class PatchProfile:
    """A named, immutable user-facing patch selection."""

    id: ProfileId
    name: str
    description: str
    patches: frozenset[PatchId]


@dataclass(frozen=True, slots=True)
class PatchPlan:
    """A deterministic dependency-ordered plan for one executable build."""

    build: BuildContext
    profile: ProfileId | None
    definitions: tuple[PatchDefinition, ...]

    @property
    def patch_ids(self) -> tuple[PatchId, ...]:
        """Return canonical patch IDs in execution order."""
        return tuple(definition.id for definition in self.definitions)

    def compile_operations(self) -> tuple[PatchOperation, ...]:
        """Compile operations and bind every mutation to declared ownership."""
        context = CompilationContext(
            build=self.build,
            selected_patches=frozenset(self.patch_ids),
        )
        operations: list[PatchOperation] = []
        for definition in self.definitions:
            for operation in definition.build_operations(context):
                if operation.owner != definition.id:
                    detail = (
                        f"patch {definition.id!r} emitted operation {operation.symbol!r} "
                        f"for foreign owner {operation.owner!r}"
                    )
                    raise PatchCompilationError(detail)
                if operation.is_mutation and operation.claim not in definition.ownership:
                    detail = (
                        f"patch {definition.id!r} emitted undeclared mutation claim "
                        f"{operation.claim.kind}:{operation.claim.key}"
                    )
                    raise PatchCompilationError(detail)
                operations.append(operation)
        return tuple(operations)


class PatchCompilationError(Exception):
    """Report operations that violate their definition's compiled contract."""


type PatchRegistry = Mapping[PatchId, PatchDefinition]
type ProfileRegistry = Mapping[ProfileId, PatchProfile]


class PatchError(Exception):
    """Report a failed reverse-engineered signature or payload postcondition."""
