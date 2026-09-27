"""Execute keyboard motion hooks; preserve native modes, input scope and ABI."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_ESP,
)

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.normalize_keyboard_camera_motion import KeyboardCameraMotionCompiler


def _expected_gains(mode: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """Independent motion-mode expectations: (starting gain, maximum gain)."""
    rotation = (0.375, 2.53)
    forward = (0.3, 1.65)
    lateral = (0.16875, 1.2375)
    horizontal = rotation if mode < 3 else lateral
    vertical = rotation if mode == 2 else lateral if mode == 3 else forward
    return horizontal, vertical


@dataclass
class Motion:
    cpu: Uc = field(default_factory=lambda: Uc(UC_ARCH_X86, UC_MODE_32))
    compiler: KeyboardCameraMotionCompiler = field(
        default_factory=lambda: KeyboardCameraMotionCompiler(GOG_BUILD)
    )
    samples: list[tuple[float, float]] = field(default_factory=list)
    entry: int = 0x800000
    stack: int = 0x901000
    ticker: int = 0x902000
    configuration: int = 0x903000
    width: int = 0x904000
    stop: int = 0x905000

    def __post_init__(self) -> None:
        self.cpu.mem_map(0x400000, 0x400000)
        self.cpu.mem_map(self.entry, 0x1000)
        self.cpu.mem_map(0x900000, 0x10000)
        self.cpu.mem_write(self.entry, self.compiler._build_payload(section_va=self.entry))
        timer = 0x906000
        self.cpu.mem_write(GOG_BUILD.address("win32.timeGetTime"), struct.pack("<I", timer))
        # Deliberately clobber volatile registers, as an actual imported call may.
        self.cpu.mem_write(
            timer,
            b"\xa1"
            + struct.pack("<I", self.ticker)
            + bytes.fromhex("b9 ef be ad de ba ef be ad de c3"),
        )
        consumer = GOG_BUILD.address("camera.apply_motion")
        bridge = self.entry + self.compiler._off_conversion_bridge
        prologue = bytes.fromhex("55 89 e5 db 45 08 d9 5d 08 b8")
        prologue += struct.pack("<I", self.configuration)
        prologue += b"\xe9" + struct.pack("<i", bridge - (consumer + len(prologue) + 5))
        self.cpu.mem_write(consumer, prologue)
        continuation = GOG_BUILD.address("camera.motion_float_conversion_continue")
        self.cpu.mem_write(continuation, bytes.fromhex("83 c4 04 5d c2 0c 00"))
        self.cpu.mem_write(
            GOG_BUILD.address("high_resolution_3d.display_width_ptr"),
            struct.pack("<I", self.width),
        )
        self.cpu.mem_write(
            GOG_BUILD.address("high_resolution_3d.display_height_ptr"),
            struct.pack("<I", self.width + 4),
        )

        def observe(cpu: Uc, address: int, _size: int, _data: object) -> None:
            if address == consumer:
                assert cpu.reg_read(UC_X86_REG_ECX) == self.configuration
                assert cpu.reg_read(UC_X86_REG_EDX) == 0x12345678
            if address == continuation:
                frame = cpu.reg_read(UC_X86_REG_EBP)
                horizontal = struct.unpack("<f", cpu.mem_read(frame + 8, 4))[0]
                vertical = struct.unpack("<f", cpu.mem_read(frame + 16, 4))[0]
                self.samples.append((horizontal, vertical))

        self.cpu.hook_add(UC_HOOK_CODE, observe)

    def sample(
        self,
        tick: int,
        horizontal: int = 12,
        vertical: int = 12,
        mode: int = 0,
        size: tuple[int, int] = (1024, 768),
    ) -> tuple[float, float]:
        self.cpu.mem_write(self.ticker, struct.pack("<I", tick & 0xFFFFFFFF))
        self.cpu.mem_write(self.width, struct.pack("<2I", *size))
        self.cpu.mem_write(self.stack, struct.pack("<I3i", self.stop, horizontal, vertical, 0))
        for register, value in (
            (UC_X86_REG_ECX, self.configuration),
            (UC_X86_REG_EDX, 0x12345678),
            (UC_X86_REG_EDI, mode),
            (UC_X86_REG_EBP, 0x76543210),
            (UC_X86_REG_ESP, self.stack),
        ):
            self.cpu.reg_write(register, value)
        self.cpu.emu_start(self.entry + self.compiler._off_keyboard_wrapper, self.stop, count=400)
        assert self.cpu.reg_read(UC_X86_REG_ESP) == self.stack + 16
        assert self.cpu.reg_read(UC_X86_REG_EBP) == 0x76543210
        active = self.entry + self.compiler._off_keyboard_active
        assert bytes(self.cpu.mem_read(active, 4)) == bytes(4)
        return self.samples[-1]


@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (3840, 2160)])
@pytest.mark.parametrize("mode", range(5))
@pytest.mark.parametrize("direction", [-1, 1])
def test_every_keyboard_camera_mode_has_precise_taps_and_faster_holds(
    size: tuple[int, int], mode: int, direction: int
) -> None:
    motion = Motion()
    delta = 12 * direction
    first = motion.sample(1000, delta, delta, mode=mode, size=size)
    for tick in range(1017, 2213, 17):
        last = motion.sample(tick, delta, delta, mode=mode, size=size)
    base = delta * 17 * 0.03
    horizontal_scale = size[0] / 1024 if mode < 3 else 1
    vertical_scale = size[1] / 768 if mode == 2 else 1
    (horizontal_start, horizontal_top), (vertical_start, vertical_top) = _expected_gains(mode)
    assert first == pytest.approx(
        (base * horizontal_scale * horizontal_start, base * vertical_scale * vertical_start)
    )
    assert last == pytest.approx(
        (base * horizontal_scale * horizontal_top, base * vertical_scale * vertical_top)
    )


@pytest.mark.parametrize("axis", [0, 1])
@pytest.mark.parametrize("reset", ["reverse", "other-axis-only", "idle"])
@pytest.mark.parametrize("mode", range(5))
def test_new_motion_starts_at_precise_base_speed(axis: int, reset: str, mode: int) -> None:
    motion = Motion()
    values = [0, 0]
    values[axis] = 12
    for tick in range(1000, 2213, 17):
        motion.sample(tick, values[0], values[1], mode=mode)
    tick = 2224
    if reset == "reverse":
        values[axis] = -12
    elif reset == "other-axis-only":
        other = [12, 12]
        other[axis] = 0
        motion.sample(tick, other[0], other[1], mode=mode)
        tick += 17
    else:
        tick += 1000
    actual = motion.sample(tick, values[0], values[1], mode=mode)
    elapsed = 34 if reset == "idle" else 17
    starts = [gains[0] for gains in _expected_gains(mode)]
    assert actual == pytest.approx(
        tuple(value * elapsed * 0.03 * start for value, start in zip(values, starts, strict=True))
    )


@pytest.mark.parametrize("held_axis", [0, 1])
@pytest.mark.parametrize("mode", range(5))
def test_each_axis_starts_precisely_while_the_other_stays_accelerated(
    held_axis: int, mode: int
) -> None:
    motion = Motion()
    values = [0, 0]
    values[held_axis] = 12
    for tick in range(1000, 2213, 17):
        motion.sample(tick, values[0], values[1], mode=mode)
    actual = motion.sample(2224, mode=mode)
    gains = _expected_gains(mode)
    expected = [12 * 17 * 0.03 * start for start, _ in gains]
    expected[held_axis] = 12 * 17 * 0.03 * gains[held_axis][1]
    assert actual == pytest.approx(expected)


@pytest.mark.parametrize("axis", [0, 1])
@pytest.mark.parametrize("mode", range(5))
def test_reversing_one_axis_does_not_reset_the_other(axis: int, mode: int) -> None:
    motion = Motion()
    for tick in range(1000, 2213, 17):
        motion.sample(tick, mode=mode)
    values = [12, 12]
    values[axis] = -12
    gains = _expected_gains(mode)
    expected = [12 * 17 * 0.03 * top for _, top in gains]
    expected[axis] = -12 * 17 * 0.03 * gains[axis][0]
    assert motion.sample(2224, values[0], values[1], mode=mode) == pytest.approx(expected)


@pytest.mark.parametrize("mode", range(5))
def test_hold_gain_ramps_linearly_to_motion_specific_caps(mode: int) -> None:
    motion = Motion()
    motion.sample(1000, mode=mode)
    (horizontal_start, horizontal_top), (vertical_start, vertical_top) = _expected_gains(mode)
    for tick in range(1025, 2525, 25):
        actual = motion.sample(tick, mode=mode)
        progress = min((tick - 1000) / 1000, 1)
        assert actual == pytest.approx(
            (
                12
                * 25
                * 0.03
                * (horizontal_start + (horizontal_top - horizontal_start) * progress),
                12 * 25 * 0.03 * (vertical_start + (vertical_top - vertical_start) * progress),
            )
        )


@pytest.mark.parametrize("step", [8, 17, 33])
@pytest.mark.parametrize("size", [(1024, 768), (1280, 800), (3840, 2160)])
def test_held_forward_travel_is_resolution_and_cadence_independent(
    step: int, size: tuple[int, int]
) -> None:
    motion = Motion()
    distance = 0.0
    tick = 1000
    end = 2000
    motion.sample(tick, horizontal=0, size=size)
    while tick < end:
        tick = min(tick + step, end)
        _, vertical = motion.sample(tick, horizontal=0, size=size)
        distance += vertical
    # 108 units/s ramps to 594 over one second: 351 units travelled, allowing
    # at most half one update's change in speed for discrete integration.
    assert distance == pytest.approx(351, abs=486 * step / 2000 + 0.01)


@pytest.mark.parametrize("step", [8, 17, 33])
def test_elapsed_time_gives_comparable_half_turns_across_refresh_rates(step: int) -> None:
    motion = Motion()
    yaw = 0.0
    elapsed = 0
    while abs(yaw) < 180:
        horizontal, _ = motion.sample(1000 + elapsed)
        yaw += horizontal * 180 / 1024
        elapsed += step
    # Base speed alone needs ~2.85s. A held turn now completes in ~1.5s,
    # independently of framebuffer size and update cadence.
    assert 1480 <= elapsed <= 1590


def test_clock_wrap_duplicate_samples_and_long_pause_do_not_jump() -> None:
    motion = Motion()
    motion.sample(0xFFFFFFF0)
    wrapped = motion.sample(1)
    assert wrapped == pytest.approx(
        (12 * 17 * 0.03 * (0.375 + 2.155 * 17 / 1000), 12 * 17 * 0.03 * (0.3 + 1.35 * 17 / 1000))
    )
    assert motion.sample(1) == (0, 0)
    assert motion.sample(10001) == pytest.approx((12 * 34 * 0.03 * 0.375, 12 * 34 * 0.03 * 0.3))


@pytest.mark.parametrize("mode", range(5))
def test_changing_camera_mode_does_not_restart_a_continuously_held_key(mode: int) -> None:
    motion = Motion()
    for tick in range(1000, 2213, 17):
        motion.sample(tick, mode=mode)
    assert motion.sample(2224) == pytest.approx((12 * 17 * 0.03 * 2.53, 12 * 17 * 0.03 * 1.65))


@pytest.mark.parametrize("mode", range(5))
def test_physical_mouse_conversion_does_not_use_keyboard_timing_or_gain(mode: int) -> None:
    motion = Motion()
    for tick in range(1000, 2213, 17):
        motion.sample(tick)
    cpu = motion.cpu
    frame = motion.stack
    cpu.mem_write(frame + 8, struct.pack("<fii", 12.0, -9, 0))
    cpu.reg_write(UC_X86_REG_EBP, frame)
    cpu.reg_write(UC_X86_REG_ESP, frame - 32)
    cpu.reg_write(UC_X86_REG_EAX, motion.configuration)
    cpu.reg_write(UC_X86_REG_EDI, mode)
    continuation = GOG_BUILD.address("camera.motion_float_conversion_continue")

    def stop_at_continuation(cpu: Uc, _address: int, _size: int, _data: object) -> None:
        cpu.emu_stop()

    # This address was already translated during the keyboard warm-up; use
    # an explicit stop hook rather than changing Unicorn's cached end address.
    cpu.hook_add(UC_HOOK_CODE, stop_at_continuation, begin=continuation, end=continuation)
    cpu.emu_start(motion.entry + motion.compiler._off_conversion_bridge, continuation, count=100)
    assert struct.unpack("<f", cpu.mem_read(frame + 8, 4))[0] == 12
    assert struct.unpack("<f", cpu.mem_read(frame + 16, 4))[0] == -9
    assert cpu.reg_read(UC_X86_REG_ESP) == frame - 36
