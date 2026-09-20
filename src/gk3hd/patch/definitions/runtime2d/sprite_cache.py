"""Preserve dense text in SIDNEY's button and styled-text bitmap caches.

Native cache dimensions and text metrics stay authoritative for layout and hit
testing. A separately owned four-times-density bitmap is selected only at an
enlarged final transfer. Native-size draws remain byte-for-byte native.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.dropdown_cache import DropdownCacheRuntime
from gk3hd.patch.definitions.runtime2d.layout import (
    FONT_BANK_SEGMENT,
    FONT_BANK_SELECT_OFFSET,
    SPRITE_CACHE_SEGMENT,
    SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET,
    SYSTEM_CONTROL_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.styled_cache import StyledTextCacheRuntime
from gk3hd.patch.model import PatchError

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols

STATE_OFFSET = 0x3000
CACHE_OFFSET = 0x4000
CACHE_CAPACITY = 512
CACHE_STRIDE = 32
# Record: handle address, owner, complete native handle, dense handle,
# native surface, dense surface, native resource, ready flag.
ENTRY_SITES = (
    ("sprite_cache.paint", 0x100, 0x2800),
    ("sprite_cache.point", 0x800, 0x2840),
    ("sprite_cache.release", 0x1800, 0x28C0),
    ("sprite_cache.alpha_constructor", 0x2200, 0x2880),
    ("sprite_cache.dropdown_paint", 0x3500, 0x3700),
)
ASSIGN_SITES = tuple(f"sprite_cache.clear_{state}" for state in ("off", "on", "disabled"))


def _u(value: int) -> bytes:
    """Encode one unsigned x86 immediate."""
    return struct.pack("<I", value)


def _clip_construction(code: X86Emitter) -> None:
    """Reclip trailing edges after density growth, using call-local rectangles.

    Native clipping has already handled leading edges, but growing the extent
    can overrun the destination's right/bottom edge. Preserve the corresponding
    source interval using the same integer ratio. MUL/DIV uses a 64-bit product.
    Repeated two-pixel strips at the last column expose this in dropdown labels.
    """
    code.raw(bytes.fromhex("8b742450 8d7c2410 b904000000 fc f3a5 8b5c2438"))
    for near, far, dimension in ((0, 8, 0x38), (4, 12, 0x3C)):
        code.raw(bytes((0x8B, 0x74, 0x24, far, 0x8B, 0x7B, dimension, 0x39, 0xFE)))
        code.jump_if(Condition.LESS_OR_EQUAL, f"clipped_{near}")
        code.raw(bytes((0x8B, 0x4C, 0x24, near, 0x39, 0xF9)))
        code.jump_if(Condition.GREATER_OR_EQUAL, "construction_empty")
        code.raw(bytes.fromhex("29ce"))  # Original destination span.
        code.raw(bytes((0x8B, 0x44, 0x24, far)) + bytes.fromhex("29f8 89f1"))
        code.raw(bytes((0x8B, 0x54, 0x24, far + 16, 0x2B, 0x54, 0x24, near + 16)))
        code.raw(bytes.fromhex("f7e2 f7f1"))  # Excess * source span / destination span.
        code.raw(bytes((0x29, 0x44, 0x24, far + 16, 0x89, 0x7C, 0x24, far)))
        code.label(f"clipped_{near}")
    code.raw(bytes.fromhex("8d442410 89442450"))


@dataclass(frozen=True, slots=True)
class SpriteCacheRuntime:
    """Explicit native and data addresses for re-entrant paired-cache adapters."""

    base_va: int
    downstream_va: int
    profile: BuildProfile
    active_font_va: int = 0

    def paint(self, *, offset: int = 0x100, callback_offset: int = 0x2800) -> bytes:
        """Render native state unchanged, then compose its owned dense counterpart."""
        base = self.base_va
        active = base + STATE_OFFSET
        active_surface = base + STATE_OFFSET + 4
        count = base + STATE_OFFSET + 8
        table = base + CACHE_OFFSET
        limit = base + CACHE_OFFSET + CACHE_CAPACITY * CACHE_STRIDE
        # Paint native cache unmodified first. Retain a second resource, keyed by
        # the owning widget and address of its native state handle.
        code = X86Emitter(base_va=base + offset)
        code.raw(
            bytes.fromhex("558bec83ec18 535657 894dfc a1")
            + _u(active)
            + bytes.fromhex("8945f0 a1")
            + _u(active_surface)
            + bytes.fromhex("8945ec ff750c ff7508")
        )
        code.call_absolute(base + callback_offset)
        code.raw(bytes.fromhex("8945f8 8b5d08 8b03 85c0"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(bytes.fromhex("50 8b0d") + _u(self.profile.address("bitmap.manager")))
        code.call_absolute(self.profile.address("sprite_cache.resolve"))
        code.raw(bytes.fromhex("85c0"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(bytes.fromhex("8945f4 8b7030 85f6"))
        code.jump_if(Condition.EQUAL, "done")
        # Bound allocation and coordinate products. Oversized/malformed native
        # caches stay native instead of risking an overflowing 4x allocation.
        for dimension in (0x38, 0x3C):
            code.raw(bytes((0x8B, 0x46, dimension)) + bytes.fromhex("48 3dff070000"))
            code.jump_if(Condition.ABOVE, "done")
        code.raw(bytes.fromhex("31d2") + b"\xbf" + _u(table))
        code.label("find")
        code.raw(bytes.fromhex("391f"))
        code.jump_if(Condition.EQUAL, "found")
        code.raw(bytes.fromhex("833f00"))
        code.jump_if(Condition.NOT_EQUAL, "next")
        code.raw(bytes.fromhex("89fa"))
        code.label("next")
        code.raw(bytes.fromhex("83c720 81ff") + _u(limit))
        code.jump_if(Condition.BELOW, "find")
        code.raw(bytes.fromhex("85d2"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(bytes.fromhex("89d7"))
        code.label("found")
        code.raw(
            bytes.fromhex(
                "891f 8b45fc 894704 8b03 894708 8b45f4 894718 897710 c7471c00000000 "
                "8b4638 c1e002 8b563c c1e202 6a00 52 50 68"
            )
            + _u(base + 0x2F00)
            + bytes.fromhex("8d4f0c")
        )
        code.call_absolute(self.profile.address("sprite_cache.allocate"))
        code.raw(bytes.fromhex("8b470c 85c0"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(bytes.fromhex("50 8b0d") + _u(self.profile.address("bitmap.manager")))
        code.call_absolute(self.profile.address("sprite_cache.dimensions"))
        code.raw(bytes.fromhex("ff770c 8b0d") + _u(self.profile.address("bitmap.manager")))
        code.call_absolute(self.profile.address("sprite_cache.resolve"))
        code.raw(bytes.fromhex("85c0"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(bytes.fromhex("8b4030 85c0"))
        code.jump_if(Condition.EQUAL, "done")
        code.raw(
            bytes.fromhex("894714 a3")
            + _u(active_surface)
            + bytes.fromhex("8b470c a3")
            + _u(active)
        )
        code.raw(bytes.fromhex("ff750c 8d470c 50 8b4dfc"))
        code.call_absolute(base + callback_offset)
        code.raw(
            bytes.fromhex("c7471c01000000 ff05")
            + _u(count)
            + bytes.fromhex("8b45f0 a3")
            + _u(active)
            + bytes.fromhex("8b45ec a3")
            + _u(active_surface)
        )
        code.label("done")
        code.raw(bytes.fromhex("8b45f8 5f5e5b c9 c20800"))
        return code.build()

    def point(self) -> bytes:
        """Map only points targeting this synchronous dense-cache construction."""
        base = self.base_va
        active = base + STATE_OFFSET
        # Scale only glyph/background points targeting the currently built dense
        # cache; Font::DrawText's own metrics and clipping stay authored.
        code = X86Emitter(base_va=base + 0x800)
        code.raw(bytes.fromhex("9c60 83ec08 a1") + _u(active) + bytes.fromhex("85c0"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("3b442430"))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("8b742438 85f6"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(
            bytes.fromhex("8b06 c1e002 890424 8b4604 c1e002 89442404 8d0424 89442438 8b4c2420")
            + bytes.fromhex("ff742440") * 5
        )
        code.call_absolute(base + 0x2840)
        code.raw(bytes.fromhex("89442424 83c408 619d c21400"))
        code.label("native")
        code.raw(bytes.fromhex("83c408 619d"))
        code.jump_absolute(base + 0x2840)
        return code.build()

    def transfer(self) -> bytes:
        """Select a validated dense cache only for an actually enlarged transfer."""
        base = self.base_va
        active_surface = base + STATE_OFFSET + 4
        draws = base + STATE_OFFSET + 12
        present = base + STATE_OFFSET + 16
        table = base + CACHE_OFFSET
        limit = base + CACHE_OFFSET + CACHE_CAPACITY * CACHE_STRIDE
        # Runs AFTER existing source-density and screen geometry dispatch, BEFORE
        # the paired font-bank selector. Rectangles remain call-local.
        code = X86Emitter(base_va=base + 0x1000)
        code.raw(bytes.fromhex("9c60 83ec20 a1") + _u(active_surface) + bytes.fromhex("85c0"))
        code.jump_if(Condition.EQUAL, "presentation")
        code.raw(bytes.fromhex("3b442438"))
        code.jump_if(Condition.NOT_EQUAL, "presentation")
        if self.active_font_va:
            # Software-alpha composition has already enlarged the glyph. Its
            # completed scratch bitmap must not receive another 4x transform.
            # Opaque glyphs still arrive directly from the active font surface.
            code.raw(b"\xa1" + _u(self.active_font_va) + bytes.fromhex("85c0"))
            code.jump_if(Condition.EQUAL, "construction")
            code.raw(bytes.fromhex("0fb7c0 8b0d") + _u(self.profile.address("bitmap.manager")))
            code.raw(bytes.fromhex("3b8124010000"))
            code.jump_if(Condition.ABOVE_OR_EQUAL, "construction")
            code.raw(bytes.fromhex("8b8920010000 8b0481 85c0"))
            code.jump_if(Condition.EQUAL, "construction")
            code.raw(bytes.fromhex("8b4030 3b442448"))
            code.jump_if(Condition.NOT_EQUAL, "native")
            code.label("construction")
        code.raw(bytes.fromhex("8b74244c 85f6"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8d3c24 b904000000 f3a5"))
        # x/y already scaled at BitmapManager entry; multiply only extent.
        for far, near in ((8, 0), (12, 4)):
            code.raw(bytes((0x8B, 0x44, 0x24, far)))
            code.raw(bytes((0x2B, 0x44, 0x24, near)))
            code.raw(bytes.fromhex("c1e002"))
            code.raw(bytes((0x03, 0x44, 0x24, near)))
            code.raw(bytes((0x89, 0x44, 0x24, far)))
        code.raw(bytes.fromhex("8d0424 8944244c ff05") + _u(draws))
        _clip_construction(code)
        code.jump("call")
        code.label("presentation")
        code.raw(bytes.fromhex("8b742448 85f6"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8b54244c 85d2"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8b5c2450 85db"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(b"\xbf" + _u(table))
        code.label("lookup")
        code.raw(bytes.fromhex("397710"))
        code.jump_if(Condition.EQUAL, "match")
        code.raw(bytes.fromhex("83c720 81ff") + _u(limit))
        code.jump_if(Condition.BELOW, "lookup")
        code.jump("native")
        code.label("match")
        code.raw(bytes.fromhex("837f1c01"))
        code.jump_if(Condition.NOT_EQUAL, "native")
        # Reject stale resource slots even if allocator reused a surface address.
        code.raw(bytes.fromhex("8b07 85c0"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8b00 3b4708"))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(
            bytes.fromhex("0fb7c0 8b0d")
            + _u(self.profile.address("bitmap.manager"))
            + bytes.fromhex("3b8124010000")
        )
        code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
        code.raw(bytes.fromhex("8b8920010000 8b0481 85c0"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("3b4718"))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("397030"))
        code.jump_if(Condition.NOT_EQUAL, "native")
        for part in (0, 4):
            code.raw(bytes((0x83, 0x7B, part, 0)))
            code.jump_if(Condition.LESS, "native")
        for part, dim in ((8, 0x38), (12, 0x3C)):
            code.raw(bytes((0x8B, 0x43, part, 0x3B, 0x46, dim)))
            code.jump_if(Condition.GREATER, "native")
            code.raw(bytes((0x3B, 0x43, part - 8)))
            code.jump_if(Condition.LESS_OR_EQUAL, "native")
        # No axis may shrink below native; at least one axis must grow.
        code.raw(bytes.fromhex("8b4208 2b02 8b4b08 2b0b 39c8"))
        code.jump_if(Condition.LESS, "native")
        code.raw(bytes.fromhex("8b420c 2b4204 8b4b0c 2b4b04 39c8"))
        code.jump_if(Condition.LESS, "native")
        code.jump_if(Condition.GREATER, "select")
        code.raw(bytes.fromhex("8b4208 2b02 8b4b08 2b0b 39c8"))
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.label("select")
        code.raw(
            bytes.fromhex("0fb7470c 8b0d")
            + _u(self.profile.address("bitmap.manager"))
            + bytes.fromhex("3b8124010000")
        )
        code.jump_if(Condition.ABOVE_OR_EQUAL, "native")
        code.raw(bytes.fromhex("8b8920010000 8b0481 85c0"))
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8b4030 3b4714"))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("85c0"))
        code.jump_if(Condition.EQUAL, "native")
        for dim in (0x38, 0x3C):
            code.raw(bytes((0x8B, 0x4E, dim)) + bytes.fromhex("c1e102") + bytes((0x3B, 0x48, dim)))
            code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("89442448 89de 8d7c2410 b904000000"))
        code.label("source")
        code.raw(bytes.fromhex("ad c1e002 ab"))
        code.loop_short("source")
        code.raw(bytes.fromhex("8d442410 89442450 ff05") + _u(present))
        code.label("call")
        code.raw(bytes.fromhex("8b4c2438") + bytes.fromhex("ff742450") * 3)
        code.call_absolute(self.downstream_va)
        code.raw(bytes.fromhex("8944243c 83c420 619d c20c00"))
        code.label("native")
        code.raw(bytes.fromhex("83c420 619d"))
        code.jump_absolute(self.downstream_va)
        code.label("construction_empty")
        code.raw(bytes.fromhex("c744243c00000000 83c420 619d c20c00"))
        return code.build()

    def release(self) -> bytes:
        """Release the dense peer before the native handle can be recycled."""
        base = self.base_va
        table = base + CACHE_OFFSET
        limit = base + CACHE_OFFSET + CACHE_CAPACITY * CACHE_STRIDE
        # Paired ownership ends with the native cache handle, not on surface reuse.
        # Invalidate BEFORE releasing its dense peer (which re-enters this hook).
        code = X86Emitter(base_va=base + 0x1800)
        code.raw(bytes.fromhex("9c60 8b742418 bf") + _u(table))
        code.label("release_find")
        code.raw(bytes.fromhex("3937"))
        code.jump_if(Condition.EQUAL, "release")
        code.raw(bytes.fromhex("83c720 81ff") + _u(limit))
        code.jump_if(Condition.BELOW, "release_find")
        code.jump("release_done")
        code.label("release")
        code.raw(bytes.fromhex("c70700000000 8d4f0c"))
        code.call_absolute(base + 0x28C0)
        code.raw(bytes.fromhex("31c0 b908000000 f3ab"))
        code.label("release_done")
        code.raw(bytes.fromhex("619d"))
        code.jump_absolute(base + 0x28C0)
        return code.build()

    def assign(self) -> bytes:
        """Invalidate the paired cache before assignment releases its native owner."""
        base = self.base_va
        table = base + CACHE_OFFSET
        limit = base + CACHE_OFFSET + CACHE_CAPACITY * CACHE_STRIDE
        # This concrete assignment-to-null path releases the peer first, then
        # delegates the original exactly once with its untouched stack argument.
        code = X86Emitter(base_va=base + 0x2000)
        code.raw(bytes.fromhex("9c60 8b742418 bf") + _u(table))
        code.label("assign_find")
        code.raw(bytes.fromhex("3937"))
        code.jump_if(Condition.EQUAL, "assign_release")
        code.raw(bytes.fromhex("83c720 81ff") + _u(limit))
        code.jump_if(Condition.BELOW, "assign_find")
        code.jump("assign_done")
        code.label("assign_release")
        code.raw(bytes.fromhex("c70700000000 8d4f0c"))
        code.call_absolute(base + 0x28C0)
        code.raw(bytes.fromhex("31c0 b908000000 f3ab"))
        code.label("assign_done")
        code.raw(bytes.fromhex("619d"))
        code.jump_absolute(self.profile.address("sprite_cache.assign"))
        return code.build()


@dataclass(frozen=True, slots=True, kw_only=True)
class SpriteCacheCompiler:
    """Own cached-label density without changing native layout or input."""

    profile: BuildProfile
    symbols: RuntimeSymbols
    id: ClassVar[str] = "runtime2d.sprite_cache"

    def precheck(self, image: PEFile) -> None:
        """Require the exact producer, submission and lifetime sites."""
        for name in (
            *(name for name, _, _ in ENTRY_SITES),
            *ASSIGN_SITES,
            "sprite_cache.styled_paint",
        ):
            site = self.profile.site(name)
            if image.read_bytes(image.va_to_offset(site.va), len(site.original)) != site.original:
                msg = f"{self.id} requires pristine {name}"
                raise PatchError(msg)

    def build(self, base: int) -> tuple[bytes, ExecutableMutationPlan]:
        """Build one bounded payload with checked native redirects."""
        payload = SegmentPayloadBuilder(
            owner=self.id, segment=SPRITE_CACHE_SEGMENT.logical_name, size=SPRITE_CACHE_SEGMENT.size
        )
        payload.place(label="identity", offset=0, payload=SPRITE_CACHE_SEGMENT.magic)
        payload.reserve(label="construction scope and counters", offset=STATE_OFFSET, size=20)
        payload.reserve(
            label="owned paired caches", offset=CACHE_OFFSET, size=CACHE_CAPACITY * CACHE_STRIDE
        )
        runtime = SpriteCacheRuntime(
            base,
            self.symbols.va(FONT_BANK_SEGMENT.logical_name, FONT_BANK_SELECT_OFFSET),
            self.profile,
            self.symbols.va(
                SYSTEM_CONTROL_SEGMENT.logical_name, SYSTEM_CONTROL_HD_FONT_ACTIVE_OFFSET
            ),
        )
        styled = StyledTextCacheRuntime(base, base + STATE_OFFSET + 4, self.profile, self.symbols)
        dropdown = DropdownCacheRuntime(base)
        payload.place(
            label="styled paint",
            offset=0x500,
            payload=runtime.paint(offset=0x500, callback_offset=0x2600),
            limit=0x800,
        )
        payload.place(
            label="dropdown paint",
            offset=0x3100,
            payload=runtime.paint(offset=0x3100, callback_offset=0x3600),
            limit=0x3500,
        )
        for name, offset, end, builder in (
            ("styled entry", 0x40, 0x100, styled.entry),
            ("paint", 0x100, 0x500, runtime.paint),
            ("point", 0x800, 0x1000, runtime.point),
            ("transfer", 0x1000, 0x1800, runtime.transfer),
            ("release", 0x1800, 0x2000, runtime.release),
            ("assignment", 0x2000, 0x2200, runtime.assign),
            ("alpha constructor", 0x2200, 0x2600, styled.alpha_constructor),
            ("styled paint bridge", 0x2600, 0x2800, styled.paint_bridge),
            ("dropdown entry", 0x3500, 0x3600, dropdown.entry),
            ("dropdown paint bridge", 0x3600, 0x3700, dropdown.paint_bridge),
        ):
            payload.place(label=name, offset=offset, payload=builder(), limit=end)
        mutations = ExecutableMutationPlan(owner=self.id)
        for name, offset, trampoline in ENTRY_SITES:
            site = self.profile.site(name)
            code = X86Emitter(base_va=base + trampoline)
            code.raw(site.original)
            code.jump_absolute(site.va + len(site.original))
            payload.place(
                label=name, offset=trampoline, payload=code.build(), limit=trampoline + 0x40
            )
            mutations.branch(
                label=name,
                opcode=BranchOpcode.JUMP,
                site_va=site.va,
                expected=site.original,
                target_va=base + offset,
                size=len(site.original),
            )
        for name, offset in (
            *((name, 0x2000) for name in ASSIGN_SITES),
            ("sprite_cache.styled_paint", 0x40),
        ):
            site = self.profile.site(name)
            mutations.branch(
                label=name,
                opcode=BranchOpcode.CALL,
                site_va=site.va,
                expected=site.original,
                target_va=base + offset,
            )
        payload.place(label="resource name", offset=0x2F00, payload=b"GK3HD dense text cache\0")
        return payload.build(), mutations

    def apply(self, image: PEFile) -> None:
        """Install cache adapters as part of the shared runtime transaction."""
        section = install_runtime_segment(image, SPRITE_CACHE_SEGMENT)
        payload, mutations = self.build(image.rva_to_va(section.virtual_address))
        image.write_bytes(section.pointer_to_raw_data, payload)
        mutations.apply(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify every generated byte and owned redirect."""
        section = image.get_section(SPRITE_CACHE_SEGMENT.logical_name)
        if section is None:
            msg = "Text cache runtime is missing"
            raise PatchError(msg)
        payload, mutations = self.build(image.rva_to_va(section.virtual_address))
        if image.read_bytes(section.pointer_to_raw_data, len(payload)) != payload:
            msg = "Text cache runtime differs from its compiler"
            raise PatchError(msg)
        mutations.verify(image)
