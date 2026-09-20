# Visual scenes

Run `uv run poe visual --suite small`, `medium`, or `large` (12/25/100 scenes).
These opt-in Windows tests use an installed game and one generated save fixture;
they do not depend on the player's save collection. Captures stay in `build/visual/`.

## Curation

Every scene should offer an appealing composition, a clear comparison of the
visual upgrade, or both. Review the actual original/HD pair, not just the camera
name. Prefer a recognizable subject, readable detail, balanced framing and
varied locations. Avoid empty ground, obstructed subjects and unfinished animations.

The small set has ten day-one views plus SIDNEY email and a highlighted driving
map. Gabriel's portrait, Jean's desk, the museum and the room-number buttons
complement wider views of interiors and village architecture. Medium samples all three days and major
interfaces. Large adds locations, material/inscription close-ups and interface
states that expose font, icon, hover, transparency and layout differences.

SIDNEY captures park the pointer off the controls and wait for the lit new-email
notice; driving-map captures wait for the green location dot and hover tooltip.
Both modes therefore show the same native blink phase, without retouching images.
The reference executable uses only a renderer cursor-history compatibility adapter
in addition to its existing startup/quality fixes: no HD interface geometry or
replacement textures. This prevents retained-surface cursor trails in the reference.

The driving map keeps the original location anchors. Three source overlays have
misaligned terrain crops; texture composition carries their matching HD crop
to the authored position (the base already contains the unlit buildings) and
joins its outer edge to the shared terrain. Highlights retain the same position.
Background, overlays, marker and pointer input share a contained 4:3 viewport.
Cross-resolution comparisons allow only final-pixel rounding, not moved locations.

Not every regression view needs to be a postcard: legible signs, a name-entry
caret, map highlights and dark-scene detail are useful comparison subjects.
Keep original lighting/gamma; do not brighten shots just to make the upgrade
look better. A useful scene can expose a rendering defect—retain that evidence
rather than hiding it with retouching.

Recipes in `support/scenes.json` name authored cameras or reviewed explicit
camera poses, plus optional native setup commands and a field of view. Each
pose is `[yaw, pitch, x, y, z]`; both resolutions use exactly the same framing.
Change a recipe and recapture **both** resolutions before
accepting a replacement. `--resume` reuses unchanged captures; start a new run
when a recipe changes. Passing pytest validates capture contracts, not artistic
quality: inspect the pairs before replacing the twelve README gallery images.

## Findings retained for regression review

- `sidney-analyze`: the scanned parchment preview is oversized at 4K relative
  to the original. Keep it as diagnostic evidence, not a gallery showcase.
- `arm-202p-at_armchair`: the wider view exposes a dark polygon near the upper
  left. Compare the scene geometry before treating this as a texture defect.
