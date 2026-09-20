from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.visual.support import catalog
from tests.visual.support.catalog import Scene, SuiteSize, camera_coordinates, scenes


def test_nested_representative_scene_sets() -> None:
    small, medium, large = (scenes(size) for size in SuiteSize)
    assert len(small) == 12
    assert len(medium) == 25
    assert len(large) == 100
    assert large[:25] == medium
    assert medium[:12] == small
    assert len({scene.name for scene in large}) == 100
    assert len({scene.room for scene in large}) >= 30
    assert all(scene.timeblock.startswith("1") for scene in small[:10])
    assert [scene.name for scene in small[10:]] == [
        "sidney-email",
        "driving-map-rennes-le-chateau-hover",
    ]
    assert {"R25", "LBY", "DIN", "MOP", "MS2", "MS3", "RC1"} <= {scene.room for scene in small}


def test_hotel_computer_uses_a_time_when_its_model_exists() -> None:
    # R25.SIF explicitly hides the laptop before 106p.
    selected = [
        scene
        for scene in scenes(SuiteSize.LARGE)
        if scene.room == "R25" and scene.camera == "COMPUTER_SCREEN"
    ]
    assert len(selected) == 1
    assert selected[0].timeblock == "205p"


def test_medium_covers_all_days_and_major_interfaces() -> None:
    selected = scenes(SuiteSize.MEDIUM)
    assert {scene.timeblock[0] for scene in selected} == {"1", "2", "3"}
    assert {scene.name for scene in selected if scene.kind == "special"} == {
        "title",
        "timeblock",
        "inventory",
        "restore-browser",
        "save-editor",
        "driving-map-rennes-le-chateau-hover",
        "sidney-email",
    }


def test_large_prioritizes_locations_over_repeated_cameras() -> None:
    selected = scenes(SuiteSize.LARGE)
    world = [scene for scene in selected if scene.kind != "special"]
    rooms = {scene.room for scene in world}
    assert len(rooms) >= 50
    assert max(sum(scene.room == room for scene in world) for room in rooms) <= 3
    interfaces = {scene.name for scene in selected if scene.kind == "special"}
    assert len([name for name in interfaces if name.startswith("sidney-")]) >= 6
    assert len([name for name in interfaces if name.startswith("driving-map-")]) == 4


def test_camera_resolution_does_not_use_conditional_or_commented_fallbacks() -> None:
    scene = Scene("RC1", "110a", "inspect", "SIGN")
    payload = """
[INSPECT_CAMERAS={Conditional()}]
noun=SIGN,angle={9,9},pos={9,9,9}
[INSPECT_CAMERAS]
// noun=SIGN,angle={8,8},pos={8,8,8}
noun=SIGN,angle={1.5,-2},pos={3,4,5}
"""
    assert camera_coordinates(payload, scene) == (1.5, -2, 3, 4, 5)
    with pytest.raises(ValueError, match="not found"):
        camera_coordinates(payload.replace("noun=SIGN,angle={1.5", "noun=OTHER,angle={1.5"), scene)


def test_console_camera_coordinates_are_always_float_literals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = Mock()
    entry.name = "CS2.SIF"
    archive = Mock(entries=[entry])
    payload = b"[ROOM_CAMERAS]\nDESK,angle={-219.38,0},pos={-98.12,70,38}"
    archive.reader.return_value = nullcontext(Mock(return_value=payload))
    monkeypatch.setattr(catalog.BarnArchive, "open", Mock(return_value=archive))
    scene = Scene("CS2", "212p", "room", "DESK")
    assert catalog.resolve_cameras(Path("Data"), (scene,)) == {
        scene.name: "CutToCameraAngleX(-219.38,0.0,-98.12,70.0,38.0);SetCameraFOV(60.0);"
    }


