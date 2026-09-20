"""Renderer policy is scoped, portable and preserves existing configuration."""

import pytest

from gk3hd.renderer.distribution import config_bytes


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_d7vk_policy_preserves_other_sections_and_is_idempotent(newline: bytes) -> None:
    previous = newline.join(
        (
            b"# player settings",
            b"d3d9.presentInterval = 1",
            b"[GK3.exe]",
            b"ddraw.forceLegacyPresent = False",
            b"[Other.exe]",
            b"d3d9.presentInterval = 2",
        )
    )
    result = config_bytes(executable_name="GK3.exe", previous=previous)
    assert result.startswith(previous + newline)
    block = result[len(previous) :]
    assert b"[GK3.exe]" + newline in block
    assert b"ddraw.forceLegacyPresent = True" + newline in block
    assert b"ddraw.legacyPresentGuard = Strict" + newline in block
    assert b"ddraw.cpuRenderTargetBacking = True" + newline in block
    assert b"d3d9.presentInterval = 0" + newline in block
    assert config_bytes(executable_name="GK3.exe", previous=result) == result


def test_d7vk_policy_keeps_executable_case_and_unicode() -> None:
    assert "[gk3-é.exe]\n".encode() in config_bytes(executable_name="gk3-é.exe")


@pytest.mark.parametrize("name", ["", "a\n[other]", "[other]", "../GK3.exe", "dir\\GK3.exe"])
def test_d7vk_policy_rejects_section_injection(name: str) -> None:
    with pytest.raises(ValueError, match="invalid D7VK"):
        config_bytes(executable_name=name)


def test_d7vk_policy_rejects_unsupported_wide_text() -> None:
    with pytest.raises(ValueError, match="non-text"):
        config_bytes(executable_name="GK3.exe", previous="# settings".encode("utf-16"))
