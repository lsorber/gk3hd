"""Retry the legacy depth-surface allocation when display-adapter VRAM is exhausted."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.operations import ReplaceBytes
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, encode_rel32_branch
from gk3hd.patch.model import PatchError, PatchId

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import PatchSite


@dataclass(frozen=True, slots=True)
class DepthSurfaceCompiler:
    """Keep the normal hardware path and retry only GK3's legacy depth allocation."""

    site: PatchSite
    section_name: ClassVar[str] = ".gkdepth"
    _characteristics: ClassVar[int] = 0x60000020

    @staticmethod
    def _payload() -> bytes:
        code = X86Emitter(base_va=0)
        # EAX=this, EDX=desc. The native caller already pushed output and outer.
        code.raw(bytes.fromhex("56 57 89 c6 89 d7"))  # Save ESI/EDI and the volatile arguments.
        code.call("create")
        code.raw(bytes.fromhex("3d 7c 01 76 88"))  # DDERR_OUTOFVIDEOMEMORY
        code.jump_short_if(Condition.NOT_EQUAL, "done")
        # DDSURFACEDESC.ddsCaps at +68h; only the exact hardware Z-buffer request
        # may retry. Leave software Z and the software renderer's RGB buffer alone.
        code.raw(bytes.fromhex("81 7f 68 00 40 02 00"))  # ZBUFFER | VIDEOMEMORY
        code.jump_short_if(Condition.NOT_EQUAL, "done")
        code.raw(bytes.fromhex("c7 47 68 00 08 02 00"))  # ZBUFFER | SYSTEMMEMORY
        code.call("create")
        code.raw(bytes.fromhex("c7 47 68 00 40 02 00"))  # Restore the caller's descriptor.
        code.label("done")
        code.raw(bytes.fromhex("5f 5e c2 08 00"))
        code.label("create")
        # The two original stack arguments each sit at +14h when pushed, in
        # stdcall order after the nested return address and saved registers.
        code.raw(bytes.fromhex("ff 74 24 14 ff 74 24 14 57 56 8b 0e ff 51 18"))
        code.ret()
        return code.build()

    def _redirect(self, address: int) -> ReplaceBytes:
        return ReplaceBytes(
            owner=PatchId("enable_modern_resolutions"),
            symbol=self.site.symbol,
            va=self.site.va,
            expected=self.site.original,
            replacement=encode_rel32_branch(
                opcode=BranchOpcode.CALL,
                site_va=self.site.va,
                target_va=address,
                size=len(self.site.original),
            ),
        )

    def precheck(self, image: PEFile) -> None:
        """Validate the native call before allocating its bridge."""
        if image.get_section(self.section_name) is not None:
            msg = "depth surface retry requires a pristine executable"
            raise PatchError(msg)
        offset = image.va_to_offset(self.site.va)
        if image.read_bytes(offset, len(self.site.original)) != self.site.original:
            msg = "depth surface retry does not match the native CreateSurface call"
            raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Install the retry into a read-only executable section."""
        self.precheck(image)
        section = image.add_section(self.section_name, self._payload(), self._characteristics)
        self._redirect(image.rva_to_va(section.virtual_address)).apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify the installed bridge and call."""
        section = image.get_section(self.section_name)
        payload = self._payload()
        if (
            section is None
            or section.characteristics != self._characteristics
            or section.size_of_raw_data < len(payload)
            or image.read_bytes(section.pointer_to_raw_data, len(payload)) != payload
        ):
            msg = "depth surface retry payload is missing or modified"
            raise PatchError(msg)
        self._redirect(image.rva_to_va(section.virtual_address)).verify(image)
