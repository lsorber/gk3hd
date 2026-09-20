"""Shared source-pixel bounds for the driving map's opaque location crops."""

from typing import Final

# (x, y, width, height) on the original 640x480 DM_BASE bitmap. Origins were
# checked against both overlay states; dimensions are their original headers.
# TR1's road/railway crop is 3 pixels right and 3 up from its shipped anchor;
# RL1's terrain is 4 down, TRE's 2 up. The runtime corrects those constructors.
# Keep layout independent of whether the installed art is original or dense.
MAP_LOCATIONS: Final = {
    "ARM": (458, 225, 55, 39),
    "BEC": (94, 400, 56, 50),
    "BMB": (499, 137, 44, 39),
    "CSD": (396, 187, 54, 40),
    "CSE": (520, 4, 58, 54),
    "LER": (387, 258, 82, 45),
    "LHE": (454, 65, 37, 24),
    "LHM": (442, 155, 37, 32),
    "MCB": (555, 72, 48, 49),
    "PLO": (447, 91, 37, 30),
    "POU": (578, 22, 53, 49),
    "RL1": (487, 174, 59, 48),
    "RLC": (193, 119, 52, 47),
    "TR1": (57, 131, 49, 38),
    "TRE": (506, 89, 44, 38),
    "WOD": (44, 218, 98, 75),
}
