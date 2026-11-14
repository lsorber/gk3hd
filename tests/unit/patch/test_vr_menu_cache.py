"""Execute independent menu-surface lifetime and failure recovery."""

from __future__ import annotations

import struct

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from gk3hd.patch.definitions.vr_menu import (
    build_menu_cache_destructor,
    build_menu_cache_prepare,
    build_menu_cache_release,
    build_menu_cache_validate,
    menu_destination_state,
)

_PREPARE, _RELEASE, _STOP, _CREATE, _DESCRIBE, _FILL, _COM_RELEASE = range(
    0x880000, 0x887000, 0x1000
)
_STATE, _ORIGINAL, _DD, _PAGE, _CACHE, _VTABLE, _GLOBALS, _STACK = range(0x900000, 0x908000, 0x1000)
_VALIDATE, _READABLE, _DESTRUCTOR, _NATIVE_DESTRUCTOR = range(0x887000, 0x88B000, 0x1000)
_ROOT, _CLASS = 0x908000, 0x12345678
_SET_KEY = 0x88B000


def _words(cpu: Uc, address: int, count: int = 1) -> tuple[int, ...]:
    return struct.unpack(f"<{count}I", cpu.mem_read(address, count * 4))


def _write(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack(f"<{len(values)}I", *values))


