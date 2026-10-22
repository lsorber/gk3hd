"""Fit native AVI replacements and preserve original Bink presentation."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gk3hd.patch.binary.mutations import ExecutableMutationPlan
from gk3hd.patch.binary.payload import SegmentPayloadBuilder
from gk3hd.patch.binary.x86 import BranchOpcode, Condition, X86Emitter
from gk3hd.patch.definitions.runtime2d.layout import (
    MOVIE_SEGMENT,
    SIDNEY_DRAW_DEPTH_OFFSET,
    SIDNEY_PRESENTATION_SEGMENT,
    install_runtime_segment,
)
from gk3hd.patch.definitions.runtime2d.system.movie_overrides import (
    MOVIE_PATH_PREFIX,
    MovieBlitABI,
    MovieOverrideImports,
    build_embedded_blt,
    build_embedded_size,
    build_factory,
    build_logical_size,
    build_palette_key,
    build_path_resolver,
)
from gk3hd.patch.definitions.runtime2d.system.movie_player import (
    PLAYER_EXPORT,
    PLAYER_PATH,
    MoviePlayerABI,
    build_open_movie,
)
from gk3hd.patch.definitions.runtime2d.system.shared import SystemCompilerContext

if TYPE_CHECKING:
    from gk3hd.patch.binary.image import PEFile


@dataclass(frozen=True, slots=True, kw_only=True)
class MovieFeatureCompiler(SystemCompilerContext):
    """Select installed AVIs and fit full-screen movies before native layout.

    Original Bink movies retain their reference-scale presentation. Full-screen
    AVI movies instead fit the display while preserving their aspect ratio.
    Installed 4x AVIs expose their original logical dimensions to embedded UI,
    while drawing from the full decoded backing. Native decoders, audio and
    frame timing remain responsible for playback.
    """

    def build_layout(self, *, wrapper_va: int, replacement_vtable_va: int = 0) -> bytes:
        """Build an idempotent, call-local extent adapter for MovieLayer."""
        code = X86Emitter(base_va=wrapper_va)
        code.raw(bytes.fromhex("9c60 83ec10 89ce"))
        code.raw(bytes.fromhex("80be4001000000"))  # MovieLayer.fullscreen
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8bbe3c010000 85ff"))
        code.jump_if(Condition.EQUAL, "native")
        for vtable in (self.profile.address("movies.avi_vtable"), replacement_vtable_va):
            if vtable:
                code.raw(b"\x81\x3f" + struct.pack("<I", vtable))
                code.jump_if(Condition.EQUAL, "avi")
        code.raw(b"\x81\x3f" + struct.pack("<I", self.profile.address("movies.bink_vtable")))
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("807f5000"))  # native hardware overlay
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(bytes.fromhex("837f6400"))  # default movie sizing only
        code.jump_if(Condition.NOT_EQUAL, "native")
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4))
        for register in (b"\x81\xf9", b"\x81\xfa"):
            code.raw(register + struct.pack("<I", 32768))
            code.jump_if(Condition.ABOVE, "native")
        code.raw(bytes.fromhex("85c9"))
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(bytes.fromhex("85d2"))
        code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(b"\x81\xf9" + struct.pack("<I", 1024))
        code.jump_if(Condition.ABOVE, "scaled")
        code.raw(b"\x81\xfa" + struct.pack("<I", 768))
        code.jump_if(Condition.BELOW_OR_EQUAL, "native")
        code.label("scaled")
        code.raw(bytes.fromhex("8b4754 85c0"))  # raw BINK dimensions, never the prior RECT
        code.jump_if(Condition.EQUAL, "native")
        code.raw(bytes.fromhex("8b18 8b6804"))
        for register, bound in ((b"\x81\xfb", 1024), (b"\x81\xfd", 768)):
            code.raw(register + struct.pack("<I", bound))
            code.jump_if(Condition.ABOVE, "native")
        for instruction in ("85db", "85ed"):
            code.raw(bytes.fromhex(instruction))
            code.jump_if(Condition.LESS_OR_EQUAL, "native")
        code.raw(b"\x81\xfb" + struct.pack("<I", 512))
        code.jump_if(Condition.ABOVE, "fit")
        code.raw(b"\x81\xfd" + struct.pack("<I", 384))
        code.jump_if(Condition.ABOVE, "fit")
        code.raw(bytes.fromhex("d1e3 d1e5"))
        code.label("fit")
        code.raw(bytes.fromhex("69c100030000 69f200040000 39f0"))
        code.jump_if(Condition.BELOW_OR_EQUAL, "width")
        code.raw(bytes.fromhex("89d6 b900030000"))  # height / 768
        code.jump("extent")
        code.label("width")
        code.raw(bytes.fromhex("89ce b900040000"))  # width / 1024
        code.label("extent")
        code.raw(bytes.fromhex("31c0 890424 89442404"))
        for source, destination in (("89d8", 8), ("89e8", 12)):
            code.raw(bytes.fromhex(source + " 0fafc6 89ca d1ea 01d0 31d2 f7f1"))
            code.raw(bytes((0x89, 0x44, 0x24, destination)))
        code.raw(bytes.fromhex("89e0 50 89f9"))
        code.call_absolute(self.profile.address("movies.set_rect"))
        code.jump("native")
        code.label("avi")
        # AVI draw uses the decoded backing size independently of this virtual
        # logical extent. Do not let MovieLayer's stretch-to-screen flag bypass
        # the fitted rectangle, including at the original display resolution.
        code.raw(bytes.fromhex("8d442408 50 89f9 8b07 ff504c"))
        code.raw(bytes.fromhex("8b5c2408 8b6c240c"))
        code.raw(b"\x8b\x0d" + struct.pack("<I", self._physical_width_va))
        code.raw(b"\x8b\x15" + struct.pack("<I", self._physical_width_va + 4))
        for register in ("85db", "85ed", "85c9", "85d2"):
            code.raw(bytes.fromhex(register))
            code.jump_if(Condition.LESS_OR_EQUAL, "native")
        for register in (b"\x81\xfb", b"\x81\xfd", b"\x81\xf9", b"\x81\xfa"):
            code.raw(register + struct.pack("<I", 32768))
            code.jump_if(Condition.ABOVE, "native")
        code.raw(bytes.fromhex("c6475000 89c8 0fafc5 89d6 0faff3 39f0"))
        code.jump_if(Condition.BELOW_OR_EQUAL, "avi_width")
        code.raw(bytes.fromhex("89d6 89e9"))
        code.jump("extent")
        code.label("avi_width")
        code.raw(bytes.fromhex("89ce 89d9"))
        code.jump("extent")
        code.label("native")
        code.raw(bytes.fromhex("83c410 619d"))
        code.jump_absolute(self.profile.address("movies.layout"))
        return code.build()

    def apply(self, image: PEFile) -> None:
        """Install both native layout entry callers as one checked transaction."""
        section = install_runtime_segment(image, MOVIE_SEGMENT)
        base = image.rva_to_va(section.virtual_address)
        payload = SegmentPayloadBuilder(
            owner=self.id, segment=MOVIE_SEGMENT.logical_name, size=MOVIE_SEGMENT.size
        )
        payload.place(label="identity", offset=0, payload=MOVIE_SEGMENT.magic)
        payload.place(
            label="movie extent",
            offset=0x100,
            payload=self.build_layout(wrapper_va=base + 0x100, replacement_vtable_va=base + 0xA04),
        )
        plan = ExecutableMutationPlan(owner=self.id)
        self._place_overrides(image=image, payload=payload, base=base, plan=plan)
        stretch_frame = self.profile.site("movies.stretch_frame")
        plan.replace(
            label="native movie stretch frame validation",
            va=stretch_frame.va,
            expected=stretch_frame.original,
            payload=stretch_frame.original,
        )
        native_stretch = X86Emitter(base_va=base + 0x480)
        native_stretch.raw(stretch_frame.original)
        native_stretch.raw(bytes.fromhex("8b7d0c"))
        native_stretch.jump_absolute(self.profile.address("movies.stretch_body"))
        payload.place(
            label="native movie stretch frame", offset=0x480, payload=native_stretch.build()
        )
        payload.place(
            label="SIDNEY movie presentation",
            offset=0xD00,
            payload=build_embedded_blt(
                wrapper_va=base + 0xD00,
                abi=MovieBlitABI(
                    replacement_vtable=base + 0xA04,
                    sidney_depth=self.symbols.va(
                        SIDNEY_PRESENTATION_SEGMENT.logical_name, SIDNEY_DRAW_DEPTH_OFFSET
                    ),
                    dimensions=self._physical_width_va,
                    native=stretch_frame.va,
                    stretch=base + 0x480,
                ),
            ),
        )
        movie_blt = self.profile.site("movies.avi_blt")
        plan.branch(
            label="embedded replacement movie draw",
            opcode=BranchOpcode.CALL,
            site_va=movie_blt.va,
            expected=movie_blt.original,
            target_va=base + 0xD00,
        )
        key = self.profile.site("movies.avi_color_key")
        payload.place(
            label="original movie palette key",
            offset=0x420,
            payload=build_palette_key(
                wrapper_va=base + 0x420,
                player_va=base + 0xC0,
                native_vtable=self.profile.address("movies.avi_vtable"),
                native_va=self.profile.address("movies.surface_color_key"),
                resume_va=key.va + len(key.original),
            ),
        )
        plan.branch(
            label="original movie palette key",
            opcode=BranchOpcode.JUMP,
            site_va=key.va,
            expected=key.original,
            target_va=base + 0x420,
            size=len(key.original),
        )
        payload.place(
            label="embedded movie extent",
            offset=0xE00,
            payload=build_embedded_size(
                wrapper_va=base + 0xE00, dimensions_va=self._physical_width_va
            ),
        )
        embedded = self.profile.site("movies.embedded_size")
        plan.branch(
            label="embedded movie layout",
            opcode=BranchOpcode.CALL,
            site_va=embedded.va,
            expected=embedded.original,
            target_va=base + 0xE00,
            size=len(embedded.original),
        )
        for name in ("initial_layout", "resize_layout"):
            site = self.profile.site(f"movies.{name}")
            plan.branch(
                label=f"movie {name}",
                opcode=BranchOpcode.CALL,
                site_va=site.va,
                expected=site.original,
                target_va=base + 0x100,
            )
        image.write_bytes(section.pointer_to_raw_data, payload.build())
        plan.apply(image)

    def _place_overrides(
        self,
        *,
        image: PEFile,
        payload: SegmentPayloadBuilder,
        base: int,
        plan: ExecutableMutationPlan,
    ) -> None:
        imports = {
            symbol.function_name: image.image_base + symbol.iat_rva
            for symbol in image.iter_import_symbols()
            if symbol.function_name is not None and symbol.dll_name.casefold() == "kernel32.dll"
        }
        api = MovieOverrideImports(
            imports["GetModuleFileNameA"], imports["CreateFileA"], imports["CloseHandle"]
        )
        payload.place(label="private player path", offset=0x40, payload=PLAYER_PATH)
        payload.place(label="private player export", offset=0x80, payload=PLAYER_EXPORT)
        payload.place(label="private player cache", offset=0xC0, payload=bytes(4))
        payload.place(
            label="private movie player",
            offset=0xF00,
            payload=build_open_movie(
                wrapper_va=base + 0xF00,
                abi=MoviePlayerABI(
                    imports["GetModuleFileNameA"],
                    imports["LoadLibraryA"],
                    imports["GetProcAddress"],
                    base + 0x40,
                    base + 0x80,
                    base + 0xC0,
                ),
            ),
        )
        opened = self.profile.site("movies.avi_open_file")
        call = X86Emitter(base_va=opened.va)
        call.raw(b"\x50")
        call.call_absolute(base + 0xF00)
        plan.replace(
            label="private AV1 movie player",
            va=opened.va,
            expected=opened.original,
            payload=call.build(),
        )
        site = self.profile.site("movies.factory")
        trampoline = X86Emitter(base_va=base + 0x900)
        trampoline.raw(site.original)
        trampoline.jump_absolute(site.va + len(site.original))
        payload.place(label="movie factory trampoline", offset=0x900, payload=trampoline.build())
        payload.place(
            label="movie replacement factory",
            offset=0x500,
            payload=build_factory(
                wrapper_va=base + 0x500,
                trampoline_va=base + 0x900,
                vtable_va=base + 0xA04,
                prefix_va=base + 0xB00,
                imports=api,
            ),
        )
        payload.place(
            label="movie logical dimensions",
            offset=0x980,
            payload=build_logical_size(
                wrapper_va=base + 0x980, native_va=self.profile.address("movies.avi_size")
            ),
        )
        table = bytearray(
            image.read_bytes(
                image.va_to_offset(self.profile.address("movies.avi_vtable") - 4), 0x60
            )
        )
        struct.pack_into("<I", table, 0x50, base + 0x980)
        payload.place(label="replacement AVI vtable", offset=0xA00, payload=bytes(table))
        payload.place(label="replacement directory", offset=0xB00, payload=MOVIE_PATH_PREFIX)
        payload.place(
            label="movie alias resolver",
            offset=0xB40,
            payload=build_path_resolver(
                wrapper_va=base + 0xB40, prefix_va=base + 0xB00, imports=api
            ),
        )
        resolver = self.profile.site("movies.avi_resolve_path")
        plan.branch(
            label="movie alias lookup",
            opcode=BranchOpcode.CALL,
            site_va=resolver.va,
            expected=resolver.original,
            target_va=base + 0xB40,
            size=len(resolver.original),
        )
        plan.branch(
            label="movie replacement lookup",
            opcode=BranchOpcode.JUMP,
            site_va=site.va,
            expected=site.original,
            target_va=base + 0x500,
        )
