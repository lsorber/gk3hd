"""Avoid full-frame transfers when GK3 only checks whether a surface can lock."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, X86Emitter
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile, PatchSite


@dataclass(frozen=True, slots=True)
class SurfaceCheckCompiler:
    """Keep surface checks inexpensive at high resolutions.

    Outcome:
        Checking whether a graphics surface can lock does not require copying
        the whole framebuffer from the GPU.

    Before:
        GK3's readiness helper locks and immediately unlocks the entire surface.
        It tests the result but never reads or writes the returned pixel data.

    After:
        The same helper checks a one-pixel rectangle and unlocks using the
        returned pointer, as required by IDirectDrawSurface's partial-lock ABI.

    Strategy:
        Redirect the two COM calls into immutable bridges. Keep the original
        access flags, surface pointer, descriptor, HRESULT handling, critical
        section and error reporter. Add no renderer-specific API or dependency.

    Boundaries:
        Actual pixel-reading/drawing locks are untouched. The helper still calls
        DirectDraw, including when a surface is busy or lost; it never fakes
        success. Both redirects and their surrounding branches are verified.
    """

    profile: BuildProfile

    id: ClassVar[str] = "speed_up_surface_checks"
    section_name: ClassVar[str] = ".gklock"
    _section_size: ClassVar[int] = 0x60
    _section_characteristics: ClassVar[int] = 0x60000020
    _rect_offset: ClassVar[int] = 0x10
    _lock_offset: ClassVar[int] = 0x20
    _unlock_offset: ClassVar[int] = 0x40

    @property
    def _sites(self) -> tuple[tuple[PatchSite, int], ...]:
        return (
            (self.profile.site("surface_check.lock"), self._lock_offset),
            (self.profile.site("surface_check.unlock"), self._unlock_offset),
        )

    def _build_payload(self, *, section_va: int) -> bytes:
        lock_site, unlock_site = (site for site, _ in self._sites)
        lock = X86Emitter(base_va=section_va + self._lock_offset)
        lock.raw(b"\x68" + struct.pack("<I", section_va + self._rect_offset))
        lock.raw(b"\x50\xff\x52\x64")  # push eax; call [edx+64h] (Lock)
        lock.jump_absolute(lock_site.va + len(lock_site.original))

        unlock = X86Emitter(base_va=section_va + self._unlock_offset)
        # The caller's DDSURFACEDESC is at EBP-7Ch; its lpSurface field is at
        # offset 24h on x86. Surface1 Unlock takes that pointer, not a RECT.
        unlock.raw(b"\xff\x75\xa8\x56\xff\x92\x80\x00\x00\x00")
        unlock.jump_absolute(unlock_site.va + len(unlock_site.original))

        payload = SegmentPayloadBuilder(
            owner=self.id, segment=self.section_name, size=self._section_size
        )
        payload.place(label="identity", offset=0, payload=b"GK3LOCK1")
        payload.place(
            label="probe rectangle",
            offset=self._rect_offset,
            payload=struct.pack("<4i", 0, 0, 1, 1),
        )
        payload.place(
            label="lock bridge", offset=self._lock_offset, payload=lock.build(maximum_size=0x20)
        )
        payload.place(
            label="unlock bridge",
            offset=self._unlock_offset,
            payload=unlock.build(maximum_size=0x20),
        )
        return payload.build()

    def _mutation_plan(self, *, section_va: int) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner=self.id)
        for site, offset in self._sites:
            plan.branch(
                label=site.symbol,
                opcode=BranchOpcode.JUMP,
                site_va=site.va,
                expected=site.original,
                target_va=section_va + offset,
                size=len(site.original),
            )
        return plan

    def _check_sites(self, image: PEFile, *, installed: bool) -> None:
        for site, _ in self._sites:
            anchors = (
                (site.va - len(site.context_before), site.context_before),
                (site.va + len(site.original), site.context_after),
            )
            if not installed:
                anchors += ((site.va, site.original),)
            for va, expected in anchors:
                if image.read_bytes(image.va_to_offset(va), len(expected)) != expected:
                    message = f"{self.id} source/context mismatch at {site.symbol}"
                    raise PatchError(message)

    def precheck(self, image: PEFile) -> None:
        """Require pristine source calls and their immutable semantic context."""
        if image.get_section(self.section_name) is not None:
            message = f"{self.id} requires a pristine executable"
            raise PatchError(message)
        self._check_sites(image, installed=False)

    def apply(self, image: PEFile) -> None:
        """Install the paired lock/unlock bridges in an immutable code section."""
        self.precheck(image)
        section = image.add_section(
            self.section_name, bytes(self._section_size), self._section_characteristics
        )
        section_va = image.rva_to_va(section.virtual_address)
        image.write_bytes(section.pointer_to_raw_data, self._build_payload(section_va=section_va))
        self._mutation_plan(section_va=section_va).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify both hooks, both bridges, their RECT and the unchanged context."""
        section = image.get_section(self.section_name)
        if section is None or section.size_of_raw_data < self._section_size:
            message = f"{self.id} postcheck failed: missing or truncated section"
            raise PatchError(message)
        if section.characteristics != self._section_characteristics:
            message = f"{self.id} postcheck failed: expected read-only executable section"
            raise PatchError(message)
        section_va = image.rva_to_va(section.virtual_address)
        if image.read_bytes(section.pointer_to_raw_data, self._section_size) != self._build_payload(
            section_va=section_va
        ):
            message = f"{self.id} postcheck failed: payload mismatch"
            raise PatchError(message)
        self._check_sites(image, installed=True)
        self._mutation_plan(section_va=section_va).verify(image)