class _CacheMachine:
    def __init__(
        self, size: tuple[int, int] = (1280, 800), *, source_key: int | None = None
    ) -> None:
        self.cpu = Uc(UC_ARCH_X86, UC_MODE_32)
        self.cpu.mem_map(0x880000, 0x90000)
        self.size = size
        self.source_key = source_key
        self.fault = ""
        self.calls: list[str] = []
        self.cpu.mem_write(_STATE, menu_destination_state(_STATE))
        _write(self.cpu, _STATE, 1)
        _write(self.cpu, _GLOBALS, _DD)
        _write(self.cpu, _GLOBALS + 4, *size, 9, _READABLE)
        _write(self.cpu, _ROOT, _CLASS)
        _write(self.cpu, _ROOT + 0x18, 1)
        _write(self.cpu, _ORIGINAL + 0x2C, _PAGE)
        _write(self.cpu, _ORIGINAL + 0x38, *size)
        for obj in (_DD, _PAGE, _CACHE):
            _write(self.cpu, obj, _VTABLE)
        for slot, function in (
            (8, _COM_RELEASE),
            (0x18, _CREATE),
            (0x58, _DESCRIBE),
            (0x14, _FILL),
            (0x74, _SET_KEY),
        ):
            _write(self.cpu, _VTABLE + slot, function)
        self.cpu.mem_write(
            _PREPARE,
            build_menu_cache_prepare(
                wrapper_va=_PREPARE,
                state_va=_STATE,
                release_va=_RELEASE,
                directdraw_owner_va=_GLOBALS,
                source_key=source_key,
            ),
        )
        self.cpu.mem_write(_RELEASE, build_menu_cache_release(wrapper_va=_RELEASE, state_va=_STATE))
        self.cpu.mem_write(
            _VALIDATE,
            build_menu_cache_validate(
                wrapper_va=_VALIDATE,
                state_va=_STATE,
                release_va=_RELEASE,
                class_vtable=_CLASS,
                directdraw_owner_va=_GLOBALS,
                dimensions_va=_GLOBALS + 4,
                generation_va=_GLOBALS + 12,
                readable_iat_va=_GLOBALS + 16,
            ),
        )
        self.cpu.mem_write(
            _DESTRUCTOR,
            build_menu_cache_destructor(
                wrapper_va=_DESTRUCTOR,
                state_va=_STATE,
                release_va=_RELEASE,
                target_va=_NATIVE_DESTRUCTOR,
            ),
        )
        self.cpu.mem_write(_READABLE, bytes.fromhex("c2 08 00"))
        self.cpu.mem_write(_NATIVE_DESTRUCTOR, bytes.fromhex("b8 d2 04 00 00 c2 04 00"))
        for function, cleanup in (
            (_CREATE, 16),
            (_DESCRIBE, 8),
            (_FILL, 24),
            (_COM_RELEASE, 4),
            (_SET_KEY, 12),
        ):
            self.cpu.mem_write(function, b"\xc2" + struct.pack("<H", cleanup))
        self.cpu.hook_add(UC_HOOK_CODE, self._com)

    def run(self, entry: int = _PREPARE, *, root: int = 21) -> int:
        registers = {
            UC_X86_REG_EBP: 17,
            UC_X86_REG_EBX: 19,
            UC_X86_REG_ECX: root,
            UC_X86_REG_EDI: 23,
            UC_X86_REG_ESI: _ORIGINAL,
            UC_X86_REG_EAX: 999,
        }
        for register, value in registers.items():
            self.cpu.reg_write(register, value)
        self.cpu.reg_write(UC_X86_REG_ESP, _STACK)
        self.cpu.reg_write(UC_X86_REG_EFLAGS, 0x202)
        _write(self.cpu, _STACK, _STOP, 7)
        self.cpu.emu_start(entry, _STOP, count=4000)
        assert self.cpu.reg_read(UC_X86_REG_ESP) == _STACK + (8 if entry == _DESTRUCTOR else 4)
        assert self.cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202
        for register, value in registers.items():
            if register != UC_X86_REG_EAX or entry == _RELEASE:
                assert self.cpu.reg_read(register) == value
        return self.cpu.reg_read(UC_X86_REG_EAX)

    def _com(self, cpu: Uc, address: int, _size: int, _data: object) -> None:
        stack = cpu.reg_read(UC_X86_REG_ESP)
        if address == _CREATE:
            self.calls.append("create")
            owner, desc, output, outer = _words(cpu, stack + 4, 4)
            assert owner == _words(cpu, _GLOBALS)[0]
            assert outer == 0
            assert _words(cpu, desc, 4) == (108, 0x1007, self.size[1], self.size[0])
            assert _words(cpu, desc + 0x48, 9) == (32, 0x40, 0, 16, 0xF800, 0x7E0, 0x1F, 0, 0x840)
            _write(cpu, output, 0 if self.fault == "null_create" else _CACHE)
            cpu.reg_write(UC_X86_REG_EAX, 0x80004005 if self.fault == "create" else 0)
        elif address == _DESCRIBE:
            self._describe(cpu, stack)
        elif address == _FILL:
            self.calls.append("fill")
            assert _words(cpu, stack + 4, 6) == (_CACHE, 0, 0, 0, 0x1000400, _STATE + 0x300)
            assert _words(cpu, _STATE + 0x300)[0] == 100
            assert _words(cpu, _STATE + 0x350)[0] == (self.source_key or 0)
            cpu.reg_write(UC_X86_REG_EAX, 0x80004005 if self.fault == "fill" else 0)
        elif address == _SET_KEY:
            self.calls.append("set_key")
            assert _words(cpu, stack + 4, 3) == (_CACHE, 8, _STATE + 0x360)
            assert _words(cpu, _STATE + 0x360, 2) == (self.source_key, self.source_key)
            cpu.reg_write(UC_X86_REG_EAX, 0x80004005 if self.fault == "key" else 0)
        elif address == _COM_RELEASE:
            self.calls.append("release")
            assert _words(cpu, stack + 4)[0] == _CACHE
            assert _words(cpu, _STATE + 4, 4) == (0, 0, 0, 0)
            assert _words(cpu, _STATE + 40)[0] == 0
            cpu.reg_write(UC_X86_REG_EAX, 0)
        elif address == _READABLE:
            assert _words(cpu, stack + 4, 2) == (_ROOT, 28)
            cpu.reg_write(UC_X86_REG_EAX, self.fault == "root_readable")
        elif address == _NATIVE_DESTRUCTOR:
            self.calls.append("native_destructor")
            assert _words(cpu, stack + 4)[0] == 7
            assert cpu.reg_read(UC_X86_REG_EFLAGS) == 0x202

    def _describe(self, cpu: Uc, stack: int) -> None:
        surface, descriptor = _words(cpu, stack + 4, 2)
        assert surface in (_PAGE, _CACHE)
        source = surface == _PAGE
        self.calls.append("describe_page" if source else "describe_cache")
        assert _words(cpu, descriptor)[0] == 108
        assert cpu.mem_read(descriptor + 4, 104) == bytes(104)
        words = [0] * 27
        words[:4] = (108, 0x1007, self.size[1], self.size[0])
        words[4] = self.size[0] * 2
        words[18:27] = (32, 0x40, 0, 16, 0xF800, 0x7E0, 0x1F, 0, 0x4000 if source else 0x840)
        if self.fault == ("page_format" if source else "cache_format"):
            words[21] = 32
        if self.fault == "cache_dimensions" and not source:
            words[2] += 1
        if self.fault == "cache_video" and not source:
            words[26] = 0x4000
        if self.fault == "page_flags" and source:
            words[1] = 7
        if self.fault == "cache_alpha" and not source:
            words[25] = 0x8000
        if self.fault == "cache_caps_flags" and not source:
            words[1] &= ~1
        _write(cpu, descriptor, *words)
        cpu.reg_write(
            UC_X86_REG_EAX,
            0x80004005 if self.fault == ("page_desc" if source else "cache_desc") else 0,
        )

    def publish(self) -> None:
        assert self.run() == 1
        _write(self.cpu, _STATE + 32, _ROOT)
        _write(self.cpu, _STATE + 0x70, 1, 5, 9)
        self.calls.clear()


