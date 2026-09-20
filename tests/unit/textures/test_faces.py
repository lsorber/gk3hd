"""Replacement face regions preserve their original texture-space layout."""

from configparser import ConfigParser
from importlib.resources import files

import pytest


@pytest.mark.parametrize(
    ("field", "original", "separator"),
    [
        ("Left Eye Offset", (102, 108), ","),
        ("Right Eye Offset", (130, 108), ","),
        ("Forehead Offset", (97, 74), ","),
        ("Eyelids Offset", (104, 111), ","),
        ("Mouth Offset", (97, 140), ","),
        ("Mouth Size", (63, 77), "x"),
    ],
)
def test_temple_bartender_regions_keep_original_normalized_placement(
    field: str, original: tuple[int, int], separator: str
) -> None:
    """The barn's 256-pixel VA3 layout must match the installed 1024-pixel face."""
    faces = ConfigParser(comment_prefixes=("//",), inline_comment_prefixes=("//",))
    faces.read_string(files("gk3hd").joinpath("assets/FACES.TXT").read_text(encoding="utf-8"))
    assert faces["VR3"]["Face Name"] == "va3_face"
    installed = tuple(int(value) for value in faces["VR3"][field].split(separator))
    assert tuple(value / 1024 for value in installed) == tuple(value / 256 for value in original)
