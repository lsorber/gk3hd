"""Opt-in native OpenXR integration under development."""

# Original FACES.TXT documents eye separation, head radius and head offsets in
# model inches. Keep tracked meters in those native units, without guessing IPD
# or rescaling Gabriel to an assumed human height.
GAME_UNITS_PER_METER = 1.0 / 0.0254