@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (3840, 2160)])
def test_menu_cache_is_reused_and_cleared_without_source_page_readback(
    size: tuple[int, int],
) -> None:
    fixture = _CacheMachine(size)
    assert fixture.run() == 1
    assert fixture.calls == ["describe_page", "create", "describe_cache", "fill"]
    assert _words(fixture.cpu, _STATE + 4, 4) == (_CACHE, *size, _DD)
    assert _words(fixture.cpu, _STATE + 40)[0] == 1
    fixture.calls.clear()
    assert fixture.run() == 1
    assert fixture.calls == ["describe_page", "describe_cache", "fill"]
    assert fixture.run(_RELEASE) == 999
    fixture.calls.clear()
    fixture.run(_RELEASE)
    assert not fixture.calls, "repeat withdrawal must not double-release"


@pytest.mark.parametrize("change", ["width", "height", "owner"])
def test_menu_cache_releases_before_replacement(change: str) -> None:
    fixture = _CacheMachine()
    assert fixture.run() == 1
    if change == "owner":
        _write(fixture.cpu, _GLOBALS, _DD + 16)
        _write(fixture.cpu, _DD + 16, _VTABLE)
    else:
        fixture.size = (1024, 800) if change == "width" else (1280, 768)
        _write(fixture.cpu, _ORIGINAL + 0x38, *fixture.size)
    fixture.calls.clear()
    assert fixture.run() == 1
    assert fixture.calls == ["describe_page", "release", "create", "describe_cache", "fill"]
    assert _words(fixture.cpu, _STATE + 4, 4) == (
        _CACHE,
        *fixture.size,
        _words(fixture.cpu, _GLOBALS)[0],
    )


@pytest.mark.parametrize(
    "fault",
    [
        "create",
        "null_create",
        "page_desc",
        "cache_desc",
        "page_format",
        "cache_format",
        "cache_dimensions",
        "cache_video",
        "page_flags",
        "cache_alpha",
        "cache_caps_flags",
        "fill",
    ],
)
def test_menu_cache_failure_withdraws_and_recovers_lazily(fault: str) -> None:
    fixture = _CacheMachine()
    fixture.fault = fault
    assert fixture.run() == 0
    assert _words(fixture.cpu, _STATE + 4, 4) == (0, 0, 0, 0)
    assert _words(fixture.cpu, _STATE + 40)[0] == 0
    fixture.fault = ""
    assert fixture.run() == 1
    assert _words(fixture.cpu, _STATE + 4)[0] == _CACHE


@pytest.mark.parametrize(
    "change",
    [
        "disabled",
        "unknown_mode",
        "dd_missing",
        "page_missing",
        "width_zero",
        "height_negative",
        "width_oversized",
        "canvas_oversized",
        "page_format",
        "cache_desc",
        "fill",
    ],
)
def test_existing_menu_cache_is_not_retained_after_invalid_preparation(change: str) -> None:
    fixture = _CacheMachine()
    assert fixture.run() == 1
    if change in ("disabled", "unknown_mode"):
        _write(fixture.cpu, _STATE, 0 if change == "disabled" else 2)
    elif change == "dd_missing":
        _write(fixture.cpu, _GLOBALS, 0)
    elif change == "page_missing":
        _write(fixture.cpu, _ORIGINAL + 0x2C, 0)
    elif change == "width_zero":
        _write(fixture.cpu, _ORIGINAL + 0x38, 0)
    elif change == "height_negative":
        _write(fixture.cpu, _ORIGINAL + 0x3C, 0xFFFFFFFF)
    elif change == "width_oversized":
        _write(fixture.cpu, _ORIGINAL + 0x38, 8193)
    elif change == "canvas_oversized":
        _write(fixture.cpu, _ORIGINAL + 0x38, 8192, 8192)
    else:
        fixture.fault = change
    fixture.calls.clear()
    assert fixture.run() == 0
    assert fixture.calls.count("release") == 1
    assert _words(fixture.cpu, _STATE + 4, 4) == (0, 0, 0, 0)
    assert _words(fixture.cpu, _STATE + 40)[0] == 0


def test_busy_menu_cannot_be_cleared_or_released_mid_traversal() -> None:
    fixture = _CacheMachine()
    assert fixture.run() == 1
    _write(fixture.cpu, _STATE + 20, 1)
    fixture.calls.clear()
    assert fixture.run() == 0
    fixture.run(_RELEASE)
    assert not fixture.calls
    assert _words(fixture.cpu, _STATE + 4)[0] == _CACHE
    assert _words(fixture.cpu, _STATE + 40)[0] == 1


def test_current_menu_is_validated_without_recreating_or_copying_pixels() -> None:
    fixture = _CacheMachine()
    fixture.publish()
    assert fixture.run(_VALIDATE) == 1
    assert not fixture.calls
    assert _words(fixture.cpu, _STATE + 0x70)[0] == 1


