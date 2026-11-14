"""Connect checked native scenery calls to the renderer's retained world path."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter, decode_rel32_branch
from gk3hd.patch.definitions.vr_loading import VRLoadingCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_loading import VRLoadingABI
    from gk3hd.patch.definitions.vr_scene import VRSceneABI


@dataclass(frozen=True, slots=True, kw_only=True)
class VRSceneryCompiler:
    """Replace supported scenery preparation only inside the shared callback.

    Native frustum rejection remains before the prepared hook. Unknown states
    retain ordered native drawing. A renderer failure suppresses further draws
    and returns E_FAIL from the enclosing scene callback, cancelling that frame.
    All original registers, flags and native HRESULT/stack behavior survive the
    dormant and unsupported paths. Ordinary PC-VR does not install these hooks.
    """

    profile: BuildProfile
    scene: VRSceneABI
    loading: VRLoadingABI
    shared_draw_va: int
    section_name: ClassVar[str] = ".gk3ws"
    section_size: ClassVar[int] = 0x3000
    _magic: ClassVar[bytes] = b"GK3WLD01"
    _code: ClassVar[int] = 0x1000
    _shared: ClassVar[int] = 0x10
    _active: ClassVar[int] = 0x14
    _failed: ClassVar[int] = 0x18
    _resolved: ClassVar[int] = 0x1C
    _scope: ClassVar[int] = 0x20
    _draw: ClassVar[int] = 0x24
    _prepared: ClassVar[int] = 0x28
    _frames: ClassVar[int] = 0x2C
    _captures: ClassVar[int] = 0x30
    _reused: ClassVar[int] = 0x34
    _config: ClassVar[int] = 0x100
    _draw_sites: ClassVar[tuple[str, ...]] = tuple(f"vr.scenery_indexed_{i}" for i in range(6))
    _hooks: ClassVar[tuple[str, ...]] = ("vr.scenery_call", "vr.scenery_prepared", *_draw_sites)

    @classmethod
    def for_scene(
        cls, image: PEFile, profile: BuildProfile, scene: VRSceneABI, loading: VRLoadingABI
    ) -> VRSceneryCompiler:
        """Capture the already verified shared visibility callback."""
        return cls(
            profile=profile,
            scene=scene,
            loading=loading,
            shared_draw_va=image.read_u32_va(scene.shared_draw_slot_va),
        )

    def _dependencies(self, image: PEFile) -> None:
        if (
            VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image) != self.scene
            or not self.shared_draw_va
            or VRLoadingCompiler.abi(image) != self.loading
        ):
            msg = "VR scenery requires the checked shared scene and loading lifetime"
            raise PatchError(msg)
        for name in ("vr.scenery_draw", "vr.scenery_footer"):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR scenery native anchor changed: {name}"
                raise PatchError(msg)

    def apply(self, image: PEFile) -> None:
        """Install the scoped adapters after checking every original hook site."""
        self._dependencies(image)
        if image.get_section(self.section_name) is not None:
            msg = "VR scenery adapter is already installed"
            raise PatchError(msg)
        if image.read_u32_va(self.scene.shared_draw_slot_va) != self.shared_draw_va:
            msg = "VR scenery shared callback changed"
            raise PatchError(msg)
        for name in self._hooks:
            site = self.profile.site(name)
            if image.read_bytes(
                image.va_to_offset(site.va), len(site.original) + len(site.context_after)
            ) != (site.original + site.context_after):
                msg = f"VR scenery native hook changed: {name}"
                raise PatchError(msg)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        payload, labels = self._payload(image.rva_to_va(section.virtual_address))
        image.write_bytes(section.pointer_to_raw_data, payload)
        plan = ExecutableMutationPlan(owner="vr_scenery")
        for name in self._hooks:
            site = self.profile.site(name)
            plan.branch(
                label=name,
                opcode=BranchOpcode.CALL,
                site_va=site.va,
                expected=site.original,
                target_va=labels[name],
                size=len(site.original),
            )
        plan.replace(
            label="shared scenery owner",
            va=self.scene.shared_draw_slot_va,
            expected=struct.pack("<I", self.shared_draw_va),
            payload=struct.pack("<I", labels["shared"]),
        )
        plan.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify the generated payload, native anchors and every installed link."""
        self._dependencies(image)
        section = image.get_section(self.section_name)
        if section is None:
            msg = "VR scenery adapter is absent"
            raise PatchError(msg)
        payload, labels = self._payload(image.rva_to_va(section.virtual_address))
        if image.read_bytes(section.pointer_to_raw_data, self.section_size) != payload or (
            image.read_u32_va(self.scene.shared_draw_slot_va) != labels["shared"]
        ):
            msg = "VR scenery payload failed verification"
            raise PatchError(msg)
        for name in self._hooks:
            site = self.profile.site(name)
            target = decode_rel32_branch(
                opcode=BranchOpcode.CALL,
                site_va=site.va,
                instruction=image.read_bytes(image.va_to_offset(site.va), 5),
            )
            if target != labels[name]:
                msg = f"VR scenery hook failed verification: {name}"
                raise PatchError(msg)

    def _payload(self, base: int) -> tuple[bytes, dict[str, int]]:
        e = X86Emitter(base_va=base + self._code)

        def absolute(op: bytes, address: int) -> None:
            e.raw(op + struct.pack("<I", address))

        def state(op: bytes, offset: int) -> None:
            absolute(op, base + offset)

        def store(offset: int, value: int) -> None:
            state(b"\xc7\x05", offset)
            e.raw(struct.pack("<I", value))

        def test(offset: int, unavailable: str) -> None:
            state(b"\x83\x3d", offset)
            e.raw(b"\x00")
            e.jump_if(Condition.EQUAL, unavailable)

        def failed(label: str) -> None:
            e.raw(bytes.fromhex("83 f8 02"))
            e.jump_if(Condition.NOT_EQUAL, label)
            store(self._failed, 1)
            e.label(label)

        def handled(label: str, counter: int) -> None:
            e.raw(bytes.fromhex("83 f8 01"))
            e.jump_if(Condition.NOT_EQUAL, label)
            state(b"\xff\x05", counter)
            e.label(label)

        e.label("shared")
        e.raw(bytes.fromhex("55 8b ec 53 56 57 68"))
        e.absolute_label("unwind")
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00 9c 60"))
        test(self._resolved, "resolve")
        e.jump("resolved")
        e.label("resolve")
        store(self._resolved, 1)
        absolute(b"\x68", base + 0x200)
        absolute(b"\xff\x15", self.profile.address("win32.GetModuleHandleA"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "resolved")
        e.raw(bytes.fromhex("89 c3"))
        for offset, string in ((self._scope, 0x220), (self._draw, 0x240), (self._prepared, 0x260)):
            absolute(b"\x68", base + string)
            e.raw(b"\x53")
            absolute(b"\xff\x15", self.profile.address("win32.GetProcAddress"))
            state(b"\xa3", offset)
        e.label("resolved")
        # A prior native unwind may have bypassed root-end. Cancel only that
        # outstanding scope, never invalidate prepared materials every frame.
        test(self._active, "clean")
        test(self._scope, "clean")
        e.raw(bytes.fromhex("6a 02 6a 00 6a 00"))
        state(b"\xff\x15", self._scope)
        e.label("clean")
        store(self._active, 0)
        store(self._failed, 0)
        store(self._shared, 0)
        for offset in (self._scope, self._draw, self._prepared):
            test(offset, "call_shared")
        store(self._shared, 1)
        e.label("call_shared")
        e.raw(bytes.fromhex("61 9d ff 75 10 ff 75 0c ff 75 08"))
        e.call_absolute(self.shared_draw_va)
        e.raw(bytes.fromhex("9c 60"))
        store(self._shared, 0)
        test(self._active, "scope_closed")
        store(self._failed, 1)
        e.label("scope_closed")
        state(b"\x83\x3d", self._failed)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "shared_return")
        e.raw(bytes.fromhex("c7 44 24 1c 05 40 00 80"))
        test(self._scope, "shared_return")
        e.raw(bytes.fromhex("6a 02 6a 00 6a 00"))
        state(b"\xff\x15", self._scope)
        e.label("shared_return")
        store(self._active, 0)
        # Unlink our registration without changing the callback's result,
        # caller-saved registers or flags.
        e.raw(
            bytes.fromhex(
                "61 9d 52 8b 54 24 04 64 89 15 00 00 00 00 5a 8d 64 24 08 5f 5e 5b c9 c2 0c 00"
            )
        )

        e.label("unwind")
        e.raw(bytes.fromhex("55 8b ec 53 56 57 8b 45 08 f7 40 04 06 00 00 00"))
        e.jump_if(Condition.EQUAL, "unwind_return")
        store(self._shared, 0)
        store(self._active, 0)
        store(self._failed, 1)
        test(self._scope, "unwind_return")
        e.raw(bytes.fromhex("6a 02 6a 00 6a 00"))
        state(b"\xff\x15", self._scope)
        e.label("unwind_return")
        # EXCEPTION_DISPOSITION::ExceptionContinueSearch, not a filter result.
        e.raw(bytes.fromhex("b8 01 00 00 00 5f 5e 5b c9 c3"))

        e.label("vr.scenery_call")
        e.raw(bytes.fromhex("51 9c 60"))
        test(self._shared, "root_native")
        state(b"\x83\x3d", self._failed)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "root_native")
        e.raw(bytes.fromhex("8b 44 24 24 6a 00 50"))
        absolute(b"\x68", base + self._config)
        state(b"\xff\x15", self._scope)
        state(b"\xa3", self._active)
        failed("root_native")
        e.raw(bytes.fromhex("61 9d"))
        e.call_absolute(self.profile.site("vr.scenery_draw").va)
        e.raw(bytes.fromhex("9c 60"))
        test(self._active, "root_return")
        e.raw(bytes.fromhex("8b 44 24 24 6a 01 50"))
        absolute(b"\x68", base + self._config)
        state(b"\xff\x15", self._scope)
        handled("root_counted", self._frames)
        failed("root_return")
        store(self._active, 0)
        e.raw(bytes.fromhex("61 9d 8d 64 24 04 c3"))

        for name in self._draw_sites:
            site = self.profile.site(name)
            e.label(name)
            e.raw(bytes.fromhex("9c 60"))
            test(self._shared, name + ".native")
            state(b"\x83\x3d", self._failed)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, name + ".skip")
            test(self._active, name + ".native")
            e.raw(bytes.fromhex("8d 44 24 28 ff 75 cc 50"))
            state(b"\xff\x15", self._draw)
            handled(name + ".counted", self._captures)
            failed(name + ".result")
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, name + ".native")
            e.label(name + ".skip")
            e.raw(bytes.fromhex("61 9d 8d 64 24 24 b8 00 00 00 00 6a 00"))
            e.jump_absolute(site.va + 5)
            e.label(name + ".native")
            e.raw(bytes.fromhex("61 9d 8d 64 24 04"))
            e.raw(site.original)
            e.jump_absolute(site.va + 5)

        name = "vr.scenery_prepared"
        e.label(name)
        e.raw(bytes.fromhex("9c 60"))
        test(self._shared, "prepared_native")
        state(b"\x83\x3d", self._failed)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "prepared_skip")
        test(self._active, "prepared_native")
        e.raw(bytes.fromhex("ff 75 cc ff 75 ec"))
        state(b"\xff\x15", self._prepared)
        handled("prepared_counted", self._reused)
        failed("prepared_result")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "prepared_native")
        e.label("prepared_skip")
        e.raw(bytes.fromhex("61 9d 8d 64 24 04"))
        e.jump_absolute(self.profile.site("vr.scenery_footer").va)
        e.label("prepared_native")
        e.raw(bytes.fromhex("61 9d"))
        e.raw(self.profile.site(name).original)
        e.ret()

        code = e.build(maximum_size=self.section_size - self._code)
        labels = {name: address for name, _offset, address in e.listing()}
        payload = SegmentPayloadBuilder(
            owner="vr_scenery", segment=self.section_name, size=self.section_size
        )
        payload.place(label="identity", offset=0, payload=self._magic)
        payload.place(
            label="config",
            offset=self._config,
            payload=struct.pack(
                "<5I",
                20,
                1,
                self.profile.address("high_resolution_3d.render_wrapper_ptr"),
                self.profile.address("vr.scenery_formats"),
                self.loading.calls_va,
            ),
        )
        for offset, text in (
            (0x200, b"ddraw.dll\0"),
            (0x220, b"Gk3hdWorldScopeV1\0"),
            (0x240, b"Gk3hdWorldDrawV1\0"),
            (0x260, b"Gk3hdWorldPreparedV1\0"),
        ):
            payload.place(label=f"export {offset}", offset=offset, payload=text)
        payload.place(label="code", offset=self._code, payload=code)
        return payload.build(), labels
