"""Portable source, payload and ABI contracts for the surface-readiness optimization."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from gk3hd.patch.binary.executor import OperationExecutor
from gk3hd.patch.binary.image import PEFile
from gk3hd.patch.binary.x86 import BranchOpcode, decode_rel32_branch
from gk3hd.patch.builds import GOG_BUILD, SUPPORTED_BUILDS, BuildProfile
from gk3hd.patch.catalog import PATCHES, PLANNER, PROFILES
from gk3hd.patch.definitions.speed_up_surface_checks import SurfaceCheckCompiler
from gk3hd.patch.install import transaction
from gk3hd.patch.install.configuration import NoopConfiguration
from gk3hd.patch.model import BuildContext, PatchError, PatchId, ProfileId
from gk3hd.patch.planner import PatchPlanner

if TYPE_CHECKING:
    from pathlib import Path


def _source(profile: BuildProfile = GOG_BUILD) -> PEFile:
    # A minimal PE32 with one sparse code page; no game executable is required.
    data = bytearray(0x1200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x14C, 1, 0, 0, 0, 0xE0, 0x10F)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x10B)
    for offset, value in ((28, 0x400000), (32, 0x1000), (36, 0x200), (56, 0x150000), (60, 0x200)):
        struct.pack_into("<I", data, optional + offset, value)
    struct.pack_into(
        "<8sIIIIIIHHI",
        data,
        0x178,
        b".text",
        0x1000,
        0x14F000,
        0x1000,
        0x200,
        0,
        0,
        0,
        0,
        0x60000020,
    )
    image = PEFile(data)
    for name in ("surface_check.lock", "surface_check.unlock"):
        site = profile.site(name)
        image.write_bytes(
            image.va_to_offset(site.va - len(site.context_before)),
            site.context_before + site.original + site.context_after,
        )
    return image


@pytest.mark.parametrize("profile", SUPPORTED_BUILDS.values(), ids=lambda profile: str(profile.id))
def test_public_patch_compiles_and_verifies_for_both_builds(profile: BuildProfile) -> None:
    patch_id = PatchId("speed_up_surface_checks")
    assert patch_id in PATCHES
    assert (
        patch_id
        in PLANNER.plan_profile(
            ProfileId("recommended"), BuildContext(build_id=profile.id)
        ).patch_ids
    )
    assert all(patch_id in group.patches for group in PROFILES.values())
    plan = PLANNER.plan_explicit((patch_id,), BuildContext(build_id=profile.id))
    source = _source(profile)
    before = source.to_bytes()
    output = OperationExecutor().execute(source, plan.compile_operations())
    assert source.to_bytes() == before
    compiler = SurfaceCheckCompiler(profile)
    compiler.postcheck(output)
    section = output.get_section(compiler.section_name)
    assert section is not None
    assert section.characteristics == 0x60000020  # read/execute, never writable
    assert section.virtual_size == 0x60
    for site, offset in compiler._sites:
        assert (
            decode_rel32_branch(
                opcode=BranchOpcode.JUMP,
                site_va=site.va,
                instruction=output.read_bytes(output.va_to_offset(site.va), 5),
            )
            == output.rva_to_va(section.virtual_address) + offset
        )


def test_bridges_preserve_com_arguments_results_and_continuations() -> None:
    compiler = SurfaceCheckCompiler(GOG_BUILD)
    base = 0x720000
    payload = compiler._build_payload(section_va=base)
    assert struct.unpack_from("<4i", payload, compiler._rect_offset) == (0, 0, 1, 1)
    disassembler = Cs(CS_ARCH_X86, CS_MODE_32)
    lock = list(disassembler.disasm(payload[0x20:0x2E], base + 0x20))
    assert [(item.mnemonic, item.op_str) for item in lock] == [
        ("push", "0x720010"),
        ("push", "eax"),
        ("call", "dword ptr [edx + 0x64]"),
        ("jmp", "0x54f622"),
    ]
    unlock = list(disassembler.disasm(payload[0x40:0x4F], base + 0x40))
    assert [(item.mnemonic, item.op_str) for item in unlock] == [
        ("push", "dword ptr [ebp - 0x58]"),
        ("push", "esi"),
        ("call", "dword ptr [edx + 0x80]"),
        ("jmp", "0x54f63a"),
    ]
    # In particular, neither bridge substitutes access flags, calls Unlock on
    # Lock failure, changes EAX/HRESULT, or adjusts the native caller's stack.


@pytest.mark.parametrize("name", ["surface_check.lock", "surface_check.unlock"])
@pytest.mark.parametrize("region", ["before", "site", "after"])
def test_changed_source_or_context_is_rejected_without_mutation(name: str, region: str) -> None:
    source = _source()
    site = GOG_BUILD.site(name)
    va = {"before": site.va - 1, "site": site.va, "after": site.va + len(site.original)}[region]
    offset = source.va_to_offset(va)
    source.write_bytes(offset, bytes([source.read_bytes(offset, 1)[0] ^ 0xFF]))
    before = source.to_bytes()
    with pytest.raises(PatchError, match="source/context mismatch"):
        SurfaceCheckCompiler(GOG_BUILD).apply(source)
    assert source.to_bytes() == before


@pytest.mark.parametrize("offset", [0, 0x10, 0x20, 0x40, 0x50])
def test_postcheck_rejects_modified_payload_and_padding(offset: int) -> None:
    source = _source()
    compiler = SurfaceCheckCompiler(GOG_BUILD)
    compiler.apply(source)
    section = source.get_section(compiler.section_name)
    assert section is not None
    position = section.pointer_to_raw_data + offset
    source.write_bytes(position, bytes([source.read_bytes(position, 1)[0] ^ 0xFF]))
    with pytest.raises(PatchError, match="postcheck failed: payload"):
        compiler.postcheck(source)


@pytest.mark.parametrize("name", ["surface_check.lock", "surface_check.unlock"])
def test_postcheck_rejects_an_uninstalled_half_of_the_pair(name: str) -> None:
    source = _source()
    compiler = SurfaceCheckCompiler(GOG_BUILD)
    compiler.apply(source)
    site = GOG_BUILD.site(name)
    source.write_bytes(source.va_to_offset(site.va), site.original)
    with pytest.raises(PatchError, match="partially installed"):
        compiler.postcheck(source)


@pytest.mark.parametrize("name", ["surface_check.lock", "surface_check.unlock"])
@pytest.mark.parametrize("region", ["before", "after"])
def test_installed_verification_rechecks_native_context(name: str, region: str) -> None:
    source = _source()
    compiler = SurfaceCheckCompiler(GOG_BUILD)
    compiler.apply(source)
    site = GOG_BUILD.site(name)
    va = site.va - 1 if region == "before" else site.va + len(site.original)
    position = source.va_to_offset(va)
    source.write_bytes(position, bytes([source.read_bytes(position, 1)[0] ^ 0xFF]))
    with pytest.raises(PatchError, match="source/context mismatch"):
        compiler.postcheck(source)


def test_reapply_and_wrong_section_permissions_are_rejected() -> None:
    source = _source()
    compiler = SurfaceCheckCompiler(GOG_BUILD)
    with pytest.raises(PatchError, match="missing or truncated"):
        compiler.postcheck(source)
    compiler.apply(source)
    installed = source.to_bytes()
    with pytest.raises(PatchError, match="pristine executable"):
        compiler.apply(source)
    assert source.to_bytes() == installed
    source.set_section_characteristics(compiler.section_name, 0xE0000020)
    with pytest.raises(PatchError, match="read-only executable"):
        compiler.postcheck(source)


def test_profile_growth_does_not_invalidate_or_expand_an_existing_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _source().to_bytes()
    profile = replace(GOG_BUILD, original_sha256=hashlib.sha256(original).hexdigest())
    monkeypatch.setattr(transaction, "profile_for_sha256", lambda _: profile)
    profile_id = ProfileId("recommended")
    patch_id = PatchId("speed_up_surface_checks")
    old_group = replace(PROFILES[profile_id], patches=frozenset({patch_id}))
    monkeypatch.setattr(transaction, "PLANNER", PatchPlanner(PATCHES, {profile_id: old_group}))
    exe = tmp_path / "GK3.exe"
    exe.write_bytes(original)
    installer = transaction.Installer(
        configuration=NoopConfiguration(), process_probe=lambda: False
    )
    prepared = installer.prepare(exe=exe, profile=profile_id, patches=(), width=1024, height=768)
    installer.apply(exe=exe, prepared=prepared)
    installed = exe.read_bytes()
    new_group = replace(
        old_group, patches=old_group.patches | frozenset({PatchId("remove_disc_requirement")})
    )
    monkeypatch.setattr(transaction, "PLANNER", PatchPlanner(PATCHES, {profile_id: new_group}))
    report = installer.verify(exe=exe)
    assert report.patches == (patch_id,)
    assert report.profile == profile_id
    assert exe.read_bytes() == installed
    installer.restore(exe=exe)
    assert exe.read_bytes() == original
