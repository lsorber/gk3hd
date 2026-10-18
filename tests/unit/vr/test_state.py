"""VR ownership cannot expand its scope or accept invalid native calibration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from gk3hd.vr.state import OWNED_FILES, VRState

if TYPE_CHECKING:
    from pathlib import Path


def test_ownership_round_trip_contains_no_resource_paths(tmp_path: Path) -> None:
    state = VRState(40, tuple((name, "a" * 64) for name in OWNED_FILES))
    path = tmp_path / "state.json"
    path.write_bytes(state.to_bytes())
    assert VRState.read(path) == state
    assert str(tmp_path).encode() not in state.to_bytes()
    state.require_owned(dict(state.files))


@pytest.mark.parametrize(("field", "value"), [("schema", True), ("schema", 2), ("files", [])])
def test_invalid_schema_is_rejected(tmp_path: Path, field: str, value: object) -> None:
    data = json.loads(VRState(40, tuple((name, "a" * 64) for name in OWNED_FILES)).to_bytes())
    data[field] = value
    path = tmp_path / "state.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid VR installation state"):
        VRState.read(path)


@pytest.mark.parametrize("scale", [True, None, "40", -1, 0, 10**400])
def test_invalid_json_calibration_is_rejected(tmp_path: Path, scale: object) -> None:
    data = {"schema": 1, "units_per_meter": scale, "files": dict.fromkeys(OWNED_FILES, "a" * 64)}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="world scale"):
        VRState.read(path)


@pytest.mark.parametrize("damage", ["extra", "missing", "hash"])
def test_invalid_owned_inventory_is_rejected(tmp_path: Path, damage: str) -> None:
    files = dict.fromkeys(OWNED_FILES, "a" * 64)
    if damage == "extra":
        files["GK3.exe"] = "a" * 64
    elif damage == "missing":
        del files[OWNED_FILES[-1]]
    else:
        files[OWNED_FILES[0]] = "../outside"
    data = {"schema": 1, "units_per_meter": 40, "files": files}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="invalid VR ownership inventory"):
        VRState.read(path)
