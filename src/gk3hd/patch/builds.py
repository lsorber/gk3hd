"""Hash-bound GK3 build profiles and symbolic executable locations."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType
from typing import TYPE_CHECKING

from gk3hd.patch.model import BuildId

if TYPE_CHECKING:
    from collections.abc import Mapping

SHA256_HEX_LENGTH = 64
PROTECTED_STEAM_SHA256 = "7f5758776816852378d418365bb519cfed53a2c01507fdacba5def1678fb10c0"


class ProfileError(Exception):
    """Report invalid profile declarations or unsupported executable hashes."""


@dataclass(frozen=True, slots=True)
class PatchSite:
    """One symbolic, context-anchored byte sequence in a supported build."""

    symbol: str
    va: int
    original: bytes
    context_before: bytes = b""
    context_after: bytes = b""


@dataclass(frozen=True, slots=True)
class BuildProfile:
    """Immutable executable identity, sites, and reverse-engineered symbols."""

    id: BuildId
    label: str
    original_sha256: str
    sites: Mapping[str, PatchSite]
    symbols: Mapping[str, int]

    def __post_init__(self) -> None:
        """Reject malformed build facts before any patch can consume them."""
        # A frozen dataclass does not freeze a mutable mapping supplied by its
        # caller. Copy both catalogs before validation so later RE tooling
        # cannot change a live build profile through an aliased dictionary.
        object.__setattr__(self, "sites", MappingProxyType(dict(self.sites)))
        object.__setattr__(self, "symbols", MappingProxyType(dict(self.symbols)))
        if not self.id or not self.label:
            detail = "build profile ID and label must be nonempty"
            raise ProfileError(detail)
        if len(self.original_sha256) != SHA256_HEX_LENGTH or any(
            character not in "0123456789abcdef" for character in self.original_sha256
        ):
            detail = f"build {self.id!r} has a noncanonical SHA-256"
            raise ProfileError(detail)
        for key, site in self.sites.items():
            if key != site.symbol:
                detail = f"build {self.id!r} site key {key!r} disagrees with {site.symbol!r}"
                raise ProfileError(detail)
            if site.va <= 0 or not site.original:
                detail = f"build {self.id!r} site {key!r} has no address or source bytes"
                raise ProfileError(detail)
        ordered_sites = sorted(self.sites.values(), key=lambda site: site.va)
        for previous, current in pairwise(ordered_sites):
            if previous.va + len(previous.original) > current.va:
                detail = (
                    f"build {self.id!r} sites {previous.symbol!r} and {current.symbol!r} overlap"
                )
                raise ProfileError(detail)
        for symbol, address in self.symbols.items():
            if not symbol or address <= 0:
                detail = f"build {self.id!r} has an invalid engine symbol {symbol!r}"
                raise ProfileError(detail)

    def site(self, symbol: str) -> PatchSite:
        """Look up a required patch site by its stable symbolic name."""
        try:
            return self.sites[symbol]
        except KeyError as exc:
            detail = f"build {self.id!r} has no patch site {symbol!r}"
            raise ProfileError(detail) from exc

    def address(self, symbol: str) -> int:
        """Look up a required engine address by its stable symbolic name."""
        try:
            return self.symbols[symbol]
        except KeyError as exc:
            detail = f"build {self.id!r} has no engine symbol {symbol!r}"
            raise ProfileError(detail) from exc


# Steamless normalization produces the same patch-relevant code/data layout as
# the DRM-free GOG executable. The hashes stay distinct because support is
# explicitly bound to the two complete input binaries rather than inferred
# from a handful of matching sites.
_SHARED_SITES = MappingProxyType(
    {
        "image.coff_characteristics": PatchSite(
            symbol="image.coff_characteristics",
            # PE headers are mapped at ImageBase + file offset. Both supported
            # build inputs share this exact header and patch-relevant layout.
            va=0x00400116,
            original=bytes.fromhex("0f 01"),
        ),
        "cd_check.failure_flag": PatchSite(
            symbol="cd_check.failure_flag",
            va=0x004374A5,
            original=bytes.fromhex("fe c3"),
            context_before=bytes.fromhex("75 02"),
            context_after=bytes.fromhex("8a 45 0f 6a 00"),
        ),
        "savegame.warning_report": PatchSite(
            symbol="savegame.warning_report",
            va=0x004CCB56,
            # Persistence has already classified and formatted a nonfatal
            # warning list here. The stock callee logs it and opens a modal
            # Win32 dialog, which tears down fullscreen DirectDraw visibility.
            original=bytes.fromhex("e8 d5 0a 07 00"),
            context_before=bytes.fromhex("ff 75 08 57 50 ff 35 d4 b0 70 00"),
            context_after=bytes.fromhex("83 c4 14 8d 4d d8"),
        ),
        "camera.keyboard_motion_dispatch": PatchSite(
            symbol="camera.keyboard_motion_dispatch",
            va=0x0044999A,
            # UserSceneController::Update has converted the configured camera
            # keys into a smoothed two-axis integer delta here. The stock call
            # sends that fixed per-update delta through the shared mouse/camera
            # path, which makes keyboard speed depend on update cadence.
            original=bytes.fromhex("e8 c6 00 00 00"),
            context_before=bytes.fromhex("e8 c3 b1 01 00 50 53 57 8b ce"),
            context_after=bytes.fromhex("8b 8e e8 00 00 00"),
        ),
        "surface_check.lock": PatchSite(
            symbol="surface_check.lock",
            va=0x0054F61C,
            # This helper tests only the HRESULT; it never accesses pixels.
            original=bytes.fromhex("6a 00 50 ff 52 64"),
            context_before=bytes.fromhex("8b 46 2c 6a 00 51 8d 4d 84 8b 10 51"),
            context_after=bytes.fromhex("85 c0 7c 1f"),
        ),
        "surface_check.unlock": PatchSite(
            symbol="surface_check.unlock",
            va=0x0054F631,
            # Match the partial Lock with DDSURFACEDESC.lpSurface at EBP-58h.
            original=bytes.fromhex("6a 00 56 ff 92 80 00 00 00"),
            context_before=bytes.fromhex("8b 76 2c 6a 00 6a 00 6a 00 8b 16"),
            context_after=bytes.fromhex("50 e8 30 99 02 00 83 c4 10 eb 02 33 db"),
        ),
        "camera.motion_float_conversion": PatchSite(
            symbol="camera.motion_float_conversion",
            va=0x00449AE3,
            # The common keyboard/mouse camera path converts both integer axes
            # to floats immediately before applying walk/fly/strafe/pitch mode.
            # A scoped runtime flag lets the bridge normalize keyboard input
            # here without changing physical mouse motion.
            original=bytes.fromhex("db 45 0c ff b0 44 01 00 00 d9 5d 10"),
            context_before=bytes.fromhex("d9 5d 08 8b 40 6c"),
            context_after=bytes.fromhex("ff d6 66 85 c0 7d 18"),
        ),
        "quality.model_lod_default": PatchSite(
            symbol="quality.model_lod_default",
            va=0x004FC667,
            original=bytes.fromhex("6a 32"),
        ),
        "quality.anisotropy_default": PatchSite(
            symbol="quality.anisotropy_default",
            va=0x004FC437,
            original=bytes.fromhex("6a 00 68 1a 5a 00 00"),
        ),
        "quality.gamma_default": PatchSite(
            symbol="quality.gamma_default",
            va=0x00559FA2,
            # RenderOptions' constructor loads one shared 1.0 scalar into
            # EDX before assigning gamma, model LOD, and another option.
            original=bytes.fromhex("ba 00 00 80 3f"),
            context_before=bytes.fromhex("8b c1"),
            context_after=bytes.fromhex("33 c9"),
        ),
        "quality.gamma_shared_scalar_restore": PatchSite(
            symbol="quality.gamma_shared_scalar_restore",
            va=0x00559FC3,
            # After gamma has consumed EDX, this sequence initializes the
            # independent -1.0 and 1.0 fields. Keep it as an asserted anchor:
            # backend-specific gamma selection belongs to persisted policy,
            # so the constructor's shared scalar must remain untouched.
            original=bytes.fromhex("c7 40 14 00 00 80 bf 89 50 18"),
            context_before=bytes.fromhex("89 50 10"),
            context_after=bytes.fromhex("89 48 1c"),
        ),
        "quality.gamma_identity_red": PatchSite(
            symbol="quality.gamma_identity_red",
            va=0x0055A092,
            # The stock loop loads an embedded, channel-specific CRT base
            # curve. Modern DirectDraw implementations apply that curve while
            # the native Windows 11 path ignores it. Derive the input from the
            # loop index instead so gamma 1.0 is a true identity ramp.
            original=bytes.fromhex("33 c9 66 8b 8e c0 7c 6f 00"),
        ),
        "quality.gamma_identity_green": PatchSite(
            symbol="quality.gamma_identity_green",
            va=0x0055A0B9,
            original=bytes.fromhex("33 c0 66 8b 86 c0 7e 6f 00"),
        ),
        "quality.gamma_identity_blue": PatchSite(
            symbol="quality.gamma_identity_blue",
            va=0x0055A0E8,
            original=bytes.fromhex("33 d2 66 8b 96 c0 80 6f 00"),
        ),
        "textures.high_quality_limits": PatchSite(
            symbol="textures.high_quality_limits",
            va=0x006F7C84,
            original=bytes.fromhex("40 00 00 00 80 00 00 00 00 01 00 00"),
        ),
        "resolution.fallback": PatchSite(
            symbol="resolution.fallback",
            va=0x0049871C,
            original=bytes.fromhex("85 f6 74 04 85 ff 75 0a be 80 02 00 00 bf e0 01 00 00"),
        ),
        "resolution.menu_filter": PatchSite(
            symbol="resolution.menu_filter",
            va=0x004E7F0B,
            original=bytes.fromhex("8b 15 d4 b0 70 00 b9 84"),
        ),
        "resolution.framebuffer_guard": PatchSite(
            symbol="resolution.framebuffer_guard",
            va=0x00574CCB,
            original=bytes.fromhex("3b f8 72 46"),
        ),
        "refresh.set_display_mode": PatchSite(
            symbol="refresh.set_display_mode",
            va=0x00574E29,
            # PUSH width; PUSH IDirectDraw4; SetDisplayMode; skip the
            # windowed-mode branch.  The wrapper retains the already-built
            # height/bpp/refresh/flags arguments and owns only this call.
            original=bytes.fromhex("52 50 ff 51 54 eb 29"),
            context_before=bytes.fromhex("8b 15 cc b0 70 00 8b 12"),
            context_after=bytes.fromhex("a1 3c d2 70 00 6a 00 85 c0"),
        ),
        "high_resolution_3d.z_attach_surface": PatchSite(
            symbol="high_resolution_3d.z_attach_surface",
            va=0x00575919,
            original=bytes.fromhex("a1 48 d2 70 00"),
        ),
        "high_resolution_3d.z_dimensions": PatchSite(
            symbol="high_resolution_3d.z_dimensions",
            va=0x00575803,
            original=bytes.fromhex("8b 08 89 8d f8 fe ff ff 8b 02 89 85 f4 fe ff ff"),
        ),
        "high_resolution_3d.device_surface": PatchSite(
            symbol="high_resolution_3d.device_surface",
            va=0x00579C68,
            original=bytes.fromhex("a1 48 d2 70 00"),
        ),
        "high_resolution_3d.end_scene": PatchSite(
            symbol="high_resolution_3d.end_scene",
            va=0x005996F0,
            original=bytes.fromhex("a1 64 d2 70 00"),
        ),
        "high_resolution_3d.projection_begin": PatchSite(
            symbol="high_resolution_3d.projection_begin",
            va=0x005586FC,
            original=bytes.fromhex("e8 cf 01 00 00"),
        ),
        "high_resolution_3d.viewport_dimensions": PatchSite(
            symbol="high_resolution_3d.viewport_dimensions",
            va=0x00575CD0,
            original=bytes.fromhex("a1 cc b0 70 00 8b 0d c8 b0 70 00"),
        ),
        "high_resolution_3d.release_surface": PatchSite(
            symbol="high_resolution_3d.release_surface",
            va=0x00575FCB,
            original=bytes.fromhex("a1 48 d2 70 00"),
        ),
        "high_resolution_3d.viewport_warning": PatchSite(
            symbol="high_resolution_3d.viewport_warning",
            va=0x0056D01C,
            original=bytes.fromhex("68 8c 54 69 00 57 e8 c9 05 fd ff 83 c4 08"),
        ),
        "high_resolution_3d.damage_history": PatchSite(
            symbol="high_resolution_3d.damage_history",
            va=0x0055C670,
            # MOV EAX,[ECX+5C]; TEST EAX,EAX. The staged wrapper preserves
            # this availability test before selecting one stable history.
            original=bytes.fromhex("8b 41 5c 85 c0"),
        ),
        "high_resolution_3d.color_damage_target": PatchSite(
            symbol="high_resolution_3d.color_damage_target",
            va=0x0056D670,
            # MOV EAX,[EAX+2C]; PUSH 0. The staged wrapper substitutes only
            # the destination surface used by native background restoration.
            original=bytes.fromhex("8b 40 2c 6a 00"),
        ),
        "high_resolution_3d.damage_snapshot_source": PatchSite(
            symbol="high_resolution_3d.damage_snapshot_source",
            va=0x0056D38F,
            # CALL FUN_0054D690; MOV EAX,[EAX+2C]. FUN_0056D310 copies this
            # renderer target into GK3's dedicated clean-background surface.
            # The call site is shared by later physical-page captures, so the
            # staged replacement must also require an active 3D projection.
            original=bytes.fromhex("e8 fc 02 fe ff 8b 40 2c"),
        ),
        "movies.update": PatchSite(
            symbol="movies.update",
            va=0x00591FE0,
            original=bytes.fromhex("53 56 8b f1 bb 01 00 00 00 8b"),
        ),
        "movies.bink_open_call": PatchSite(
            symbol="movies.bink_open_call",
            va=0x00591B2B,
            original=bytes.fromhex("ff 15 d0 53 66 00"),
        ),
        "movies.complete_anchor": PatchSite(
            symbol="movies.complete_anchor",
            va=0x00591880,
            original=bytes.fromhex("55 8b ec 56 8b f1 66 83 7e 06 00 74 36 8b 06 ff"),
        ),
        "quality.mipmapping_default": PatchSite(
            symbol="quality.mipmapping_default",
            va=0x004FC0F2,
            original=bytes.fromhex("6a 01 68 15 5a 00 00"),
        ),
        "quality.interpolation_default": PatchSite(
            symbol="quality.interpolation_default",
            va=0x004FC204,
            original=bytes.fromhex("6a 01 68 16 5a 00 00"),
        ),
        "quality.trilinear_device_default": PatchSite(
            symbol="quality.trilinear_device_default",
            va=0x004FC312,
            original=bytes.fromhex("a1 d4 b0 70 00 53 56 8b f1 8b 80 18 01 00 00"),
        ),
        "quality.lightmap_default": PatchSite(
            symbol="quality.lightmap_default",
            va=0x004FCB97,
            original=bytes.fromhex("c7 45 f0 04 00 00 00"),
        ),
        "quality.diffuse_default": PatchSite(
            symbol="quality.diffuse_default",
            va=0x004FCD45,
            original=bytes.fromhex("c7 45 f0 05 00 00 00"),
        ),
        "quality.surface_memory_check": PatchSite(
            symbol="quality.surface_memory_check",
            va=0x004FC774,
            original=bytes.fromhex("a1 dc b0 70 00 53 56 57 8b 40 68 6a 01 5f 3d 00 00 00 03"),
        ),
        "anisotropy.signed_override": PatchSite(
            symbol="anisotropy.signed_override",
            va=0x0049B6EF,
            original=bytes.fromhex("e8 33 0d 06 00 85 c0 7c 09 8b 8b 18 01 00 00 89 41 20"),
        ),
        "anisotropy.capability_detection": PatchSite(
            symbol="anisotropy.capability_detection",
            va=0x00579FD9,
            original=bytes.fromhex(
                "8b 43 6c 83 c4 18 33 ff a9 00 00 02 00 89 7e 30 74 09 8b 8b d4 00 00 00 89 4e 30"
            ),
        ),
        "anisotropy.renderer_path": PatchSite(
            symbol="anisotropy.renderer_path",
            va=0x00579B93,
            original=bytes.fromhex(
                "8b 59 20 85 db 7e 7a 6a 00 6a 00 6a 00 6a 05 6a 10 "
                "57 8b ce e8 c4 0a 00 00 50 e8 be f3 ff ff 83 c4 10 "
                "8b ce 6a 00 6a 00 6a 00 6a 03 6a 11 57 e8 a9 0a 00 "
                "00 50 e8 a3 f3 ff ff 83 c4 10 6a 00 6a 00 6a 00 53 6a 15"
            ),
        ),
        "textures.low_quality_limits": PatchSite(
            symbol="textures.low_quality_limits",
            va=0x006F7C78,
            original=bytes.fromhex("40 00 00 00 40 00 00 00 80 00 00 00"),
        ),
        "textures.limit_lookup": PatchSite(
            symbol="textures.limit_lookup",
            va=0x0054E521,
            original=bytes.fromhex(
                "8d 45 08 50 e8 f6 fa ff ff a1 d4 b0 70 00 83 c4 04 "
                "8a 48 6d 84 c9 74 2b 8b 88 18 01 00 00 8b 55 18 8b "
                "01 8d 0c 42 03 c1 8b 04 85 78 7c 6f 00 85 c0 74 10 "
                "39 45 08 7e 03 89 45 08 39 45 0c 7e 03 89 45 0c"
            ),
        ),
        "transition.flip_hook": PatchSite(
            symbol="transition.flip_hook",
            va=0x0055C49B,
            original=bytes.fromhex("a1 44 d2 70 00 56 6a 00 50 8b 08 ff 51 2c"),
        ),
        "transition.seed_hook": PatchSite(
            symbol="transition.seed_hook",
            va=0x0052A5DD,
            original=bytes.fromhex("b8 22 3d 61 00"),
        ),
        "transition.begin_hook": PatchSite(
            symbol="transition.begin_hook",
            va=0x005996C0,
            original=bytes.fromhex("a1 64 d2 70 00"),
        ),
        "transition.blt_hook": PatchSite(
            symbol="transition.blt_hook",
            va=0x0054FA39,
            original=bytes.fromhex("ff 52 14 3d ae 01 76 88"),
        ),
        "transition.flip_retry_anchor": PatchSite(
            symbol="transition.flip_retry_anchor",
            va=0x0055C490,
            original=bytes.fromhex("8b 1d 80 51 66 00 bf 9f 86 01 00"),
        ),
        "transition.flip_result_anchor": PatchSite(
            symbol="transition.flip_result_anchor",
            va=0x0055C4A9,
            original=bytes.fromhex("3d a0 00 76 88"),
        ),
        "transition.scene_setup_anchor": PatchSite(
            symbol="transition.scene_setup_anchor",
            va=0x0052A5E2,
            original=bytes.fromhex("e8 39 72 09 00"),
        ),
        "transition.begin_scene_anchor": PatchSite(
            symbol="transition.begin_scene_anchor",
            va=0x005996C5,
            original=bytes.fromhex("8b 80 e8 04 00 00 50 8b 08"),
        ),
        "transition.blt_result_anchor": PatchSite(
            symbol="transition.blt_result_anchor",
            va=0x0054FA41,
            original=bytes.fromhex("77 12 74 17 3d 01 40 00 80"),
        ),
        "mouse_move.target_dispatch": PatchSite(
            symbol="mouse_move.target_dispatch",
            va=0x004BEC08,
            original=bytes.fromhex("8b 4e 14 57 8b 01 ff 50 50"),
        ),
        "mouse_move.target_dispatch_prefix": PatchSite(
            symbol="mouse_move.target_dispatch_prefix",
            va=0x004BEBF0,
            original=bytes.fromhex("56 57 8b 7c 24 0c 6a 00 8b f1 57 e8 f4 06 00 00 57 8b ce"),
        ),
        "mouse_move.target_dispatch_suffix": PatchSite(
            symbol="mouse_move.target_dispatch_suffix",
            va=0x004BEC11,
            original=bytes.fromhex("33 c9 b8 67 4d 44 00 51 50 57 8b ce e8 33 03 00 00"),
        ),
        "mouse_move.ui_dispatch_call": PatchSite(
            symbol="mouse_move.ui_dispatch_call",
            va=0x0049AB75,
            original=bytes.fromhex("e8 76 40 02 00"),
        ),
        "mouse_move.ui_dispatch_prefix": PatchSite(
            symbol="mouse_move.ui_dispatch_prefix",
            va=0x0049AB66,
            original=bytes.fromhex("a1 38 f8 6f 00 57 8b 80 44 04 00 00 8b 48 44"),
        ),
        "mouse_move.ui_dispatch_suffix": PatchSite(
            symbol="mouse_move.ui_dispatch_suffix",
            va=0x0049AB7A,
            original=bytes.fromhex("80 be 44 05 00 00 00 74 14"),
        ),
        "input.left_press_dispatch_call": PatchSite(
            symbol="input.left_press_dispatch_call",
            va=0x0049A944,
            original=bytes.fromhex("e8 80 4b 02 00"),
        ),
        "input.drag_begin_dispatch_call": PatchSite(
            symbol="input.drag_begin_dispatch_call",
            va=0x0049AC02,
            original=bytes.fromhex("e8 5a 44 02 00"),
            context_after=bytes.fromhex("a1 10 6f 70 00 89 03"),
        ),
        "input.right_press_dispatch_call": PatchSite(
            symbol="input.right_press_dispatch_call",
            va=0x0049A993,
            original=bytes.fromhex("e8 54 4b 02 00"),
        ),
        "input.middle_press_dispatch_call": PatchSite(
            symbol="input.middle_press_dispatch_call",
            va=0x0049A9D5,
            original=bytes.fromhex("e8 35 4b 02 00"),
        ),
        "input.left_release_dispatch_call": PatchSite(
            symbol="input.left_release_dispatch_call",
            va=0x0049ACA3,
            original=bytes.fromhex("e8 ad 42 02 00"),
        ),
        "input.right_release_dispatch_call": PatchSite(
            symbol="input.right_release_dispatch_call",
            va=0x0049AD2F,
            original=bytes.fromhex("e8 21 42 02 00"),
        ),
        "input.middle_release_dispatch_call": PatchSite(
            symbol="input.middle_release_dispatch_call",
            va=0x0049ADAE,
            original=bytes.fromhex("e8 a2 41 02 00"),
        ),
        "input.left_click_dispatch_call": PatchSite(
            symbol="input.left_click_dispatch_call",
            va=0x0049AD05,
            original=bytes.fromhex("e8 dc 42 02 00"),
        ),
        "input.right_click_dispatch_call": PatchSite(
            symbol="input.right_click_dispatch_call",
            va=0x0049AD84,
            original=bytes.fromhex("e8 c0 41 02 00"),
        ),
        "input.middle_click_dispatch_call": PatchSite(
            symbol="input.middle_click_dispatch_call",
            va=0x0049AE0C,
            original=bytes.fromhex("e8 d5 41 02 00"),
        ),
        "mouse_move.motion_dispatch_call": PatchSite(
            symbol="mouse_move.motion_dispatch_call",
            va=0x0049AC66,
            # MouseManager's second traversal publishes context-sensitive
            # hover state through vtable slot +0x78. It consumes the same
            # current POINT as the earlier common UI traversal but also owns
            # physical delta/flag arguments which must remain untouched.
            original=bytes.fromhex("e8 7d 44 02 00"),
            context_before=bytes.fromhex(
                "8d 45 f8 50 a1 38 f8 6f 00 57 8b 80 44 04 00 00 8b 48 44"
            ),
            context_after=bytes.fromhex("8b 07 89 86 1c 05 00 00 8b 47 04 89 86 20 05 00 00"),
        ),
        "mouse_move.periodic_cursor_select_call": PatchSite(
            symbol="mouse_move.periodic_cursor_select_call",
            va=0x004BF249,
            # CursorDispatcher's activation update reads DirectInput outside
            # MouseManager::Move, then reselects from the authored UI tree.
            # Modern fixed canvases must inverse-map this independent POINT at
            # the selector boundary without retaining logical cursor state.
            original=bytes.fromhex("e8 a6 00 00 00"),
            context_before=bytes.fromhex("6a 01 8b ce 8b 45 f8 50"),
            context_after=bytes.fromhex("8d 45 f8 8b ce 50 e8 47 01 00 00"),
        ),
        "mouse_move.idle_cursor_select_call": PatchSite(
            symbol="mouse_move.idle_cursor_select_call",
            va=0x004BEBAD,
            # Descriptor invalidation enters this idle helper independently of
            # MouseManager::Move. It polls DirectInput into a stack POINT and
            # selects the cursor immediately before the paired idle tooltip
            # resolver, so it owns the same fixed-interface inverse contract.
            original=bytes.fromhex("e8 42 07 00 00"),
            context_before=bytes.fromhex("ff 75 08 8d 45 f8 50 e8 38 dd 0a 00 59 50 8b ce"),
            context_after=bytes.fromhex("5e c9 c2 04 00"),
        ),
        "mouse_move.nested_dispatch": PatchSite(
            symbol="mouse_move.nested_dispatch",
            va=0x00525422,
            original=bytes.fromhex("ff 90 b4 00 00 00"),
        ),
        "mouse_move.nested_dispatch_prefix": PatchSite(
            symbol="mouse_move.nested_dispatch_prefix",
            va=0x0052541E,
            original=bytes.fromhex("8b 06 8b ce"),
        ),
        "mouse_move.nested_dispatch_suffix": PatchSite(
            symbol="mouse_move.nested_dispatch_suffix",
            va=0x00525428,
            original=bytes.fromhex("5e 33 c0 5b c2 04 00"),
        ),
        "mouse_move.interactive_point_cache": PatchSite(
            symbol="mouse_move.interactive_point_cache",
            va=0x005253C4,
            original=bytes.fromhex(
                "8b 44 24 0c 38 9e ac 01 00 00 8b 08 89 8e a0 01 00 00 8b 40 04 89 86 a4 01 00 00"
            ),
        ),
        "mouse_move.wndproc_dispatch": PatchSite(
            symbol="mouse_move.wndproc_dispatch",
            va=0x00533CE7,
            original=bytes.fromhex("8b 11 ff 52 58"),
        ),
        "mouse_move.wndproc_dispatch_prefix": PatchSite(
            symbol="mouse_move.wndproc_dispatch_prefix",
            va=0x00533CDD,
            original=bytes.fromhex("8b 0d d4 b0 70 00 8d 45 f8 50"),
        ),
        "mouse_move.wndproc_dispatch_suffix": PatchSite(
            symbol="mouse_move.wndproc_dispatch_suffix",
            va=0x00533CEC,
            original=bytes.fromhex("5f 5e 33 c0 5b 8b e5 5d c2 10 00"),
        ),
        "mouse_move.popup_message_dispatch": PatchSite(
            symbol="mouse_move.popup_message_dispatch",
            va=0x004BECE6,
            original=bytes.fromhex("8b 01 8d 55 08 52 ff 50 0c"),
        ),
        "mouse_move.popup_query_dispatch": PatchSite(
            symbol="mouse_move.popup_query_dispatch",
            va=0x004BEE44,
            original=bytes.fromhex("8b 01 ff 50 60"),
        ),
        "mouse_move.message_primary_dispatch": PatchSite(
            symbol="mouse_move.message_primary_dispatch",
            va=0x004BECB6,
            original=bytes.fromhex("8b 01 ff 50 0c"),
        ),
        "mouse_move.message_secondary_dispatch": PatchSite(
            symbol="mouse_move.message_secondary_dispatch",
            va=0x004BECC2,
            original=bytes.fromhex("8b 01 ff 50 0c"),
        ),
        "mouse_move.message_list_dispatch": PatchSite(
            symbol="mouse_move.message_list_dispatch",
            va=0x004BEDD0,
            original=bytes.fromhex("8b 01 ff 50 0c"),
        ),
        "mouse_move.message_selected_dispatch": PatchSite(
            symbol="mouse_move.message_selected_dispatch",
            va=0x004BEE03,
            original=bytes.fromhex("8b 08 8b 01 ff 50 0c"),
        ),
        "mouse_move.tree_b8_1": PatchSite(
            symbol="mouse_move.tree_b8_1",
            va=0x004BF30F,
            original=bytes.fromhex("ff 90 b8 00 00 00"),
        ),
        "mouse_move.tree_b8_2": PatchSite(
            symbol="mouse_move.tree_b8_2",
            va=0x004BF326,
            original=bytes.fromhex("ff 90 b8 00 00 00"),
        ),
        "mouse_move.tree_b8_3": PatchSite(
            symbol="mouse_move.tree_b8_3",
            va=0x004BF33D,
            original=bytes.fromhex("ff 90 b8 00 00 00"),
        ),
        "mouse_move.tree_b8_4": PatchSite(
            symbol="mouse_move.tree_b8_4",
            va=0x004BF367,
            original=bytes.fromhex("ff 90 b8 00 00 00"),
        ),
        "mouse_move.tree_bc_1": PatchSite(
            symbol="mouse_move.tree_bc_1",
            va=0x004BF3C4,
            original=bytes.fromhex("ff 90 bc 00 00 00"),
        ),
        "mouse_move.tree_bc_2": PatchSite(
            symbol="mouse_move.tree_bc_2",
            va=0x004BF3DD,
            original=bytes.fromhex("ff 90 bc 00 00 00"),
        ),
        "mouse_move.tree_bc_3": PatchSite(
            symbol="mouse_move.tree_bc_3",
            va=0x004BF408,
            original=bytes.fromhex("ff 90 bc 00 00 00"),
        ),
        "mouse_move.tree_b4_1": PatchSite(
            symbol="mouse_move.tree_b4_1",
            va=0x004BF46B,
            original=bytes.fromhex("ff 90 b4 00 00 00"),
        ),
        "mouse_move.tree_b4_2": PatchSite(
            symbol="mouse_move.tree_b4_2",
            va=0x0052516C,
            original=bytes.fromhex("ff 90 b4 00 00 00"),
        ),
        "editbox.caret_fill_call": PatchSite(
            symbol="editbox.caret_fill_call",
            va=0x0048755F,
            original=bytes.fromhex("e8 f2 20 01 00"),
        ),
        "console.layout_width": PatchSite(
            symbol="console.layout_width",
            va=0x00463946,
            original=bytes.fromhex("8b 8e d0 00 00 00"),
        ),
        **{
            f"console.pointer_{slot:02x}": PatchSite(
                symbol=f"console.pointer_{slot:02x}",
                va=0x00674DBC + slot,
                original=target.to_bytes(4, "little"),
            )
            for slot, target in zip(
                range(0x44, 0x60, 4),
                (0x463CCF, 0x463CE7, 0x463CFF, 0x463D17, 0x463D2F, 0x463D47, 0x463D5F),
                strict=True,
            )
        },
        "console.layout_bounds": PatchSite(
            symbol="console.layout_bounds",
            va=0x00463B76,
            original=bytes.fromhex("83 4d fc ff 6a 01"),
        ),
        "console.caret_entry": PatchSite(
            symbol="console.caret_entry",
            va=0x00499656,
            original=bytes.fromhex("b8 ca 06 60 00"),
        ),
        "console.border_entry": PatchSite(
            symbol="console.border_entry",
            va=0x0055C0F0,
            original=bytes.fromhex("55 8b ec 6a ff"),
        ),
        "bitmap.solid_fill_call": PatchSite(
            symbol="bitmap.solid_fill_call",
            va=0x0054D47A,
            original=bytes.fromhex("e8 61 2c 00 00"),
        ),
        "sidney.construct.origin_width": PatchSite(
            symbol="sidney.construct.origin_width",
            va=0x00648E88,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.width_01": PatchSite(
            symbol="sidney.construct.width_01",
            va=0x00647CB0,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.height_01": PatchSite(
            symbol="sidney.construct.height_01",
            va=0x00647CCF,
            original=bytes.fromhex("a1 c8 b0 70 00"),
        ),
        "sidney.construct.width_02": PatchSite(
            symbol="sidney.construct.width_02",
            va=0x00647D46,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.width_03": PatchSite(
            symbol="sidney.construct.width_03",
            va=0x00647D92,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.width_04": PatchSite(
            symbol="sidney.construct.width_04",
            va=0x00647E15,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.height_02": PatchSite(
            symbol="sidney.construct.height_02",
            va=0x00647EA2,
            original=bytes.fromhex("a1 c8 b0 70 00"),
        ),
        "sidney.construct.height_03": PatchSite(
            symbol="sidney.construct.height_03",
            va=0x00647F2F,
            original=bytes.fromhex("a1 c8 b0 70 00"),
        ),
        "sidney.construct.width_05": PatchSite(
            symbol="sidney.construct.width_05",
            va=0x00647FA4,
            original=bytes.fromhex("8b 0d cc b0 70 00"),
        ),
        "sidney.construct.height_04": PatchSite(
            symbol="sidney.construct.height_04",
            va=0x00647FC9,
            original=bytes.fromhex("8b 0d c8 b0 70 00"),
        ),
        "sidney.construct.height_05": PatchSite(
            symbol="sidney.construct.height_05",
            va=0x00648152,
            original=bytes.fromhex("a1 c8 b0 70 00"),
        ),
        "sidney.construct.width_06": PatchSite(
            symbol="sidney.construct.width_06",
            va=0x006481D3,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.height_06": PatchSite(
            symbol="sidney.construct.height_06",
            va=0x00648E9F,
            original=bytes.fromhex("a1 c8 b0 70 00"),
        ),
        "sidney.construct.width_07": PatchSite(
            symbol="sidney.construct.width_07",
            va=0x00648EC5,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.width_08": PatchSite(
            symbol="sidney.construct.width_08",
            va=0x00648F11,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.width_09": PatchSite(
            symbol="sidney.construct.width_09",
            va=0x00648F94,
            original=bytes.fromhex("a1 cc b0 70 00"),
        ),
        "sidney.construct.height_07": PatchSite(
            symbol="sidney.construct.height_07",
            va=0x0064901B,
            original=bytes.fromhex("a1 c8 b0 70 00"),
        ),
        "sidney.construct.height_08": PatchSite(
            symbol="sidney.construct.height_08",
            va=0x006490A2,
            original=bytes.fromhex("a1 c8 b0 70 00"),
        ),
        "sidney.construct.height_09": PatchSite(
            symbol="sidney.construct.height_09",
            va=0x00649227,
            original=bytes.fromhex("a1 c8 b0 70 00"),
        ),
        "sidney.construct.width_10": PatchSite(
            symbol="sidney.construct.width_10",
            va=0x006492AD,
            original=bytes.fromhex("8b 0d cc b0 70 00"),
        ),
        "runtime2d.final_blt_call_1": PatchSite(
            symbol="runtime2d.final_blt_call_1",
            va=0x0054F913,
            original=bytes.fromhex("e8 68 00 00 00"),
        ),
        "runtime2d.final_blt_call_2": PatchSite(
            symbol="runtime2d.final_blt_call_2",
            va=0x0054F944,
            original=bytes.fromhex("e8 37 00 00 00"),
        ),
        "runtime2d.final_blt_call_3": PatchSite(
            symbol="runtime2d.final_blt_call_3",
            va=0x0054FB94,
            original=bytes.fromhex("e8 e7 fd ff ff"),
        ),
        "inventory.effect_constructor_call": PatchSite(
            symbol="inventory.effect_constructor_call",
            va=0x0054F8B5,
            original=bytes.fromhex("e8 76 7e 02 00"),
        ),
        "inventory.selection_layout_call": PatchSite(
            symbol="inventory.selection_layout_call",
            va=0x00492A43,
            original=bytes.fromhex("e8 6b e9 02 00"),
            context_before=bytes.fromhex("e8 4d 85 fc ff 8b c8"),
            context_after=bytes.fromhex("c2 0c 00"),
        ),
        "inventory.selection_grid_call": PatchSite(
            symbol="inventory.selection_grid_call",
            va=0x004C13A9,
            original=bytes.fromhex("e8 f5 07 00 00"),
            context_before=bytes.fromhex("8b 00 89 83 40 01 00 00 8b cb"),
            context_after=bytes.fromhex("5f 5e 5b c9 c3"),
        ),
        "inventory.scrollbar_width": PatchSite(
            symbol="inventory.scrollbar_width",
            va=0x004C1FC7,
            original=bytes.fromhex("8b 0d cc b0 70 00"),
            context_after=bytes.fromhex("8b 11 59 2b d1 89 10"),
        ),
        "inventory.scrollbar_grid_call": PatchSite(
            symbol="inventory.scrollbar_grid_call",
            va=0x004C1850,
            original=bytes.fromhex("e8 4e 03 00 00"),
            context_after=bytes.fromhex("c2 04 00"),
        ),
        "inventory.scrollbar_page_size_call": PatchSite(
            symbol="inventory.scrollbar_page_size_call",
            va=0x004C1914,
            original=bytes.fromhex("e8 78 06 00 00"),
            context_after=bytes.fromhex("50 8b ce"),
        ),
        "inventory.scrollbar_height": PatchSite(
            symbol="inventory.scrollbar_height",
            va=0x004C1FDA,
            original=bytes.fromhex("8b 0d c8 b0 70 00 8b 09"),
            context_after=bytes.fromhex("89 48 04 c3"),
        ),
        "runtime2d.closeup_center_call": PatchSite(
            symbol="runtime2d.closeup_center_call",
            va=0x0045AA3B,
            original=bytes.fromhex("e8 9a be 00 00"),
        ),
        "bitmap.drawable_entry": PatchSite(
            symbol="bitmap.drawable_entry", va=0x0046709A, original=bytes.fromhex("55 8b ec 51 51")
        ),
        "bitmap.set_image_rect": PatchSite(
            symbol="bitmap.set_image_rect",
            va=0x00467040,
            original=bytes.fromhex("ff 90 a8 00 00 00"),
        ),
        "bitmap.set_image_dimensions": PatchSite(
            symbol="bitmap.set_image_dimensions",
            va=0x0046700A,
            original=bytes.fromhex("e8 c1 d4 0c 00"),
            context_after=bytes.fromhex("8b 55 08 8b c8"),
        ),
        "sidney.preview_dimensions": PatchSite(
            symbol="sidney.preview_dimensions",
            va=0x0064497A,
            original=bytes.fromhex("e8 51 fb ee ff"),
            context_after=bytes.fromhex("8b 10 8b 5e 1c 8b 4e 20"),
        ),
        "bitmap.pixel_hit_entry": PatchSite(
            symbol="bitmap.pixel_hit_entry",
            va=0x004670E2,
            original=bytes.fromhex("55 8b ec 51 51"),
        ),
        "bitmap.dimensions_return": PatchSite(
            symbol="bitmap.dimensions_return",
            va=0x005344F5,
            original=bytes.fromhex("8b 46 30 83 c0 38"),
        ),
        "loadsave.preview_attach": PatchSite(
            symbol="loadsave.preview_attach",
            va=0x004CA3DE,
            original=bytes.fromhex("ff 92 c4 00 00 00"),
        ),
        **{
            f"sidney.frame.{name}": PatchSite(
                symbol=f"sidney.frame.{name}", va=va, original=bytes.fromhex(original)
            )
            for name, va, original in (
                ("create_top", 0x00647DB7, "e8 64 c8 ee ff"),
                ("create_bottom", 0x00647E3A, "e8 e1 c7 ee ff"),
                ("create_left", 0x00647EC7, "e8 54 c7 ee ff"),
                ("create_right", 0x00647F54, "e8 c7 c6 ee ff"),
                ("rebuild_top", 0x00648F36, "e8 e5 b6 ee ff"),
                ("rebuild_bottom", 0x00648FB9, "e8 62 b6 ee ff"),
                ("rebuild_left", 0x00649040, "e8 db b5 ee ff"),
                ("rebuild_right", 0x006490C7, "e8 54 b5 ee ff"),
            )
        },
        "driving_map.draw_call": PatchSite(
            symbol="driving_map.draw_call", va=0x0049C74C, original=bytes.fromhex("e8 2b 27 02 00")
        ),
        "driving_map.ellipse_call": PatchSite(
            symbol="driving_map.ellipse_call",
            va=0x00480F9A,
            original=bytes.fromhex("ff 15 38 50 66 00"),
        ),
        "driving_map.TR1.origin": PatchSite(
            symbol="driving_map.TR1.origin",
            va=0x0047D0B3,
            original=bytes.fromhex("68 86 00 00 00 6a 36"),
        ),
        "driving_map.RL1.origin": PatchSite(
            symbol="driving_map.RL1.origin",
            va=0x0047D051,
            original=bytes.fromhex("68 aa 00 00 00 68 e7 01 00 00"),
        ),
        "driving_map.TRE.origin": PatchSite(
            symbol="driving_map.TRE.origin",
            va=0x0047D111,
            original=bytes.fromhex("6a 5b 68 fa 01 00 00"),
        ),
        "timeblock.center_call": PatchSite(
            symbol="timeblock.center_call", va=0x004D5790, original=bytes.fromhex("e8 45 11 f9 ff")
        ),
        # Bitmap resources normally copy into a same-sized cached surface.
        # TitleLayer is the one verified caller that deliberately creates a
        # display-sized cache for a potentially denser replacement bitmap.
        # Native DirectDraw interprets the stock pair of NULL rectangles as a
        # clipped copy, so the runtime2d compositor supplies explicit extents.
        "resource.cache_blt_call": PatchSite(
            symbol="resource.cache_blt_call",
            va=0x0054D581,
            original=bytes.fromhex("ff 52 14 6a 00 6a 00"),
        ),
        "display.width_initializer": PatchSite(
            symbol="display.width_initializer",
            va=0x00532D80,
            original=bytes.fromhex("c7 05 cc b0 70 00"),
        ),
        "runtime2d.final_blt_entry": PatchSite(
            symbol="runtime2d.final_blt_entry",
            va=0x0054F980,
            original=bytes.fromhex("55 8b ec 6a ff"),
        ),
        "sprite_cache.paint": PatchSite(
            symbol="sprite_cache.paint", va=0x0063FA02, original=bytes.fromhex("55 8b ec 83 ec 28")
        ),
        "sprite_cache.styled_paint": PatchSite(
            symbol="sprite_cache.styled_paint",
            va=0x006290E3,
            original=bytes.fromhex("e8 1a 00 00 00"),
        ),
        "sprite_cache.dropdown_paint": PatchSite(
            symbol="sprite_cache.dropdown_paint",
            va=0x00641749,
            original=bytes.fromhex("55 8b ec 83 ec 3c"),
        ),
        "sprite_cache.alpha_constructor": PatchSite(
            symbol="sprite_cache.alpha_constructor",
            va=0x00577730,
            original=bytes.fromhex("55 8b ec 6a ff"),
        ),
        "sprite_cache.point": PatchSite(
            symbol="sprite_cache.point", va=0x005343E0, original=bytes.fromhex("55 8b ec 8b 45 0c")
        ),
        "sprite_cache.release": PatchSite(
            symbol="sprite_cache.release", va=0x005318F0, original=bytes.fromhex("56 8b f1 8b 06")
        ),
        "sprite_cache.clear_off": PatchSite(
            symbol="sprite_cache.clear_off", va=0x0063F714, original=bytes.fromhex("e8 84 2b dd ff")
        ),
        "sprite_cache.clear_on": PatchSite(
            symbol="sprite_cache.clear_on", va=0x0063F724, original=bytes.fromhex("e8 74 2b dd ff")
        ),
        "sprite_cache.clear_disabled": PatchSite(
            symbol="sprite_cache.clear_disabled",
            va=0x0063F734,
            original=bytes.fromhex("e8 64 2b dd ff"),
        ),
        "runtime2d.high_blt_entry": PatchSite(
            symbol="runtime2d.high_blt_entry",
            va=0x0054F670,
            original=bytes.fromhex("55 8b ec 6a ff"),
        ),
        "runtime2d.high_blt_dimensions": PatchSite(
            symbol="runtime2d.high_blt_dimensions",
            va=0x0054F6AA,
            original=bytes.fromhex("8b 57 38 8b 43 38 89 55 a4 8b 57 3c 8b 4b 3c 89 55 a8"),
        ),
        "runtime2d.mid_blt_entry": PatchSite(
            symbol="runtime2d.mid_blt_entry",
            va=0x0054D330,
            original=bytes.fromhex("55 8b ec 8b 45 14"),
        ),
        "cursor.final_blt_call": PatchSite(
            symbol="cursor.final_blt_call", va=0x004997A3, original=bytes.fromhex("e8 38 ac 09 00")
        ),
        "cursor.restore_history_query": PatchSite(
            symbol="cursor.restore_history_query",
            va=0x0056C81C,
            original=bytes.fromhex("e8 4f fe fe ff"),
        ),
        "gps.show": PatchSite(
            symbol="gps.show", va=0x0046FEB0, original=bytes.fromhex("53 56 57 8b f9")
        ),
        "gps.destroy": PatchSite(
            symbol="gps.destroy", va=0x0046EF91, original=bytes.fromhex("b8 9a d1 5f 00")
        ),
        **{
            name: PatchSite(symbol=name, va=slot, original=target.to_bytes(4, "little"))
            for name, slot, target in (
                ("gps.bitmap_draw", 0x006685E8, 0x0046709A),
                ("gps.button_draw", 0x006689D0, 0x0046709A),
                ("gps.text_draw", 0x00674FAC, 0x004674C1),
                ("gps.auxiliary_draw", 0x00675C84, 0x00432A83),
                ("gps.button_down", 0x00668974, 0x004474C2),
                ("gps.button_bounds", 0x006689C4, 0x0041F1C0),
                ("gps.button_pixels", 0x006689FC, 0x00447403),
                ("gps.auxiliary_bounds", 0x00675C78, 0x0041F1C0),
            )
        },
        "cursor.frame_begin_call": PatchSite(
            symbol="cursor.frame_begin_call",
            # The room loop updates CursorManager before selecting the current
            # retained history. Resource changes must invalidate the outgoing
            # footprint at this pre-traversal boundary.
            va=0x0049C664,
            original=bytes.fromhex("e8 ad 8f fd ff"),
        ),
        "cursor.platform_initialize_call": PatchSite(
            symbol="cursor.platform_initialize_call",
            # CursorManager initializes the native save-under/composition
            # surfaces once after reading its logical maximum.
            va=0x0047500E,
            original=bytes.fromhex("e8 4d 6b 0f 00"),
        ),
        "cursor.platform_restore_call": PatchSite(
            symbol="cursor.platform_restore_call",
            # Save restoration deserializes the same logical maximum, then
            # recreates both native surfaces through the identical allocator.
            va=0x004753EB,
            original=bytes.fromhex("e8 70 67 0f 00"),
        ),
        "cursor.bounds_hook": PatchSite(
            symbol="cursor.bounds_hook", va=0x00475856, original=bytes.fromhex("83 7b 18 00 5f")
        ),
        "cursor.draw_call_scope": PatchSite(
            symbol="cursor.draw_call_scope",
            va=0x004758C3,
            original=bytes.fromhex("89 45 e8 8b 01 ff 50 18"),
        ),
        "cursor.manager_draw_slot": PatchSite(
            symbol="cursor.manager_draw_slot",
            # CursorManager's renderable +8 subobject publishes Draw at vtable
            # slot two. Owning the slot lets the staged-room patch reject an
            # entire retained transaction when its concrete point differs from
            # CursorManager's authoritative current point.
            va=0x00676B5C,
            original=bytes.fromhex("77 58 47 00"),
        ),
        "death.retry_layout": PatchSite(
            symbol="death.retry_layout",
            va=0x004D5E54,
            original=bytes.fromhex("e8 70 d2 ff ff"),
            context_before=bytes.fromhex("56"),
        ),
        "zodiac.constructor_width": PatchSite(
            symbol="zodiac.constructor_width",
            va=0x004CE656,
            original=bytes.fromhex("a1 cc b0 70 00 c6 45 fc 07 8b 00"),
        ),
        "zodiac.constructor_height": PatchSite(
            symbol="zodiac.constructor_height",
            va=0x004CE678,
            original=bytes.fromhex("a1 c8 b0 70 00 8b 00"),
        ),
        "zodiac.layout_width": PatchSite(
            symbol="zodiac.layout_width",
            va=0x004CE97E,
            original=bytes.fromhex("a1 cc b0 70 00 8b 00"),
        ),
        "zodiac.layout_height": PatchSite(
            symbol="zodiac.layout_height",
            va=0x004CE99C,
            original=bytes.fromhex("a1 c8 b0 70 00 8b 00"),
        ),
        "zodiac.exit_height": PatchSite(
            symbol="zodiac.exit_height",
            va=0x004CE9CD,
            original=bytes.fromhex("8b 0d 28 e8 6f 00 8b 49 04"),
        ),
        "death.restore_layout": PatchSite(
            symbol="death.restore_layout",
            va=0x004D5E5A,
            original=bytes.fromhex("e8 6a d2 ff ff"),
            context_before=bytes.fromhex("57"),
        ),
        "death.quit_layout": PatchSite(
            symbol="death.quit_layout",
            va=0x004D5E60,
            original=bytes.fromhex("e8 64 d2 ff ff"),
            context_before=bytes.fromhex("53"),
        ),
        "ui.backdrop_draw_entry": PatchSite(
            symbol="ui.backdrop_draw_entry",
            # Draw cached physical framebuffer slices without a dialog affine.
            va=0x004C40E5,
            original=bytes.fromhex("53 8b 5c 24 08"),
        ),
        "restore_progress.background_attach_call": PatchSite(
            symbol="restore_progress.background_attach_call",
            # RestoreProgressController has resolved the selected PROGRESS_*
            # resource and passes it to its private UI owner here. The callee
            # derives the model rectangle from raster dimensions, making this
            # the exact boundary at which storage and presentation diverge.
            va=0x004CC94E,
            original=bytes.fromhex("e8 53 b1 03 00"),
        ),
        "restore_progress.initial_show_call": PatchSite(
            symbol="restore_progress.initial_show_call",
            # The constructor's one concrete UI Show owns the first progress
            # presentation, before any controller Update can run.
            va=0x004CC963,
            original=bytes.fromhex("8b 01 ff 50 04"),
        ),
        "restore_progress.canvas_update_call": PatchSite(
            symbol="restore_progress.canvas_update_call",
            # The concrete controller's only UI Update call owns every later
            # progress presentation while restore blocks the render loop.
            va=0x004CCBFC,
            original=bytes.fromhex("e8 22 59 01 00"),
        ),
        "cursor.drawable_blt_call": PatchSite(
            symbol="cursor.drawable_blt_call",
            va=0x00424E3F,
            original=bytes.fromhex("e8 de 48 07 00"),
        ),
        "cursor.resolved_blt_call": PatchSite(
            symbol="cursor.resolved_blt_call",
            # FUN_0054D330 has now resolved both bitmap resources to the low-
            # level surface wrappers consumed by the native final blitters.
            va=0x0054D354,
            original=bytes.fromhex("e8 17 23 00 00"),
        ),
        # ToolTip::Draw first asks its base UI object to repaint the authored
        # 84x20 backing, then emits four fixed one-pixel border primitives.
        # The modern compositor owns that entire output-scale panel; retaining
        # either native decoration would overwrite only the authored portion
        # after the scaled fill. Native text and hover policy remain intact.
        "tooltip.base_draw_call": PatchSite(
            symbol="tooltip.base_draw_call",
            va=0x005254B2,
            original=bytes.fromhex("e8 e5 cc f0 ff"),
        ),
        "tooltip.border_top_call": PatchSite(
            symbol="tooltip.border_top_call",
            va=0x00525593,
            original=bytes.fromhex("e8 d8 f2 00 00"),
        ),
        "tooltip.border_left_call": PatchSite(
            symbol="tooltip.border_left_call",
            va=0x005255B1,
            original=bytes.fromhex("e8 ba f2 00 00"),
        ),
        "tooltip.border_right_call": PatchSite(
            symbol="tooltip.border_right_call",
            va=0x005255CF,
            original=bytes.fromhex("e8 9c f2 00 00"),
        ),
        "tooltip.border_bottom_call": PatchSite(
            symbol="tooltip.border_bottom_call",
            va=0x005255F0,
            original=bytes.fromhex("e8 7b f2 00 00"),
        ),
        # MouseManager resolves one hovered descriptor after idle, event, and
        # activation traversals. The live ActionMenu is a room child and is
        # absent from the two registered top-level roots queried by the stock
        # resolver, so Runtime2D gives these three equivalent call boundaries
        # one exact-class-first policy with native fallback.
        "tooltip.action_resolve_idle_call": PatchSite(
            symbol="tooltip.action_resolve_idle_call",
            va=0x004BEBCF,
            original=bytes.fromhex("e8 cc 07 00 00"),
        ),
        "tooltip.action_resolve_event_call": PatchSite(
            symbol="tooltip.action_resolve_event_call",
            va=0x004BEC03,
            original=bytes.fromhex("e8 98 07 00 00"),
        ),
        "tooltip.action_resolve_activation_call": PatchSite(
            symbol="tooltip.action_resolve_activation_call",
            va=0x004BF254,
            original=bytes.fromhex("e8 47 01 00 00"),
        ),
        # Fixed system layers run their native render pair, then the UI update
        # at 0x004AB1C0 can publish a delayed tooltip edge. This epilogue is the
        # first non-reentrant boundary after both producers have returned.
        "tooltip.fixed_layer_epilogue": PatchSite(
            symbol="tooltip.fixed_layer_epilogue",
            va=0x004CB039,
            original=bytes.fromhex("5f 5e 5b c2 04 00"),
        ),
        "sidney.stale_lookup": PatchSite(
            symbol="sidney.stale_lookup",
            va=0x00496240,
            original=bytes.fromhex("8b 06 8b 0d 54 55 66 00"),
        ),
        "shutdown.stale_release": PatchSite(
            symbol="shutdown.stale_release",
            va=0x0053448C,
            original=bytes.fromhex("8b 10 8b c8 ff 52 10"),
        ),
        "shutdown.stale_update": PatchSite(
            symbol="shutdown.stale_update",
            va=0x0053446C,
            original=bytes.fromhex("8b 10 8b c8 ff 52 0c"),
        ),
        "cursor.clipped_blt_call": PatchSite(
            symbol="cursor.clipped_blt_call",
            va=0x0049984D,
            original=bytes.fromhex("e8 8e ab 09 00"),
        ),
        "font.clipped_blt_call": PatchSite(
            symbol="font.clipped_blt_call", va=0x00495040, original=bytes.fromhex("e8 9b f3 09 00")
        ),
        "font.initialize_metrics": PatchSite(
            symbol="font.initialize_metrics",
            va=0x00495C35,
            original=bytes.fromhex("8b 46 38 ff 4e 34 99 f7 7e 4c 5b 48 33 d2 89 46 38"),
        ),
        "room_text.fill_call": PatchSite(
            symbol="room_text.fill_call",
            va=0x00467A36,
            original=bytes.fromhex("e8 35 ce 0c 00"),
        ),
    }
)

_SHARED_SYMBOLS = MappingProxyType(
    {
        "movies.complete": 0x00591880,
        "movies.update": 0x00591FE0,
        # Same variadic formatting ABI as the modal reporter used by
        # persistence, but dispatches directly through GK3's generic output
        # vtable slot. The modal reporters call this sink themselves before
        # opening a Win32 dialog; using it directly retains only the log step.
        "savegame.warning_log": 0x0053D880,
        # UserSceneController's common camera-motion consumer is shared by
        # physical mouse deltas and synthesized keyboard deltas. The keyboard
        # call-site bridge marks only the latter while this native function
        # retains every configured camera mode and collision rule.
        "camera.apply_motion": 0x00449A65,
        "camera.motion_float_conversion_continue": 0x00449AEF,
        # GK3 already imports WINMM's millisecond monotonic timer. Reusing its
        # IAT slot keeps camera normalization dependency-free and consistent
        # with the timer source used elsewhere in the executable.
        "win32.timeGetTime": 0x006653B4,
        "transition.primary_surface_ptr": 0x0070D244,
        "transition.back_surface_ptr": 0x0070D248,
        "high_resolution_3d.directdraw_ptr": 0x0070D238,
        "refresh.set_display_mode_continue": 0x00574E59,
        "high_resolution_3d.render_wrapper_ptr": 0x0070D264,
        # Native clean-background surfaces populated by FUN_0056D310 and
        # consumed by the retained-damage restore helpers.  The staged renderer
        # temporarily substitutes private, stage-sized equivalents at these
        # ownership points; modal 2D captures must continue to see the native
        # physical histories after EndScene.
        "high_resolution_3d.damage_source_surface_ptr": 0x0070D254,
        "high_resolution_3d.damage_aux_surface_ptr": 0x0070D258,
        "high_resolution_3d.current_renderer": 0x0054D690,
        "high_resolution_3d.projection_setup": 0x005588D0,
        "high_resolution_3d.directx_error": 0x00578F70,
        "high_resolution_3d.viewport_warning_report": 0x0053D5F0,
        "high_resolution_3d.display_width_ptr": 0x0070B0CC,
        "high_resolution_3d.display_height_ptr": 0x0070B0C8,
        # FUN_005588D0 publishes the active software-projection dimensions
        # here. Room construction resets them to zero before the first valid
        # 3D frame, providing a semantic input-readiness boundary.
        "input.projection_dimensions": 0x00710948,
        "transition.engine_loop_ptr": 0x006FF838,
        # EngineLoop's ordinary system-layer render transaction. It owns
        # MouseManager Draw, the linked pre-Flip presenters, and GK3's native
        # DirectDraw Flip ordering.
        "engine.render_frame": 0x0049C641,
        "transition.invalidate_all_damage": 0x00499332,
        # FUN_0049C641's ordinary 3D scene loop owns this concrete layer.
        # Modal interfaces publish different vtables through ui.current_layer,
        # giving transition repair an engine-owned scope boundary.
        "transition.room_layer_vtable": 0x0067A248,
        # RoomLayer's first direct child is the retained top status TextBox.
        # Its completed Draw transaction is the narrow producer boundary at
        # which the result can be synchronized to the other DirectDraw peer.
        "room_text.vtable": 0x00675810,
        "room_text.draw": 0x00467989,
        # CaptionMgr retains up to three instances of this concrete Caption
        # class.  Its unique Draw and destructor slots let the fixed-interface
        # runtime hand those overlays to the final staged-room page owner
        # without classifying arbitrary font coordinates or shared drawables.
        "caption.vtable": 0x00669A14,
        "caption.draw": 0x00450C3C,
        "caption.destructor": 0x004507F2,
        # Publisher/splash layer active before GK3 publishes the first usable
        # input graph. Physical mode-switch movement must not enter it.
        "transition.startup_splash_layer_vtable": 0x0067E550,
        "transition.seed_continue": 0x0052A5E2,
        "transition.blt_continue": 0x0054FA41,
        "mouse_move.target_dispatch_continue": 0x004BEC11,
        # Common UI traversal called after MouseManager has committed its
        # durable physical cursor state. Fixed-interface input adapters enter
        # here so their temporary logical POINT covers hit selection as well
        # as the selected target's movement callback.
        "mouse_move.ui_dispatch": 0x004BEBF0,
        "mouse_move.motion_dispatch": 0x004BF0E8,
        # MouseManager normally resolves the active cursor before its trailing
        # +0x78 traversal refreshes dynamic per-object descriptors. Fixed-
        # interface adapters must repeat only this native selector while their
        # temporary logical POINT is still in scope; once the durable cursor
        # returns to physical space, authored object RECTs cannot be queried.
        "mouse_move.cursor_select": 0x004BF2F4,
        "mouse_move.wndproc_dispatch_continue": 0x00533CEC,
        "mouse_move.mouse_manager": 0x0070B0D4,
        "mouse_move.engine_loop": 0x006FF838,
        "win32.IsBadReadPtr": 0x00665164,
        "win32.IsBadCodePtr": 0x006651E8,
        # Imported USER32 entry points used to compare a queued WM_MOUSEMOVE
        # with the cursor's current client position.  Calling through GK3's
        # own IAT keeps the injected runtime independent of DLL load addresses.
        "win32.ScreenToClient": 0x00665360,
        "win32.GetCursorPos": 0x00665384,
        "mouse_move.interactive_handler": 0x00525399,
        "mouse_move.interactive_point_cache_continue": 0x005253DF,
        "display.dimensions": 0x006F7B50,
        "engine.loop": 0x006FF838,
        # Current software-cursor POINT consumed by the input dispatcher.
        # World hit-testing compares this engine cache with the event POINT;
        # it is distinct from the selected display dimensions above.
        "input.cursor_position": 0x00706F10,
        "input.set_cursor_position": 0x0056C920,
        "ingame_toolbar.sound_cursor_return_call": 0x004E4A7B,
        "ingame_toolbar.lod_cursor_return_call": 0x004E5E00,
        "ingame_toolbar.gamma_cursor_return_call": 0x004E7787,
        "ingame_toolbar.volume_cursor_return_call": 0x004E9A9A,
        "bitmap.resolve_resource": 0x00534560,
        "bitmap.fill_rectangle": 0x00499656,
        "bitmap.solid_fill": 0x005500E0,
        "bitmap.effect_constructor": 0x00577730,
        "bitmap.effect_executor": 0x00577200,
        "bitmap.effect_callback": 0x005778D0,
        "bitmap.effect_destructor": 0x00577870,
        "bitmap.effect_lockable": 0x0054F570,
        "directdraw.primary_surface": 0x0070D244,
        # Pointer to GK3's live screen RECT, passed to the native drawable
        # centering helper. TimeBlock presentation uses the same engine-owned
        # operation synchronously instead of retaining replacement dimensions
        # as authored UI geometry.
        "ui.screen_rect_ptr": 0x006FE824,
        "display.dimension_pointers": 0x006FE828,
        "inventory.vtable": 0x0067BE24,
        "inventory.destructor": 0x004C0DF0,
        "ui.container_draw": 0x004DCA32,
        "inventory.layout": 0x004C1817,
        "inventory.base_layout": 0x004C3E53,
        "inventory.reference_layout": 0x004C13B3,
        "inventory.grid_layout": 0x004C1BA3,
        "inventory_item.vtable": 0x00683A70,
        "inventory_item.draw": 0x004773FB,
        "runtime2d.final_blt": 0x0054F980,
        "runtime2d.high_blt_final_return": 0x0054F949,
        "runtime2d.high_blt_fallback_return": 0x0054F918,
        "help.vtable": 0x006853B0,
        "zodiac.vtable": 0x0067D3E8,
        "zodiac.draw": 0x004DCA32,
        "zodiac.destructor": 0x004CE72C,
        "message_box.vtable": 0x0067DD44,
        "message_box.draw": 0x004D3D16,
        "message_box.destructor": 0x004D39C1,
        "help.draw": 0x004EF0D0,
        "help.destructor": 0x004EE263,
        "keyboard_config.vtable": 0x006855EC,
        "keyboard_config.draw": 0x004F0247,
        "keyboard_config.destructor": 0x004EF923,
        "ui.set_visible": 0x00466A60,
        "ui.center_drawable": 0x004668DA,
        "resource.manager": 0x0070B0D4,
        "driving_map.draw": 0x004BEE7C,
        "driving_map.vtable": 0x00677534,
        "bitmap_node.destructor_slot": 0x00668548,
        "bitmap_node.destructor": 0x00443CF4,
        "win32.Ellipse": 0x00665038,
        "timeblock.vtable": 0x0067DF90,
        "timeblock.draw": 0x004D4F22,
        "sequence.series_vtable": 0x00666AC4,
        "ui.current_layer": 0x00474B2D,
        # Generic image/text button class used by Title and fixed-interface
        # object trees. Its live RECT is the authoritative authored hit area.
        "ui.button_vtable": 0x00668930,
        "sidney.root_destructor_slot": 0x00690540,
        "sidney.root_destructor": 0x00648A3D,
        "sidney.root_draw_slot": 0x006905E0,
        "runtime2d.final_blt_continue": 0x0054F985,
        "cursor.save_under_return_1": 0x00577315,
        "cursor.save_under_return_2": 0x005773E3,
        "sidney.stale_lookup_continue": 0x0049624E,
        "sidney.stale_lookup_skip": 0x00496268,
        "shutdown.stale_release_continue": 0x00534493,
        "shutdown.stale_update_continue": 0x00534473,
        "input.left_down_slot": 0x0067A054,
        "input.left_down": 0x0049A92D,
        "input.left_up_slot": 0x0067A058,
        "input.left_up": 0x0049AC83,
        "input.right_down_slot": 0x0067A05C,
        "input.right_down": 0x0049A97C,
        "input.right_up_slot": 0x0067A060,
        "input.right_up": 0x0049AD0F,
        "input.pointer_move_slot": 0x0067A064,
        "input.pointer_move": 0x0049AA00,
        "input.middle_down_slot": 0x0067A074,
        "input.middle_down": 0x0049A9BE,
        "input.middle_up_slot": 0x0067A078,
        "input.middle_up": 0x0049AD8E,
        "death.vtable": 0x0067E114,
        "ui.destructor": 0x004D59A2,
        "ui.show": 0x004C3E5E,
        "ui.hide": 0x004C3E9C,
        "finished.vtable": 0x0067E24C,
        "finished.destructor": 0x004D5FB2,
        "binocular.vtable": 0x00668428,
        "binocular.destructor": 0x00440C6B,
        "binocular.draw": 0x004410B9,
        # LoadGame and the in-room right-click toolbar are unrelated classes.
        # Older patch code conflated them because both inherit the generic
        # container Draw slot. Keep their identities explicit: the former owns
        # the Restore browser/layout; the latter owns the compact HUD overlay.
        "loadgame.vtable": 0x0067CD40,
        "loadgame.destructor": 0x004CA540,
        "loadsave_text.vtable": 0x00685130,
        "loadsave_text.draw": 0x004ED8E8,
        # ScrollBar's outer container is laid out in final framebuffer space
        # by Runtime2D, while its private arrow/thumb/track model intentionally
        # remains in GK3's native coordinates. Its event slots are adapted only
        # after generic traversal has selected this concrete outer component.
        "scrollbar.vtable": 0x0068969C,
        "scrollbar.event_44": 0x004446E4,
        "scrollbar.event_48": 0x004446F9,
        "scrollbar.event_4c": 0x0044470E,
        "scrollbar.event_50": 0x00444723,
        "scrollbar.event_54": 0x00444738,
        "scrollbar.event_58": 0x0044474D,
        "scrollbar.event_5c": 0x00444762,
        "scrollbar.event_7c": 0x00444992,
        "scrollbar.event_80": 0x004449AF,
        "scrollbar.hit_test": 0x004DC942,
        "scrollbar_arrow.vtable": 0x00668FD8,
        "scrollbar_arrow.left_down": 0x00447D14,
        "scrollbar_arrow.left_release": 0x00447D43,
        "scrollbar_thumb.vtable": 0x0068959C,
        "scrollbar_thumb.drag_begin": 0x005084D1,
        "scrollbar_thumb.drag_move": 0x00508506,
        "ui.rect_hit_test": 0x0041F1C0,
        "ingame_toolbar.vtable": 0x00684FA4,
        "ingame_toolbar.destructor": 0x004EB8B5,
        "ingame_toolbar.layout_commit_call": 0x004ECCC5,
        "ingame_toolbar.layout_commit": 0x004ECCD1,
        # ToolTip is a global room overlay, not a child of InGameToolbar.
        # Its concrete Draw owns the complete text/background/border producer
        # transaction; Runtime2D uses that boundary to keep its already-
        # physical transfers out of the toolbar's authored-space affine.
        "tooltip.vtable": 0x006924C4,
        # The concrete visibility virtual owns the delayed animation callback
        # which finally publishes a hidden tooltip. Runtime2D observes that
        # exact edge without modifying native hover timing.
        "tooltip.set_visible": 0x0052542F,
        "tooltip.draw": 0x00525470,
        "tooltip.resolve_hover": 0x004BF3A0,
        "tooltip.set_descriptor": 0x0052514E,
        "tooltip.clear": 0x004BF43A,
        # The resolution combo expands into a generic list popup attached as
        # a sibling of the toolbar rather than a child of its object tree.
        # Its concrete Draw first paints the list background, then delegates
        # its rows to the ordinary container traversal.
        "resolution_dropdown.vtable": 0x006841E4,
        "resolution_dropdown.draw": 0x004E3C8F,
        # ResolutionList inherits DrawableObject::SetVisible(bool) through
        # vtable +0xB0. Owning this exact class slot lets Runtime2D publish
        # and fit the popup before its first visible frame, rather than
        # depending on a later Draw callback to discover its lifetime.
        "resolution_dropdown.set_visible": 0x00466A60,
        # The dropdown owns one embedded SolidColorObject at +0x134 for its
        # current-row hover highlight. Unlike the bitmap background and text
        # rows, this child submits through the engine's color-primitive path.
        "solid_color.vtable": 0x00669C84,
        "solid_color.draw": 0x00466DF3,
        "action_menu.vtable": 0x00692E9C,
        "action_menu.destructor": 0x00527B6E,
        "loadsave.vtable": 0x0067CBA0,
        "loadsave.destructor": 0x004C8B4F,
        "savegame.vtable": 0x0067CE58,
        "savegame_edit.vtable": 0x0067CF80,
        "savegame_edit.draw": 0x00487452,
        "loadsave.layout": 0x004C93FD,
        "bitmap.manager": 0x0070B0D4,
        "sprite_cache.allocate": 0x00531830,
        "sprite_cache.resolve": 0x00534560,
        "sprite_cache.dimensions": 0x005344D0,
        "sprite_cache.assign": 0x0041229D,
        "sprite_cache.styled_paint": 0x00629102,
        "bitmap.dimensions": 0x005344D0,
        "bitmap.get_pixel": 0x00534770,
        "savegame.destructor": 0x004CA88D,
        "runtime2d.clipped_blt": 0x005343E0,
        "runtime2d.fill_rect": 0x00534870,
        "runtime2d.final_fast_blt": 0x0054F670,
        "runtime2d.final_stretch_blt": 0x0054F980,
        "cursor.drawable_blt": 0x00499722,
        "cursor.platform_initialize": 0x0056BB60,
        "win32.GetModuleHandleA": 0x0066508C,
        "win32.GetProcAddress": 0x00665108,
        "win32.LoadCursorA": 0x00665320,
        "cursor.platform_instance": 0x00710B98,
        "cursor.platform_get_count": 0x0056BE20,
        "cursor.platform_set_count": 0x0056BD90,
        "win32.EnterCriticalSection": 0x00665124,
        "win32.LeaveCriticalSection": 0x00665200,
        "cursor.manager_vtable": 0x00676B54,
        "cursor.manager_draw": 0x00475877,
        "cursor.frame_begin": 0x00475616,
        # Converts Win32's current screen-space pointer to GK3's physical
        # client coordinates. Fixed retained canvases consume this producer
        # instead of reconstructing a point from authored UI input state.
        "cursor.get_client_point": 0x0056C8E0,
        "cursor.bitmap_drawable_vtable": 0x00666A28,
        "restore_progress.background_attach": 0x00507AA6,
        "restore_progress.initial_show": 0x00507B8F,
        "restore_progress.canvas_update": 0x004E2523,
        "cursor.bounds_continue": 0x0047585B,
        "cursor.draw_call_continue": 0x004758CB,
        "title.vtable": 0x0069238C,
        "title.destructor": 0x00523EA7,
        "title.draw": 0x005240D9,
        # ConfirmQuitLayer is a centered modal with one physical-space root and
        # 1024-era child geometry. Its generic recursive Draw needs a distinct
        # runtime scope from both the full-screen TitleLayer and room UI.
        "confirm_quit.vtable": 0x0067DC14,
        "pause.vtable": 0x0067DB04,
        "confirm_quit.destructor": 0x004D35CB,
        "resource.cache_blt_continue": 0x0054D588,
        "title.cache_resize_return": 0x005246C1,
        "closeup.vtable": 0x00674798,
        "console.vtable": 0x00674DBC,
        "console.alpha_capture_return": 0x005773E3,
        "closeup.destructor": 0x0045A7E6,
        "fingerprint.vtable": 0x00678264,
        "fingerprint.destructor": 0x0048E173,
        "fingerprint.dust": 0x0048F0FE,
    }
)

GOG_BUILD = BuildProfile(
    id=BuildId("gog"),
    label="GOG",
    original_sha256="ca544d6d6fe940da1b7787faefbf675990779dc5de4bbeca75f684d177996875",
    sites=_SHARED_SITES,
    symbols=_SHARED_SYMBOLS,
)

STEAM_NORMALIZED_BUILD = BuildProfile(
    id=BuildId("steam_normalized"),
    label="Steam (SteamStub normalized)",
    original_sha256="2085f4574bf092484984e7e7459b996875b84474320967f6509644fcbd391949",
    sites=_SHARED_SITES,
    symbols=_SHARED_SYMBOLS,
)

STEAM_BUILD = BuildProfile(
    id=BuildId("steam"),
    label="Steam (automatically normalized)",
    original_sha256=PROTECTED_STEAM_SHA256,
    sites=_SHARED_SITES,
    symbols=_SHARED_SYMBOLS,
)

_BUILD_ITEMS = (GOG_BUILD, STEAM_NORMALIZED_BUILD, STEAM_BUILD)


def _index_build_profiles(
    profiles: tuple[BuildProfile, ...],
) -> tuple[Mapping[BuildId, BuildProfile], Mapping[str, BuildProfile]]:
    """Index profiles without silently overwriting duplicate IDs or hashes."""
    by_id: dict[BuildId, BuildProfile] = {}
    by_hash: dict[str, BuildProfile] = {}
    for profile in profiles:
        if profile.id in by_id:
            detail = f"duplicate build profile ID {profile.id!r}"
            raise ProfileError(detail)
        if profile.original_sha256 in by_hash:
            detail = f"duplicate build profile SHA-256 {profile.original_sha256}"
            raise ProfileError(detail)
        by_id[profile.id] = profile
        by_hash[profile.original_sha256] = profile
    return MappingProxyType(by_id), MappingProxyType(by_hash)


SUPPORTED_BUILDS, _BUILDS_BY_HASH = _index_build_profiles(_BUILD_ITEMS)

SUPPORTED_ORIGINAL_SHA256 = frozenset(
    profile.original_sha256 for profile in SUPPORTED_BUILDS.values()
)


def profile_for_sha256(sha256: str) -> BuildProfile:
    """Resolve an exact supported original executable hash."""
    try:
        return _BUILDS_BY_HASH[sha256.lower()]
    except KeyError as exc:
        detail = f"unsupported GK3 executable SHA-256: {sha256}"
        raise ProfileError(detail) from exc
