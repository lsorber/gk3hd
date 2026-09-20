"""Complete preflight, in-memory application, and postcondition execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, TypeVar

from gk3hd.patch.binary.operations import OperationError
from gk3hd.patch.model import AddressSpan, MutableExecutable, PatchOperation

if TYPE_CHECKING:
    from collections.abc import Iterable


class CloneableExecutable(MutableExecutable, Protocol):
    """Mutable executable image that can produce an independent clone."""

    def clone(self) -> Self:
        """Return an independent image with identical bytes."""


ExecutableT = TypeVar("ExecutableT", bound=CloneableExecutable)


class OperationExecutor:
    """Execute a declared operation graph atomically on one private image."""

    def execute(
        self,
        source: ExecutableT,
        operations: Iterable[PatchOperation],
    ) -> ExecutableT:
        """Validate and apply operations in dependency order on a private clone.

        Later operations are allowed to validate generated state exported by
        earlier declared dependencies.  The caller's source is never mutated,
        and the private image is returned only after both immediate and final
        postcondition checks succeed.  This keeps dependency orchestration in
        the executor instead of forcing one patch compiler to install another.
        """
        ordered = tuple(operations)
        self._validate_composition(ordered)
        output = source.clone()
        for operation in ordered:
            operation.validate_source(output)
            operation.apply(output)
            # Fail at the owning operation while its error still has the most
            # precise context.  The final pass below additionally detects a
            # later operation corrupting an earlier operation's output.
            operation.verify(output)
        for operation in ordered:
            operation.verify(output)
        return output

    @staticmethod
    def _validate_composition(operations: tuple[PatchOperation, ...]) -> None:
        fixed: list[tuple[AddressSpan, bytes, str]] = []
        for operation in operations:
            span = operation.span
            payload = operation.payload
            if span is None or payload is None:
                continue
            for other_span, other_payload, other_symbol in fixed:
                if span.overlaps(other_span) and not (
                    span == other_span and payload == other_payload
                ):
                    detail = (
                        f"incompatible writes overlap: {other_symbol!r} and {operation.symbol!r}"
                    )
                    raise OperationError(detail)
            fixed.append((span, payload, operation.symbol))
