"""Execute menu ownership, native layer callbacks and single-use XR intent."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from unicorn import UC_HOOK_CODE, UC_PROT_EXEC, UC_PROT_READ
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

from gk3hd.patch.binary.x86 import X86Emitter
from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS
from gk3hd.patch.definitions.vr_game_menu import VRGameMenuCompiler
from gk3hd.patch.definitions.vr_ownership import VROwnershipCompiler
from gk3hd.patch.definitions.vr_protagonist import VRProtagonistCompiler
from gk3hd.patch.definitions.vr_return import VRReturnCompiler
from gk3hd.patch.definitions.vr_scene import VRSceneCompiler
from gk3hd.patch.model import PatchError
from tests.unit.patch.test_vr_panel import _linked_panel
from tests.unit.patch.test_vr_scene import _HEAP, _RETURN, _STACK, _machine

if TYPE_CHECKING:
    from unicorn import Uc

    from gk3hd.patch.builds import BuildProfile


class MenuHarness:
    """Model native recipients and XR output, without duplicating the router."""

    module = _HEAP + 0xB000
    resolver = _HEAP + 0xB100
    bridge = _HEAP + 0xB200
    quit = _HEAP + 0xB300

    def __init__(self, *, linked_return: bool = False) -> None:
        image, self.panel, self.previous = _linked_panel(paired=True)
        self.return_abi = None
        if linked_return:
            scene = VRSceneCompiler(profile=GOG_BUILD, units_per_meter=40).abi(image)
            owner = VROwnershipCompiler(profile=GOG_BUILD, panel=self.panel, scene=scene)
            owner.apply(image)
            protagonist = VRProtagonistCompiler(profile=GOG_BUILD)
            protagonist.apply(image)
            observer = VRReturnCompiler(
                profile=GOG_BUILD,
                panel=self.panel,
                scene=scene,
                ownership=owner.abi(image),
                protagonist=protagonist.abi(image),
            )
            observer.apply(image)
            observer.postcheck(image)
            self.return_abi = observer.abi(image)
        self.return_allowed = True
        self.return_requests: list[int] = []
        self.compiler = VRGameMenuCompiler(
            profile=GOG_BUILD,
            panel=self.panel,
            expected_presenter_va=self.previous,
            observer_return=self.return_abi,
        )
        self.compiler.apply(image)
        self.compiler.postcheck(image)
        self.image = image
        self.abi = self.compiler.abi(image)
        self.machine = _machine(image)
        self.machine.mem_map(0, 0x1000)
        self.word(0, 0x12345678)
        self.engine, self.services, self.manager, self.scene = (
            _HEAP + off for off in (0x1000, 0x2000, 0x3000, 0x4000)
        )
        self.root = _HEAP + 0x5000
        self.pause = _HEAP + 0x6000
        self.save = _HEAP + 0x7000
        self.restore = _HEAP + 0x8000
        self.owner = self.root
        self.parents: list[int] = []
        self.calls: list[tuple[str, int]] = []
        self.requests: list[tuple[int, int]] = []
        self.reply: tuple[int, int] = (0, 0)
        self.bridge_available = True
        self.bridge_hresult = 0
        self.presented = self.composed = 0
        self.initialize_engine()
        self.initialize_callbacks()
        self.machine.hook_add(UC_HOOK_CODE, self.observe)
        self.snapshot()

    def initialize_engine(self) -> None:
        for address, value in (
            (GOG_BUILD.address("engine.loop"), self.engine),
            (self.engine + 0x444, self.services),
            (self.services + 0x48, self.manager),
            (GOG_BUILD.address("vr.room_global"), self.scene),
            (self.scene, GOG_BUILD.address("vr.user_scene_vtable")),
            (self.root, GOG_BUILD.address("vr.room_layer_vtable")),
            (self.pause, GOG_BUILD.address("pause.vtable")),
            (self.save, GOG_BUILD.address("savegame.vtable")),
            (self.restore, GOG_BUILD.address("restoregame.vtable")),
            (self.abi.enabled_va, 1),
            (self.panel.enabled_va, 1),
            (self.panel.submitted_frames_va, 1),
            (GOG_BUILD.address("high_resolution_3d.render_wrapper_ptr"), _HEAP + 0xC000),
            (_HEAP + 0xC4E8, _HEAP + 0xC800),
        ):
            self.word(address, value)

    def initialize_callbacks(self) -> None:
        if self.return_abi is not None:
            for address, cleanup in (
                (self.return_abi.available_va, 4),
                (self.return_abi.request_va, 4),
                (self.return_abi.tick_va, 0),
                (self.return_abi.cancel_va, 0),
            ):
                self.machine.mem_write(
                    address, b"\xc3" if not cleanup else b"\xc2" + struct.pack("<H", cleanup)
                )
        for address, cleanup in (
            (self.previous, 0),
            (self.panel.composition_presenter_va, 0),
            (GOG_BUILD.address("ui.current_layer"), 0),
            (GOG_BUILD.site("vr.layer_show").va, 8),
            (GOG_BUILD.site("vr.layer_hide").va, 4),
            (self.module, 4),
            (self.resolver, 8),
            (self.bridge, 8),
            (self.quit, 4),
        ):
            self.machine.mem_write(
                address, b"\xc3" if not cleanup else b"\xc2" + struct.pack("<H", cleanup)
            )
        for name, target in (
            ("win32.GetModuleHandleA", self.module),
            ("win32.GetProcAddress", self.resolver),
            ("win32.PostQuitMessage", self.quit),
        ):
            self.word(GOG_BUILD.address(name), target)

    def word(self, address: int, value: int) -> None:
        self.machine.mem_write(address, struct.pack("<I", value))

    def read(self, address: int) -> int:
        return struct.unpack("<I", self.machine.mem_read(address, 4))[0]

    def snapshot(self, held: int = 0, *, pressed: int | None = None, focused: bool = True) -> None:
        for offset, value in (
            (16, 1),
            (64, int(focused)),
            (68, 1),
            (116, 1),
            (168, 1),
            (180, held),
            (184, held if pressed is None else pressed),
        ):
            self.word(self.panel.frame_va + offset, value)

    def invoke(self) -> None:
        self.machine.mem_write(_STACK, struct.pack("<I", _RETURN))
        self.machine.reg_write(UC_X86_REG_ESP, _STACK)
        self.machine.emu_start(self.abi.presenter_va, _RETURN, count=4000)
        assert self.machine.reg_read(UC_X86_REG_ESP) == _STACK + 4
        assert self.read(0) == 0x12345678

    def open(self) -> None:
        self.invoke()
        self.snapshot(4)
        self.invoke()
        assert self.owner == self.pause

    def observe(self, current: Uc, address: int, _size: int, _context: object) -> None:
        self.observe_return(current, address)
        if address == self.previous:
            self.presented += 1
        if address == self.panel.composition_presenter_va:
            self.composed += 1
        if address == GOG_BUILD.address("ui.current_layer"):
            current.reg_write(UC_X86_REG_EAX, self.owner)
        if address == self.module:
            current.reg_write(UC_X86_REG_EAX, 1)
        if address == self.resolver:
            current.reg_write(UC_X86_REG_EAX, self.bridge if self.bridge_available else 0)
        if address == self.bridge:
            self.observe_bridge(current)
        if address == GOG_BUILD.site("vr.layer_show").va:
            self.observe_show(current)
        if address == GOG_BUILD.site("vr.layer_hide").va:
            assert current.reg_read(UC_X86_REG_ECX) == self.manager
            assert self.read(current.reg_read(UC_X86_REG_ESP) + 4) == 13
            self.calls.append(("hide", 13))
            self.owner = self.parents.pop()
        if address == self.quit:
            assert self.read(current.reg_read(UC_X86_REG_ESP) + 4) == 0
            self.calls.append(("quit", 0))

    def observe_return(self, current: Uc, address: int) -> None:
        if self.return_abi is not None:
            if address == self.return_abi.available_va:
                current.reg_write(
                    UC_X86_REG_EAX, int(self.return_allowed and self.owner == self.root)
                )
            elif address == self.return_abi.request_va:
                assert self.owner == self.root, "Return was requested before leaving Pause"
                prior = self.read(current.reg_read(UC_X86_REG_ESP) + 4)
                assert prior == self.root
                self.return_requests.append(prior)
                current.reg_write(UC_X86_REG_EAX, 1)

    def observe_show(self, current: Uc) -> None:
        assert current.reg_read(UC_X86_REG_ECX) == self.manager
        index, flag = struct.unpack(
            "<2I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 8)
        )
        assert flag == 1
        self.calls.append(("show", index))
        self.parents.append(self.owner)
        self.owner = {13: self.pause, 14: self.save, 9: self.restore}[index]
        current.reg_write(UC_X86_REG_ECX, 0xBAD)  # Native calls may clobber volatile registers.

    def observe_bridge(self, current: Uc) -> None:
        device, request = struct.unpack(
            "<2I", current.mem_read(current.reg_read(UC_X86_REG_ESP) + 4, 8)
        )
        assert device == _HEAP + 0xC800
        assert self.read(request) == 20
        self.requests.append((self.read(request + 4), self.read(request + 8)))
        self.word(request + 12, self.reply[0])
        self.word(request + 16, self.reply[1])
        self.reply = (0, 0)
        current.reg_write(UC_X86_REG_EAX, self.bridge_hresult)


def test_controller_menu_preserves_native_owner_and_resume_runs_once() -> None:
    h = MenuHarness()
    h.open()
    assert h.calls == [("show", 13)]
    assert h.read(h.abi.owner_va) == h.pause
    assert h.read(h.panel.frame_va + 64) == 1, "modal ownership must not falsify runtime focus"
    assert h.read(h.panel.frame_va + 180) == h.read(h.panel.frame_va + 184) == 0
    epoch = h.read(h.abi.epoch_va)
    h.reply = (epoch, 1)
    h.snapshot()
    h.invoke()
    h.invoke()
    assert h.calls == [("show", 13), ("hide", 13)]
    assert h.owner == h.root
    assert h.parents == []
    assert h.read(h.abi.accepted_va) == 1


def test_optional_filter_can_withdraw_held_menu_and_deliver_a_completed_tap() -> None:
    h = MenuHarness()
    callback = _HEAP + 0xE100
    decision = _HEAP + 0xE200
    h.word(h.abi.shortcut_filter_slot_va, callback)
    h.machine.mem_write(callback, b"\x8b\x15" + struct.pack("<I", decision) + b"\xc3")
    h.word(decision, 0)
    h.snapshot(held=4)
    h.invoke()
    assert h.calls == []
    h.word(decision, 4)
    h.snapshot(held=0, pressed=0)
    h.invoke()
    assert h.calls == [("show", 13)]


def test_return_menu_resumes_its_room_before_requesting_one_observer_transaction() -> None:
    h = MenuHarness(linked_return=True)
    h.open()
    assert h.requests[-1][1] & 64
    h.reply = (h.read(h.abi.epoch_va), 6)
    h.snapshot()
    h.invoke()
    h.invoke()
    assert h.calls == [("show", 13), ("hide", 13)]
    assert h.return_requests == [h.root]


@pytest.mark.parametrize("inventory", [False, True])
def test_unavailable_or_interface_return_is_disabled_and_rejects_injected_intent(
    inventory: bool,
) -> None:
    h = MenuHarness(linked_return=True)
    if inventory:
        h.owner = h.root + 0x100
        h.word(h.owner, GOG_BUILD.address("inventory.vtable"))
    else:
        h.return_allowed = False
    h.open()
    assert not h.requests[-1][1] & 64
    h.reply = (h.read(h.abi.epoch_va), 6)
    h.snapshot()
    h.invoke()
    assert h.owner == h.pause
    assert h.return_requests == []


@pytest.mark.parametrize(("command", "target"), [(2, "save"), (3, "restore")])
def test_save_and_load_use_original_dialogs_after_leaving_pause(command: int, target: str) -> None:
    h = MenuHarness()
    h.owner = h.root + 0x100
    h.word(h.owner, GOG_BUILD.address("inventory.vtable"))
    inventory = h.owner
    h.open()
    h.reply = (h.read(h.abi.epoch_va), command)
    h.snapshot()
    h.invoke()
    assert h.owner == getattr(h, target)
    assert h.parents == [inventory]
    assert h.calls == [("show", 13), ("hide", 13), ("show", 14 if command == 2 else 9)]


def test_only_an_epoch_qualified_confirmed_quit_reaches_normal_shutdown() -> None:
    h = MenuHarness()
    h.open()
    h.reply = (h.read(h.abi.epoch_va) - 1, 7)
    h.snapshot()
    h.invoke()
    assert h.calls == [("show", 13)]
    assert h.read(h.abi.rejected_va) == 1
    h.reply = (h.read(h.abi.epoch_va), 7)
    h.invoke()
    h.invoke()
    assert h.calls.count(("quit", 0)) == 1


@pytest.mark.parametrize(
    "reason",
    [
        "focus",
        "tracking",
        "producer",
        "completion",
        "empty",
        "disabled",
        "no_bridge",
        "bridge_failure",
    ],
)
def test_unavailable_owner_never_opens_pause(reason: str) -> None:
    h = MenuHarness()
    h.invoke()
    h.snapshot(4, focused=reason != "focus")
    if reason == "tracking":
        h.word(h.panel.frame_va + 68, 0)
        h.word(h.panel.frame_va + 116, 0)
    for state, address, value in (
        ("producer", h.panel.result_va, 1),
        ("completion", h.panel.completion_result_va, 1),
        ("empty", h.panel.submitted_frames_va, 0),
        ("disabled", h.abi.enabled_va, 0),
        ("no_bridge", h.abi.enabled_va - h.compiler._enabled + h.compiler._bridge, 0),
    ):
        if reason == state:
            h.word(address, value)
    h.bridge_available = reason != "no_bridge"
    h.bridge_hresult = 0x80004005 if reason == "bridge_failure" else 0
    h.invoke()
    assert h.calls == []
    assert h.owner == h.root


def test_tracking_recovery_cannot_replay_an_accepted_menu_action() -> None:
    h = MenuHarness()
    h.open()
    h.reply = (h.read(h.abi.epoch_va), 1)
    h.snapshot(4, focused=False)
    h.invoke()
    h.snapshot(4)
    h.invoke()
    assert h.owner == h.pause
    assert h.calls == [("show", 13)]


@pytest.mark.parametrize("command", [4, 6, 8, 0xFFFFFFFF])
def test_unsupported_intent_cannot_leave_the_owned_menu(command: int) -> None:
    h = MenuHarness()
    h.open()
    h.reply = (h.read(h.abi.epoch_va), command)
    h.snapshot()
    h.invoke()
    assert h.owner == h.pause
    assert h.calls == [("show", 13)]
    assert h.read(h.abi.rejected_va) == 1


def test_switching_pointing_hands_invalidates_old_selection() -> None:
    h = MenuHarness()
    h.open()
    epoch = h.read(h.abi.epoch_va)
    h.reply = (epoch, 1)
    h.snapshot()
    h.word(h.panel.pointing_hand_va, h.read(h.panel.pointing_hand_va) ^ 1)
    h.invoke()
    assert h.read(h.abi.epoch_va) != epoch
    assert h.owner == h.pause
    assert h.read(h.abi.rejected_va) == 1


def test_held_menu_needs_release_after_tracking_recovers() -> None:
    h = MenuHarness()
    h.invoke()
    h.snapshot(4, focused=False)
    h.invoke()
    for _ in range(3):
        h.snapshot(4, pressed=0)
        h.invoke()
    assert h.calls == []
    h.snapshot()
    h.invoke()
    h.snapshot(4)
    h.invoke()
    assert h.calls == [("show", 13)]


@pytest.mark.parametrize("reason", ["wrapper", "device"])
def test_device_withdrawal_preserves_native_back_instead_of_cached_success(reason: str) -> None:
    h = MenuHarness()
    h.open()
    address = (
        GOG_BUILD.address("high_resolution_3d.render_wrapper_ptr")
        if reason == "wrapper"
        else _HEAP + 0xC4E8
    )
    h.word(address, 0)
    h.snapshot(2)
    h.invoke()
    assert h.read(h.abi.bridge_result_va) != 0
    assert h.read(h.panel.frame_va + 180) == 2
    assert h.owner == h.pause


@pytest.mark.parametrize("command", [2, 3])
def test_running_action_blocks_save_but_does_not_prevent_loading(command: int) -> None:
    h = MenuHarness()
    child = _HEAP + 0x9000
    h.word(h.root + 0x4C, child + 0x100)
    h.word(h.root + 0x50, 1)
    h.word(child + 0x100, child)
    h.word(child, GOG_BUILD.address("vr.action_skip_vtable"))
    h.word(child + 0x18, 0x101)  # Visible and enabled native ActionSkipper.
    h.open()
    assert h.requests[-1][1] == 8
    h.reply = (h.read(h.abi.epoch_va), command)
    h.snapshot()
    h.invoke()
    if command == 2:
        assert h.owner == h.pause
        assert h.read(h.abi.rejected_va) == 1
    else:
        assert h.owner == h.restore
        assert h.calls[-2:] == [("hide", 13), ("show", 9)]


@pytest.mark.parametrize("anchor", VRGameMenuCompiler._anchors)
def test_changed_native_layer_dependency_is_rejected_before_mutation(anchor: str) -> None:
    image, panel, previous = _linked_panel(paired=True)
    compiler = VRGameMenuCompiler(profile=GOG_BUILD, panel=panel, expected_presenter_va=previous)
    image.write_bytes(image.va_to_offset(GOG_BUILD.site(anchor).va), b"\xcc")
    before = image.to_bytes()
    with pytest.raises(PatchError, match="anchor changed"):
        compiler.apply(image)
    assert image.to_bytes() == before


def test_menu_does_not_write_its_instruction_page() -> None:
    h = MenuHarness()
    h.machine.mem_protect(h.abi.presenter_va & ~0xFFF, 0x2000, UC_PROT_READ | UC_PROT_EXEC)
    h.open()
    h.reply = (h.read(h.abi.epoch_va), 1)
    h.snapshot()
    h.invoke()
    assert h.owner == h.root


def test_native_layer_redraws_do_not_repeat_xr_or_dispatch() -> None:
    h = MenuHarness()
    address = GOG_BUILD.site("vr.layer_show").va
    e = X86Emitter(base_va=address)
    e.call_absolute(h.abi.presenter_va)
    e.raw(bytes.fromhex("c2 08 00"))
    h.machine.mem_write(address, e.build())
    h.open()
    assert h.calls == [("show", 13)]
    assert h.presented == 2
    assert h.composed == 1


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda item: str(item.id))
def test_menu_is_dormant_and_verifiable_on_each_supported_layout(profile: BuildProfile) -> None:
    image, panel, previous = _linked_panel(paired=True)
    compiler = VRGameMenuCompiler(profile=profile, panel=panel, expected_presenter_va=previous)
    compiler.apply(image)
    compiler.postcheck(image)
    assert image.read_u32_va(compiler.abi(image).enabled_va) == 0
