"""Preserve visibility for both eyes during a shared world draw."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, decode_rel32_branch
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@dataclass(frozen=True, slots=True, kw_only=True)
class VRVisibilityCompiler:
    """Collect the native visibility union, retaining native recursive calls.

    The renderer passes typed snapshots, not executable addresses. Only the
    shared callback enables the two-eye scope. Ordinary drawing remains one
    native collection. Both normal return and SEH unwind restore the authored
    origin; no world geometry or visibility list persists between frames.
    """

    profile: BuildProfile
    scene: VRSceneABI
    draw_va: int
    context_va: int

    section_name: ClassVar[str] = ".gk3vv"
    section_size: ClassVar[int] = 0x2000
    _magic: ClassVar[bytes] = b"GK3XRV01"
    _code: ClassVar[int] = 0x1000
    _active: ClassVar[int] = 0x10
    _point_active: ClassVar[int] = 0x14
    _left: ClassVar[int] = 0x20
    _right: ClassVar[int] = 0x30
    _saved: ClassVar[int] = 0x40
    _model_device: ClassVar[int] = 0x50
    _model_restore_failed: ClassVar[int] = 0x54
    _model_back_limit: ClassVar[int] = 0x58
    _half: ClassVar[int] = 0x5C
    _plane_slack: ClassVar[int] = 0x60
    _model_hooks: ClassVar[tuple[tuple[str, BranchOpcode], ...]] = (
        ("vr.model_clip_facing", BranchOpcode.JUMP),
        ("vr.model_clip_end", BranchOpcode.CALL),
    )

    @classmethod
    def for_scene(
        cls, image: PEFile, profile: BuildProfile, scene: VRSceneABI
    ) -> VRVisibilityCompiler:
        """Capture the verified descriptor's callback identity before installation."""
        base = scene.recenter_va - 4
        return cls(
            profile=profile,
            scene=scene,
            draw_va=image.read_u32_va(base + 228),
            context_va=image.read_u32_va(base + 232),
        )

    def _check(self, image: PEFile) -> None:
        if VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene:
            msg = "VR visibility scene dependency changed"
            raise PatchError(msg)
        descriptor = self.scene.recenter_va - 4
        if (
            not self.draw_va
            or not self.context_va
            or image.read_u32_va(descriptor + 228) != self.draw_va
            or image.read_u32_va(descriptor + 232) != self.context_va
        ):
            msg = "VR visibility draw dependency changed"
            raise PatchError(msg)
        site = self.profile.site("vr.visibility_collect")
        if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
            msg = "VR visibility collector dependency changed"
            raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Install a dormant collector detour and the explicit shared callback."""
        self._check(image)
        site = self.profile.site("vr.visibility_collect_call")
        model_sites = [(self.profile.site(name), opcode) for name, opcode in self._model_hooks]
        if (
            image.get_section(self.section_name) is not None
            or image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original
            or image.read_u32_va(self.scene.shared_draw_slot_va)
            or any(
                image.read_bytes(image.va_to_offset(model.va), len(model.original))
                != model.original
                for model, _ in model_sites
            )
        ):
            msg = "VR visibility precheck failed or adapter already installed"
            raise PatchError(msg)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        payload, labels = self._payload(image.rva_to_va(section.virtual_address))
        image.write_bytes(section.pointer_to_raw_data, payload)
        plan = ExecutableMutationPlan(owner="vr_visibility")
        plan.branch(
            label="top-level visibility",
            site_va=site.va,
            expected=site.original,
            target_va=labels["collect"],
            opcode=BranchOpcode.CALL,
            size=len(site.original),
        )
        for model, opcode in model_sites:
            plan.branch(
                label=model.symbol,
                site_va=model.va,
                expected=model.original,
                target_va=labels[model.symbol],
                opcode=opcode,
                size=len(model.original),
            )
        plan.replace(
            label="shared draw callback",
            va=self.scene.shared_draw_slot_va,
            expected=bytes(4),
            payload=struct.pack("<I", labels["shared_draw"]),
        )
        plan.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify callback, complete dormant payload and original recursive entry."""
        self._check(image)
        section = image.get_section(self.section_name)
        if section is None:
            msg = "VR visibility adapter is absent"
            raise PatchError(msg)
        expected, labels = self._payload(image.rva_to_va(section.virtual_address))
        site = self.profile.site("vr.visibility_collect_call")
        target = decode_rel32_branch(
            opcode=BranchOpcode.CALL,
            site_va=site.va,
            instruction=image.read_bytes(image.va_to_offset(site.va), 5),
        )
        if (
            target != labels["collect"]
            or image.read_u32_va(self.scene.shared_draw_slot_va) != labels["shared_draw"]
            or image.read_bytes(section.pointer_to_raw_data, self.section_size) != expected
        ):
            msg = "VR visibility adapter failed verification"
            raise PatchError(msg)
        for name, opcode in self._model_hooks:
            model = self.profile.site(name)
            target = decode_rel32_branch(
                opcode=opcode,
                site_va=model.va,
                instruction=image.read_bytes(image.va_to_offset(model.va), 5),
            )
            if target != labels[name]:
                msg = f"VR model visibility hook failed verification: {name}"
                raise PatchError(msg)

    def _payload(self, base: int) -> tuple[bytes, dict[str, int]]:
        e = X86Emitter(base_va=base + self._code)
        origin = self.profile.address("vr.visibility_origin")
        native = self.profile.site("vr.visibility_collect").va

        def absolute(op: bytes, address: int) -> None:
            e.raw(op + struct.pack("<I", address))

        def store(offset: int, value: int) -> None:
            absolute(b"\xc7\x05", base + offset)
            e.raw(struct.pack("<I", value))

        def copy(source: int, destination: int) -> None:
            absolute(b"\xbe", source)
            absolute(b"\xbf", destination)
            e.raw(bytes.fromhex("b9 03 00 00 00 fc f3 a5"))

        e.label("shared_draw")
        e.raw(bytes.fromhex("55 8b ec 53 56 57"))
        absolute(b"\x81\x7d\x08", self.context_va)
        e.jump_if(Condition.NOT_EQUAL, "unavailable")
        for argument in (0x0C, 0x10):
            e.raw(bytes((0x83, 0x7D, argument, 0)))
            e.jump_if(Condition.EQUAL, "unavailable")
        absolute(b"\x83\x3d", base + self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "unavailable")
        e.raw(bytes.fromhex("8b 75 10 83 c6 1c"))
        absolute(b"\xbf", base + self._left)
        e.raw(bytes.fromhex("b9 03 00 00 00 fc f3 a5"))
        e.raw(bytes.fromhex("8b 75 10 81 c6 04 01 00 00"))  # Second 232-byte eye + position.
        absolute(b"\xbf", base + self._right)
        e.raw(bytes.fromhex("b9 03 00 00 00 fc f3 a5"))
        self._emit_eye_radius(e, base)
        e.raw(b"\x68")
        e.absolute_label("unwind")
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
        store(self._model_restore_failed, 0)
        store(self._active, 1)
        e.raw(bytes.fromhex("ff 75 0c 6a 00 ff 75 08"))
        e.call_absolute(self.draw_va)
        e.call("restore")
        e.raw(bytes.fromhex("8b 14 24 64 89 15 00 00 00 00 83 c4 08"))
        absolute(b"\x83\x3d", base + self._model_restore_failed)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "shared_return")
        e.label("unavailable")
        absolute(b"\xb8", 0x80004005)
        e.label("shared_return")
        e.raw(bytes.fromhex("5f 5e 5b c9 c2 0c 00"))

        e.label("collect")
        absolute(b"\x83\x3d", base + self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "native")
        e.raw(bytes.fromhex("55 8b ec 53 56 57 8b d9"))
        copy(origin, base + self._saved)
        store(self._point_active, 1)
        for source in (self._left, self._right):
            copy(base + source, origin)
            e.raw(bytes.fromhex("ff 75 0c ff 75 08 8b cb"))
            e.call_absolute(native)
        copy(base + self._saved, origin)
        store(self._point_active, 0)
        e.raw(bytes.fromhex("5f 5e 5b c9 c2 08 00"))
        e.label("native")
        e.jump_absolute(native)

        e.label("restore")
        e.call("restore_model_cull")
        absolute(b"\x83\x3d", base + self._point_active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "restore_done")
        copy(base + self._saved, origin)
        store(self._point_active, 0)
        e.label("restore_done")
        store(self._active, 0)
        e.ret()
        e.label("unwind")
        e.raw(bytes.fromhex("55 8b ec 53 56 57 8b 45 08 f7 40 04 06 00 00 00"))
        e.jump_if(Condition.EQUAL, "unwind_done")
        e.call("restore")
        e.label("unwind_done")
        e.raw(bytes.fromhex("33 c0 5f 5e 5b c9 c3"))
        self._emit_model_hooks(e, base)
        code = e.build(maximum_size=0x1000)
        labels = {name: address for name, _offset, address in e.listing()}
        payload = SegmentPayloadBuilder(
            owner="vr_visibility", segment=self.section_name, size=self.section_size
        )
        payload.place(label="identity", offset=0, payload=self._magic)
        payload.place(
            label="plane constants", offset=self._half, payload=struct.pack("<2f", 0.5, 0.001)
        )
        payload.place(label="code", offset=self._code, payload=code)
        return payload.build(), labels

    def _emit_eye_radius(self, e: X86Emitter, base: int) -> None:
        # The shared camera is centered between the eyes. Convert half the
        # interocular baseline to its scaled/sheared camera space. The distance
        # from the center to either eye cannot move a normalized triangle plane
        # by more than this radius. Slack covers float/plane normalization error.
        e.raw(bytes.fromhex("8b 5d 0c be") + struct.pack("<I", base))
        for column in range(3):
            for axis in range(3):
                e.raw(bytes((0xD9, 0x46, self._left + 4 * axis)))  # fld left[axis]
                e.raw(bytes((0xD8, 0x66, self._right + 4 * axis)))  # fsub right[axis]
                e.raw(bytes((0xD8, 0x4B, 0x28 + 4 * (3 * axis + column))))  # fmul matrix
                if axis:
                    e.raw(b"\xde\xc1")  # faddp st(1), st
            e.raw(b"\xd8\xc8")  # fmul st, st
            if column:
                e.raw(b"\xde\xc1")
        e.raw(b"\xd9\xfa\xd8\x0d" + struct.pack("<I", base + self._half))  # fsqrt; fmul
        e.raw(b"\xd8\x05" + struct.pack("<I", base + self._plane_slack))
        e.raw(b"\xd9\xe0\xd9\x1d" + struct.pack("<I", base + self._model_back_limit))  # fchs; fstp

    def _emit_model_hooks(self, e: X86Emitter, base: int) -> None:
        def state(op: bytes, offset: int) -> None:
            e.raw(op + struct.pack("<I", base + offset))

        # This native model pass normally uses D3DCULL_NONE and rejects
        # backfaces before clipping. Its center-eye test can discard a triangle
        # that faces one eye. Let the GPU cull after per-eye reprojection for
        # this pass only, and keep the CPU rejection for definite backfaces.
        facing = self.profile.site("vr.model_clip_facing")
        e.label(facing.symbol)
        e.raw(facing.original[:5])  # fnstsw ax; test ah, 1
        e.jump_if(Condition.EQUAL, "model_front")
        e.raw(b"\x9c")
        state(b"\x83\x3d", self._active)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "model_back")
        e.raw(b"\x51")
        state(b"\x8b\x0d", self._model_back_limit)
        # Signed plane distance lies in [negative radius, +inf). IEEE float
        # bits compared unsigned give the opposite order for negative values.
        e.raw(bytes.fromhex("39 4d e0 59"))  # cmp [ebp-0x20], ecx; pop ecx
        e.jump_if(Condition.ABOVE, "model_back")
        state(b"\x83\x3d", self._model_device)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "model_rescue")
        e.raw(b"\x60")  # pushad, the original flags are already saved.
        e.raw(bytes.fromhex("8b 75 e8 8b b6 e8 04 00 00"))  # Native IDirect3DDevice3*.
        e.raw(bytes.fromhex("6a 00 8b d4 8b 06 52 6a 16 56 ff 50 54"))  # GetRenderState.
        e.raw(bytes.fromhex("5a 85 c0"))  # Read the result and test HRESULT.
        e.jump_if(Condition.NOT_EQUAL, "model_enable_failed")
        e.raw(bytes.fromhex("83 fa 01"))  # D3DCULL_NONE.
        e.jump_if(Condition.NOT_EQUAL, "model_enable_failed")
        e.raw(bytes.fromhex("8b 06 6a 03 6a 16 56 ff 50 58 85 c0"))  # D3DCULL_CCW.
        e.jump_if(Condition.NOT_EQUAL, "model_enable_failed")
        state(b"\x89\x35", self._model_device)
        e.raw(b"\x61")
        e.label("model_rescue")
        e.raw(b"\x9d")
        e.label("model_front")
        continuation = facing.va + len(facing.original)
        e.jump_absolute(continuation)
        e.label("model_enable_failed")
        e.raw(b"\x61")
        e.label("model_back")
        e.raw(b"\x9d")
        e.jump_absolute(continuation + int.from_bytes(facing.original[-1:], signed=True))

        end = self.profile.site("vr.model_clip_end")
        e.label(end.symbol)
        e.call("restore_model_cull")
        e.raw(end.original)
        e.ret()

        e.label("restore_model_cull")
        e.raw(bytes.fromhex("9c 60"))
        state(b"\x8b\x35", self._model_device)
        e.raw(bytes.fromhex("85 f6"))
        e.jump_if(Condition.EQUAL, "model_restore_done")
        state(b"\xc7\x05", self._model_device)
        e.raw(bytes(4))
        e.raw(bytes.fromhex("8b 06 6a 01 6a 16 56 ff 50 58 85 c0"))
        e.jump_if(Condition.EQUAL, "model_restore_done")
        state(b"\xc7\x05", self._model_restore_failed)
        e.raw(struct.pack("<I", 1))
        e.label("model_restore_done")
        e.raw(bytes.fromhex("61 9d"))
        e.ret()
