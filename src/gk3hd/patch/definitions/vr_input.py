"""Native game-event routing for the private OpenXR panel pointer."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameCompiler
from gk3hd.patch.definitions.vr_native_scene import (
    check_native_scene_types,
    emit_native_scene_guard,
)
from gk3hd.patch.definitions.vr_navigation import VRNavigationCompiler
from gk3hd.patch.definitions.vr_panel import VRPanelCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.definitions.vr_world import VRWorldCompiler
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.vr_navigation import VRNavigationABI
    from gk3hd.patch.definitions.vr_panel import VRPanelABI
    from gk3hd.patch.definitions.vr_world import VRWorldABI


@dataclass(frozen=True, slots=True)
class VRInputABI:
    """Private interaction switch and render-thread diagnostics."""

    enabled_va: int
    pointer_va: int
    held_va: int
    dispatch_count_va: int
    cancellation_count_va: int
    pending_release_va: int
    unwind_count_va: int


@dataclass(frozen=True, slots=True, kw_only=True)
class VRInputCompiler:
    """Reuse native mouse methods and the game's interface-specific inverses.

    Select supports press/hold/release. Menu is a right-click pulse, not a
    camera-drag button. Loss of pointing or layer/hand ownership cancels a held
    selection outside all controls and requires release before reactivation.
    Virtual client-point queries and warps never move the desktop mouse.
    Back uses native Escape in interfaces, the configured native action-skip
    binding while the room owns a visible ActionSkipper, and native P to
    pause/resume an unobstructed world. Inventory uses native I, and Menu is a right-click
    pulse. Back preserves interfaces such as the driving map which do not
    support Escape. Travel uses native destination selection, not a forced pop
    that would expose an unloaded room. These shortcuts do not require a panel hit.
    Movie Back follows the native character-event skip binding, not a key-down
    approximation or forced layer pop.
    Native button callbacks still run, but their two blocking feedback sleeps
    are omitted while successfully presenting VR, avoiding head-tracking stalls.
    Dormant, hidden and failed VR retain the original delays.
    An explicitly linked world picker owns room
    interaction while action menus and toolbars retain panel pointing. This
    private bridge can link seated navigation after world input completes.
    Text entry has a separate qualified-editor consumer.
    Physical keyboard events retain native editing and shortcuts while XR is
    focused. Dashboard/focus loss retires accepted scan codes; held autorepeat
    cannot resume typing until a fresh physical press. Focus loss releases
    native modifiers even if the dashboard receives their physical key-ups.
    Key-up always reaches native cleanup. Controller shortcuts
    call the original methods directly, independently of this host-input gate.
    """

    profile: BuildProfile
    panel: VRPanelABI
    expected_presenter_va: int
    world: VRWorldABI | None = None
    navigation: VRNavigationABI | None = None

    section_name: ClassVar[str] = ".gk3vi"
    section_size: ClassVar[int] = 0x2000
    _magic: ClassVar[bytes] = b"GK3XRI01"
    _enabled: ClassVar[int] = 0x0C
    _point: ClassVar[int] = 0x10
    _held: ClassVar[int] = 0x18
    _blocked: ClassVar[int] = 0x1C
    _owner: ClassVar[int] = 0x20
    _hand: ClassVar[int] = 0x24
    _dispatching: ClassVar[int] = 0x28
    _valid: ClassVar[int] = 0x2C
    _calls: ClassVar[int] = 0x30
    _cancels: ClassVar[int] = 0x34
    _current: ClassVar[int] = 0x38
    _shortcut_owner: ClassVar[int] = 0x3C
    _shortcut_hand: ClassVar[int] = 0x40
    _shortcut_held: ClassVar[int] = 0x44
    _shortcut_blocked: ClassVar[int] = 0x48
    _shortcut_valid: ClassVar[int] = 0x4C
    _routing: ClassVar[int] = 0x50
    _world_saved: ClassVar[int] = 0x54
    _mode: ClassVar[int] = 0x58
    _previous_mode: ClassVar[int] = 0x5C
    _navigation_allowed: ClassVar[int] = 0x60
    _pending_release: ClassVar[int] = 0x64
    _unwinds: ClassVar[int] = 0x68
    _release_required: ClassVar[int] = 0x6C
    _release_key: ClassVar[int] = 0x70
    _release_key_flags: ClassVar[int] = 0x74
    _move_owner: ClassVar[int] = 0x78
    _move_hand: ClassVar[int] = 0x7C
    _move_point: ClassVar[int] = 0x80
    _host_keys: ClassVar[int] = 0x88  # 512 scan-code/extended-key stroke permissions.
    _host_focus: ClassVar[int] = 0xC8  # Last completed producer's focus, not its scratch output.
    _code: ClassVar[int] = 0x100
    _panel_frame_size: ClassVar[int] = 188
    _keyboard_events: ClassVar[tuple[str, ...]] = ("key_down", "key_up", "character")
    _events: ClassVar[tuple[str, ...]] = (
        "left_down",
        "left_up",
        "right_down",
        "right_up",
        "middle_down",
        "middle_up",
        "pointer_move",
    )

    def abi(self, image: PEFile) -> VRInputABI:
        """Return only the versioned private input boundary."""
        section = image.get_section(self.section_name)
        if section is None or image.read_bytes(section.pointer_to_raw_data, 8) != self._magic:
            msg = "VR input section is absent or incompatible"
            raise PatchError(msg)
        base = image.rva_to_va(section.virtual_address)
        return VRInputABI(
            base + self._enabled,
            base + self._point,
            base + self._held,
            base + self._calls,
            base + self._cancels,
            base + self._pending_release,
            base + self._unwinds,
        )

    def precheck(self, image: PEFile) -> None:
        """Require unchanged point producers, native events, and panel chain."""
        if image.get_section(self.section_name) is not None:
            msg = "VR input hooks are already installed"
            raise PatchError(msg)
        transition = TransitionFrameCompiler.runtime_abi(image)
        if image.read_u32_va(transition.pre_flip_presenter_slot_va) != self.expected_presenter_va:
            msg = "VR input final-page presenter changed"
            raise PatchError(msg)
        if image.read_u32_va(self.panel.frame_va) != self._panel_frame_size:
            msg = "VR input panel ABI is incompatible"
            raise PatchError(msg)
        if VRPanelCompiler(profile=self.profile).abi(image) != self.panel:
            msg = "VR input panel composition boundary changed"
            raise PatchError(msg)
        self._check_world(image)
        for name in (
            "vr.client_point",
            "vr.set_client_point",
            "vr.key_down",
            "vr.key_up",
            "vr.button_wait",
            "vr.character_event",
            "vr.movie_character",
            "vr.movie_character_slot",
            "vr.action_skip_key",
            "vr.action_skip_key_slot",
            "vr.menu_down",
            "vr.menu_up",
        ):
            site = self.profile.site(name)
            actual = image.read_bytes(
                image.va_to_offset(site.va), len(site.original) + len(site.context_after)
            )
            if actual != site.original + site.context_after:
                msg = f"VR input anchor changed: {name}"
                raise PatchError(msg)
        for event in self._events:
            if image.read_u32_va(
                self.profile.address(f"input.{event}_slot")
            ) != self.profile.address(f"input.{event}"):
                msg = f"VR input event owner changed: {event}"
                raise PatchError(msg)
        for event in self._keyboard_events:
            site = self.profile.site(f"vr.host_{event}_slot")
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR physical keyboard event owner changed: {event}"
                raise PatchError(msg)

    def _mutations(self, labels: dict[str, int]) -> ExecutableMutationPlan:
        plan = ExecutableMutationPlan(owner="vr_input")
        for name, label in (("vr.client_point", "get_point"), ("vr.set_client_point", "set_point")):
            site = self.profile.site(name)
            plan.branch(
                label=name,
                opcode=BranchOpcode.JUMP,
                site_va=site.va,
                expected=site.original,
                target_va=labels[label],
                size=len(site.original),
            )
        for event in self._events:
            plan.pointer(
                label=event,
                slot_va=self.profile.address(f"input.{event}_slot"),
                expected=self.profile.address(f"input.{event}"),
                target_va=labels[f"host_{event}"],
            )
        for event in self._keyboard_events:
            name = "character_event" if event == "character" else event
            plan.pointer(
                label=f"physical {event}",
                slot_va=self.profile.site(f"vr.host_{event}_slot").va,
                expected=self.profile.site(f"vr.{name}").va,
                target_va=labels[f"host_{event}"],
            )
        wait = self.profile.site("vr.button_wait")
        plan.replace(
            label="native button wait dispatch",
            va=wait.va,
            expected=wait.original,
            payload=b"\xbf" + struct.pack("<I", labels["button_wait"]) + b"\x90",
        )
        return plan

    def _check_world(self, image: PEFile) -> None:
        check_native_scene_types(image, self.profile)
        if self.world is None:
            if self.navigation is not None:
                msg = "VR navigation requires linked world ownership"
                raise PatchError(msg)
            return
        scene = VRSceneCompiler(profile=self.profile, units_per_meter=1).abi(image)
        compiler = VRWorldCompiler(profile=self.profile, scene=scene)
        if scene.enabled_va != self.panel.world_enabled_va or compiler.abi(image) != self.world:
            msg = "VR input world composition boundary changed"
            raise PatchError(msg)
        compiler.postcheck(image)
        if self.navigation is not None:
            navigation = VRNavigationCompiler(profile=self.profile, panel=self.panel, scene=scene)
            if navigation.abi(image) != self.navigation:
                msg = "VR input navigation boundary changed"
                raise PatchError(msg)
            navigation.postcheck(image)

    def apply(self, image: PEFile) -> None:
        """Install a dormant panel-input route after the final XR snapshot."""
        self.precheck(image)
        section = image.add_section(self.section_name, bytes(self.section_size), 0xE0000060)
        base = image.rva_to_va(section.virtual_address)
        payload, labels = self._payload(base)
        image.write_bytes(section.pointer_to_raw_data, payload)
        plan = self._mutations(labels)
        plan.pointer(
            label="panel input presenter",
            slot_va=TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va,
            expected=self.expected_presenter_va,
            target_va=labels["present"],
        )
        plan.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify the complete native input graph and deterministic payload."""
        base = self.abi(image).enabled_va - self._enabled
        expected, labels = self._payload(base)
        if image.read_bytes(image.va_to_offset(base), self.section_size) != expected:
            msg = "VR input payload failed verification"
            raise PatchError(msg)
        self._mutations(labels).verify(image)
        wait = self.profile.site("vr.button_wait")
        if (
            image.read_bytes(
                image.va_to_offset(wait.va + len(wait.original)), len(wait.context_after)
            )
            != wait.context_after
        ):
            msg = "VR native button delay calls changed"
            raise PatchError(msg)
        self._check_world(image)
        if VRPanelCompiler(profile=self.profile).abi(image) != self.panel:
            msg = "VR input panel composition boundary failed verification"
            raise PatchError(msg)
        for name in (
            "vr.key_down",
            "vr.key_up",
            "vr.character_event",
            "vr.movie_character",
            "vr.movie_character_slot",
            "vr.action_skip_key",
            "vr.action_skip_key_slot",
            "vr.menu_down",
            "vr.menu_up",
        ):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"VR shortcut entry failed verification: {name}"
                raise PatchError(msg)
        for name in ("vr.client_point", "vr.set_client_point"):
            site = self.profile.site(name)
            if (
                image.read_bytes(
                    image.va_to_offset(site.va + len(site.original)), len(site.context_after)
                )
                != site.context_after
            ):
                msg = f"VR input continuation failed verification: {name}"
                raise PatchError(msg)
        if (
            image.read_u32_va(TransitionFrameCompiler.runtime_abi(image).pre_flip_presenter_slot_va)
            != labels["present"]
        ):
            msg = "VR input presenter failed verification"
            raise PatchError(msg)

    def _payload(self, base: int) -> tuple[bytes, dict[str, int]]:
        e = X86Emitter(base_va=base + self._code)
        p = self.profile
        frame = self.panel.frame_va

        def absolute(opcode: bytes, address: int) -> None:
            e.raw(opcode + struct.pack("<I", address))

        def state(opcode: bytes, offset: int) -> None:
            absolute(opcode, base + offset)

        def store(offset: int, value: int) -> None:
            state(b"\xc7\x05", offset)
            e.raw(struct.pack("<I", value))

        def native(event: str) -> None:
            release = {"left_down": 1, "left_up": 1, "right_down": 2, "right_up": 2}.get(event, 0)
            if release:
                state(b"\x83\x0d", self._release_required)
                e.raw(bytes((release,)))
            state(b"\x68", self._point)
            # Use the EngineLoop owner explicitly. The native client-point
            # global aliases it in this build, but is not the input contract.
            absolute(b"\x8b\x0d", p.address("engine.loop"))
            e.call_absolute(p.address(f"input.{event}"))
            state(b"\xff\x05", self._calls)
            if event in {"left_up", "right_up"}:
                state(b"\x83\x25", self._release_required)
                e.raw(bytes((0xFF ^ release,)))

        owner_checks = 0

        def check_owner() -> None:
            nonlocal owner_checks
            e.call_absolute(p.address("ui.current_layer"))
            state(b"\x3b\x05", self._owner)
            e.jump_if(Condition.NOT_EQUAL, "lost")
            if self.world is not None:
                label = f"owner_valid_{owner_checks}"
                owner_checks += 1
                state(b"\x83\x3d", self._mode)
                e.raw(b"\x01")
                e.jump_if(Condition.NOT_EQUAL, label)
                e.call("world_owner")
                e.raw(bytes.fromhex("83 f8 01"))
                e.jump_if(Condition.NOT_EQUAL, "lost")
                e.label(label)

        # The snapshot belongs to the completed XR panel frame. Model changes
        # caused below appear in the next normal game update, not another tick.
        e.label("present")
        e.raw(bytes.fromhex("9c 60"))
        # Native key handlers can synchronously paint a newly opened layer.
        # Nested presentation cannot resample XR or consume this input twice.
        state(b"\x83\x3d", self._routing)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "nested")
        # Cover presentation, native input and navigation with one x86 SEH
        # registration. Inner native handlers may recover normally. If this
        # transaction is unwound, retire ownership without running more game
        # callbacks from the exception handler itself.
        e.raw(b"\x68")
        e.absolute_label("unwind")
        e.raw(bytes.fromhex("64 ff 35 00 00 00 00 64 89 25 00 00 00 00"))
        store(self._routing, 1)
        store(self._navigation_allowed, 0)
        e.call_absolute(self.expected_presenter_va)
        # Publish only after the producer returns. Native window dispatch can
        # occur inside that producer while its public output is being cleared
        # and rebuilt. Host events keep the previous completed focus instead
        # of mistaking a scratch zero for dashboard ownership. Modifier cleanup
        # is inside this protected, non-reentrant native transaction too.
        e.call("active")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "inactive_keyboard_focus")
        absolute(b"\xa1", frame + 64)
        e.raw(bytes.fromhex("83 e0 01"))
        state(b"\xa3", self._host_focus)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "keyboard_focus_ready")
        e.call("cancel_host_modifiers")
        e.jump("clear_keyboard_focus")
        e.label("inactive_keyboard_focus")
        store(self._host_focus, 0)
        e.label("clear_keyboard_focus")
        e.call("clear_host_keys")
        e.label("keyboard_focus_ready")
        state(b"\x83\x3d", self._pending_release)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "released")
        # Defer native outside-release/hover cleanup to a healthy game update.
        # Keep the request set until cancellation returns, including faults in
        # the cancellation callback itself.
        e.call("cancel")
        state(b"\x83\x3d", self._release_required)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "done")
        state(b"\x83\x3d", self._release_key)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "done")
        store(self._pending_release, 0)
        store(self._valid, 0)
        e.label("released")
        if self.world is not None:
            # Prepare only a successfully completed shared world/UI frame.
            # Native callbacks below can redraw and clear the scene producer.
            absolute(b"\xc7\x05", self.world.ready_va)
            e.raw(bytes(4))
            absolute(b"\x83\x3d", self.panel.completion_result_va)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, "world_unprepared")
            absolute(b"\xff\x35", frame + 168)
            e.call_absolute(self.world.prepare_va)
            e.label("world_unprepared")
        if self.panel.world_enabled_va:
            # The outer world is already submitted. Native event handlers may
            # synchronously render another desktop page, but that is not a new
            # game update and must not start another XR world transaction.
            absolute(b"\xa1", self.panel.world_enabled_va)
            state(b"\xa3", self._world_saved)
            absolute(b"\xc7\x05", self.panel.world_enabled_va)
            e.raw(bytes(4))
        e.call("active")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "inactive")
        absolute(b"\x83\x3d", p.address("engine.loop"))
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "unavailable")
        absolute(b"\x83\x3d", self.panel.result_va)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "unavailable")
        absolute(b"\x83\x3d", self.panel.completion_result_va)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "unavailable")
        absolute(b"\xf7\x05", frame + 64)
        e.raw(struct.pack("<I", 1))
        e.jump_if(Condition.EQUAL, "unavailable")
        absolute(b"\xa1", frame + 168)  # selected hand
        e.raw(bytes.fromhex("83 f8 01"))
        e.jump_if(Condition.ABOVE, "unavailable")
        e.raw(bytes.fromhex("6b c0 30"))
        absolute(b"\x83\xb8", frame + 68)  # hand's AimValid flag
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "unavailable")
        e.call("shortcuts")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "done")
        store(self._mode, 0)
        if self.world is not None:
            e.call("world_owner")
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.SIGN, "lost")
            e.jump_if(Condition.EQUAL, "panel_point")
            e.raw(bytes.fromhex("83 f8 02"))
            e.jump_if(Condition.EQUAL, "navigation_only")
            store(self._mode, 1)
            for size, offset in ((8, self._point), (12, self._point + 4)):
                absolute(b"\xa1", frame + size)
                e.raw(bytes.fromhex("d1 e8"))
                state(b"\xa3", offset)
            e.jump("point_ready")
            e.label("panel_point")
        e.call("read_point")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "lost")
        e.label("point_ready")
        e.call_absolute(p.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "lost")
        state(b"\x3b\x05", self._owner)
        e.jump_if(Condition.NOT_EQUAL, "handoff")
        absolute(b"\x8b\x15", frame + 168)
        state(b"\x3b\x15", self._hand)
        e.jump_if(Condition.NOT_EQUAL, "handoff")
        state(b"\x8b\x15", self._mode)
        state(b"\x3b\x15", self._previous_mode)
        e.jump_if(Condition.NOT_EQUAL, "handoff")
        state(b"\x83\x3d", self._valid)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "same_owner")
        e.label("handoff")
        state(b"\xa3", self._owner)
        absolute(b"\xa1", frame + 168)
        state(b"\xa3", self._hand)
        state(b"\xa1", self._mode)
        state(b"\xa3", self._previous_mode)
        absolute(b"\xa1", frame + 180)
        e.raw(bytes.fromhex("83 e0 01"))
        state(b"\xa3", self._blocked)
        # Preserve the new point while retiring an old drag outside controls.
        state(b"\xff\x35", self._point + 4)
        state(b"\xff\x35", self._point)
        e.call("cancel")
        e.raw(b"\x58")
        state(b"\xa3", self._point)
        e.raw(b"\x58")
        state(b"\xa3", self._point + 4)
        e.label("same_owner")
        store(self._valid, 1)
        store(self._dispatching, 1)
        if self.world is not None:
            state(b"\xa1", self._mode)
            absolute(b"\xa3", self.world.dispatch_va)
        for offset in (0, 4):
            state(b"\xa1", self._point + offset)
            absolute(b"\xa3", p.address("input.cursor_position") + offset)
        absolute(b"\xa1", frame + 180)
        e.raw(bytes.fromhex("83 e0 01"))
        state(b"\x21\x05", self._blocked)  # unblock only after release
        state(b"\x8b\x15", self._blocked)
        e.raw(bytes.fromhex("f7 d2 21 d0"))
        state(b"\xa3", self._current)
        # Retire Select before pointer movement so outside cancellation cannot
        # turn a stale held button into a huge camera delta.
        e.raw(bytes.fromhex("a8 01"))
        e.jump_if(Condition.NOT_EQUAL, "move")
        state(b"\xf7\x05", self._held)
        e.raw(struct.pack("<I", 1))
        e.jump_if(Condition.EQUAL, "move")
        state(b"\x83\x25", self._held)
        e.raw(b"\xfe")
        native("left_up")
        check_owner()
        e.label("move")
        # ToolTip::MouseMove restarts its native appearance/fade animation.
        # Real mouse movement is event-driven, not an unchanged point every
        # render tick. Preserve that behavior without throttling ray updates,
        # Select transitions, or the world noun picker below. A new hand/layer
        # must still receive its first move even at identical coordinates.
        for source, previous in (
            (self._owner, self._move_owner),
            (self._hand, self._move_hand),
            (self._point, self._move_point),
            (self._point + 4, self._move_point + 4),
        ):
            state(b"\xa1", source)
            state(b"\x3b\x05", previous)
            e.jump_if(Condition.NOT_EQUAL, "changed_point")
        e.jump("point_delivered")
        e.label("changed_point")
        for source, previous in (
            (self._owner, self._move_owner),
            (self._hand, self._move_hand),
            (self._point, self._move_point),
            (self._point + 4, self._move_point + 4),
        ):
            state(b"\xa1", source)
            state(b"\xa3", previous)
        native("pointer_move")
        check_owner()
        e.label("point_delivered")
        if self.world is not None:
            state(b"\x83\x3d", self._mode)
            e.raw(b"\x01")
            e.jump_if(Condition.NOT_EQUAL, "hover_done")
            # Desktop hover is throttled on a changed pixel position. World
            # aim can change while the menu anchor stays centered. Refresh the
            # original noun/tooltip producer without spoofing a screen delta.
            absolute(b"\x8b\x0d", p.address("vr.room_global"))
            e.raw(bytes.fromhex("85 c9"))
            e.jump_if(Condition.EQUAL, "lost")
            emit_native_scene_guard(e, p, register="ecx", rejected="lost")
            state(b"\x68", self._point)
            e.call_absolute(p.site("vr.world_hover").va)
            state(b"\xff\x05", self._calls)
            check_owner()
            e.label("hover_done")
        state(b"\xa1", self._current)
        e.raw(bytes.fromhex("a8 01"))
        e.jump_if(Condition.EQUAL, "buttons_done")
        state(b"\xf7\x05", self._held)
        e.raw(struct.pack("<I", 1))
        e.jump_if(Condition.NOT_EQUAL, "buttons_done")
        state(b"\x83\x0d", self._held)
        e.raw(b"\x01")
        native("left_down")
        check_owner()
        e.label("buttons_done")
        if self.navigation is not None:
            state(b"\xa1", self._mode)
            state(b"\xa3", self._navigation_allowed)
        state(b"\xa1", self._current)
        state(b"\xa3", self._held)
        store(self._dispatching, 0)
        e.jump("done")
        if self.navigation is not None:
            e.label("navigation_only")
            # Retire selection/hover, including a held trigger. Keep locomotion
            # available so a wall-safety fade cannot trap the observer. Native
            # cancellation can change layers: check room/overlay ownership again.
            e.call("cancel")
            store(self._valid, 0)
            store(self._blocked, 1)
            e.call("world_owner")
            e.raw(bytes.fromhex("83 f8 02"))
            e.jump_if(Condition.NOT_EQUAL, "done")
            store(self._navigation_allowed, 1)
            e.jump("done")
        elif self.world is not None:
            e.label("navigation_only")
            e.jump("lost")
        e.label("inactive")
        store(self._owner, 0)
        store(self._blocked, 0)
        e.label("unavailable")
        store(self._shortcut_valid, 0)
        e.label("lost")
        e.call("cancel")
        store(self._valid, 0)
        e.label("done")
        if self.world is not None:
            absolute(b"\xc7\x05", self.world.dispatch_va)
            e.raw(bytes(4))
        if self.navigation is not None:
            # Camera callbacks may redraw synchronously. Keep world rendering
            # suppressed and nested input blocked until camera commit returns.
            state(b"\xff\x35", self._navigation_allowed)
            e.call_absolute(self.navigation.tick_va)
            store(self._navigation_allowed, 0)
        if self.panel.world_enabled_va:
            state(b"\xa1", self._world_saved)
            absolute(b"\xa3", self.panel.world_enabled_va)
        store(self._routing, 0)
        e.raw(bytes.fromhex("8b 14 24 64 89 15 00 00 00 00 83 c4 08"))
        e.jump("return")
        e.label("nested")
        # Keep ordinary cursor/retained-page composition in a native redraw.
        # Only XR presentation/input are skipped, not the flat UI producer.
        if self.panel.composition_presenter_va:
            e.call_absolute(self.panel.composition_presenter_va)
        e.label("return")
        e.raw(bytes.fromhex("61 9d c3"))

        e.label("unwind")
        e.raw(bytes.fromhex("8b 44 24 04 f7 40 04 06 00 00 00"))
        e.jump_if(Condition.EQUAL, "unwind_search")
        for offset in (
            self._enabled,
            self._dispatching,
            self._routing,
            self._navigation_allowed,
            self._world_saved,
            self._shortcut_valid,
            self._host_focus,
            self._owner,
            self._mode,
            self._current,
        ):
            store(offset, 0)
        store(self._point, 0xFFFFD8F0)
        store(self._point + 4, 0xFFFFD8F0)
        store(self._pending_release, 1)
        store(self._blocked, 1)
        store(self._shortcut_blocked, 14)
        state(b"\xff\x05", self._unwinds)
        addresses = [self.panel.enabled_va]
        if self.panel.world_enabled_va:
            addresses.append(self.panel.world_enabled_va)
        if self.world is not None:
            addresses.extend(
                (
                    self.world.enabled_va,
                    self.world.active_va,
                    self.world.dispatch_va,
                    self.world.ready_va,
                )
            )
        if self.navigation is not None:
            addresses.append(self.navigation.enabled_va)
        for address in addresses:
            absolute(b"\xc7\x05", address)
            e.raw(bytes(4))
        e.label("unwind_search")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))  # ExceptionContinueSearch, cdecl.

        if self.world is not None:
            e.label("world_owner")
            e.call_absolute(p.address("ui.current_layer"))
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "not_world")
            e.raw(bytes.fromhex("81 38"))
            e.raw(struct.pack("<I", p.address("vr.room_layer_vtable")))
            e.jump_if(Condition.NOT_EQUAL, "not_world")
            # Both native action menus and toolbars live under the room root,
            # not in a new layer. Their visibility takes priority over world
            # rays. A corrupt/unbounded child list is not treated as a room.
            e.raw(bytes.fromhex("8b 50 4c 8b 48 50 81 f9 00 01 00 00"))
            e.jump_if(Condition.ABOVE, "world_unavailable")
            e.raw(bytes.fromhex("85 c9"))
            e.jump_if(Condition.EQUAL, "is_world")
            e.raw(bytes.fromhex("85 d2"))
            e.jump_if(Condition.EQUAL, "world_unavailable")
            e.label("world_children")
            e.raw(bytes.fromhex("8b 02 85 c0"))
            e.jump_if(Condition.EQUAL, "world_next_child")
            e.raw(bytes.fromhex("80 78 18 00"))
            e.jump_if(Condition.EQUAL, "world_next_child")
            e.raw(bytes.fromhex("8b 00"))
            for name in ("vr.action_menu_vtable", "vr.toolbar_vtable"):
                e.raw(b"\x3d" + struct.pack("<I", p.address(name)))
                e.jump_if(Condition.EQUAL, "not_world")
            e.label("world_next_child")
            e.raw(bytes.fromhex("83 c2 04 49"))
            e.jump_if(Condition.NOT_EQUAL, "world_children")
            e.label("is_world")
            absolute(b"\xa1", self.world.ready_va)
            for value in (1, 2):
                e.raw(bytes((0x83, 0xF8, value)))
                e.jump_if(Condition.EQUAL, "world_ready")
            e.jump("world_unavailable")
            e.label("world_ready")
            # A completed runtime hit on any qualified interactive overlay
            # owns this pointer, even when it is not one of the two menu
            # classes. Puzzle HUD controls must not become world selections.
            absolute(b"\x83\x3d", frame + 164)
            e.raw(b"\x01")
            e.jump_if(Condition.EQUAL, "not_world")
            e.raw(b"\xc3")
            e.label("world_unavailable")
            e.raw(bytes.fromhex("b8 ff ff ff ff c3"))
            e.label("not_world")
            e.raw(bytes.fromhex("31 c0 c3"))

        e.label("read_point")
        absolute(b"\x83\x3d", frame + 164)
        e.raw(b"\x01")
        e.jump_if(Condition.NOT_EQUAL, "point_invalid")
        # cvttss2si rejects NaN/overflow as INT_MIN. Partial coordinates never
        # escape because the caller retires pointing if either axis is invalid.
        for coordinate, size, offset in ((172, 8, self._point), (176, 12, self._point + 4)):
            e.raw(bytes.fromhex("0f 57 c0"))
            absolute(bytes.fromhex("f3 0f 10 0d"), frame + coordinate)
            e.raw(bytes.fromhex("0f 2e c8"))
            e.jump_if(Condition.BELOW, "point_invalid")
            absolute(bytes.fromhex("f3 0f 2c 05"), frame + coordinate)
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.SIGN, "point_invalid")
            absolute(b"\x3b\x05", frame + size)
            e.jump_if(Condition.ABOVE_OR_EQUAL, "point_invalid")
            state(b"\xa3", offset)
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        e.label("point_invalid")
        e.raw(bytes.fromhex("31 c0 c3"))

        e.label("shortcuts")
        e.call_absolute(p.address("ui.current_layer"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "shortcut_unavailable")
        state(b"\x3b\x05", self._shortcut_owner)
        e.jump_if(Condition.NOT_EQUAL, "shortcut_handoff")
        absolute(b"\x8b\x15", frame + 168)
        state(b"\x3b\x15", self._shortcut_hand)
        e.jump_if(Condition.NOT_EQUAL, "shortcut_handoff")
        state(b"\x83\x3d", self._shortcut_valid)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "shortcut_same_owner")
        e.label("shortcut_handoff")
        state(b"\xa3", self._shortcut_owner)
        absolute(b"\xa1", frame + 168)
        state(b"\xa3", self._shortcut_hand)
        absolute(b"\xa1", frame + 180)
        e.raw(bytes.fromhex("83 e0 0e"))
        state(b"\xa3", self._shortcut_blocked)
        store(self._shortcut_held, 0)
        e.label("shortcut_same_owner")
        store(self._shortcut_valid, 1)
        absolute(b"\xa1", frame + 180)
        e.raw(bytes.fromhex("83 e0 0e"))
        state(b"\x21\x05", self._shortcut_blocked)
        state(b"\x8b\x15", self._shortcut_blocked)
        e.raw(bytes.fromhex("f7 d2 21 c2"))
        state(b"\x8b\x0d", self._shortcut_held)
        e.raw(bytes.fromhex("f7 d1 21 ca"))  # newly pressed, unblocked shortcuts
        state(b"\xa3", self._shortcut_held)
        e.raw(bytes.fromhex("85 d2"))
        e.jump_if(Condition.EQUAL, "shortcut_none")
        # Retire any drag BEFORE changing the layer. All newly pressed shortcuts
        # are consumed, but only one action runs on this layer (Back wins).
        e.raw(b"\x52")
        e.call("cancel")
        store(self._valid, 0)
        e.raw(b"\x5a")
        e.raw(b"\x52")
        e.call_absolute(p.address("ui.current_layer"))
        state(b"\x3b\x05", self._shortcut_owner)
        e.raw(b"\x5a")
        e.jump_if(Condition.NOT_EQUAL, "shortcut_done")
        store(self._dispatching, 1)
        for button, key, scan, label in ((2, 0x1B, 1, "back"), (8, 0x49, 0x17, "inventory")):
            e.raw(bytes((0xF6, 0xC2, button)))
            e.jump_if(Condition.EQUAL, f"shortcut_after_{label}")
            store(self._release_key, key)
            store(self._release_key_flags, 0xC0000001 + 0x10000 * scan)
            if label == "back":
                # Pause is deliberately keyboard-driven and ignores Escape.
                # Invoke its native toggle rather than popping a modal layer,
                # which would bypass the game's simulation pause ownership.
                e.call_absolute(p.address("ui.current_layer"))
                e.raw(bytes.fromhex("85 c0"))
                e.jump_if(Condition.EQUAL, "back_key_ready")
                e.raw(b"\x81\x38" + struct.pack("<I", p.address("movies.layer_vtable")))
                e.jump_if(Condition.EQUAL, "movie_back")
                e.raw(b"\x81\x38" + struct.pack("<I", p.address("pause.vtable")))
                e.jump_if(Condition.EQUAL, "back_pause_toggle")
                if self.world is not None:
                    e.call("back_action_owner")
                    e.raw(bytes.fromhex("85 c0"))
                    e.jump_if(Condition.NOT_EQUAL, "action_back")
                    e.call("world_owner")
                    e.raw(bytes.fromhex("83 f8 01"))
                    e.jump_if(Condition.NOT_EQUAL, "back_key_ready")
                else:
                    e.jump("back_key_ready")
                e.label("back_pause_toggle")
                store(self._release_key, 0x50)
                store(self._release_key_flags, 0xC0190001)
                e.jump("back_key_ready")
                if self.world is not None:
                    e.label("action_back")
                    # ActionSkipper's original key-down route owns all native
                    # skip guards and callbacks. Read its configured virtual
                    # key, rather than assuming Escape or forcing completion.
                    store(self._release_key, 0)
                    absolute(b"\xa1", p.address("engine.loop"))
                    for instruction in (
                        bytes.fromhex("8b 80 44 04 00 00"),
                        bytes.fromhex("8b 40 44"),
                        bytes.fromhex("8b 40 6c"),
                        bytes.fromhex("8b 80 f8 00 00 00"),
                    ):
                        e.raw(bytes.fromhex("85 c0"))
                        e.jump_if(Condition.EQUAL, "shortcut_done")
                        e.raw(instruction)
                    e.raw(bytes.fromhex("85 c0"))
                    e.jump_if(Condition.EQUAL, "shortcut_done")
                    state(b"\xa3", self._release_key)
                    # No physical scan code or OS event is invented for a
                    # remapped virtual binding. Native handlers use its VK.
                    store(self._release_key_flags, 0xC0000001)
                e.label("back_key_ready")
            # Native EngineLoop key callbacks take (virtual key, Win32 flags)
            # and clean both arguments. No OS keyboard event is synthesized.
            for name in ("down", "up"):
                state(b"\xa1", self._release_key_flags)
                if name == "down":
                    e.raw(b"\x25" + struct.pack("<I", 0x3FFFFFFF))
                e.raw(b"\x50")
                state(b"\xff\x35", self._release_key)
                absolute(b"\x8b\x0d", p.address("engine.loop"))
                e.call_absolute(p.site(f"vr.key_{name}").va)
                state(b"\xff\x05", self._calls)
                if name == "up":
                    store(self._release_key, 0)
            e.jump("shortcut_done")
            e.label(f"shortcut_after_{label}")
        e.call("read_point")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.NOT_EQUAL, "shortcut_menu")
        # A nonpointing Menu opens at the panel center, never outside the game
        # or at a stale hand/layer's last hovered control.
        for size, offset in ((8, self._point), (12, self._point + 4)):
            absolute(b"\xa1", frame + size)
            e.raw(bytes.fromhex("d1 e8"))
            state(b"\xa3", offset)
        e.label("shortcut_menu")
        for offset in (0, 4):
            state(b"\xa1", self._point + offset)
            absolute(b"\xa3", p.address("input.cursor_position") + offset)
        native("pointer_move")
        e.call_absolute(p.address("ui.current_layer"))
        state(b"\x3b\x05", self._shortcut_owner)
        e.jump_if(Condition.NOT_EQUAL, "shortcut_done")
        native("right_down")
        native("right_up")
        e.label("shortcut_done")
        store(self._dispatching, 0)
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        e.label("shortcut_unavailable")
        store(self._shortcut_valid, 0)
        e.label("shortcut_none")
        e.raw(bytes.fromhex("31 c0 c3"))

        if self.world is not None:
            e.label("back_action_owner")
            e.raw(b"\x53")
            e.call_absolute(p.address("ui.current_layer"))
            e.raw(bytes.fromhex("31 db 85 c0"))
            e.jump_if(Condition.EQUAL, "back_action_absent")
            e.raw(b"\x81\x38" + struct.pack("<I", p.address("vr.room_layer_vtable")))
            e.jump_if(Condition.NOT_EQUAL, "back_action_absent")
            e.raw(bytes.fromhex("8b 50 4c 8b 48 50 81 f9 00 01 00 00"))
            e.jump_if(Condition.ABOVE, "back_action_absent")
            e.raw(bytes.fromhex("85 c9"))
            e.jump_if(Condition.EQUAL, "back_action_absent")
            e.raw(bytes.fromhex("85 d2"))
            e.jump_if(Condition.EQUAL, "back_action_absent")
            e.label("back_action_children")
            e.raw(bytes.fromhex("8b 02 85 c0"))
            e.jump_if(Condition.EQUAL, "back_action_next")
            for offset in (0x18, 0x19):
                e.raw(bytes((0x80, 0x78, offset, 0)))
                e.jump_if(Condition.EQUAL, "back_action_next")
            e.raw(bytes.fromhex("8b 00"))
            for name in ("vr.action_menu_vtable", "vr.toolbar_vtable"):
                e.raw(b"\x3d" + struct.pack("<I", p.address(name)))
                e.jump_if(Condition.EQUAL, "back_action_absent")
            e.raw(b"\x3d" + struct.pack("<I", p.address("vr.action_skip_vtable")))
            e.jump_if(Condition.NOT_EQUAL, "back_action_next")
            e.raw(bytes.fromhex("bb 01 00 00 00"))
            e.label("back_action_next")
            e.raw(bytes.fromhex("83 c2 04 49"))
            e.jump_if(Condition.NOT_EQUAL, "back_action_children")
            e.raw(bytes.fromhex("8b c3 5b c3"))
            e.label("back_action_absent")
            e.raw(bytes.fromhex("31 c0 5b c3"))

        e.label("movie_back")
        # Match MovieLayer's native UIKeyType_SkipMovie character binding.
        # This is a discrete explicit Back action, never keyboard text entry.
        store(self._release_key, 0)
        absolute(b"\xa1", p.address("engine.loop"))
        for instruction in (
            bytes.fromhex("8b 80 44 04 00 00"),
            bytes.fromhex("8b 40 44"),
            bytes.fromhex("8b 40 6c"),
        ):
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, "shortcut_done")
            e.raw(instruction)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "shortcut_done")
        e.raw(bytes.fromhex("8b 80 08 01 00 00"))
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "shortcut_done")
        e.push_imm32(1)
        e.raw(b"\x50")
        absolute(b"\x8b\x0d", p.address("engine.loop"))
        e.call_absolute(p.site("vr.character_event").va)
        state(b"\xff\x05", self._calls)
        e.jump("shortcut_done")

        e.label("cancel")
        store(self._move_owner, 0)
        if self.world is not None:
            # An outside release must never activate a pointed world object.
            absolute(b"\xc7\x05", self.world.dispatch_va)
            e.raw(bytes(4))
        store(self._point, 0xFFFFD8F0)  # -10000: outside every authored canvas
        store(self._point + 4, 0xFFFFD8F0)
        absolute(b"\x83\x3d", p.address("engine.loop"))
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "cancel_done")
        state(b"\xa1", self._held)
        state(b"\x0b\x05", self._valid)
        state(b"\x0b\x05", self._release_required)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "cancel_done")
        store(self._dispatching, 1)
        for offset in (0, 4):
            state(b"\xa1", self._point + offset)
            absolute(b"\xa3", p.address("input.cursor_position") + offset)
        state(b"\xa1", self._held)
        state(b"\x0b\x05", self._release_required)
        e.raw(bytes.fromhex("a8 01"))
        e.jump_if(Condition.EQUAL, "cancel_hover")
        native("left_up")
        state(b"\xff\x05", self._cancels)
        e.label("cancel_hover")
        state(b"\xf7\x05", self._release_required)
        e.raw(struct.pack("<I", 2))
        e.jump_if(Condition.EQUAL, "cancel_move")
        native("right_up")
        e.label("cancel_move")
        native("pointer_move")
        e.label("cancel_done")
        store(self._held, 0)
        store(self._dispatching, 0)
        absolute(b"\x83\x3d", p.address("engine.loop"))
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "cancel_return")
        state(b"\x83\x3d", self._release_key)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "cancel_return")
        store(self._dispatching, 1)
        state(b"\xff\x35", self._release_key_flags)
        state(b"\xff\x35", self._release_key)
        absolute(b"\x8b\x0d", p.address("engine.loop"))
        e.call_absolute(p.site("vr.key_up").va)
        state(b"\xff\x05", self._calls)
        store(self._release_key, 0)
        store(self._dispatching, 0)
        e.label("cancel_return")
        e.raw(b"\xc3")

        e.label("active")
        # Cancellation still owns queries while closing/disabled. Native UI
        # callbacks must not suddenly read the physical mouse mid-release.
        state(b"\x83\x3d", self._dispatching)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "active_dispatch")
        state(b"\x83\x3d", self._pending_release)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "active_dispatch")
        state(b"\xa1", self._enabled)
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "active_done")
        absolute(b"\xa1", self.panel.enabled_va)
        e.label("active_done")
        e.raw(b"\xc3")
        e.label("active_dispatch")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))

        e.label("get_point")
        e.raw(bytes.fromhex("51 52"))
        e.call("active")
        e.raw(bytes.fromhex("85 c0"))
        e.jump_if(Condition.EQUAL, "get_native")
        e.raw(bytes.fromhex("8b 44 24 0c"))
        state(b"\x8b\x15", self._point)
        e.raw(bytes.fromhex("89 10"))
        state(b"\x8b\x15", self._point + 4)
        e.raw(bytes.fromhex("89 50 04 5a 59 c3"))
        e.label("get_native")
        e.raw(bytes.fromhex("5a 59"))
        site = p.site("vr.client_point")
        e.raw(site.original)
        e.jump_absolute(site.va + len(site.original))

        e.label("set_point")
        e.raw(b"\x50")
        e.call("active")
        e.raw(bytes.fromhex("85 c0 58"))
        e.jump_if(Condition.EQUAL, "set_native")
        e.raw(bytes.fromhex("b8 01 00 00 00 c3"))
        e.label("set_native")
        site = p.site("vr.set_client_point")
        e.raw(site.original)
        e.jump_absolute(site.va + len(site.original))

        for event in self._events:
            e.label(f"host_{event}")
            e.raw(bytes.fromhex("9c 50"))
            state(b"\x83\x3d", self._dispatching)
            e.raw(b"\x00")
            e.jump_if(Condition.NOT_EQUAL, f"native_{event}")
            e.call("active")
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, f"native_{event}")
            e.raw(bytes.fromhex("58 9d 31 c0 c2 04 00"))
            e.label(f"native_{event}")
            e.raw(bytes.fromhex("58 9d"))
            e.jump_absolute(p.address(f"input.{event}"))

        e.label("clear_host_keys")
        e.raw(bytes.fromhex("9c 60 fc 31 c0"))
        state(b"\xbf", self._host_keys)
        e.raw(bytes.fromhex("b9 10 00 00 00 f3 ab 61 9d c3"))
        e.label("cancel_host_modifiers")
        e.raw(bytes.fromhex("9c 60"))
        for key, mask in ((0x10, 8), (0x11, 16), (0x12, 32)):
            absolute(b"\x8b\x0d", p.address("engine.loop"))
            e.raw(bytes.fromhex("85 c9"))
            e.jump_if(Condition.EQUAL, "modifiers_cancelled")
            e.raw(bytes.fromhex("f7 81 18 05 00 00") + struct.pack("<I", mask))
            e.jump_if(Condition.EQUAL, f"modifier_released_{key}")
            e.push_imm32(0xC0000001)
            e.push_imm32(key)
            e.call_absolute(p.site("vr.key_up").va)
            state(b"\xff\x05", self._calls)
            e.label(f"modifier_released_{key}")
        e.label("modifiers_cancelled")
        e.raw(bytes.fromhex("61 9d c3"))
        for event in self._keyboard_events:
            native_label = f"native_host_{event}"
            rejected = f"reject_host_{event}"
            e.label(f"host_{event}")
            e.raw(bytes.fromhex("9c 60"))
            e.call("active")
            e.raw(bytes.fromhex("85 c0"))
            e.jump_if(Condition.EQUAL, native_label)
            # Native Win32 keyboard callbacks own two arguments (VK/character,
            # LPARAM flags). Preserve the complete thiscall ABI and registers.
            # Scan code plus extended-key flag occupy LPARAM bits 16..24.
            e.raw(bytes.fromhex("8b 54 24 2c c1 ea 10 81 e2 ff 01 00 00"))
            if event != "key_up":
                state(b"\x83\x3d", self._host_focus)
                e.raw(b"\x00")
                e.jump_if(Condition.NOT_EQUAL, f"focused_host_{event}")
                e.call("cancel_host_modifiers")
                e.call("clear_host_keys")
                e.jump(rejected)
                e.label(f"focused_host_{event}")
                if event == "key_down":
                    e.raw(bytes.fromhex("f7 44 24 2c 00 00 00 40"))
                    e.jump_if(Condition.NOT_EQUAL, f"repeat_host_{event}")
                    state(bytes.fromhex("0f ab 15"), self._host_keys)
                    e.jump(native_label)
                    e.label(f"repeat_host_{event}")
                state(bytes.fromhex("0f a3 15"), self._host_keys)
                e.jump_if(Condition.ABOVE_OR_EQUAL, rejected)  # BT: CF=0 means not accepted.
            # TranslateMessage can enqueue WM_CHAR behind an already queued
            # key-up. Keep that stroke's permission until XR focus changes;
            # native key-up still retires modifiers/keys in the original game.
            e.label(native_label)
            e.raw(bytes.fromhex("61 9d"))
            name = "character_event" if event == "character" else event
            e.jump_absolute(p.site(f"vr.{name}").va)
            if event != "key_up":
                e.label(rejected)
                e.raw(bytes.fromhex("61 9d 31 c0 c2 08 00"))

        e.label("button_wait")
        # Button::Activate repaints before and after Sleep(70)/Sleep(50), then
        # invokes its ordinary callback. Neither sleep advances native animation
        # or XR; omitting these feedback delays cannot add a simulation tick or
        # bypass a native lock. Redirect only this button's imported call target,
        # never the process-wide Sleep import or unrelated waits.
        e.raw(bytes.fromhex("8b 44 24 04 83 f8 46"))
        e.jump_if(Condition.EQUAL, "button_wait_check")
        e.raw(bytes.fromhex("83 f8 32"))
        e.jump_if(Condition.NOT_EQUAL, "button_wait_native")
        e.label("button_wait_check")
        absolute(b"\x83\x3d", self.panel.enabled_va)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "button_wait_native")
        absolute(b"\x83\x3d", self.panel.submitted_frames_va)
        e.raw(b"\x00")
        e.jump_if(Condition.EQUAL, "button_wait_native")
        absolute(b"\x83\x3d", self.panel.completion_result_va)
        e.raw(b"\x00")
        e.jump_if(Condition.NOT_EQUAL, "button_wait_native")
        e.raw(bytes.fromhex("31 c0 c2 04 00"))
        e.label("button_wait_native")
        absolute(b"\xff\x25", p.address("win32.Sleep"))

        code = e.build(maximum_size=0x1F00)
        labels = {name: address for name, _offset, address in e.listing()}
        payload = SegmentPayloadBuilder(
            owner="vr_input", segment=self.section_name, size=self.section_size
        )
        header = bytearray(0x100)
        header[:8] = self._magic
        struct.pack_into("<2i", header, self._point, -10000, -10000)
        payload.place(label="input state", offset=0, payload=bytes(header))
        payload.place(label="native input router", offset=self._code, payload=code)
        return payload.build(), labels