@pytest.mark.parametrize(
    "change",
    [
        "hidden",
        "missing_root",
        "foreign_class",
        "root_readable",
        "owner",
        "width",
        "height",
        "disabled",
        "unknown_mode",
    ],
)
def test_invalid_live_menu_releases_and_withdraws_its_publication(change: str) -> None:
    fixture = _CacheMachine()
    fixture.publish()
    if change == "hidden":
        _write(fixture.cpu, _ROOT + 0x18, 0)
    elif change == "missing_root":
        _write(fixture.cpu, _STATE + 32, 0)
    elif change == "foreign_class":
        _write(fixture.cpu, _ROOT, _CLASS + 4)
    elif change == "root_readable":
        fixture.fault = change
    elif change == "owner":
        _write(fixture.cpu, _GLOBALS, _DD + 16)
    elif change == "width":
        _write(fixture.cpu, _GLOBALS + 4, 1024)
    elif change == "height":
        _write(fixture.cpu, _GLOBALS + 8, 768)
    else:
        _write(fixture.cpu, _STATE, 0 if change == "disabled" else 2)
    assert fixture.run(_VALIDATE) == 0
    assert fixture.calls == ["release"]
    assert _words(fixture.cpu, _STATE + 4)[0] == 0
    assert _words(fixture.cpu, _STATE + 32)[0] == 0
    assert _words(fixture.cpu, _STATE + 0x70)[0] == 0


@pytest.mark.parametrize("change", ["stale_page", "not_ready", "busy"])
def test_a_noncurrent_menu_cannot_publish_but_keeps_the_reusable_surface(change: str) -> None:
    fixture = _CacheMachine()
    fixture.publish()
    offset, value = {
        "stale_page": (_GLOBALS + 12, 10),
        "not_ready": (_STATE + 0x70, 0),
        "busy": (_STATE + 20, 1),
    }[change]
    _write(fixture.cpu, offset, value)
    assert fixture.run(_VALIDATE) == 0
    assert not fixture.calls
    assert _words(fixture.cpu, _STATE + 4)[0] == _CACHE
    assert _words(fixture.cpu, _STATE + 0x70)[0] == 0


@pytest.mark.parametrize("owner", [True, False])
def test_only_the_exact_menu_destructor_releases_before_native_teardown(*, owner: bool) -> None:
    fixture = _CacheMachine()
    fixture.publish()
    assert fixture.run(_DESTRUCTOR, root=_ROOT if owner else _ROOT + 256) == 1234
    assert fixture.calls == (["release", "native_destructor"] if owner else ["native_destructor"])
    assert _words(fixture.cpu, _STATE + 4)[0] == (0 if owner else _CACHE)
    assert _words(fixture.cpu, _STATE + 32)[0] == (0 if owner else _ROOT)
    assert _words(fixture.cpu, _STATE + 0x70)[0] == int(not owner)


def test_reentrant_release_cannot_release_the_same_cache_twice() -> None:
    fixture = _CacheMachine()
    fixture.publish()
    fixture.cpu.mem_write(
        _COM_RELEASE,
        b"\xe8"
        + struct.pack("<i", _RELEASE - (_COM_RELEASE + 5))
        + bytes.fromhex("31 c0 c2 04 00"),
    )
    assert fixture.run(_RELEASE) == 999
    assert fixture.calls == ["release"]
    assert _words(fixture.cpu, _STATE + 4)[0] == 0


@pytest.mark.parametrize("source_key", [0, 1, 0xF81F, 0xFFFF])
def test_glyph_cache_has_an_explicit_source_key_on_each_preparation(source_key: int) -> None:
    fixture = _CacheMachine(source_key=source_key)
    assert fixture.run() == 1
    assert fixture.calls == ["describe_page", "create", "describe_cache", "set_key", "fill"]
    fixture.calls.clear()
    assert fixture.run() == 1
    assert fixture.calls == ["describe_page", "describe_cache", "set_key", "fill"]


def test_failed_source_key_setup_cannot_leave_a_ready_or_stale_glyph_cache() -> None:
    fixture = _CacheMachine(source_key=1)
    assert fixture.run() == 1
    fixture.fault = "key"
    fixture.calls.clear()
    assert fixture.run() == 0
    assert fixture.calls == ["describe_page", "describe_cache", "set_key", "release"]
    assert _words(fixture.cpu, _STATE + 4, 4) == (0, 0, 0, 0)
    assert _words(fixture.cpu, _STATE + 40)[0] == 0
    fixture.fault = ""
    assert fixture.run() == 1


@pytest.mark.parametrize("source_key", [-1, 0x10000])
def test_non_rgb565_key_is_rejected_before_emission(source_key: int) -> None:
    with pytest.raises(ValueError, match="source key"):
        _CacheMachine(source_key=source_key)