def test_model_camera_names_resolve_without_inventing_coordinates() -> None:
    scene = Scene("TE1", "309p", "inspect", "te1fire")
    assert camera_coordinates(
        "[INSPECT_CAMERAS]\nmodel=te1fire, angle={0.54,-11.62}, pos={0.98,252.79,205.18}",
        scene,
    ) == (0.54, -11.62, 0.98, 252.79, 205.18)


def test_time_specific_camera_precedes_base_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    base, period = Mock(), Mock()
    base.name, period.name = "DIN.SIF", "DIN110A.SIF"
    archive = Mock(entries=[base, period])
    read = Mock(
        side_effect=lambda entry: (
            b"[CINEMATIC_CAMERAS]\nCOFFEE,angle={1,2},pos={3,4,5}"
            if entry is period
            else b"[CINEMATIC_CAMERAS]\nCOFFEE,angle={6,7},pos={8,9,10}"
        )
    )
    archive.reader.return_value = nullcontext(read)
    monkeypatch.setattr(catalog.BarnArchive, "open", Mock(return_value=archive))
    scene = Scene("DIN", "110a", "cinematic", "COFFEE", setup="EndConversation();")
    assert catalog.resolve_cameras(Path("Data"), (scene,))[scene.name] == (
        "EndConversation();CutToCameraAngleX(1.0,2.0,3.0,4.0,5.0);SetCameraFOV(60.0);"
    )


def test_different_labels_do_not_count_as_different_camera_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = Mock()
    entry.name = "TE5.SIF"
    archive = Mock(entries=[entry])
    payload = b"[INSPECT_CAMERAS]\nnoun=BRIDGE,angle={1,2},pos={3,4,5}\n"
    payload += b"noun=FULL_BRIDGE,angle={1,2},pos={3,4,5}"
    archive.reader.return_value = nullcontext(Mock(return_value=payload))
    monkeypatch.setattr(catalog.BarnArchive, "open", Mock(return_value=archive))
    selected = tuple(Scene("TE5", "309p", "inspect", name) for name in ("BRIDGE", "FULL_BRIDGE"))
    with pytest.raises(ValueError, match="duplicate camera coordinates"):
        catalog.resolve_cameras(Path("Data"), selected)


def test_explicit_framing_is_reproducible_and_keeps_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = Mock(name="entry")
    entry.name = "R25.SIF"
    archive = Mock(entries=[entry])
    archive.reader.return_value = nullcontext(Mock(return_value=b"[ROOM_CAMERAS]"))
    monkeypatch.setattr(catalog.BarnArchive, "open", Mock(return_value=archive))
    scene = Scene(
        "R25",
        "110a",
        "custom",
        "PORTRAIT",
        setup='SetActorPosition("Gabriel","FR_HALL");',
        fov=32,
        pose=(0, 0, 242.15, 65, 210),
    )
    assert catalog.resolve_cameras(Path("Data"), (scene,))[scene.name] == (
        'SetActorPosition("Gabriel","FR_HALL");'
        "CutToCameraAngleX(0.0,0.0,242.15,65.0,210.0);SetCameraFOV(32.0);"
    )


@pytest.mark.parametrize(
    ("pose", "fov"),
    [
        ((0, 0, 1), 60),
        ((0, 0, 1, 2, float("nan")), 60),
        ((0, 0, 1, 2, 3), 0),
        ((0, 0, 1, 2, 3), float("inf")),
        ((0, 0, 1, 2, 3), 180),
    ],
)
def test_invalid_explicit_framing_is_rejected(
    monkeypatch: pytest.MonkeyPatch, pose: tuple[float, ...], fov: float
) -> None:
    entry = Mock()
    entry.name = "R25.SIF"
    archive = Mock(entries=[entry])
    archive.reader.return_value = nullcontext(Mock(return_value=b""))
    monkeypatch.setattr(catalog.BarnArchive, "open", Mock(return_value=archive))
    with pytest.raises(ValueError, match="invalid camera framing"):
        catalog.resolve_cameras(
            Path("Data"), (Scene("R25", "110a", "custom", "BAD", fov=fov, pose=pose),)
        )
