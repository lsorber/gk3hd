"""Declarative operations for independent engine behavior fixes."""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import TYPE_CHECKING

from gk3hd.patch.binary.operations import AssertBytes, ReplaceBytes
from gk3hd.patch.binary.x86 import BranchOpcode, encode_rel32_branch
from gk3hd.patch.builds import SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.model import (
    BuildContext,
    CompilationContext,
    PatchDefinition,
    PatchId,
    PatchOperation,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

type EngineOperationFactory = Callable[[CompilationContext], tuple[PatchOperation, ...]]


def _profile(context: CompilationContext) -> BuildProfile:
    """Resolve the exact build selected by the planner."""
    try:
        return SUPPORTED_BUILDS[context.build.build_id]
    except KeyError as exc:
        detail = f"no engine patch profile for build {context.build.build_id!r}"
        raise EngineDefinitionError(detail) from exc


class EngineDefinitionError(Exception):
    """Report an incomplete or inconsistent engine patch definition."""


def _assert(profile: BuildProfile, owner: PatchId, symbol: str) -> AssertBytes:
    site = profile.site(symbol)
    return AssertBytes(owner=owner, symbol=symbol, va=site.va, expected=site.original)


def _replace(
    profile: BuildProfile,
    owner: PatchId,
    symbol: str,
    replacement: bytes,
) -> ReplaceBytes:
    site = profile.site(symbol)
    return ReplaceBytes(
        owner=owner,
        symbol=symbol,
        va=site.va,
        expected=site.original,
        replacement=replacement,
    )


def _remove_disc_requirement(context: CompilationContext) -> tuple[PatchOperation, ...]:
    """Bypass the obsolete optical-drive startup requirement.

    Outcome:
        A complete installed copy starts on PCs without an optical disc drive.
    Before:
        GK3 turns a failed drive/disc probe into a startup failure flag.
    After:
        The probe's established setup runs, but its failure flag is not stored.
    Strategy:
        Replace only the validated two-byte flag assignment and assert its
        surrounding control-flow context for every supported executable.
    Boundaries:
        File loading, installation discovery, and all later startup checks are
        unchanged.
    """
    owner = PatchId("remove_disc_requirement")
    profile = _profile(context)
    site = profile.site("cd_check.failure_flag")
    before_va = site.va - len(site.context_before)
    after_va = site.va + len(site.original)
    return (
        AssertBytes(owner, "cd_check.before_failure_flag", before_va, site.context_before),
        _replace(profile, owner, site.symbol, bytes.fromhex("90 90")),
        AssertBytes(owner, "cd_check.after_failure_flag", after_va, site.context_after),
    )


def _prevent_save_warning_dialogs(
    context: CompilationContext,
) -> tuple[PatchOperation, ...]:
    """Keep save-game warnings nonmodal during fullscreen restoration.

    Outcome:
        A recoverable save warning cannot strand the game behind a hidden or
        disruptive Windows message box.
    Before:
        The warning path reports through GK3's modal UI and can interrupt native
        fullscreen presentation while a save is still being restored.
    After:
        The same warning text is written through GK3's existing log path and
        restoration continues under its native error policy.
    Strategy:
        Redirect the one validated reporting call to the existing warning-log
        function while preserving its call ABI and surrounding instructions.
    Boundaries:
        Warning detection, save parsing, fatal errors, and log formatting remain
        native.
    """
    owner = PatchId("prevent_save_warning_dialogs")
    profile = _profile(context)
    site = profile.site("savegame.warning_report")
    before_va = site.va - len(site.context_before)
    after_va = site.va + len(site.original)
    replacement = encode_rel32_branch(
        opcode=BranchOpcode.CALL,
        site_va=site.va,
        target_va=profile.address("savegame.warning_log"),
        size=len(site.original),
    )
    return (
        AssertBytes(
            owner, "savegame.warning_report_context_before", before_va, site.context_before
        ),
        _replace(profile, owner, site.symbol, replacement),
        AssertBytes(owner, "savegame.warning_report_context_after", after_va, site.context_after),
    )


def _skip_all_movies(context: CompilationContext) -> tuple[PatchOperation, ...]:
    """Complete Bink playback immediately through GK3's native teardown.

    Outcome:
        Startup and transition movies do not delay automated or player-driven
        entry into the next game state.
    Before:
        GK3 waits for each initialized Bink stream to reach its final frame.
    After:
        The first update requests normal movie completion and reports no further
        playback work.
    Strategy:
        Replace the validated update body with a call to GK3's existing
        completion routine, preserving stream initialization and destruction.
    Boundaries:
        Movie discovery, Bink opening, audio resources, and post-movie game
        transitions remain native.
    """
    owner = PatchId("skip_all_movies")
    profile = _profile(context)
    return (
        _assert(profile, owner, "movies.bink_open_call"),
        _assert(profile, owner, "movies.complete_anchor"),
        _replace(
            profile,
            owner,
            "movies.update",
            bytes.fromhex("6a 01 e8 99 f8 ff ff 32 c0 c3"),
        ),
    )


def _maximize_graphics_quality(context: CompilationContext) -> tuple[PatchOperation, ...]:
    """Select GK3's maximum-detail rendering policy on the live device.

    Outcome:
        Models, replacement textures, mip filtering, and anisotropy use the
        highest quality supported by the selected hardware, while gamma 1.0
        remains a true identity transfer on every presentation backend.
    Before:
        The executable defaults model LOD below maximum, caps high-quality
        texture uploads for period hardware, accepts only a persisted fixed
        anisotropy value.
    After:
        Model LOD defaults to 100 percent, high-quality upload caps are removed,
        ``DWORD(-1)`` selects the detected anisotropy ceiling, the legacy CRT
        base curves become identity inputs to GK3's existing user-gamma power
        function, and the PE opts into the 4 GiB user address space available
        to 32-bit processes on 64-bit Windows.
    Strategy:
        Patch the quality policy values and the standard Large Address Aware
        COFF bit. Preserve the native gamma calculation but feed it the loop
        index instead of three embedded CRT curves; this makes 1.0 exactly
        identity while retaining the user adjustment for every other value.
        Address space and uncapped uploads remain one coherent policy:
        enabling either without the other is not useful.
    Boundaries:
        Resource discovery, texture contents, GPU capability detection, the
        gamma exponent and DirectDraw ramp submission, and the low-quality
        policy remain native.
    """
    owner = PatchId("maximize_graphics_quality")
    profile = _profile(context)
    quality_anchors = (
        "quality.mipmapping_default",
        "quality.interpolation_default",
        "quality.trilinear_device_default",
        "quality.lightmap_default",
        "quality.diffuse_default",
        "quality.surface_memory_check",
        # Preserve GK3's native 1.0 default and constructor-wide shared scalar.
        "quality.gamma_default",
        "quality.gamma_shared_scalar_restore",
    )
    return (
        # Model LOD, anisotropy, and upload ceilings are three parts of one
        # player-facing policy: retain as much source detail as the device can
        # present. Keeping them under one owner prevents incoherent partial
        # "quality" configurations without coupling unrelated runtime hooks.
        *(_assert(profile, owner, symbol) for symbol in quality_anchors),
        # Removing GK3's period 256-pixel upload cap can exhaust its original
        # 2 GiB user address space while loading dense replacement textures.
        # Bit 0x20 is IMAGE_FILE_LARGE_ADDRESS_AWARE; preserve every other
        # validated COFF characteristic.
        _replace(profile, owner, "image.coff_characteristics", bytes.fromhex("2f 01")),
        _replace(profile, owner, "quality.model_lod_default", bytes.fromhex("6a 64")),
        _assert(profile, owner, "anisotropy.signed_override"),
        _assert(profile, owner, "anisotropy.capability_detection"),
        _assert(profile, owner, "anisotropy.renderer_path"),
        _replace(
            profile,
            owner,
            "quality.anisotropy_default",
            bytes.fromhex("6a ff 68 1a 5a 00 00"),
        ),
        # ESI is a byte offset (0, 2, ..., 510). Multiplying it by 128 yields
        # the canonical 16-bit identity-ramp sample (0, 256, ..., 65280).
        # Keep the original pow(input, 1/gamma) calculation and only replace
        # each channel's embedded CRT-table load with that exact input.
        _replace(
            profile,
            owner,
            "quality.gamma_identity_red",
            bytes.fromhex("8b ce c1 e1 07 90 90 90 90"),
        ),
        _replace(
            profile,
            owner,
            "quality.gamma_identity_green",
            bytes.fromhex("8b c6 c1 e0 07 90 90 90 90"),
        ),
        _replace(
            profile,
            owner,
            "quality.gamma_identity_blue",
            bytes.fromhex("8b d6 c1 e2 07 90 90 90 90"),
        ),
        _assert(profile, owner, "textures.low_quality_limits"),
        _assert(profile, owner, "textures.limit_lookup"),
        _replace(profile, owner, "textures.high_quality_limits", bytes(12)),
    )


def _enable_modern_resolutions(context: CompilationContext) -> tuple[PatchOperation, ...]:
    """Admit modern driver modes and their live framebuffer dimensions.

    Outcome:
        GK3 can select any valid mode enumerated by the current DirectDraw
        driver, including widescreen and high-density modes.
    Before:
        The options menu filters modes through period limits and framebuffer
        startup rejects dimensions outside the original range.
    After:
        Enumerated modes remain visible and the chosen live dimensions reach
        renderer initialization without a named-resolution whitelist.
    Strategy:
        Make the validated menu predicate accept enumerated modes and replace
        the framebuffer bound branch while retaining the conservative 640x480
        fallback for missing or malformed external settings.
    Boundaries:
        Mode enumeration, persisted selection, refresh choice, legacy Direct3D
        staging, and fixed-interface scaling have separate owners.
    """
    owner = PatchId("enable_modern_resolutions")
    profile = _profile(context)
    menu_site = profile.site("resolution.menu_filter")
    menu_replacement = bytes.fromhex("b0 01 c3") + menu_site.original[3:]
    return (
        # Installation writes an explicit, driver-enumerated resolution. If
        # those external settings are missing or malformed, preserve GK3's
        # conservative 640x480 fallback instead of assuming every display can
        # enter 1920x1080. This anchor still proves the expected startup path.
        _assert(profile, owner, "resolution.fallback"),
        _replace(profile, owner, menu_site.symbol, menu_replacement),
        _replace(
            profile,
            owner,
            "resolution.framebuffer_guard",
            bytes.fromhex("3b f8 eb 46"),
        ),
    )


def _definition(
    patch_id: str,
    name: str,
    description: str,
    factory: EngineOperationFactory,
) -> PatchDefinition:
    """Create one definition after proving build-independent ownership."""
    owner = PatchId(patch_id)
    ownership_by_build = tuple(
        frozenset(
            operation.claim
            for operation in factory(
                CompilationContext(
                    build=BuildContext(build_id=build_id),
                    selected_patches=frozenset({owner}),
                )
            )
            if operation.is_mutation
        )
        for build_id in SUPPORTED_BUILDS
    )
    ownership = ownership_by_build[0]
    if any(candidate != ownership for candidate in ownership_by_build[1:]):
        detail = f"engine patch {patch_id!r} changes resource ownership between builds"
        raise EngineDefinitionError(detail)
    return PatchDefinition(
        id=owner,
        name=name,
        description=description,
        build_operations=factory,
        supported_builds=frozenset(SUPPORTED_BUILDS),
        ownership=ownership,
    )


_DEFINITIONS = (
    _definition(
        "remove_disc_requirement",
        "Remove optical-drive requirement",
        "Start on PCs without a CD/DVD drive.",
        _remove_disc_requirement,
    ),
    _definition(
        "prevent_save_warning_dialogs",
        "Prevent save warning dialogs",
        "Log save/load warnings without modal dialogs.",
        _prevent_save_warning_dialogs,
    ),
    _definition(
        "skip_all_movies",
        "Skip all movies",
        "Skip all movies, including story videos.",
        _skip_all_movies,
    ),
    _definition(
        "enable_modern_resolutions",
        "Enable modern resolutions",
        "Allow widescreen and resolutions above 1024x768.",
        _enable_modern_resolutions,
    ),
    _definition(
        "maximize_graphics_quality",
        "Maximize graphics quality",
        "Max detail, anisotropy and faithful gamma.",
        _maximize_graphics_quality,
    ),
)


def _index_definitions(
    definitions: tuple[PatchDefinition, ...],
) -> Mapping[PatchId, PatchDefinition]:
    """Index definitions without silently overwriting a duplicate ID."""
    result: dict[PatchId, PatchDefinition] = {}
    for definition in definitions:
        if definition.id in result:
            detail = f"duplicate engine patch ID {definition.id!r}"
            raise EngineDefinitionError(detail)
        result[definition.id] = definition
    return MappingProxyType(result)


ENGINE_PATCHES = _index_definitions(_DEFINITIONS)
