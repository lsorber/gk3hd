"""Release metadata must pin every part before the wheel is published."""

import pytest

from gk3hd.package import validate_release_assets
from gk3hd.textures.pack.format import TexturePackError
from gk3hd.textures.pack.source import TexturePackSource


def _lock() -> dict[str, object]:
    return {
        "tag": "v1.0",
        "archives": [
            {
                "filename": f"gk3hd-texture-pack-v1.0-part0{i}-of-02.zip",
                "sha256": str(i) * 64,
                "size": i * 100,
            }
            for i in (1, 2)
        ],
    }


def _release() -> dict[str, object]:
    return {
        "tag_name": "v1.0",
        "assets": [
            {
                "name": f"gk3hd-texture-pack-v1.0-part0{i}-of-02.zip",
                "digest": "sha256:" + str(i) * 64,
                "size": i * 100,
                "state": "uploaded",
            }
            for i in (2, 1)
        ],
    }


def test_urls_are_derived_from_pinned_tag_without_release_discovery() -> None:
    source = TexturePackSource.from_lock(_lock())
    assert len(source.assets) == 2
    assert source.assets[0].archive_url == (
        "https://github.com/lsorber/gk3hd/releases/download/v1.0/"
        "gk3hd-texture-pack-v1.0-part01-of-02.zip"
    )
    validate_release_assets(_lock(), _release())


def test_release_gate_rejects_empty_lock_and_missing_parts() -> None:
    with pytest.raises(ValueError, match="empty"):
        validate_release_assets({"tag": None, "archives": []}, _release())
    with pytest.raises(ValueError, match="missing"):
        validate_release_assets(_lock(), {"tag_name": "v1.0", "assets": []})


def test_release_gate_rejects_wrong_texture_release() -> None:
    release = {**_release(), "tag_name": "v1.1"}
    with pytest.raises(ValueError, match="does not match"):
        validate_release_assets(_lock(), release)


@pytest.mark.parametrize("state", [None, "starter", "uploading"])
def test_release_gate_rejects_incomplete_upload_even_with_matching_hash(state: str | None) -> None:
    release = _release()
    assets = release["assets"]
    assert isinstance(assets, list)
    assets[0]["state"] = state
    with pytest.raises(ValueError, match="incomplete"):
        validate_release_assets(_lock(), release)


def test_release_gate_rejects_duplicate_assets_even_when_both_match() -> None:
    release = _release()
    assets = release["assets"]
    assert isinstance(assets, list)
    assets.append(dict(assets[0]))
    with pytest.raises(ValueError, match="duplicated"):
        validate_release_assets(_lock(), release)


@pytest.mark.parametrize(("field", "value"), [("size", 1), ("digest", "sha256:" + "0" * 64)])
def test_release_gate_rejects_mismatching_uploaded_asset(field: str, value: str | int) -> None:
    release = _release()
    assets = release["assets"]
    assert isinstance(assets, list)
    assets[0][field] = value
    with pytest.raises(ValueError, match="differs"):
        validate_release_assets(_lock(), release)


@pytest.mark.parametrize("tag", ["../v1.0", "v1.0/other", "https://example.com", "latest"])
def test_lock_rejects_unsafe_or_mutable_tag(tag: str) -> None:
    with pytest.raises(TexturePackError, match="invalid release tag"):
        TexturePackSource.from_lock({**_lock(), "tag": tag})
