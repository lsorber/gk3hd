"""Execute cumulative font-table normalization, including shared row boundaries."""

import struct
import subprocess
import sys
from pathlib import Path

import pytest
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_ESP

from gk3hd.patch.builds import GOG_BUILD
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import TransitionFrameABI
from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols
from gk3hd.patch.definitions.runtime2d.room_rendering import RoomRenderingABI
from gk3hd.patch.definitions.runtime2d.system import SystemScreenCompiler
from gk3hd.patch.definitions.runtime2d.system.load_save import LoadSaveFeatureCompiler
from gk3hd.textures.upscale.fonts.bank import FONT_ROW_BANK_LAYOUTS, FontRowBankLayout

BASE, DATA, STACK = 0x800000, 0xA00000, 0xB08000
FONT, RESOURCE, SURFACE, ROW_X, ROW_Y = (DATA + n * 0x1000 for n in range(5))
COUNT, HANDLE_COUNT, HANDLES = DATA + 0x5000, DATA + 0x5004, DATA + 0x5010


def put(cpu: Uc, address: int, *values: int) -> None:
    cpu.mem_write(address, struct.pack("<" + "I" * len(values), *values))


def run() -> None:
    compiler = SystemScreenCompiler(
        symbols=RuntimeSymbols(segments=()),
        profile=GOG_BUILD,
        room_rendering_abi=RoomRenderingABI(width_va=DATA + 0x6000, height_va=DATA + 0x6004),
        transition_abi=TransitionFrameABI(
            successful_flip_count_va=DATA + 0x6010,
            room_presentation_active_va=DATA + 0x6014,
            pre_flip_presenter_slot_va=DATA + 0x6018,
            post_flip_presenter_slot_va=DATA + 0x601C,
        ),
    ).load_save_feature()
    payload = compiler.build_hd_font_metrics_wrapper(
        wrapper_va=BASE,
        normalize_count_va=COUNT,
        handle_count_va=HANDLE_COUNT,
        handles_va=HANDLES,
    )
    for lines in range(1, 7):
        cpu = Uc(UC_ARCH_X86, UC_MODE_32)
        cpu.mem_map(0x400000, 0x500000)
        cpu.mem_map(DATA, 0x10000)
        cpu.mem_map(0xB00000, 0x10000)
        cpu.mem_write(BASE, payload)
        cpu.mem_write(
            compiler._resolve_bitmap_resource_va,
            b"\xb8" + struct.pack("<I", RESOURCE) + bytes.fromhex("c20400"),
        )
        origins = [500 * i for i in range(lines)]
        # Every shared boundary belongs to the following row. This includes
        # row carries that cross a multiple of four and previously enlarged
        # the preceding character's logical advance.
        boundaries = sorted({origin + delta for origin in origins for delta in (0, 1, 7, 499)})
        boundaries += [origins[-1] + 500]
        encoded = [
            value * 4 + 3 * max(i for i, origin in enumerate(origins) if origin <= value)
            for value in boundaries
        ]
        words = encoded + [0xFFFF] * (257 - len(encoded))
        cpu.mem_write(FONT + 0x50, struct.pack("<257H", *words))
        put(cpu, FONT + 4, 7)
        put(cpu, FONT + 0x34, 2400, lines * 64, 0, 40)
        put(cpu, FONT + 0x4C, lines)
        put(cpu, FONT + 0x258, ROW_X if lines > 1 else 0, ROW_Y if lines > 1 else 0)
        cpu.mem_write(
            ROW_X, struct.pack("<" + "H" * lines, *(v * 4 + 3 * i for i, v in enumerate(origins)))
        )
        cpu.mem_write(ROW_Y, struct.pack("<" + "H" * lines, *(64 * i + 1 for i in range(lines))))
        put(cpu, RESOURCE + 0x30, SURFACE)
        put(cpu, SURFACE + 0x38, 2400, lines * 64)
        put(cpu, STACK, 0x12345678)
        cpu.reg_write(UC_X86_REG_ESI, FONT)
        cpu.reg_write(UC_X86_REG_ESP, STACK)
        cpu.emu_start(BASE, compiler._font_metrics_continue_va, count=100000)
        actual = struct.unpack("<257H", cpu.mem_read(FONT + 0x50, 514))
        assert actual == tuple(boundaries + [0xFFFF] * (257 - len(boundaries)))
        if lines > 1:
            assert struct.unpack("<" + "H" * lines, cpu.mem_read(ROW_X, lines * 2)) == tuple(
                origins
            )
            assert struct.unpack("<" + "H" * lines, cpu.mem_read(ROW_Y, lines * 2)) == tuple(
                16 * i + 1 for i in range(lines)
            )
        assert struct.unpack("<II", cpu.mem_read(FONT + 0x34, 8)) == (599, 15)
        assert cpu.reg_read(UC_X86_REG_ESI) == FONT
        assert cpu.reg_read(UC_X86_REG_EBX) == 0x12345678
        assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 4
    _narrow_cases(compiler)


