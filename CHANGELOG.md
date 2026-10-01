## v1.1.1 (2026-09-29)

### Fix

- **renderer**: preserve cursor and tooltip backgrounds on AMD GPUs
- **patch**: keep SIDNEY menus aligned and reachable
- **patch**: keep pointer aligned after motorcycle travel

## v1.1.0 (2026-09-27)

### Feat

- **patch**: speed up held camera controls while preserving precise taps
- **install**: show progress through downloads and installation checks

### Fix

- **package**: make release drafting reliable on Windows
- **renderer**: preserve correct graphics while shaders compile
- **renderer**: prevent descriptor exhaustion crashes on Vulkan drivers
- **renderer**: prevent Proton crashes triggered by logging
- **renderer**: prevent invalid texture access after surface release
- **renderer**: prevent stale interface pixels between redraws
- **renderer**: restore startup in older Proton environments
- **patch**: keep fading text readable under Proton
- **patch**: prevent redundant window updates from causing Wine flicker
- **patch**: show fullscreen movies at the correct high-resolution size
- **patch**: keep SIDNEY controls usable at smaller resolutions
- **patch**: keep action menu buttons visible near screen edges
- **patch**: correct oversized and misplaced driving map locations
- **system**: detect correct default display settings on Linux
- **cli**: flag Steam settings that can interfere with launching GK3
- **system**: keep Linux installation settings between launches
- **install**: allow uninstall after game settings have changed

## v1.0.0 (2026-09-20)

### Feat

- initial commit
