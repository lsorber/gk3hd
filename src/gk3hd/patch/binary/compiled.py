"""Adapter for proven complex compilers while their payloads move to typed emission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from gk3hd.patch.model import MutableExecutable, PatchId, PatchOperation, ResourceClaim

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile


class PatchCompiler(Protocol):
    """Current validation/application interface of a complex payload compiler."""

    def precheck(self, image: PEFile, /) -> None:
        """Validate every source signature needed by the compiler."""

    def apply(self, image: PEFile, /) -> None:
        """Compile and install the payload into an in-memory image."""

    def postcheck(self, image: PEFile, /) -> None:
        """Verify every installed payload and redirect."""


@dataclass(frozen=True, slots=True)
class CompiledPayload(PatchOperation):
    """Treat one cohesive generated payload as a self-validating operation."""

    owner: PatchId
    symbol: str
    resource: ResourceClaim
    compiler: PatchCompiler

    @property
    def is_mutation(self) -> bool:
        """A cohesive compiler installs generated code and redirects."""
        return True

    @property
    def claim(self) -> ResourceClaim:
        """Return the compiler's primary injected section or hook claim."""
        return self.resource

    @property
    def span(self) -> None:
        """Generated sections and redirects are validated by the compiler."""
        return None

    @property
    def payload(self) -> None:
        """The payload depends on its assigned section virtual address."""
        return None

    def validate_source(self, image: MutableExecutable) -> None:
        """Run the compiler's complete source-signature validation."""
        self.compiler.precheck(cast("PEFile", image))

    def apply(self, image: MutableExecutable) -> None:
        """Generate and install the cohesive payload in memory."""
        self.compiler.apply(cast("PEFile", image))

    def verify(self, image: MutableExecutable) -> None:
        """Run the compiler's complete installed-state verification."""
        self.compiler.postcheck(cast("PEFile", image))
