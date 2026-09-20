"""Canonical authored geometry for GK3's fixed 2D interfaces."""

AUTHORED_FRAME_WIDTH = 1024
AUTHORED_FRAME_HEIGHT = 768

# RestoreProgressController's background is authored as a 593x201 logical UI
# object. Replacement packs may provide a denser raster, but raster storage is
# not presentation geometry; the concrete controller constructor uses these
# dimensions when it attaches that raster to its UI model.
RESTORE_PROGRESS_LOGICAL_WIDTH = 593
RESTORE_PROGRESS_LOGICAL_HEIGHT = 201

# The animated child strip is inset inside that controller. Its destination
# right edge advances from the fixed left edge while loading; this authored
# extent is therefore the authoritative progress denominator.
RESTORE_PROGRESS_STRIP_LOGICAL_WIDTH = 513
RESTORE_PROGRESS_STRIP_LOGICAL_HEIGHT = 50