def _narrow_cases(compiler: LoadSaveFeatureCompiler) -> None:
    # Storage support is tested independently of admitting an artwork recipe.
    FONT_ROW_BANK_LAYOUTS["TEST_NARROW.BMP"] = FontRowBankLayout((183, 64), 4, 94)
    payload = compiler.build_hd_font_metrics_wrapper(
        wrapper_va=BASE,
        normalize_count_va=COUNT,
        handle_count_va=HANDLE_COUNT,
        handles_va=HANDLES,
    )
    for width, height, lines, surface_width, surface_height, calls, accepted in (
        (1464, 256, 4, 1464, 256, 1, True),
        (183, 64, 4, 183, 64, 0, False),
        (1466, 17, 1, 1466, 17, 0, False),
        (1485, 18, 1, 1485, 18, 0, False),
        (1468, 256, 4, 1468, 256, 0, False),
        (1464, 260, 4, 1464, 260, 0, False),
        (1464, 256, 3, 1464, 256, 0, False),
        (1464, 256, 4, 183, 64, 1, False),
        (1464, 256, 4, 1464, 257, 1, False),
        (2400, 256, 4, 2396, 256, 1, False),
    ):
        cpu = Uc(UC_ARCH_X86, UC_MODE_32)
        cpu.mem_map(0x400000, 0x500000)
        cpu.mem_map(DATA, 0x10000)
        cpu.mem_map(0xB00000, 0x10000)
        cpu.mem_write(BASE, payload)
        cpu.mem_write(
            compiler._resolve_bitmap_resource_va,
            b"\xb8" + struct.pack("<I", RESOURCE) + bytes.fromhex("c20400"),
        )
        observed: list[int] = []

        def observe(_cpu: Uc, address: int, _size: int, _user: list[int]) -> None:
            if address == compiler._resolve_bitmap_resource_va:
                _user.append(address)

        cpu.hook_add(UC_HOOK_CODE, observe, observed)
        cpu.mem_write(FONT + 0x50, b"\xff" * 514)
        put(cpu, FONT + 4, 7)
        put(cpu, FONT + 0x34, width, height, 0, 44)
        put(cpu, FONT + 0x4C, lines)
        put(cpu, FONT + 0x258, ROW_X, ROW_Y)
        cpu.mem_write(ROW_X, struct.pack("<4H", 0, 403, 806, 1209))
        cpu.mem_write(ROW_Y, struct.pack("<4H", 1, 65, 129, 193))
        put(cpu, RESOURCE + 0x30, SURFACE)
        put(cpu, SURFACE + 0x38, surface_width, surface_height)
        before = bytes(cpu.mem_read(FONT, 0x300))
        put(cpu, STACK, 0x12345678)
        cpu.reg_write(UC_X86_REG_ESI, FONT)
        cpu.reg_write(UC_X86_REG_ESP, STACK)
        cpu.emu_start(BASE, compiler._font_metrics_continue_va, count=100000)
        assert len(observed) == calls
        assert struct.unpack("<I", cpu.mem_read(COUNT, 4))[0] == int(accepted)
        if accepted:
            assert struct.unpack("<4I", cpu.mem_read(FONT + 0x34, 16)) == (365, 15, 0, 11)
        else:
            # The displaced native tail subtracts one from width and divides
            # height into rows. Rejection must perform exactly that, not noop.
            expected = bytearray(before)
            struct.pack_into("<2I", expected, 0x34, width - 1, height // lines - 1)
            assert bytes(cpu.mem_read(FONT, 0x300)) == expected
        assert cpu.reg_read(UC_X86_REG_ESI) == FONT
        assert cpu.reg_read(UC_X86_REG_EBX) == 0x12345678
        assert cpu.reg_read(UC_X86_REG_ESP) == STACK + 4
    del FONT_ROW_BANK_LAYOUTS["TEST_NARROW.BMP"]


@pytest.mark.slow
def test_executed_multirow_font_metrics() -> None:
    subprocess.run(  # noqa: S603 - fixed interpreter and this test module.
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


if __name__ == "__main__":
    run()
