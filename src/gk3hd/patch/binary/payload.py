"""Build bounded injected sections from non-overlapping named regions."""

from __future__ import annotations

from dataclasses import dataclass

from gk3hd.patch.model import PatchError


@dataclass(frozen=True, slots=True)
class PayloadRegion:
    """One named code or state interval inside an injected section."""

    label: str
    offset: int
    payload: bytes

    @property
    def end(self) -> int:
        """Return the exclusive section-relative end."""
        return self.offset + len(self.payload)


class SegmentPayloadBuilder:
    """Compose and validate a complete deterministic injected-section image.

    Outcome:
        Every injected byte has one named owner and the section is written as
        one deterministic image.

    Before:
        Compilers separately checked wrapper limits, zeroed broad ranges, and
        issued ordered writes. A later write could conceal an earlier collision.

    After:
        Code and state regions are declared through one boundary which rejects
        invalid bounds and any overlap before producing the section bytes.

    Strategy:
        Start from an explicitly zero-filled image, claim each nonempty region,
        enforce its optional slot limit and section bounds, then render all
        claims in offset order. Zero-only state is reserved with the same API.

    Boundaries:
        This builder owns injected-section layout only. Existing-executable
        redirects and semantic source-byte checks have separate owners.
    """

    __slots__ = ("_owner", "_regions", "_segment", "_size")

    def __init__(self, *, owner: str, segment: str, size: int) -> None:
        """Create an empty zero-filled section contract."""
        if size <= 0:
            msg = f"{owner} {segment} segment has invalid size {size}"
            raise PatchError(msg)
        self._owner = owner
        self._segment = segment
        self._size = size
        self._regions: list[PayloadRegion] = []

    def place(
        self,
        *,
        label: str,
        offset: int,
        payload: bytes,
        limit: int | None = None,
    ) -> None:
        """Claim and initialize one exact interval."""
        if not payload:
            return
        effective_limit = self._size if limit is None else limit
        end = offset + len(payload)
        if offset < 0 or effective_limit < 0 or effective_limit > self._size:
            msg = (
                f"{self._owner} {self._segment} {label} has invalid bounds "
                f"0x{offset:x}..0x{effective_limit:x}"
            )
            raise PatchError(msg)
        if end > effective_limit:
            msg = (
                f"{self._owner} {self._segment} {label} ends at 0x{end:x}, "
                f"past its 0x{effective_limit:x} limit"
            )
            raise PatchError(msg)
        region = PayloadRegion(label=label, offset=offset, payload=bytes(payload))
        for existing in self._regions:
            if region.offset < existing.end and existing.offset < region.end:
                msg = (
                    f"{self._owner} {self._segment} payload overlap: {label} "
                    f"0x{region.offset:x}..0x{region.end:x} intersects "
                    f"{existing.label} 0x{existing.offset:x}..0x{existing.end:x}"
                )
                raise PatchError(msg)
        self._regions.append(region)

    def reserve(self, *, label: str, offset: int, size: int) -> None:
        """Claim one zero-initialized state interval."""
        if size < 0:
            msg = f"{self._owner} {self._segment} {label} has negative size"
            raise PatchError(msg)
        self.place(label=label, offset=offset, payload=bytes(size))

    def build(self) -> bytes:
        """Render the validated complete section image."""
        image = bytearray(self._size)
        for region in sorted(self._regions, key=lambda item: item.offset):
            image[region.offset : region.end] = region.payload
        return bytes(image)
