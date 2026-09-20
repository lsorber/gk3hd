"""Dependency-free classification of scalar silhouettes, not filename families."""

from collections.abc import Sequence

TRANSPARENT_MAX = 8
OPAQUE_MIN = 247
MAX_INTERIOR_GRAY = 2
_EDGE_RADIUS = 2
_NEIGHBORS = tuple(
    (dx, dy)
    for dy in range(-_EDGE_RADIUS, _EDGE_RADIUS + 1)
    for dx in range(-_EDGE_RADIUS, _EDGE_RADIUS + 1)
    if dx * dx + dy * dy <= _EDGE_RADIUS**2
)


def is_alpha_silhouette(rows: Sequence[bytes]) -> bool:
    """Require transparent exterior, solid core and gray confined to a 2px edge.

    Two interior gray samples are tolerated for classification only, never erased.
    Virtual pixels outside the image are transparent, including clipped objects.
    """
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        return False
    width, height = len(rows[0]), len(rows)
    perimeter = rows[0] + rows[-1] + bytes(v for row in rows[1:-1] for v in (row[0], row[-1]))
    if sum(v <= TRANSPARENT_MAX for v in perimeter) * 2 <= len(perimeter):
        return False
    if not any(max(row) >= OPAQUE_MIN for row in rows):
        return False
    interior = 0
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            if TRANSPARENT_MAX < value < OPAQUE_MIN and all(
                0 <= x + dx < width
                and 0 <= y + dy < height
                and rows[y + dy][x + dx] > TRANSPARENT_MAX
                for dx, dy in _NEIGHBORS
            ):
                interior += 1
                if interior > MAX_INTERIOR_GRAY:
                    return False
    return True
