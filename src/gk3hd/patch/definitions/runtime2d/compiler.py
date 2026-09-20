"""Single owner and compiler for GK3's shared fixed-interface runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from gk3hd.patch.definitions.guard_stale_mouse_move_targets import (
    MouseMoveDispatchABI,
    StaleMouseMoveCompiler,
)
from gk3hd.patch.definitions.repair_2d_to_3d_transition_frames import (
    TransitionFrameABI,
    TransitionFrameCompiler,
)
from gk3hd.patch.definitions.runtime2d.captions import CaptionFeatureCompiler
from gk3hd.patch.definitions.runtime2d.console import ConsoleFeatureCompiler
from gk3hd.patch.definitions.runtime2d.fingerprint import FingerprintFeatureCompiler
from gk3hd.patch.definitions.runtime2d.gps import GPSFeatureCompiler
from gk3hd.patch.definitions.runtime2d.inventory import InventoryFeatureCompiler
from gk3hd.patch.definitions.runtime2d.inventory_navigation import InventoryNavigationCompiler
from gk3hd.patch.definitions.runtime2d.layout import RuntimeImage, RuntimeLayout, RuntimeLayoutError
from gk3hd.patch.definitions.runtime2d.resources import ResourceDispatchCompiler
from gk3hd.patch.definitions.runtime2d.room_rendering import (
    DirectRoomRenderingCompiler,
    RoomRenderingABI,
)
from gk3hd.patch.definitions.runtime2d.sidney_construction import SidneyConstructionCompiler
from gk3hd.patch.definitions.runtime2d.sidney_presentation import SidneyPresentationCompiler
from gk3hd.patch.definitions.runtime2d.sprite_cache import SpriteCacheCompiler
from gk3hd.patch.definitions.runtime2d.system import SystemScreenCompiler

if TYPE_CHECKING:
    from gk3hd.patch.binary.compiled import PatchCompiler
    from gk3hd.patch.binary.image import PEFile
    from gk3hd.patch.builds import BuildProfile
    from gk3hd.patch.definitions.runtime2d.layout import RuntimeSymbols


@dataclass(frozen=True, slots=True, kw_only=True)
class Runtime2DCompiler:
    """Fit authored fixed interfaces through one shared 2D mutation owner.

    Outcome:
        Fixed interfaces retain their 1024x768-relative composition, control
        scale, cursor behavior, and hit testing at any larger live resolution;
        ordinary 3D rooms keep their full widescreen field of view.

    Before:
        GK3 mixes authored, physical, cached-hit-test, cursor, and retained-page
        coordinates behind shared blitter and pointer entry points. Independent
        screen patches therefore stack order-dependent hooks and disagree about
        the current coordinate domain.

    After:
        Each visual domain has one internal feature owner, while one facade owns
        the shared final-blitter, pointer, cursor, lifetime, and runtime-section
        mutation boundary. SIDNEY alone receives fitted 4:3 outer bands because
        its laptop composition is intrinsically bounded.

    Strategy:
        Build feature payloads in dependency order against one typed runtime
        symbol table and the direct-room, transition, and mouse ABIs. Apply
        local semantic postchecks, validate the complete section layout, then
        independently rebuild and compare every deterministic payload byte.

    Boundaries:
        Native DirectDraw presentation, ordinary-room camera width, resource
        selection, display cadence, and screen-specific game logic remain with
        their existing owners.
    """

    profile: BuildProfile

    def _components(
        self,
        symbols: RuntimeSymbols,
        *,
        transition_abi: TransitionFrameABI,
        room_rendering_abi: RoomRenderingABI,
        mouse_move_abi: MouseMoveDispatchABI,
    ) -> tuple[PatchCompiler, ...]:
        """Return the complete fixed compiler graph in dependency order.

        ``scale_fixed_interfaces`` owns this graph as one indivisible payload
        because the components share final-blitter, input, cursor, and lifetime
        hooks. SIDNEY's outer bands are part of that fitted composition, not a
        second no-op registry patch whose selection merely changes this
        compiler's constructor.
        """
        return (
            DirectRoomRenderingCompiler(symbols=symbols, profile=self.profile),
            SidneyConstructionCompiler(profile=self.profile),
            InventoryNavigationCompiler(profile=self.profile),
            GPSFeatureCompiler(profile=self.profile),
            ConsoleFeatureCompiler(profile=self.profile),
            SpriteCacheCompiler(profile=self.profile, symbols=symbols),
            InventoryFeatureCompiler(
                symbols=symbols,
                profile=self.profile,
                room_rendering_abi=room_rendering_abi,
            ),
            ResourceDispatchCompiler(
                symbols=symbols,
                profile=self.profile,
                transition_abi=transition_abi,
            ),
            FingerprintFeatureCompiler(symbols=symbols, profile=self.profile),
            CaptionFeatureCompiler(
                symbols=symbols,
                profile=self.profile,
                room_rendering_abi=room_rendering_abi,
                transition_abi=transition_abi,
            ),
            SystemScreenCompiler(
                symbols=symbols,
                profile=self.profile,
                room_rendering_abi=room_rendering_abi,
                transition_abi=transition_abi,
            ),
            SidneyPresentationCompiler(
                symbols=symbols,
                profile=self.profile,
                room_rendering_abi=room_rendering_abi,
                mouse_move_abi=mouse_move_abi,
            ),
        )

    def precheck(self, image: PEFile) -> None:
        """Compile a disposable clone after declared dependencies are present.

        ``OperationExecutor`` presents operations in planner order, so the
        transition and mouse-dispatch ABIs already exist in this image. The
        direct room ABI is intrinsic to this payload. Rebuilding this compiler
        on a clone validates its complete source and payload contract without
        privately invoking any other registry patch implementation.
        """
        clone = image.clone()
        self._compile(clone)

    def apply(self, image: PEFile) -> None:
        """Compile every interface feature into the in-memory target."""
        self._compile(image)

    def postcheck(self, image: PEFile) -> None:
        """Verify the complete runtime and every executable mutation once."""
        runtime = RuntimeImage(image)
        runtime.prepare()
        runtime.validate_complete()
        self._verify_deterministic_payload(image)

    def _verify_deterministic_payload(self, image: PEFile) -> None:
        """Rebuild and byte-verify the runtime plus all of its redirects.

        The installed executable is a deterministic compiler output. Starting
        from a clone, erase every owned runtime segment and apply each feature
        again. Comparing the rebuilt image with the installed image verifies
        wrapper bodies, hook redirects, vtable entries, constants, and shared
        ABI bytes through one generic mechanism. Runtime counters change mapped
        process memory, never the executable on disk.
        """
        expected = image.clone()
        expected_shared = expected.get_section(RuntimeLayout.section_name)
        actual_shared = image.get_section(RuntimeLayout.section_name)
        if expected_shared is None or actual_shared is None:
            raise RuntimeLayoutError.missing_shared_section()

        # Preserve the physical PE section and its shared ABI header, but erase
        # every logical feature segment.  Component apply methods can then
        # rebuild those reserved ranges through the same RuntimeImage adapter
        # used during installation.  Existing executable redirects are safe:
        # apply writes their identical deterministic values and does not need
        # a second pristine-input precheck.
        for segment in RuntimeLayout.segments:
            expected.write_bytes(
                expected_shared.pointer_to_raw_data + segment.offset,
                b"\x00" * segment.size,
            )
        rebuilt_runtime = RuntimeImage(expected)
        rebuilt_symbols = rebuilt_runtime.prepare()
        rebuilt_view = cast("PEFile", rebuilt_runtime)
        transition_abi = TransitionFrameCompiler.runtime_abi(expected)
        room_rendering_abi = DirectRoomRenderingCompiler(
            symbols=rebuilt_symbols,
            profile=self.profile,
        ).abi()
        mouse_move_abi = StaleMouseMoveCompiler(profile=self.profile).input_abi(expected)
        for component in self._components(
            rebuilt_symbols,
            transition_abi=transition_abi,
            room_rendering_abi=room_rendering_abi,
            mouse_move_abi=mouse_move_abi,
        ):
            component.apply(rebuilt_view)
        rebuilt_runtime.validate_complete()

        # Compare segment-by-segment so a mismatch identifies its owning
        # feature family instead of surfacing as an opaque executable hash.
        for segment in RuntimeLayout.segments:
            actual = image.read_bytes(
                actual_shared.pointer_to_raw_data + segment.offset,
                segment.size,
            )
            rebuilt = expected.read_bytes(
                expected_shared.pointer_to_raw_data + segment.offset,
                segment.size,
            )
            if actual != rebuilt:
                raise RuntimeLayoutError.payload_mismatch(segment.logical_name)

        # Each component's apply method also reconstructs its mutations in the
        # original executable sections. Starting the clone from the installed
        # image deliberately preserves unrelated bytes while overwriting every
        # owned redirect. Any remaining difference is therefore an owned hook
        # or constant whose installed value is stale or corrupt.
        if image.to_bytes() != expected.to_bytes():
            owner = "executable redirects"
            raise RuntimeLayoutError.payload_mismatch(owner)

    def _compile(self, image: PEFile) -> None:
        """Build every feature once using the shared exported symbol table."""
        if image.get_section(RuntimeLayout.section_name) is not None:
            raise RuntimeLayoutError.requires_pristine()

        runtime = RuntimeImage(image)
        symbols = runtime.prepare()
        view = cast("PEFile", runtime)
        transition_abi = TransitionFrameCompiler.runtime_abi(image)
        room_rendering_abi = DirectRoomRenderingCompiler(
            symbols=symbols,
            profile=self.profile,
        ).abi()
        mouse_move_abi = StaleMouseMoveCompiler(profile=self.profile).input_abi(image)
        components = self._components(
            symbols,
            transition_abi=transition_abi,
            room_rendering_abi=room_rendering_abi,
            mouse_move_abi=mouse_move_abi,
        )
        for component in components:
            self._apply_and_check(component, view)
        runtime.validate_complete()

    @staticmethod
    def _apply_and_check(component: PatchCompiler, image: PEFile) -> None:
        """Apply one feature compiler and validate its local contract."""
        component.precheck(image)
        component.apply(image)
        component.postcheck(image)
