# Native VR for GK3HD

Research and implementation plan, updated 16 October 2026. The development
prototype has isolated original-engine stereo and controller-operated sessions.
This is not a released or headset-validated feature.

The first worn Crystal tryout on 16 October confirms plausible world scale,
usable snap turning and functioning smooth navigation. It also reveals missing
audio (native master volume was zero), inventory selection failure, inadequate
interface-pointer feedback, oversized/displaced action menus, slow locomotion,
small room-status text and corridor-lamp blackouts. These now take priority over
the earlier untracked-headset workbench controls below. Preserve the accepted
world scale and keep normal GK3 isolated. Follow-up acceptance is still needed.

The grouped first-release progress tracker is [VR_CHECKLIST.md](VR_CHECKLIST.md).
Keep its implementation milestones and outstanding acceptance gates synchronized
with the evidence recorded here.

Current priority is a coherent first seated session, not exhaustive interface
polish. A state-scoped scene-resource preparation candidate now passes connected
controller gameplay and reduces the sampled map-return submission gap from
28.78 to 11.10 ms. Connected play, captured map/travel and moving-head movies pass,
so it is enabled in the development VR compiler. Physical comfort, same-frame
transition fidelity and delivered headset frame pacing remain
unqualified. The detailed evidence below distinguishes candidates from defaults.

The unworn physical-runtime game path passes on the connected Pimax Crystal
and RTX 4090, including Play/stereo, native Quit/cancellation and clean removal.
The updated vendor stack recommends 4312×5100 per eye. Fresh-state game samples
reach about 119.5 stereo submissions/sec, and an independent native runtime
probe sustains 119.8/sec for 330 seconds. However, later independent sessions
can again run near 17/sec. Physical tracking remains invalid. Repeatable pacing
and valid tracking are immediate hardware-readiness questions, not reasons to
add more optional gameplay modes. Earlier 60/sec measurements used the old
vendor stack and are retained as historical controls below.
SteamVR's bad-tracking fade is reproduced independently of the game and is not
being disabled in the player. No physical comfort/readability acceptance is
claimed.

## Prototype setup and controls

This is a development workbench, not an invitation to put on a headset yet.
The first supported target is seated play on Windows with SteamVR and tracked
controllers. Steam Deck/Proton VR and other OpenXR runtimes are not qualified.

From the repository, with the Windows renderer build toolchain installed:

```shell
uv run gk3hd vr build      # Build and test under <GAME>/gk3hd/vr/renderer/
uv run gk3hd vr install    # Create the separate GK3-VR.exe and private renderer
uv run gk3hd vr verify     # Check installed files and the matching build recipe
uv run gk3hd vr launch     # Start SteamVR first, then launch the supervised player
uv run gk3hd vr uninstall  # Remove owned VR player files, retaining builds/logs
```

Use `--game-dir PATH` on a command to select a private game copy. Ordinary
`GK3.exe`, its renderer and its INI are preserved. Do not double-click the VR
executable: the launcher verifies it and activates VR before game code runs.
It selects a compatible 32-bit OpenXR runtime for this child only. No persistent
environment variables or system runtime changes are required. `--runtime PATH`
is an optional explicit runtime manifest, not a normal setup step.

The default pointing hand is right; `vr launch --hand left` selects left.
If that hand loses tracking, the other tracked hand can take over. Release held
buttons before using the replacement hand. Aim at an object to interact with
Gabriel or Grace through the original action menus.

Current suggested Valve Index controls:

- Trigger: select, hold and release, including interface dragging and keyboard keys.
- Left B: open the game's contextual menu. Right B: Back, skip the current scripted action, or pause/resume an unobstructed room, according to the current native owner.
- A on either controller: inventory.
- Left stick: gentle camera translation. Right stick: 30-degree snap turning;
  return to center before the next turn.
- Stick click: recenter the seated viewpoint.

Movement changes your viewpoint, not Gabriel's position. The left stick moves
the observer gently at up to 0.8 m/s through the native camera controls; the
right stick snap-turns. Head tracking lets you lean, crouch and stand relative
to the recentered position. Gabriel and Grace still walk and act through the
original point-and-interact gameplay. Scripted camera owners and interfaces
take priority over free navigation.

There is no teleport arc in the prototype. If added later, it should use a
separate movement input with an explicit destination preview and cancellation,
leaving the trigger for object interaction. It must distinguish relocating the
observer from commanding the character to walk, validate destinations and
preserve story triggers. This is a possible comfort option, not implemented or
part of the current controls.

The floating keyboard appears for supported native text editors, including save
names and SIDNEY search/notes. SIDNEY's Home/Exit and driving-map destinations
use their actual on-screen controls, not a forced Back action. Bindings for
other controller families exist but still need physical-device acceptance.
Physical keyboard typing/editing can also be used in native editors. Runtime
focus loss retires held inputs; release and press again after focus returns.
Controller pointing remains the interaction baseline. Independent desktop mouse
control and unrestricted mixed mouse/controller ownership are not qualified.

The launcher reports sustained headset-tracking loss and recovery once per
change, without treating a running but untracked headset as a renderer crash.
Brief startup changes are suppressed. If tracking is unavailable, controller
interaction stays paused; after recovery, release held controls before acting.
Headset tracking alone does not prove runtime focus or controller readiness.

Headset eye dimensions come from OpenXR, independently of the 1280×800 desktop
mirror. Start seated and recenter before navigation. Physical world scale,
readability, comfort, full-story coverage, reconnection and sustained headset
frame pacing remain release gates. A virtual-headset test cannot settle them.

Native model coordinates use inches, as documented in the original `FACES.TXT`.
The default therefore uses **39.37007874 game units per meter**, not the earlier
rounded approximation of 40. Runtime eye separation still comes from the actual
headset. The independent observer's resting eye height is approximately
**1.765 m** above a known floor, based on Gabriel's original 69.5-unit eye height.
Physical scale/comfort acceptance remains open; `--units-per-meter` is an explicit
calibration override, not a required setup step.

If launch fails, follow its runtime/headset message and inspect the reported
`<GAME>/gk3hd/vr/logs/launch-.../` directory. Launch failures stop the owned VR
process rather than silently starting flat play. The normal game remains a
separate launch. Do not publish this prototype as ready for headset play while
the first-release acceptance gates in the checklist are open.

Save normally before closing SteamVR. Terminal XR session loss or a runtime
request to end the experience stops the owned VR player and reports how to
relaunch. This is not automatic reconnection or an emergency save of unsaved
gameplay. Temporary visibility/focus changes do not trigger that terminal path.

### First physical acceptance check

This is a short validation procedure, not a released-VR readiness claim. The
local play loop is verified, but an unworn headset with no tracked pose cannot
establish comfort, aiming, readable text or delivered frame pacing. Keep those
acceptance boxes open until someone actually performs the check.

Use a private game copy with the current verified VR player installed. Leave
the normal game untouched. Start SteamVR, check that the headset and controllers
are tracking, then run:

```shell
uv run gk3hd vr launch --game-dir <PRIVATE_GAME>
```

No persistent environment variables, calibration override or direct launch of
`GK3-VR.exe` is required. Keep the terminal available for cancellation.

1. Begin seated with a clear physical space. Recenter using stick click while
   looking level, then release all controls. Stop if the initial display is
   unstable or uncomfortable.
2. Use the trigger to select Play. Back skips the opening movie. In the room,
   recenter again and check Gabriel and nearby furniture at rest. Leaning and
   small up/down head movements should have the right direction and scale,
   with a level horizon and comfortable binocular depth. Stop if they do not.
   You are a separate Gabriel-height observer, not his embodied character.
3. Try short left-stick movements and one right-stick snap turn, returning
   the stick to neutral between turns. Near-wall fading must still allow
   retreat, without selecting objects through the obscured view.
4. Select an object and use its original action menu. Check the pointer,
   hover/tooltip alignment and text sharpness. Open inventory and return to
   the room. Save a named game with the floating keyboard and restore it.
5. Open the game menu with Left B, select Quit and confirm. If controls are
   unusable, cancel from the launch terminal with Ctrl+C. The supervisor closes
   only its player; unsaved progress is not recovered.

Record the headset, controllers, refresh rate, visible defects and comfort
observations. Use SteamVR's headset frame timing for delivered-frame acceptance,
not the game's submission counter. A passing short check permits a longer
session; it does not establish full-story or other-headset compatibility.

## Recommendation

Add opt-in OpenXR support to the original GK3 engine through executable patches
and our modified D7VK/DXVK-Sarek renderer. Keep the original game, scripts,
characters, saves, lighting, textures, and interactions. Render the actual scene
from both eyes, rather than converting a finished flat image into approximate
depth-based stereo.

The first release should be a seated, tracked spectator camera in GK3's world.
The player still directs Gabriel or Grace through the original interactions.
It should feel like visiting the game's locations, not like watching the
desktop on a headset or turning GK3 into a first-person action game.

Start with Windows and SteamVR. Make the implementation portable to other
OpenXR runtimes and Proton, but do not make every runtime a prerequisite for
the first release. Steam Deck compatibility of flat GK3HD does not establish
VR compatibility or sufficient VR performance.

## Confidence and what remains uncertain

The original-engine stereo prototype now works in isolated private tests, with
synthetic tracking and actual Vulkan rendering. Confidence in the architecture
is high. Confidence in a robust whole-game release remains moderate until real
headset presentation, comfort, frame timing and complete gameplay are verified.
There is no measured basis for claiming a success percentage or delivery date.

### Alternatives considered

| Route | What it delivers | Assessment |
| --- | --- | --- |
| Desktop/cinema screen in a headset | The flat game on a large virtual display. | Lowest engineering cost, but no tracked viewpoint inside the game. Useful for media and fallback presentation, not the main VR goal. |
| Depth-based stereo through an injector | Approximate stereo reconstructed from one view's depth, using vorpX or ReShade/Depth3D. | A quick preview, with unavoidable missing geometry at disocclusions and no automatic game/UI integration. |
| Geometry stereo through a generic injector | Separate eye views where the intercepted rendering path permits it. | Potentially better than depth stereo, but GK3's CPU projection/culling and unusual interfaces still need game-specific work. |
| Native OpenXR in GK3HD | Original-engine stereo, tracked camera, and purpose-built interaction. | Recommended. More initial engine work, but we control correctness, installation, and player experience. |
| Native OpenVR integration | Similar game-specific work with a SteamVR-oriented API. | A viable alternative, but does not remove the engine challenges. Prefer OpenXR's runtime/action abstraction rather than maintain two VR APIs initially. |
| VR in G-Engine | Add VR to a source-available replacement engine using GK3 data. | Easier access to camera/render code, but a different engine with its own fidelity and compatibility validation. A separate project direction. |
| Standalone headset port or engine remake | Run without a PC or redesign the game around VR. | A much larger platform/game project, not an incremental GK3HD feature. |

There is a concrete GK3 vorpX community profile from January 2023 using
dgVoodoo 2.79 and Z3D, optimized for cinema modes. That demonstrates an existing
headset-viewing option, not native tracked original-engine VR or compatibility
with our current renderer.
[Profile author's report](https://www.vorpx.com/forums/topic/gabriel-knight-3/).

Depth3D provides depth-based stereo and an OpenXR headset mode, but this is not
evidence that GK3's current renderer supplies a usable depth buffer or that
tracked game-camera movement works. Its current redistribution terms also need
checking before including it in a GK3HD download. Treat it as an external
experiment, not a dependency to silently bundle.
[Depth3D project](https://github.com/BlueSkyDefender/Depth3D).

G-Engine is a source-available GK3 reimplementation whose author reports the game
as completable with remaining bugs. Source access would simplify engine changes,
but does not establish a ready-made VR implementation or perfect equivalence to
the original. Its GPL-3.0 licensing also needs consideration for any code reuse.
[G-Engine project](https://github.com/kromenak/gengine).

UEVR is not a generic shortcut for this game: it targets Unreal Engine games,
whereas GK3 uses its own engine. Changing DirectDraw wrappers does not turn GK3
into an Unreal game. [UEVR's stated scope](https://github.com/praydog/UEVR).

These tradeoffs are engineering assessments, not claims that every injector or
runtime combination has been experimentally tested here.

| Area | Confidence | Remaining question and how to settle it |
| --- | --- | --- |
| Windows OpenXR integration in a 32-bit process | High for the SteamVR target | Run a minimal x86 Vulkan session on the selected runtime before modifying the game. |
| Vulkan presentation in our renderer | High in principle | Verify runtime GPU selection, image wrapping, and queue synchronization with the pinned Sarek backend. |
| Head pose and camera transforms | Medium-high | Recover and test the camera basis, world-unit scale, and CPU projection coefficients. |
| Correct original-engine stereo | Medium | Find a draw-only boundary, rerun projection/culling per eye, and prove simulation and render state remain coherent. |
| Readable menus, SIDNEY, map, and controller pointing | Medium-high | Isolate the original interface canvas and test panel coordinates independently of world and eye resolution. |
| Full-game camera and puzzle compatibility | Medium | Exercise scripted cameras, scene transitions, close-ups, and interface-heavy puzzles. |
| Comfortable headset-rate performance | Medium | Measure actual stereo frame times, not desktop FPS or a synthetic Vulkan demo. |
| Proton and additional runtimes | Medium-low until tested | Validate the complete 32-bit loader/runtime/graphics path and controller profiles on each supported configuration. |

Research has substantially reduced the runtime and API uncertainty. It cannot
prove engine reentrancy, headset comfort, or full-game correctness. Those are
experimental questions. The gates below are the shortest route to reducing
that uncertainty, rather than building a large feature set on an untested base.

## Evidence from this repository and the executable

The existing renderer is a modified D7VK legacy front end on the pinned
DXVK-Sarek backend. Its source/build metadata and native checks live in
[the renderer package](src/gk3hd/renderer/). We control both the game patches
and the renderer, which is a significant advantage over a generic injector.

Existing DXVK OpenXR/OpenVR extension-provider code is not a playable VR
implementation. It supplies graphics-extension plumbing, not GK3 stereo,
head tracking, controller interaction, or an application-owned XR frame loop.

Read-only disassembly of the locally installed, normalized patched executable
identified the following useful boundaries. These addresses are research
anchors for that image, not portable offsets to apply blindly to other builds.
Implementation must resolve them through the existing verified build profiles.

| Anchor | Observation | Consequence |
| --- | --- | --- |
| `0x005588D0`, projection setup | Initializes shared projection data around `0x00710928`, copies a matrix-shaped block, and computes dimensions and projection terms. | Investigate this path before attempting renderer-only stereo. |
| `0x005586F0` / `0x00558750`, scene begin/end | A shared nesting counter at `0x00710A30` skips projection setup inside a nested scene. | Each eye needs a complete, correctly scoped projection transaction. A nested second eye is insufficient. |
| `0x00599DF0`, primitive submission | Passes vertex format `0x244`, including `XYZRHW`, to a Direct3D draw call. | At least this submission path already contains transformed vertices. A downstream view-matrix change cannot reconstruct missing geometry or undo earlier culling. |
| `0x0049C641`, frame transaction | Advances bookkeeping and page state and participates in interface/cursor work. | Do not call the whole frame transaction twice and assume it is pure scene drawing. |
| `0x00449A65`, camera motion | Converts input deltas and uses mode-specific movement paths. | Head tracking must bypass mouse/keyboard acceleration and integer-delta scaling. |

`XYZRHW` denotes transformed vertices in Microsoft's
[FVF documentation](https://learn.microsoft.com/en-us/windows/win32/direct3d9/d3dfvf).
The disassembly establishes an architectural constraint, not that every GK3
draw uses this format or that a safe stereo render boundary has already been found.

### Runtime findings

GK3 is a 32-bit Windows process. A 64-bit OpenXR loader cannot simply be loaded
into it. However, Valve's September 2026 SteamVR 2.17 announcement explicitly
adds 32-bit OpenXR support. This makes an in-process x86 implementation a
credible first choice rather than requiring a 64-bit bridge from the outset.
Runtime registration and graphics support still need a startup probe.
[Valve's release announcement](https://steamcommunity.com/games/250820/announcements/detail/679635225181946199)
and [official announcement listing](https://steamcommunity.com/app/250820/announcements/).

Valve has also implemented a 32-bit wineopenxr library in newer Proton
development. That is evidence of a route forward, not a promise that Proton 9
or every released Proton version supports this path.
[Valve's implementation commit](https://github.com/ValveSoftware/Proton/commit/6e6dc01f743478e70c946bbae77baf2ce6ede24e).

Do not require a standalone Quest port, convert GK3 to 64-bit, or replace its
engine for this project. A Quest headset would initially connect to a VR-capable
PC through a supported PC runtime. Additional runtimes are explicit validation
targets, not inferred compatibility from their headset brand.

## The first enjoyable release

The internal technical demo can be limited. The first player-facing release
should cover the following complete experience.

### World, camera, and comfort

- Genuine per-eye scene rendering with runtime-provided eye poses and asymmetric
  fields of view. Correct depth and perspective, without artificial eye toe-in.
- One-to-one head rotation and positional tracking for natural seated leaning.
  A rotation-only technical demo is useful, but is not the final initial target.
- A calibrated world scale and easy seated recentering. Use the runtime's eye
  separation, not a hard-coded game IPD. Apply world scale consistently to eye
  offsets, head translation, controller rays, and camera movement.
- Gentle thumbstick camera translation and snap turning, initially 30-degree
  steps with a neutral-return latch. No inherited keyboard hold ramp on head
  tracking. Smooth turning is optional, not the comfort default.
- Preserve the original character-directed gameplay. Camera navigation must not
  teleport the character, bypass triggers, or change walker boundaries.
- Keep the horizon stable during ordinary navigation. Script-driven movement
  must not force an unexpected rotation onto the player's head.
- Fade during scene jumps and unsafe camera transitions. For cinematic camera
  sequences, default to a comfortable virtual screen until a sequence is
  explicitly verified for immersive presentation.
- Fade or mask the world when leaning through a wall. Do not forcibly clamp or
  lag the tracked head pose in a way that makes the view fight the player.

Full room-scale navigation, character-body embodiment, grabbing objects,
gesture controls, and physically walking through the game are outside the first
release. Small tracked head movements remain supported.

### Interaction

- A visible controller laser selects objects through the game's existing
  noun/verb interaction logic. Press to open/select, back to cancel, and a
  simple shortcut for inventory and the main menu.
- Provide left- and right-handed pointing. Handle controller tracking loss
  safely and do not activate actions when the runtime dashboard owns focus.
- Show the original action icons and readable captions. A full replacement
  interaction wheel is unnecessary initially.
- Keep mouse/keyboard and gamepad as alternate input paths where practical.
  Their pointer must use the same documented canvas-to-hit-test mapping.
- Save, restore, pause, quit, and enter save names without removing the headset.
  A small built-in panel keyboard is the dependable baseline. A runtime-specific
  keyboard can be an optional enhancement, not a mandatory extension.

Use OpenXR actions for aim pose, select, cancel, movement, turning, menu, and
recenter. Suggest bindings for tested controller profiles and let the runtime
manage rebinding. Do not encode one vendor's button layout throughout engine
hooks. [OpenXR binding mechanism](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrSuggestInteractionProfileBindings.html).

### Interfaces and media

- Menus, dialogue, inventory inspection, SIDNEY, the driving map, and 2D puzzles
  appear on a stable, comfortably sized virtual panel. Preserve their intended
  aspect ratio rather than stretching them to the headset's eye dimensions.
- Place panels in front of the player when opened, then keep them stable.
  Provide a recenter/reposition action rather than making them constantly chase
  head movements. Place subtitles at a comfortable distance, not at infinity
  or uncomfortably close to the eyes.
- Keep text sharp with adequate panel texture resolution and sensible sampling.
  Reconstructed font atlases and the existing texture pack remain usable.
- Draw one cursor on the panel, with no native desktop cursor leaking into
  either eye. Hover, highlights, tooltips, and clicks must agree everywhere.
- Movies and loading screens use the virtual screen, with working audio, skip
  controls, and an appropriate dark surrounding environment.
- Maintain head tracking while a panel, movie, loading screen, or pause menu is
  visible. Never leave a stale head-locked world frame on the headset.

OpenXR quad composition layers provide a standard presentation mechanism for
such panels. They do not automatically separate GK3's interface from its world,
which remains our engine/renderer responsibility.
[Quad layer specification](https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrCompositionLayerQuad.html).

## Implementation architecture

### Keep Python for installation, native code for frames

Do not add a Python OpenXR frame loop or run Python callbacks at headset rate.
Python should discover the game, download verified artifacts, install patches
and configuration, launch the game, and report diagnostics. Native code should
own tracking, graphics, timing, and interaction.

Proposed additions, keeping the current component structure:

| Location | Responsibility |
| --- | --- |
| `src/gk3hd/vr/` | Small installer/configuration/launch service and Typer command group. |
| `src/gk3hd/patch/definitions/` | Verified VR camera, projection, draw-transaction, interface, and input adapters. |
| `src/gk3hd/renderer/` | Pinned OpenXR build inputs and renderer source patch, using the existing build/distribution machinery. |
| Native renderer patch | A small XR session/frame module, engine bridge, and panel/input module. Split further only when warranted. |
| `tests/unit/`, `tests/integration/` | Portable configuration, installation, math, and rollback tests. |
| Renderer native tests and `tests/visual/` | Mock-runtime graphics/bridge tests and opt-in live VR scene tests. |

The first implementation should extend the existing renderer, not install a
second independent graphics proxy. Establish a versioned native bridge with
sized structures, explicit calling conventions, ownership, and capability
negotiation. Never identify compatibility only by a DLL filename.

The bridge needs a frozen frame context containing simulation/frame identity,
base camera, two eye poses/FOVs, world scale, target extents, and interface state.
All per-eye work must use it consistently. Hook callbacks must not retain
temporary game pointers or reenter the engine from a runtime thread.

### OpenXR startup and Vulkan ownership

Initialize XR outside `DllMain`, before the renderer selects its Vulkan device.
Load the matching x86 OpenXR loader, enumerate available extensions, select the
system, and obtain the runtime's graphics requirements. Prefer
`XR_KHR_vulkan_enable2` and the runtime's device creation/selection contract.
A tested `vulkan_enable` path can be added where needed, not assumed equivalent.
The runtime must agree with the actual device and queue used by Sarek.
[Device selection](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrGetVulkanGraphicsDevice2KHR.html)
and [device creation](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrCreateVulkanDeviceKHR.html).

Do not switch to a different GPU after GK3's renderer has initialized. Do not
assume that Sarek's normal Vulkan requirements are sufficient for every runtime,
or unnecessarily require Vulkan 1.3 just because a tutorial uses it.

Use seated `LOCAL` space initially, with our own calibrated game-world origin.
Handle runtime recenter/reference-space changes without abruptly rotating the
world. `STAGE` is optional and should not be a seated-mode requirement.
[Reference-space definitions](https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrReferenceSpaceType.html).

The normal frame protocol is:

1. Process XR events and input, then wait/begin the next XR frame.
2. Update game simulation once with its ordinary time semantics.
3. Locate the views for the runtime's predicted display time, as late as feasible.
4. Freeze animation and game state for both eye draws.
5. Acquire/wait for XR images and render each eye through the engine adapter.
6. Render/update the panel once, when needed, and submit graphics work.
7. Release the images and end the XR frame with world and panel layers.

Actual threading/order must follow the runtime and graphics synchronization
contracts. `shouldRender == false` still requires a valid frame protocol, with
no unnecessary scene rendering. Check pose validity rather than using an invalid
head pose. [Frame timing](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrWaitFrame.html)
and [predicted per-eye poses](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrLocateViews.html).

Wrap runtime-owned images correctly, or initially copy GPU-to-GPU from owned
eye targets into those images. The latter is a useful correctness-first
prototype, not an excuse for CPU readbacks. Preserve the specified image layouts
and queue ownership. Submit writes before releasing images, with external
queue synchronization covering both Sarek's submission thread and runtime calls.
Do not put a device-wide idle wait into every frame.
[Image lifecycle](https://docs.vulkan.org/tutorial/latest/OpenXR_Vulkan_Spatial_Computing/03_Runtime_Owned_Swapchains/04_memory_ownership_lifecycle.html)
and [Vulkan/OpenXR concurrency requirements](https://registry.khronos.org/OpenXR/specs/1.1/man/html/XR_KHR_vulkan_enable-concurrency.html).

### Original-engine stereo

This is the first and most important engine task:

- Trace scene traversal, camera transforms, CPU projection, visibility/culling,
  and submission. Identify where world-space information still exists.
- Find or create a draw-only room transaction after animation/scripts update
  and before interface composition and desktop presentation.
- Compose the game base camera with the calibrated tracked eye pose, explicitly
  converting coordinate handedness, axes, matrix convention, and world units.
- Apply the runtime's asymmetric projection to the CPU projection path, including
  clipping and screen-center terms. Do not substitute a symmetric desktop FOV.
- Traverse/project for both eyes. Per-eye culling is the safe first version.
  A combined visibility frustum is an optimization only after correctness tests.
- Complete begin/end state for each view. Restore the original camera and
  projection after the transaction, including error paths.
- Separate per-eye color/depth targets, viewport state, and any view-dependent
  caches. Textures and immutable geometry can be shared.
- Prevent page rotation, animation, scripts, input consumption, random effects,
  and CPU background history from advancing once per eye.

Do not snapshot the entire game heap or globally replace screen dimensions and
hope every subsystem adapts. Record and scope the specific view-dependent state
found during tracing. Existing UI and input coordinate systems remain separate
from physical eye render targets.

Verify characters, face/eye overlays, billboards, particles, shadows, skyboxes,
water, near-plane intersections, transparency ordering, and portal visibility.
Both eyes must see geometry newly exposed by head motion, not a reconstruction
of the already-clipped center view.

Recovering camera-space positions from transformed vertices might support
particular optimizations later. It is not the primary correctness path because
it cannot restore geometry discarded before submission.

### Camera ownership and interaction coordinates

Maintain three explicit spaces: game world, tracked XR space, and interface
canvas. Eye render pixels are a fourth space and must not become the universal
input coordinate system.

The game owns the base camera and story transitions. XR supplies head pose
relative to a recentered origin. Controller navigation changes the base, not the
tracked pose. Head pose is never fed through the existing keyboard speed ramp
or converted into accumulated mouse deltas.

For world interaction, locate the controller's aim pose and cast a ray through
the existing world-selection machinery. Recover that ray-selection boundary
instead of fabricating mouse coordinates for one eye. If a center-view adapter
is used temporarily, document its field-of-view limitations and prove it selects
the same object before accepting it for player use.

For panels, intersect the aim ray with the panel plane, map the intersection to
canvas coordinates, and feed the original menu/puzzle logic. Drawing and picking
must use the same origin, scale, clipping, and rounding. Modal panels suppress
world clicks. Native hover animations and map hitboxes remain intact.

### Presentation fidelity

Preserve GK3HD's neutral default gamma and working brightness adjustment. Choose
XR swapchain formats intentionally: encoded color must not be treated as linear,
nor corrected twice. Test color patches and representative scenes in exported
images as well as the headset. Differences caused by headset display calibration
are not evidence that the engine should apply an arbitrary extra gamma ramp.

Maintain original color-key semantics when producing transparent panel content.
Do not infer alpha from all black pixels or let magenta become visible around
icons. Validate premultiplied alpha, fade weights, antialiasing, minification,
tooltip text, and retained-background restoration with native pixel fixtures.

Keep XR world rendering independent of DirectDraw's desktop retained-page
history. Interface capture may reuse the established CPU-backed canvas path,
but its history must not be shared accidentally between the two eyes.

## Installation and distribution

Proposed user commands, not available yet:

```shell
uvx gk3hd vr install    # Install verified VR patches and the compatible renderer
uvx gk3hd vr launch     # Check the runtime and start GK3 in VR
uvx gk3hd vr status     # Report capabilities and actionable setup problems
uvx gk3hd vr uninstall  # Remove VR-specific changes, preserving flat GK3HD
```

Keep this opt-in. Ordinary `gk3hd install` and double-clicking the game remain
flat by default. A later `gk3hd install --vr` shortcut may compose the same
services, but is not needed to prove the experience.

Reuse existing game discovery, renderer verification, executable profiling and
the shared game transaction lock. The tested layout is an alternate
`GK3-VR.exe` beside the original game data, explicitly bound to its private
`gk3hd/vr/player/ddraw.dll` and renderer configuration. Rebuild that alternate
player from a supported pristine executable or the flat installation's verified
original backup. Do not replace the flat executable, renderer, backup or
manifest. The player reads the original data, INI, textures and saves in place.
VR-only ownership and interrupted-operation recovery are separate from the flat
installation. Runtime absence should produce a clear error or an explicitly
offered flat launch, not silent fake VR.

Ship compiled native components as verified release assets. Reuse the existing
renderer DLL release format if the XR build can preserve the flat path. Record
an explicit VR capability/ABI version in its metadata. No renderer compilation
or OpenXR SDK installation is required for players.

The OpenXR loader can be compiled into the native build or distributed as a
matching loader DLL after checking the chosen build. Include required notices
and pinned build inputs. The Khronos SDK provides loader source and headers
under Apache-2.0. Do not distribute a headset vendor's runtime or game files.
[OpenXR SDK](https://github.com/KhronosGroup/OpenXR-SDK).

No new Python dependency or extra is intrinsically required for VR. This is a
native renderer capability, unlike the optional Python AI upscaling stack.
Reuse release manifests and checksums rather than introducing a second release
system. Development builds use the existing renderer build command and pinned
toolchain, with explicit XR build inputs.

Store local configuration below the game's `gk3hd/vr/` directory. Keep captures,
traces, downloaded source, and test output in ignored repository `build/vr/`.
Diagnostics should omit account names, credentials, and machine-specific paths
when exported for an issue report.

## Performance and robustness

Use the runtime's recommended view extents initially, with one clearly named
render-scale setting. Monitor resolution is not headset render resolution.
Two views plus distortion overhead mean that 120 FPS on a 4K desktop does not
guarantee 120 Hz VR.

Measure CPU update time, per-eye traversal/projection, GPU time, presentation
waits, and runtime missed frames separately. Aim for stable native 90 Hz on the
reference PC first, then evaluate 120 Hz. The corresponding total frame budgets
are about 11.1 ms and 8.3 ms. Check tail latency and sustained sessions, not just
an average FPS counter. Reprojection is a safety net, not a claim of native FPS.

Keep the existing no-readback engine patches, shared texture caches, and renderer
batching. Avoid duplicate simulation, CPU eye-buffer copies, unnecessary mirrors,
and per-frame allocation. Start with sequential eye rendering because the game
has shared projection state. GPU multiview, parallel scene traversal, aggressive
late-latching, and foveation are later optimizations, not first-release dependencies.

Budget the 32-bit address space. Share textures across views, bound staging and
history buffers, avoid redundant decoded texture copies, and log allocation
failures cleanly. A large-address-aware flag is not a substitute for measuring
memory use and checking pointer assumptions.

Handle session loss, runtime exit, headset removal, controller disconnect,
device/surface loss, and stopping states. Pause story progression where
appropriate while keeping XR lifecycle handling responsive. Do not leave the
original renderer or input hooks active against destroyed session resources.
Restarts are preferable to unsafe live switching of graphics devices.

## Implementation stages and acceptance gates

### 1. Resolve the architecture before expanding scope

Build a minimal x86 OpenXR/Vulkan session using the pinned native toolchain.
Verify runtime discovery, device selection, two clear-colored views, a panel,
input actions, focus changes, and clean shutdown. Do not involve GK3 yet.

Separately instrument GK3's camera/projection and draw boundaries in a private
test install. Record submitted vertex formats and update/page counters. Produce
offline left/right images from a frozen room state with different eye poses.

**Gate:** real scene stereo with correct parallax and independently exposed
geometry, no doubled animation/script progression, no page-history corruption,
and unchanged flat output when disabled. If this fails, continue investigating
the engine boundary before building controller menus or promising support.

### 2. Establish a tracked world in the headset

Connect that stereo transaction to the XR frame loop. Calibrate world units,
coordinate conventions, projection, and seated recentering. Validate translation,
rotation, stereo depth, clipping, frame pacing, and tracking loss in several rooms.

**Gate:** a stable, comfortable room-viewing prototype with no eye disagreement,
head-pose lag introduced by our input path, incorrect scale, or repeated GPU
synchronization errors. This is an internal prototype, not a complete release.

### 3. Deliver the first full player loop

Add controller world selection, action menus, panel capture/picking, navigation,
subtitles, inventory, movies, and save/restore. Include a brief first-launch setup
for recentering, handedness, and comfort controls.

**Gate:** a player can launch, start or restore a game, interact with characters
and objects, use SIDNEY and the map, inspect inventory, save under a chosen name,
and quit without needing to remove the headset or manually edit configuration.

### 4. Validate and release a bounded compatibility target

Run representative scenes and longer play sessions. Check Windows Steam and
GOG executables, the tested SteamVR runtime, controller bindings, uninstall, and
flat-mode regressions. Document the exact tested hardware/runtime versions.

**Gate:** all essential paths pass, sustained frame-time measurements meet the
chosen headset target on reference hardware, and the installer is reproducible.
Publish the first release with explicit support boundaries, not a blanket
claim that every OpenXR headset and Proton version works.

### 5. Extend after the first release

Validate newer Proton's 32-bit XR path and Linux runtime/device requirements.
Test other Windows runtimes where their x86 Vulkan combination is available.
Add smooth-turn preferences, optional depth submission, optimized eye draws,
and selected immersive cinematic camera paths.

Teleportation, room-scale traversal, physical puzzle interactions, hands, and
character embodiment require separate game-design and collision/trigger work.
They should not hold up a good seated release.

## Testing and reproducibility

Add an opt-in `vr` pytest marker, keeping ordinary CI fast and headset-free.
Reuse the existing visual scene catalog rather than create another save corpus.
Deterministic test poses should include center, yaw/pitch, near-wall lean, and
left/right translation. Freeze simulation state for stereo comparisons.

Portable tests cover transforms, handedness, projection, recentering, panel ray
intersection, clipping, coordinate rounding, profile/configuration validation,
capability negotiation, and install/uninstall behavior. Native mock-runtime tests
cover frame/image ordering, invalid poses, failure cleanup, and queue ownership.
Mock success does not establish real compositor latency or comfort.

Live acceptance tests should include:

- Hotel room and lobby, near and far objects, Gabriel's face, and character animation.
- Outdoor geometry, alpha-tested trees/signs, particles, water, and scene transitions.
- Driving-map location/hover alignment and SIDNEY's text, controls, and puzzle panels.
- Context menus at every panel edge, tooltips, score fade, and inventory inspection.
- Save/restore preview, text entry, movies, subtitles, and cinematic cameras.
- Dashboard/focus changes, controller loss, recentering, session shutdown, and flat launch.

Export paired eye images, panel images, reproducible poses, timings, and logs to
`build/vr/`. Use geometry landmarks and numeric reprojection checks in addition
to visual inspection. Include GPU validation on development builds and verify
color-key/alpha behavior with small fixtures rather than requiring full texture
upscaling in tests.

A headset is not necessary for the installer, transform, offline stereo, and
many native tests. A real headset and tracked input are necessary before claiming
comfortable playable VR. WSL or a VM can help with particular Proton/installer
checks, but cannot certify the complete headset compositor or tracking path.

## Decisions to keep simple

- Native original-engine stereo is the goal. A depth-stereo injector or G-Engine
  replacement is not an equivalent fallback to quietly ship under that name.
- Prefer in-process x86 integration now that the primary runtime supports it.
  Investigate a 64-bit companion only if actual runtime or memory constraints
  justify its IPC, synchronization, and deployment complexity.
- Keep the modified renderer and original game logic. Extend their boundaries
  deliberately rather than rewriting the graphics/game stack at once.
- Ship a complete seated interaction loop before pursuing room-scale features.
- Make runtime/hardware support an evidence-backed matrix, not a list of assumed
  brand compatibilities.

The runtime probe and frozen-state engine experiment now provide initial
evidence for stage 1, as described below. They do not pass the complete stereo
acceptance gate: additional scenes, production render-state isolation, and actual headset
submission still need validation. The principal uncertainty is robust
original-engine stereo, not whether OpenXR has APIs for presenting two eyes.

## Implementation progress

The native foundation now lives in
[`src/gk3hd/renderer/vr/`](src/gk3hd/renderer/vr/README.md). It builds as x86 with
the pinned Khronos loader and Vulkan headers. It implements instance/system
discovery, the Vulkan enable2 handshake, session/local-space lifecycle,
independent eye swapchains, predicted view poses, and projection-layer submission.
Tracking transform, asymmetric projection, and panel-ray coordinate helpers
are also implemented. The renderer exposes private frame and scene bridges that
accept game-rendered D3D targets. A profile-checked engine compiler calls the
scene bridge in isolated tests. Public installation and the complete player
interaction loop are not implemented yet.

Verified locally:

- Release x86 native build succeeds.
- Mock-runtime lifecycle and camera/panel math tests pass without a headset.
- The renderer Python unit tests pass, including native recipe cache invalidation.
- Actual runtime discovery fails without a registered x86 runtime. Selecting
  the installed SteamVR x86 manifest for the probe process successfully loads
  that runtime, then reports `XR_ERROR_FORM_FACTOR_UNAVAILABLE` because no headset
  is available. No persistent runtime setting was changed.
- An engine-camera adapter handles GK3's scaled camera basis, per-eye clipping,
  and asymmetric projection. Its output was compared with execution of the
  original CPU projection routine for 384 vertices across three fields of view.
  The original polygon outcode routine also agrees for 150 points across three
  asymmetric fields of view. GK3's fast clipping paths assume `|X|, |Y| <= Z`.
  The adapter therefore includes frustum scale and off-axis shear in the camera
  matrix, rather than changing only projection coefficients or plane equations.
  Native tests check conservative BSP sphere bounds under that transform.
- An isolated game experiment renders center, left, right, and center again
  inside one draw transaction. The outer engine frame counter stays unchanged,
  the original camera is restored after each draw, and the two center images
  match exactly. The left/right images show different perspectives.
- Instrumentation confirms real static room geometry is drawn for each eye,
  not just actors over a cached flat image. The tested room submits 288 static
  geometry draws and 72 dynamic batches per original-FOV view. A wider asymmetric
  FOV produces 370 or 371 static draws and 87 dynamic batches per view.
- The evidence now includes direct render-target readbacks, not only desktop
  captures. A clear-only control produced a completely solid target. Both
  eyes receive a full-rectangle color/depth clear inside the active scene.
  The earlier zero-rectangle `Clear2` returned success without clearing this
  path. Its captures did not establish retained-page correctness.
- The narrow right-edge feature also appears in the original center view and
  survives a verified full clear followed by geometry rendering. The handle
  originally suspected to be a cached background is actually the room BSP
  resource. The earlier diagnosis of a stale background strip was unsupported
  and is withdrawn. Other scenes and transitions still need isolation tests.
- No captured image has been submitted to a headset. Diagnostic CPU readback
  is only an experiment tool and must not become the production eye transport.
- Runtime initialization verifies opaque presentation support. Teardown handles
  acquired-but-not-waited images without an invalid release/frame end or blocking
  indefinitely. The renderer host must drain GPU work before destroying XR
  swapchains, as required by the
  [OpenXR destruction contract](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrDestroySwapchain.html).

### Renderer integration progress and next boundary

The pinned Sarek backend has a borrowed-image `DxvkImage` constructor and queue
submission synchronization. Its existing `DxvkXrProvider` only queries graphics
extensions through Wine, not XR sessions or frame submission. It is not an
existing integration that can simply be enabled with a configuration switch.

The opt-in Sarek patch now participates before Vulkan instance/device creation,
selects the runtime's GPU, creates the XR session, and wraps runtime-owned eye
images without allocating or freeing their memory. Device destruction drains
GPU work and discards wrappers before closing the session. The normal renderer
path remains the default.

The complete build is reproducible using `build.ps1 -OpenXR`. A fresh source and
dependency build produced the x86 combined renderer and passed native lifecycle
tests plus the ordinary GPU surface/readback/retention checks with XR disabled.
The recipe includes OpenXR/JsonCpp notices, checks for machine-specific binary
paths, records the native input hashes, and uses a distinct prototype filename
that the release verifier rejects. A separate test-only runtime exercises actual
Vulkan instance/device/session bootstrap and image allocation on the RTX 4090,
with synthetic tracking and no headset compositor. Overlapping D3D9 interfaces
share one XR instance, and device recreation preserves that instance without
deferring XR/GPU cleanup to `DllMain`.

The renderer now transports D3D targets to acquired eye images entirely on the
GPU, using the bound graphics queue and restoring the required layout before
release. It converts/scales encoded RGB565 values into UNORM intermediate images,
then copies their bytes into compatible sRGB eye images. Direct UNORM-to-sRGB
blitting would introduce an extra encode. Linear-only runtime formats are rejected
until their separate conversion is implemented.

A GPU fixture renders distinct left/right quadrant patterns and checks the
actual submitted pixels from 16-bit and 32-bit targets, with both RGBA and BGRA
runtime formats, including mid-tones, orientation, opaque alpha, repeated
image acquisition, cancelled partial frames, invalid operation ordering, and
device/session recreation. Diagnostic readback and synthetic tracking live only
in the test runtime, not the player renderer. This is real GPU transport evidence,
not headset presentation or evidence of a playable game.

The game draw-only transaction now calls the versioned scene bridge through
`VRSceneCompiler`. Each predicted eye receives independently cleared world
geometry and actors, followed by one two-eye projection-layer submission.
The compiler derives dimensions and current room/camera pointers from verified
build symbols, not experiment-specific addresses. Authored camera and shared
projection state are scoped per eye; the ordinary center draw still owns desktop
history and picking. Unknown hooks, modified engine anchors, incompatible or
modified transition adapters, and unrepresentable world scales are rejected.

Local evidence now includes:

- 32 consecutive stereo pairs in each of R25, LBY, and RC1 at both 1024x768 and
  1280x800. Captured submitted GPU images show separate views, and sampled
  authored camera state is restored. The eye targets are only 256x256.
- More than 2,500 submitted stereo pairs while changing R25 -> LBY -> RC1 -> R25
  in one game process with stereo continuously enabled and changing synthetic
  predicted poses. Sampled camera state restores across these transitions.
- Portable compiler/native-emulation tests cover flat/non-world rendering,
  camera/projection restoration, callee ABI, hidden frames, missing renderer
  exports, failed eye clears, and preflight rejection without partial writes.
- Native GPU scene tests cover callback failure cancellation and recovery in
  addition to the previously verified image transport paths.

Captures and live-game runners remain under ignored `build/vr/`; no original
game executable or game capture is distributed. The optional evidence-file
writer exists only in the GPU test runtime, not the player renderer.

### Controller input foundation

Native OpenXR actions now provide independent left/right aim poses, select,
back, menu, inventory, recenter, and camera-stick snapshots. Aim poses are
located in seated LOCAL space at the same predicted display time as the eyes.
Suggested bindings use core Simple, Touch, Index, Vive, and Microsoft motion
controller profiles, without binding reserved system/dashboard buttons. These
are provisional layouts, not hardware-validated support claims.

Input is neutral when the session is unfocused, rendering is hidden, or head
tracking is invalid. An invalid/untracked pointing pose neutralizes its hand.
After focus, tracking, profile, action, or session recovery, held buttons must
be released before activating. Sticks must return to neutral before movement.
Invalid/nonfinite poses and stick values cannot leak into engine commands.
Action spaces close before their session, while action sets survive renderer
device recreation and close before the XR instance.

The private frame bridge now carries these fixed-width input snapshots.
Controller recentering is connected to the stereo coordinator. Selection,
camera navigation, inventory/menu activation, and visible lasers still need
engine/panel adapters. Obtaining an action snapshot does not make those game
interactions playable.

Native tests cover button edges, independent hands, predicted pointing poses,
focus/tracking loss, release/neutral recovery, inactive actions, profile changes,
partial initialization, frame failures, and session recreation. GPU fixture
tests also pass snapshots through the actual combined renderer, for RGBA/BGRA
eye images and 16-/32-bit game targets. All controller input in these tests is
synthetic and lives only in test code.

A fresh complete prototype build passed all three native test executables,
ordinary flat renderer surface/helper checks, and both RGBA/BGRA GPU transport
checks. Its recorded native source hashes match the current source tree. The
resulting candidate rendered 32 stereo pairs in each of R25, LBY, and RC1 at
1280x800 through the private engine compiler, with distinct submitted eye
images and restored authored camera state. Input in these scene tests was
inactive. The normal installed game was not modified, and the private game
processes were closed after testing. These are regression checks, not a
physical-controller, comfort, or headset-performance validation.

A separate x86 input probe can validate action definitions and suggested
bindings against a selected real runtime. On the available SteamVR installation,
instance creation succeeds but the first hand-path lookup returns
`XR_ERROR_RUNTIME_FAILURE`. The headset probe separately reports
`XR_ERROR_FORM_FACTOR_UNAVAILABLE`. With no headset attached, this does not
establish whether the failure is a headset prerequisite or another runtime
issue. Actual controller bindings, tracking, focus, and gameplay remain
unverified on hardware.

OpenXR requires accepting valid core allowlisted binding suggestions even for
absent controller hardware. Invalid bindings are not silently skipped.
Its positive `XR_SESSION_NOT_FOCUSED` result is treated as neutral input, not
ordinary success. [Binding contract](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrSuggestInteractionProfileBindings.html)
and [focus contract](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrSyncActions.html).

The next boundary is engine interaction and stable interface/media panels,
then cross-scene state isolation and actual headset acceptance.
The bridge currently transports neutral game colors. Applying the player's
non-default brightness setting to XR output still needs integration and testing.

Still unverified or incomplete: actual headset presentation and controller
hardware, engine interaction, full-game per-eye state isolation, automatic UI capture, installation/launch
commands, non-default brightness, calibrated scale, sustained headset-rate
performance, and comfort. Existing scene evidence does not complete the engine
stereo acceptance gate or player experience. The goal must not
be marked complete based on the foundation, desktop captures, or mock tests.

### Native interface-panel transport

The native renderer now exposes `Gk3hdXrPanelV1` for an explicitly selected 2D
canvas. Its independent quad swapchain retains the canvas pixel dimensions and
aspect ratio rather than stretching to either eye image. The panel anchors
upright when opened, stays fixed in local space as the head moves, and can be
recentered. Reopening establishes a new anchor. Drawing and controller picking
consume the same pose and physical extent; outside and back-face rays cannot
activate a button.

Four native test executables pass, including panel placement, both-hand edge
picking, focus/tracking loss, aspect changes, recentering, and invalid placement.
The actual RTX GPU transport fixture passes RGBA and BGRA targets, each across
four device/session cycles covering 16-bit and 32-bit game canvases. Each cycle
submits 34 quad frames, checks square and 4:3 canvas pixels, compares the returned
geometry to the submitted layer, samples 15 points for each hand including the
edges, rejects a canvas mismatch without leaking its frame, and resumes stereo
world presentation afterward. Tracking remains synthetic; this is not a
headset/compositor or comfort test.

The non-square clear-only canvas regression exposed a deferred producer clear
that an ordinary command-list flush did not materialize before XR read it.
A diagnostic source readback made the defect disappear. That readback was
removed, and the producer now finishes its render pass/deferred clears before
the GPU-only transfer. Both transport formats pass without a source readback or
normal-frame GPU-idle wait. Resize and exceptional teardown may still drain
pending GPU work to safely destroy old swapchains.

The next integration boundary is the engine's interface canvas and input update.
Its DirectDraw producers may need their final CPU-authored canvas uploaded
before XR presentation. Existing fixed-screen/cursor presenters already use
linked pre/post-Flip callbacks, so a VR hook must compose with those callbacks,
not overwrite them. World and interface callbacks also need one consistent XR
frame owner. The renderer bridge alone neither captures every interface nor
routes controller actions into the game. Installation, headset acceptance,
brightness, scale, comfort, and full-game validation remain incomplete.

The fresh panel candidate built from pinned sources completed all four native
test executables, ordinary flat renderer checks, and RGBA/BGRA GPU transport
checks. All 28 recorded native input hashes match the source tree. Its SHA-256
is `4e80809671f102cd5fc76ba5e2644546dd9557ba003a2c02319634c224f68503`.
The private engine regression rendered 32 stereo pairs each in R25, LBY, and
RC1 at 1280x800, restored authored camera state, and closed every private game
process. Captures were inspected for obvious rendering regressions. The
ordinary test suite passed with 2,524 tests, 20 skipped, and 402 deselected in
34.33 seconds on an idle rerun; lint and types passed. Evidence remains under
ignored `build/vr/panel-evidence/` and `build/vr/recipe-panel-20261009/`.
This candidate was neither installed into the user's game nor published.

### Completed game-page capture

The private `VRPanelCompiler` now chains after GK3HD's existing final-page
presenter, before native Flip. Cursor, caption, tooltip, and retained-screen
composition keep their existing owner. The renderer uploads the current
DirectDraw target's dirty CPU-authored pixels before the GPU-only panel copy,
so the quad does not display the earlier, incomplete 3D target. The ordinary
Flip and post-Flip callbacks remain unchanged.

Private live-game tests at 1280x800 submitted 32 panel frames each for the
driving map, SIDNEY home, and the right-click menu. The map and SIDNEY panel
captures matched their desktop pages within eight RGB levels at every pixel.
The separately timed menu capture matched that tolerance at over 98% of pixels,
with the room continuing to animate. The captured interface pixels were also
visually inspected. Evidence lives in ignored `build/vr/engine-panel-evidence/`.
All private game processes were closed and registry settings restored; the
user's installation was not modified.

A dedicated GPU regression fills a native 16-/32-bit DirectDraw page after its
3D draw and requires the next quad to show those new pixels without waiting for
Flip. This passes for both RGBA and BGRA XR targets. Panel capture has 12 new
portable tests for callback composition, supported builds, dormant behavior,
missing renderer exports, hidden frames, failure recovery, closing, and
competing frame owners. Lint/types pass, and the ordinary suite passes with
2,536 tests, 20 skipped, and 402 deselected in 34.86 seconds.

This is still an explicitly enabled panel-only development gate, not automatic
selection of every UI or a completed immersive experience. A guard prevents
the separate world and panel prototypes from both owning XR frame submission.
Their eventual common scheduler must choose/combine layers once per game
update. Controller snapshots reach the engine bridge but are not yet routed
into GK3. That routing should enter the existing physical-canvas input path
and its tested per-interface coordinate inverses, while ensuring the visible
software cursor uses the same pointer. No desktop mouse movement should be
needed for that integration. Real headset/controller validation, brightness,
scale, comfort, installation, and full-game state isolation remain outstanding.

The fresh reproducible engine-panel renderer has SHA-256
`dca0652a76a63dd558912e57ab5860dad4c7f0408a7026f337c19e500d7e2434`.
All 28 recorded native input hashes match the current source tree. It passed
the four native test executables, ordinary renderer checks, and both GPU
transport formats. The three actual-interface captures were repeated with
this fresh build, not only the incremental development DLL. It remains a
private prototype and was not installed into the user's game or published.
The fresh DLL also repeated the live R25, LBY, and RC1 stereo regressions:
32 stereo pairs per room, 64 eye draws, distinct eye images, and restored
authored camera state. All private processes were closed afterward.

Input tracing confirmed that the game's shared client-point producer reads
the host pointer and subtracts the renderer's window offset. A VR adapter
must virtualize that producer consistently with event delivery, not just send
mouse messages while leaving final software-cursor painting on the host
pointer. Existing SIDNEY/map/menu dispatchers already provide the necessary
physical-canvas-to-authored-coordinate transforms. Button release on focus
loss, tracking recovery, modal-layer changes, pointer exit, and panel closure
needs explicit behavior tests before this becomes a playable interface.

### Native panel interaction

The private `VRInputCompiler` now routes the panel pointer into GK3's own
mouse-event methods on the render thread. Existing interface-specific coordinate
inverses remain responsible for SIDNEY, the driving map and menus. Client-point
queries use that same virtual point, and cursor warps do not move the desktop
mouse. Host mouse events are suppressed only while VR owns this input path;
the dormant bridge preserves native mouse behavior.

Select has native press/hold/release semantics. Menu emits one native right-click
pulse rather than a sustained camera-drag button. Focus/tracking loss, pointer
exit, changing hands or active UI layers, disabling input and closing the panel
retire held selection outside all controls. Recovery requires release before a
new press. Cancellation callbacks continue to see the virtual outside point
even after the mode is disabled. Dispatch stops if a native event changes the
active layer, so subsequent actions cannot reuse its snapshot on a new screen.

Thirty-nine portable emulation tests execute those hooks, including native
event ABI/stack behavior, host isolation, invalid coordinates, cancellation,
new modal layers and dormant point/warp continuations. A test-runtime-only
shared-memory fixture can supply synthetic controller poses/actions to a private
live game process. It checks committed packet sequences and acknowledges sampled
input; it is neither compiled into nor installed as the player runtime.

Private live tests with the fresh renderer opened SIDNEY email and returned
home through controller Select, verified six held-press cancellation/recovery
cases without accidentally activating email, highlighted three separated driving
map locations, and closed the native right-click menu with Menu. Captures were
visually reviewed. All three experiments kept the physical desktop cursor
unchanged, closed their game processes and restored temporary settings. Evidence
is in ignored `build/vr/engine-input-evidence/`.

The fresh candidate SHA-256 is
`6ee6edecf5b1c9d07339657e051ec5c4522ddb02e901f9d21aa023a8cae92acb`.
All 28 native input hashes match the source tree. The full build passed native
lifecycle/scene/input/panel tests, ordinary renderer checks, and RGBA/BGRA GPU
transport checks. Lint/types pass; the ordinary suite passes with 2,575 tests,
20 skipped and 402 deselected in 33.21 seconds. The fresh renderer also repeated
32 stereo pairs in each of R25, LBY and RC1 at 1024x768, with distinct eye images
and restored authored camera state. All private processes closed afterward.

This remains an explicitly enabled panel-only development boundary. It does not
complete world-ray selection, navigation, back/inventory shortcuts, save-name
entry, a common world/UI/media frame scheduler or public installation/launch.
Actual headset/controllers, full-game stereo state isolation, brightness,
calibrated scale, comfort and sustained headset performance remain unverified.
No prototype was installed into the user's game or published. The full native
VR goal remains active.

### Shared world and panel frame ownership

The renderer now coordinates deferred world drawing and completed-page panel
presentation through one native frame scheduler. They use the same predicted
views and controller snapshot, and submit projection and quad layers together.
The final-page hook runs even with the panel disabled, completing a pending
world without waiting for a second XR frame. A recenter request cannot remove
deferred ownership. Pairing requires the verified deferred scene bridge.

Hidden frames are sampled once and retired by the finalizer. Invalid panels,
incomplete/duplicate world draws, and submission failures retire ownership
without submitting partial worlds or double-ending a consumed frame. The raw
diagnostic bridge cannot steal a coordinated transaction. Paired completion
failures disable further world draws rather than stranding new transactions.

Portable scheduler tests cover input snapshot consistency, combined/panel-only/
world-only layers, hidden updates, cancellation, duplicate draws, and end errors.
Actual GPU tests inspect test-runtime counters and pixels: one begin and one
action sync, two composition layers in one end, unchanged rendered eyes after
UI painting, completed panel pixels, next-frame controller edges, and recovery.
RGBA/BGRA swapchains and 16-/32-bit game sources pass across device recreation.

A private original-engine experiment at 1280x800 rendered both eyes and the
completed right-click menu page together, switched to world-only, panel-only,
combined again, then dormant. All completion results were successful. Combined
world/panel counts advanced together, disabled layers stopped advancing, and
the desktop cursor stayed unchanged. Eye and panel captures were inspected.
Evidence is in ignored `build/vr/shared-frame-evidence/`; temporary game settings
were restored and the private process closed.

The fresh pinned renderer candidate has SHA-256
`05e6b6424aac0908362ffec5b502c1177667a8f2044dcea5ee4827070772fe44`.
All 29 recorded native source inputs match the worktree. This fresh build also
repeated native lifecycle/scene/input/panel checks and both GPU target formats,
then live SIDNEY/map/menu controller regressions. SIDNEY retained all six
held-selection cancellation checks. Original-engine stereo regressions rendered
32 pairs each in R25, LBY and RC1 at 1024x768, with distinct eye images and
restored authored cameras; captures were inspected. All private processes closed.
The ordinary suite passes with 2,584 tests, 20 skipped and 402 deselected in
36.68 seconds. These are development gates, not real-headset acceptance.
The quad still contains the opaque completed desktop page, including the world
behind its menus. Isolated UI composition and automatic world/panel/media
selection remain required, as do world-controller interaction, navigation,
save-name entry, comfort, brightness, calibrated scale, sustained performance,
full-game state isolation, and public installation/launch. Nothing was installed
into the user's game or published. The full VR goal remains active.

### Controller shortcuts and native driving-map travel

The private panel input bridge now opens Inventory through native I, emits Menu
as one right-click pulse, and closes supported interfaces through native Escape.
These shortcuts work without pointing at the panel. Menu falls back to the
canvas center when no ray hits it, rather than using a stale outside point.
Held shortcuts do not repeat. Focus/tracking recovery and hand/layer changes
require release before another action, and a held Select is canceled before
dispatching a shortcut. Synchronous native redraws neither resample OpenXR nor
start another world transaction, and stereo enablement is restored afterward.

The Menu investigation found a mislabeled native event contract. GK3's Windows
message table routes right down/up through EngineLoop vtable offsets 0x68/0x6c.
Offsets 0x50/0x54 are middle down/up, whose click invokes Escape instead of
opening the toolbar. The profiles and interface dispatcher argument counts
now agree with those native events. The renderer/client-point global and
EngineLoop global alias in the actual game, so choosing between those globals
was not the cause of the failed Menu action.

A stronger map acceptance gate rejected an initially attempted UI-pop shortcut.
`ShowDrivingInterface` unloads the room, and the original map does not handle
Escape. Popping its layer exposes an empty room even though the active layer
changes successfully. That forced-pop code was removed. Back now preserves the
map. Controller Select on its native Cuiza-station button performs actual travel
and loads the rendered TR1 destination. This retains the original interaction
and script ownership instead of inventing a map cancellation transaction.

Private live tests cover Inventory and Back, Menu at center and bottom-right,
held Menu without repeated toolbar creation, focus/tracking recovery, Back on
the map, and native map destination selection. The sequence also passes with
shared stereo world/panel presentation. Captures were reviewed, including the
rendered station rather than accepting only a UI-layer change. SIDNEY email,
six held-selection cancellation cases, and three map hover targets also pass
again. All tracking/actions are synthetic, with actual Vulkan rendering and
original-engine callbacks. Evidence lives under ignored `build/vr/` directories.
The private processes close and temporary settings are restored afterward.

The native renderer candidate remains unchanged at SHA-256
`05e6b6424aac0908362ffec5b502c1177667a8f2044dcea5ee4827070772fe44`.
The portable scene/panel/input compiler gates pass 128 tests. These results
are accompanied by clean lint/type/spelling checks and the ordinary suite:
2,627 passed, 20 skipped, and 402 deselected in 33.56 seconds. These results
do not establish headset compatibility, automatic screen ownership, isolated
transparent UI, world-ray interaction, locomotion, text entry, calibrated scale,
comfort, brightness, or sustained headset performance. The user's installed
game was not modified. Full playable VR remains incomplete and the goal active.

### Native controller world picking

The scene bridge now returns both controller world-space segments and focused
input from the same predicted frame and seated origin as the eyes. Camera axes
share the stereo adapter's authored-basis normalization, including its explicit
OpenXR-to-engine handedness conversion. Physical offsets and recentering affect
eyes and controller origins consistently. World rays do not depend on desktop
pixels or either eye's field of view. Hidden/failing draws and tracking/focus
loss clear validity. Native math, scene and GPU transport tests cover the shared
snapshot, both hands, asymmetric authored axis scales, recentering, invalid data
and failure recovery.

`VRWorldCompiler` installs a dormant, explicitly invoked native Room3D picker
scope. It preserves the original BSP and actor intersection routines and
nearest-hit comparison, supplying a frozen controller near/far segment and
origin wherever those routines previously generated a desktop camera ray.
Both the outer room rectangle and the actor candidate screen rectangles need
controller-aware handling. The live gate initially missed Gabriel because the
native candidate collector discarded him using the out-of-screen placeholder
point before intersecting his geometry. The scope now skips that desktop-only
filter while retaining the preceding actor selectable/resource checks and the
native intersection rules. Hidden rooms remain non-interactive. Ordinary
callers keep all their original rectangle, ray and camera-origin behavior.

The private wrapper registers an x86 unwind handler. If a native exception
unwinds past its scope, it clears active ownership and disables controller
picking rather than leaking the controller ray into later ordinary calls. It
continues native exception search, does not swallow faults, and leaves ownership
untouched during the search phase so an inner handler may recover normally.
Portable emulation covers registration restoration, native caller stack/registers,
candidate selectability, missing resources and search/unwind flags. An actual
Windows exception was not injected into the game as part of this gate.

A live original-engine gate at 1280x800 made 16 matched picks across both hands
on Gabriel and static room surfaces. Screen-reference and controller picks ran
in the same update, preventing character animation from creating false hit
disagreements. Hit positions differed by less than 0.001 game units. Two
translated controller origins still hit the intended surface. Two controller
rays outside the desktop viewport hit room geometry while ordinary screen
picking rejected the equivalent out-of-screen points. Disabled or failed scene
ownership also rejects stale output. The private picker always
received a deliberately invalid desktop placeholder, demonstrating that it did
not silently select via the panel or desktop projection. Focus/tracking loss
rejected picks, authored camera state remained unchanged, and the physical
desktop cursor did not move. The capture was inspected. Evidence and the bounded
private harness are ignored under `build/vr/world-pick-evidence/` and
`build/vr/world_gate.py`. Private game processes were closed and temporary
settings restored.

The fresh combined renderer candidate has SHA-256
`7c29cab3043753fd404818f9937e6f3ccaf90a2846c297f1ffacbe990ccf950e`.
Its 29 recorded native source hashes match the worktree. The reproducible build
passed native lifecycle/scene/input/panel gates, ordinary renderer checks and
actual GPU transport gates. The world compiler has 39 portable tests. Lint,
types and spelling pass, and the ordinary suite reports 2,666 passed, 20 skipped
and 402 deselected in 34.60 seconds. This candidate also repeated the paired
stereo/interface regression for Inventory, Back, Menu, held-action recovery and
native driving-map travel to the rendered TR1 destination. Temporary settings
were restored, the desktop pointer stayed unchanged and all private processes
closed afterward.

Controller Select is not yet connected from these world picks to the native
noun/action/menu transaction. Automatic world/UI/movie ownership, transparent UI
composition, navigation, text entry, calibrated scale, brightness, comfort,
sustained headset performance, full-game coverage and public installation/launch
remain incomplete. All poses/actions here are synthetic. No prototype was
installed into the user's game or published. The full VR goal remains active.

### Controller Select through native actions

The private world/input compilers now connect controller Select to GK3's native
noun/action/menu transaction. The input router prepares one completed-frame
ray before temporarily disabling another stereo draw during native synchronous
redraws. Native Room3D calls made in that input scope use the frozen ray. All
ordinary calls outside it still use their original screen picker. An invalid
world or frame-completion result rejects world selection instead of quietly
clicking the object behind a desktop coordinate.

The controller ray determines the object, while a centered native client point
determines menu placement. ActionMenu and toolbar children take panel priority
despite sharing the room's root layer. Crossing world/panel ownership retires a
held press outside controls and requires release. GK3's native hover producer
is refreshed explicitly for the controller ray because its ordinary update is
throttled on changed mouse pixels. No fake screen delta or host mouse movement
is used.

Live tests for each hand selected `R25CURTAINS`, opened its original action menu
and chose Look. The resulting camera is the game's scripted close-up of the
window/curtains, not a simulated menu result. Holding Select across focus or
tracking loss canceled it and did not open the menu when tracking recovered.
Captures were inspected. Evidence and bounded harnesses are ignored under
`build/vr/world-action-evidence/` and `build/vr/world_action_gate.py`.

The combined world/input bridge also passed the paired stereo regression:
Inventory, Back, centered/corner right-click toolbar, held-button recovery,
driving-map preservation on Back and actual travel to the rendered TR1 station
scene. It recorded 174 stereo pairs, 299 panels and 168 native callbacks. The
desktop cursor remained unchanged. Temporary settings were restored and all
private game processes closed. No native renderer changes were needed for this
step, so it uses the same verified renderer candidate recorded above.

The earlier statement that Select is not connected is superseded by this
section, not a claim that the whole mode is finished. Automatic world/UI/movie
ownership, transparent isolated UI, controller reticle, navigation, text entry,
calibrated scale, brightness, comfort, sustained headset performance, complete
game coverage and public installation/launch remain unfinished. Inputs remain
synthetic, and the installed Steam game was not modified.

The final-page input guard also retires a held panel press if shared-frame
completion fails, rather than interacting with an interface that was not
successfully submitted. The portable world/input tests cover this separately
from world-picking failure. Lint, types and spelling pass. The ordinary suite
passed 2,680 tests with 20 skips and 402 deselections in 33.80 seconds before
the additional shared-frame failure regression was added.

### Seated controller navigation through native camera methods

The private `VRNavigationCompiler` now links to the completed-input router.
It uses the original CameraManager float translation, yaw rotation and collision
commit, not keyboard events, mouse deltas, direct character writes or changes
to walker boundaries. Left stick has a radial dead zone and a maximum speed
of 0.8 metres/second, converted using the scene's world scale. Diagonal movement
does not increase that speed. Right stick turns by 30 degrees once and requires
both axes to return to neutral before another step.

Navigation runs only after successful room-owned input, with scoped world picking
already retired. Native camera commit may redraw; the outer input guard still
prevents another XR transaction during that redraw. The same CameraManager lock
checked by GK3's keyboard input disables navigation. Menus, failed frame completion,
lost ownership, focus/tracking loss and invalid axes retire movement. Both hands
independently require neutral on recovery. Elapsed milliseconds wrap safely,
are capped at 50 ms and do not accumulate across long stalls or ownership loss.
Head tracking and the keyboard hold ramp remain separate.

The ignored `build/vr/navigation_gate.py` verifies the actual native camera in
the private hotel-room game. Yaw changes by 0.523598790 radians for one right
snap and returns with the opposite step. Held turning does not repeat. Forward
movement and right strafe work, translation stops on neutral, and Inventory,
focus/tracking loss and the native camera lock stop movement without a recovery
jump. The gate records 133 stereo pairs, twelve native movement callbacks and
two snap turns. Host cursor position is unchanged, temporary settings restored
and the process closed. Evidence is under `build/vr/navigation-evidence/`.
The installed Steam game was not modified and no renderer rebuild was necessary.

Portable tests observe native method arguments, collision-commit ordering,
world scale, radial/diagonal speed, elapsed-time cadence, clock wrap, camera locks,
panel handoff, same-dispatch action-menu opening, invalid axes and release latching.
These verify camera integration, not physical-headset comfort or complete-game
script compatibility. Calibration, comfort transitions, head-lean wall masking,
automatic screen/media ownership, isolated UI, reticle, text entry, public
installation/launch, headset performance and full-game coverage remain unfinished.

Final verification for this increment: 2,712 ordinary tests passed, 20 skipped
and 402 deselected in 35.01 seconds. All four native XR CTest checks passed;
lint, types, spelling and whitespace checks passed. No commit, publication or
installation into the user's game was performed.

### Current-frame world reticle and interrupted native transactions

The current private renderer queries the selected controller's predicted ray
before either eye draws. It uses the original Room3D picker and requires a
finite hit on that segment. A small depth-tested ring is rendered at the same
world hit in each eye, with a small surface bias. It is not a desktop crosshair
or a marker based on the previous completed frame. Misses, lost tracking/focus
and visible native menus suppress world pointing. The completed diagnostic
target and action snapshot are published only after successful frame transport.

Actual GPU tests cover depth occlusion, stereo disparity, restored drawing state,
RGBA/BGRA runtime targets and 16-bit/32-bit game targets. A private hotel-room
gate picked `R25CURTAINS` and recorded 45 stereo pairs. The hit differs from its
same-update native reference by about 0.000077 game units. Both captured eyes
were inspected. Poses and controllers are synthetic; this is not headset UX
acceptance. Captures remain ignored under `build/vr/reticle-evidence/`.

The fresh renderer candidate for these tests has SHA-256
`574257f070e152867aba88829718aea5a1d98c4eac3375913a5bd5e082dc68d7`.
Its pinned build record identifies 29 native source inputs and the passed native
and GPU gates. The executable-adapter changes below do not change those renderer
inputs or publish a new DLL.

`VRInputCompiler` now protects the outer presentation/input/navigation transaction
with x86 exception registration. Native search leaves ownership intact so an
inner handler can recover. An escaping unwind disables linked VR components,
retires the controller ray and virtual pointer, and records any unfinished mouse
or key release. It calls no game methods from the handler. A later healthy
update releases buttons outside controls and delivers a pending native key-up.
Another fault, or a temporarily unavailable EngineLoop, retains that request.
Recovery requires neutral input before a fresh press. Actual Windows synthetic
tests cover seven input fault/recovery cases, including nested redraw and another
fault during deferred release. These tests do not inject faults into GK3.

`VRSceneCompiler` now independently guards each eye and the outer scene bridge.
Camera/projection snapshots are complete before ownership is marked, and the
ownership flag is set before the first camera write. Unwind restores the authored
camera, projection globals (including nesting), and room cache using owned memory
only. It invalidates world pointing, disables the scene and continues exception
search. Both nested registrations clean up idempotently, counting one aborted
transaction. Normal returns also reject and restore an eye whose native scene-end
routine was bypassed. Synchronous nested redraws retain the native draw path
without replacing saved state or starting another XR transaction.

Portable instruction-execution tests cover search/unwind flags, partial camera
copies, camera setup, clear/end failures, outer flat-draw failure, recursion,
nonvolatile registers and registration-chain restoration. A loader-mapped
synthetic PE additionally passed nine actual Windows cases: healthy rendering,
faults in setup/clear/end/flat/bridge, balanced inner recovery, recovered drawing
without native scene end, and an eye fault caught inside the synthetic renderer.
No process protections were disabled. These verify CPU-owned scene cleanup, not
arbitrary fault recovery of GK3, COM resources or an actual headset runtime.

After these changes, both hands again selected the curtains and reached the
original Look close-up. Native navigation recorded 132 stereo pairs, twelve
movement callbacks and two snap turns; Inventory, focus/tracking loss and the
native camera lock stopped movement. The host cursor remained unchanged,
temporary settings were restored and all private game processes closed.
The latest checks pass 299 focused VR tests and 2,798 ordinary tests, with
20 skips and 402 deselections in 49.51 seconds. Lint, types, spelling and whitespace
checks pass. The verified candidate also passes all four native XR CTest gates
and both actual-GPU RGBA/BGRA transport controls; its 29 native source hashes
and the private game's DLL still match the build record. Native fixtures and
private experiment output remain under ignored
`build/vr/`; portable regression tests live in `tests/unit/patch/`.

The full goal remains active. Automatic world/UI/movie ownership, isolated
transparent interfaces, save-name entry, calibrated world scale, head-lean wall
masking, comfort transitions, actual-headset readability/brightness/performance,
complete-game coverage, public installation/launch and Proton OpenXR qualification
remain unfinished. A hit ring is implemented, but complete pointing/laser UX is
not yet accepted. No prototype was installed into the user's Steam game,
committed, published or presented as a playable VR release.

### Depth-tested controller aiming beam

World pointing now includes a thin cyan aiming beam, independently projected
for each eye, ending at the same native hit as the orange ring. The native query
distinguishes an eligible world miss from unavailable ownership. A miss shows
a 1.5-metre beam but publishes no hit or selectable target. Native menus,
tracking/focus loss and unavailable world ownership suppress both visuals.
Neither visual changes action picking or moves the desktop cursor.

The beam begins 3 cm from the controller, clips against all six native eye
frustum planes, retains per-endpoint depth and reciprocal W, and uses scoped
alpha blending without writing depth. Width is physically scaled with bounded
pixel coverage for readability. Math tests exercise binocular projection,
near-plane crossings, behind/offscreen segments, short segments, bad scale and
off-ray hits. The actual GPU gate verifies that foreground geometry hides the
occluded portion of a beam, while a miss still gives feedback and tracking or
ownership loss removes it. It also checks native blend/state restoration.

A first candidate exposed a faulty pixel-count test: a translucent cyan beam
over a warm background did not meet its RGB threshold, and foreground depth
should hide only the beam portion behind it, not its nearer portion. Those
assertions were corrected using the known fixture background and actual depth
ordering. A fresh recipe build with the finalized tests passes all native
renderer checks, all four XR CTest gates and RGBA/BGRA GPU transport. Its DLL is
`6d64bdd6a930c50374f16686bd30cc733712d15a9944aeca40145537d945b50a`.
All 29 recorded native source hashes independently match the current worktree,
and the private game uses that exact candidate.

The bounded private-game experiment captures a controller 25 cm to the side
and 20 cm below/in front of the viewer. Both eye images visibly contain the
beam and native hit ring. Both hands reproduce the reference curtains pick,
with a hit error of 0.000046565 game units. Tracking/focus loss retires the target.
The experiment recorded 46 stereo pairs and closed the private game. Separate
both-hand action and navigation regressions pass, including Inventory and native
camera locks, neutral recovery, twelve movement callbacks and two snap turns.
Navigation recorded 132 stereo pairs; temporary display/settings were restored.
Evidence remains under ignored `build/vr/beam-evidence/`.

All 301 focused VR instruction tests and 2,800 ordinary tests pass. The ordinary
suite takes 50.53 seconds with 20 skips and 402 deselections. Lint, strict types,
spelling and whitespace checks pass. The nine actual Windows scene exception
cases were rerun successfully. No live test ran against the installed Steam
game, and no changes were committed or published.

This completes the private world-beam increment, not the full VR goal. Automatic
screen/media ownership, isolated transparent interfaces, panel pointing UX,
save-name entry, calibrated scale, head-lean wall masking, comfort transitions,
actual-headset acceptance, full-game coverage, public install/launch and Proton
OpenXR qualification remain unfinished. Controller poses remain synthetic.

### Automatic room/interface ownership and world-only input completion

A dormant native classifier is now linked into the scene and completed-page
producers. It reads the original current layer, bounded child graph, room owner
and camera manager. A free room selects stereo only; a visible native action
menu/toolbar selects stereo plus the interface panel; modal/unknown layers,
missing room/camera state or the original camera input lock select the panel
only. It never rewrites native camera locks or scene/interface master switches.
Disabled classification selects no XR layers. Its diagnostics describe the
classification, not proof that an XR runtime has displayed a frame.

World-only completion was added to the native renderer bridge. It exports the
completed world's predicted controller snapshot without copying the desktop
into a quad, beginning another frame or advancing action edge detection again.
An empty completion clears output and cannot resurrect earlier input. It keeps
the selected/fallback hand and shortcuts but does not invent a panel hit.
The actual GPU gate verifies one predicted frame, identical world/finalizer
input, one projection layer, no quad capture, and no extra frame after completion.

Ownership changes also retire previous world rays and target diagnostics before
interface input can consume them. This happens in the classifier even when a
modal update never calls Room3D::Draw, and in the scene gate before any suppressed
draw. Frame submission and native input remain in their existing render-thread
transaction; no Python callback enters the frame loop.

The full fresh renderer recipe passes with these changes, including the four
native XR CTest gates and actual RTX GPU transport in RGBA/BGRA configurations.
Its private candidate hash is
`d6c04b0e9c441e6337721edaa842d2aa3a8dd4093a6ef1f10a28c109dd8f0531`.
An initial GPU failure exposed the legacy export's operation-range check, which
was corrected to accept the new world-only operation without uploading a panel.
The finalized candidate was built from a fresh pinned source/toolchain recipe.

The private-game ownership gate records nine successful states/transitions:
initial rooms, Inventory, return from Inventory, room context menu, return from
the menu, driving map and SIDNEY home. Stereo advances only when the classifier
allows world ownership. Free rooms expose zero quad dimensions; interfaces
expose their current native-resolution canvas and focused controller input.
Both-hand Select/native Look actions pass with automatic classification, and
navigation retains neutral recovery and stops for Inventory, focus/tracking
loss and native camera locks. A finalized-candidate navigation run records 128
stereo pairs, twelve movement callbacks and two snap turns. The SIDNEY desktop
capture was inspected. All captures/output stay under ignored
`build/vr/ownership-evidence/`; all launched copies are private games.

There are 31 new portable ownership tests, covering supported normalized builds,
dependency rejection, dormant behavior, room/menu/modal classification, camera
locks, bounded child graphs, producer gates, unchanged native state and stale
world-output retirement. All 332 focused VR tests pass. The ordinary suite
passes 2,831 tests with 20 skips and 402 deselections, and lint/strict types pass.
The nine actual Windows scene exception cases and seven input exception cases
also pass after the linked ABI changes. No process protections were weakened.

This is still incomplete VR. Free-room HUD/captions need transparent isolation;
room menus still show the opaque completed page rather than an isolated overlay.
Movie/scripted-camera coverage, panel pointing UX, save-name entry, calibrated
scale, wall masking, comfort transitions, real-headset acceptance, full-game
coverage, public installation/launch and Proton OpenXR remain open. No installed
Steam game was modified, and no prototype was committed or published.

### Transparent dialogue captions, wrapping and stacking

The native renderer accepts the caption producer's explicitly keyed RGB565
system-memory surface, not a desktop crop or eye readback. It converts that
isolated generation to a premultiplied transparent quad and completes the same
deferred world frame. Black outlines remain opaque, empty pixels transparent,
and controller pointing continues to belong to the world. Clearing captions
returns to world-only presentation. Inventory and its return transition retain
their separate opaque-panel/world ownership.

Live testing exposed three engine-side defects. Shared glyph transfers were
not publishing their final physical bounds; the recorder now follows the final
transform and excludes cursor/save-under traffic. Native wrapping measured
physical caption width against authored font metrics; initial layout now uses
inverse-scaled width, preserving the box centre and moving every native line
origin alongside it. Stacked captions used authored spacing between independently
scaled bottom anchors; all now scale about the framebuffer bottom, keeping the
original spacing proportional to glyph size.

The private candidate with SHA-256
`1c021e470707654edd67df359c7434e2fc487e107dc22e7767297ca26bfef5f9`
passes the complete renderer recipe, four native XR CTest gates and RGBA/BGRA
GPU transport, including device/session recreation. Long-caption and stacking
tests pass at 1024x768, 1280x800 and 3840x2160. Final 4K long dialogue fits in
three lines within `[516, 2017, 3324, 2160]`; three short captions have separate
opaque bands `[2025, 2064)`, `[2073, 2112)`, `[2121, 2160)`. Captures and run
records remain in ignored `build/vr/caption-evidence-*` directories.

Eighty portable instruction tests cover caption ownership, cursor exclusion,
final geometry, three stack offsets, native layout, large intermediate products,
unchanged native line breaks, and register/stack/state restoration. The ordinary
suite passes 2,924 tests with 20 skips and 402 deselections in 35.65 seconds.
The live tests closed their private games and restored temporary settings.
No installed game was changed and no prototype was committed or published.

This does not finish transparent room menus/status/tooltips, media ownership,
save-name entry, comfort, physical scale calibration, headset acceptance,
full-game coverage, public installation/launch or Proton OpenXR qualification.

### Accepted native brightness in XR eyes and panels

The XR transfer previously bypassed the application's accepted DirectDraw gamma
ramp. A new actual-GPU regression first failed against the previous candidate:
the requested correction expected red 163 at its mid-tone sample, but XR still
submitted 132. The renderer now uses its existing desktop swapchain blitter for
non-identity ramps. This preserves the game's corrected neutral default and
native brightness control rather than introducing a separate VR brightness knob.
Identity ramps keep the GPU-copy fast path. Correction occurs once in UNORM
before the compatible sRGB copy, without source readback or a normal-path
GPU-idle wait.

The first implementation passed eye and opaque-panel correction but failed the
transparent-caption regression. Its shader flag had been assigned specialization
ID 2, which belongs to DXVK's resource-bound range, while pipeline constant index
2 maps to ID 1227. With the correct ID, alpha-aware gamma leaves every transparent
pixel zero RGB/alpha, even when a submitted ramp raises the black point. Opaque
black outlines remain actual visible black and receive the accepted correction.
The specialization value is reset after each draw so ordinary presentation does
not inherit the caption mode.

The final fresh pinned-source candidate has SHA-256
`146130286a88c5b224116c96df7ac3647e150e76a937ee4e7b00082f4b993b89`.
Its complete build passes ordinary renderer checks, all four XR CTest gates,
device/session recreation and GPU transport in RGBA/BGRA runtime formats with
RGB565/32-bit game sources. Brightness tests check both eyes, opaque panels,
caption coverage and black/mid-tone pixels, and exact whole-image restoration
when the ramp returns to neutral. All 30 recorded native source hashes match
the current files independently of the recipe's own assertions.

Two bounded private-game runs at 1280x800 verify native gamma 1 and `SetGamma(2)`
with the final candidate. The submitted world RGB means change from approximately
`[73.37, 64.54, 51.51]` to `[130.00, 122.53, 103.61]`. Three stacked native captions
have identical alpha coverage and separate bands `[750, 764)`, `[768, 782)` and
`[786, 800)` in both runs; gray glyph pixels brighten while black outlines and
transparent holes remain correct. Clearing captions, opening Inventory and
returning to the room preserve world/panel ownership. This is submitted-pixel
evidence using synthetic tracking, not headset brightness calibration.
Captures remain under ignored `build/vr/caption-evidence-1280x800-brightness-accepted-*`.

The ordinary suite passes 2,924 tests, with 20 skips and 402 deselections in
43.36 seconds. Formatting, lint, strict types, spelling and whitespace checks
pass. Both private games closed and temporary settings were restored. A stray
development log was moved from the repository root into ignored `build/vr/`.
No installed Steam game, commit, release or persistent XR registration changed.

The full goal remains incomplete. Non-binary HUD transparency, isolated room
menus/status/tooltips, media/scripted-camera ownership, save-name entry, physical
scale calibration, head-lean wall masking, comfort transitions, physical-headset
readability/color/performance acceptance, full-game coverage, public installation
and launch, and Proton OpenXR qualification still need implementation or testing.

### Bounded composition of isolated interface sources

The private renderer bridge now accepts an ordered batch of up to 16 isolated
RGB565 system-memory surfaces. Each piece has a local source crop, a physical
canvas destination and an explicit keyed-or-opaque contract. This allows a future
menu/tooltip producer to share one transparent quad with captions without
copying the scenery underneath. Keyed holes preserve earlier pieces, opaque
black is never treated as a hole, and destination clipping keeps the source
origin and scale unchanged. Canvas allocation is bounded to 64 MiB, and source
span arithmetic is checked before reading.

The bridge rejects completed pages, render targets and video-memory sources.
Every source is unlocked before the GPU upload. A malformed later piece cancels
the pending frame instead of submitting partially composed content or leaving
an image acquired. Display-only composition retains the already sampled world
input and does not manufacture panel pointer hits. Removing it still returns to
world-only rendering; opaque modal panels retain their normal interaction.

The fresh pinned-source candidate is
`build/vr/recipe-overlay-parts-accepted-20261010/`, with DLL SHA-256
`bd2b78e783de9c02ffd49d571a0a8b8a07ff00b445e69b6ad49b3792199a4ed7`.
All four native XR CTest gates and ordinary renderer tests pass. GPU transport
checks exact submitted RGBA/BGRA pixels for local crops, overlapping layers,
key holes, black, clipping and differently shaped canvases. It also checks
maximum part count, atomic failure, source unlocks, recovery, world-eye
preservation and device/session recreation with 16-bit and 32-bit game targets.
A negative control using the previous accepted renderer fails specifically at
the new composition gate. All 30 recorded native source hashes independently
match the current files.

The existing native caption producer now uses the shared compositor internally.
Two private-game checks pass with this exact candidate: three captions at
1280x800 with native gamma 2, and three at 3840x2160 with neutral gamma. Their
opaque bands remain separate at `[750, 764)`, `[768, 782)`, `[786, 800)` and
`[2025, 2064)`, `[2073, 2112)`, `[2121, 2160)` respectively. Every transparent
pixel has zero RGB, black glyph outlines remain visible, captions clear, and
Inventory/room transitions preserve ownership. Both games closed normally and
temporary settings were restored. Evidence is ignored under
`build/vr/caption-evidence-*-overlay-parts-accepted-*`.

The ordinary Python suite passes 2,924 tests, with 20 skips and 402 deselections
in 44.37 seconds. This is a transport foundation, not completed transparent
room UI. At that stage tooltip caches copied their final pixels back from the
flat page and could not enter this path unchanged. Tooltips needed an independent
producer, menus needed isolated drawing and coverage-aware interaction, and room
status needs proper non-binary alpha handling. Full-canvas allocation/upload
also remains a VR performance qualification item. The larger unfinished
requirements above remain open. No installed game, public release or persistent
XR registration changed, and nothing was committed or pushed.

### Independent native tooltip composition

Scaled tooltip generations now draw their native glyphs directly into their
own RGB565 system-memory cache. The final tooltip affine first maps the native
glyph to physical coordinates, then subtracts the cache's physical origin. Each
glyph transfer receives a private copy of the raw destination wrapper, with the
cache's COM surface and dimensions. Neither the live game page wrapper nor
caller-owned destination/source rectangles are mutated. Disassembly confirmed
that this wrapper embeds a Windows critical section. The private render-thread
copy explicitly disables that lock rather than trying to use a copied mutex;
the original source's native locking remains unchanged.

The previous reverse page-to-cache `BltFast` was removed. The completion pass
now submits only cache-to-page pixels, publishing readiness after a successful
transfer. Existing generation identity, hover timing, replay, dismissal and
destructor ownership are retained. Missing cache surfaces leave glyph transfers
on their native physical destination and keep composition pending for retry.
The new code and private wrapper occupy declared, non-overlapping payload ranges
checked by complete public-plan compilation for both supported executables.

Bounded private-game runs compare two hover labels with the previous compiled
game at 1280x800 and 3840x2160. All four completed tooltip crops match exactly,
pixel-for-pixel and at the same physical bounds. Both generations replay and
clear on menu dismissal. Their descriptors change from ordinary off-screen
caps `0x40` to explicit system-memory caps `0x840`. The 4K Configuration options
crop was also visually inspected. Captures and logs remain ignored under
`build/vr/tooltip-isolation-*`; both games close normally and temporary settings
are restored. The accepted native renderer remains unchanged.

Portable instruction tests cover three resolutions, three physical origins,
composition/replay/completion scopes and present/missing cache surfaces. They
verify native register/stack effects, the unchanged live wrapper and source
rectangles, local origin/extent mapping, absence of a borrowed critical section
and native fallback. There are 54 passing cases. Scaled tooltips now have an
independent source suitable for the XR compositor, but are not yet submitted
as transparent room UI. Reference-height VR needs explicit producer activation,
and menus still need isolated rendering with coverage-aware pointer ownership.
Status alpha, media/camera ownership, keyboard entry, physical scale and comfort,
headset acceptance, full-game coverage and public installation/Proton support
remain unfinished. No installed game, commit, release or persistent runtime
registration changed.

The final ordinary suite passes 2,978 tests, with 20 skips and 402 deselections
in 35.44 seconds; formatting, lint, strict types, spelling and whitespace checks
pass. A further private VR regression with native gamma 2 passes three isolated
captions, clearing, Inventory and room return after the tooltip changes. Caption
coverage stays at 1,150 pixels with the same three glyph bands as before. No game
process remains running.

### Current-frame tooltip submission and reference-height isolation

The native tooltip producer now publishes a versioned cache ABI with its live
surface, local source crop, physical destination, visibility/pending state,
successful replay counter and explicit isolation ownership. Installation checks
the descriptor header and CPU-memory caps. Pixel format is established at runtime
and validated by the renderer, not guessed from an unstarted descriptor.

The pre-Flip presenter starts each transfer with a failed result and advances the
publication counter only after a successful completed transfer. Hidden or invalid
objects, ConfirmQuit, failed/skipped transfers and incomplete composition cannot
make old pixels appear current. Counter comparisons tolerate wraparound.

The paired VR presenter sets isolation ownership before calling the original UI
presenter. Both its world and panel controls must be enabled. Disable, renderer
unavailability and closure release the flag. A small shared predicate selects
the compositor for HD, full-map or explicit XR ownership, preserving flat
reference-height native ownership by default. This avoids enlarging tightly
bounded decoration thunks and keeps their original registers intact.

World-owned frames append current captions first and current tooltips second to
one overlay batch. Captions retain their explicit colour key; tooltip chrome is
opaque. Every frame clears the batch count and alpha flag before choosing its
owner. Stale, hidden, missing or pending sources are omitted. Modal and ordinary
room-menu ownership continue to use the opaque panel rather than silently losing
native controls. Overlay submission retains world input and cannot create a
panel pointer hit.

Private-game GPU controls pass tooltip-only at 1024x768 and 1280x800 and combined
caption/tooltip at 1280x800. Each submitted tooltip crop matches its native
desktop pixels exactly, including alpha covering its complete rectangular panel.
The reference-height Configuration options rectangle is `[572,415,685,435)`.
Changing hover replaces it with `[532,415,559,435)`. At 1280x800 the corresponding
rectangles are `[702,432,820,453)` and `[661,432,690,453)`. Captions and tooltips
contribute 2,825 covered pixels together, versus 2,478 for the tooltip alone.
Every pixel outside their explicit source footprints stays transparent black.
Hover changes and dismissal remove stale parts, and clearing captions returns
to a world-only frame.

These gates use an explicitly documented private panel-ownership override after
or before native hover creation as needed. They do not alter scene classification
or claim that the omitted room menu is isolated or interactive. Synthetic poses
drive actual Vulkan rendering, not a physical headset. The renderer binary is
unchanged from the accepted overlay-parts candidate. Captures and records remain
ignored under `build/vr/tooltip-overlay-*`. A fresh 4K flat control also matches
both previous tooltip crops exactly and verifies publication stops on dismissal.

Portable tests execute producer success/failure/skip/withdrawal, counter wrap,
isolation enable/disable and renderer absence, plus caption/tooltip batching,
modal ownership and fresh/stale/missing/pending combinations. Formatting, lint,
strict types and spelling pass. Reference-height tooltip isolation and batch
transport are now verified foundations, not complete playable VR. Isolated menus
and coverage-aware picking, status fades, movie/scripted-camera ownership, text
entry, physical scale/comfort, real-headset acceptance, full-game coverage and
public installation/Proton qualification remain unfinished. No installed game,
release, persistent XR registration, commit or push is changed.

The final ordinary suite passes 3,102 tests with 20 skips and 402 deselections
in 36.48 seconds. All lint tasks and whitespace checks pass. Each bounded private
game closes normally; no GK3 process remains running. The next integration
boundary is isolated room-menu composition and coverage-aware controller picking,
without replacing the world by an opaque completed desktop page.

### Explicit interactive overlay coverage

The renderer now accepts `OverlayInteractive` on an explicitly isolated source
part. Its binary picking coverage follows the same local crop, physical pixel
placement, screen clipping and producer-owned colour key as its displayed
pixels. Non-keyed black stays visible and hittable. A keyed hole retains the
preceding part's image and interaction; an opaque noninteractive label occludes
an underlying control without capturing input itself. Caption/tooltip sources
remain noninteractive by default. No colour heuristic promotes labels to menus.

Coverage is built afresh with each current batch, and allocated only when an
interactive part contributes to the canvas. `PanelState` validates the image,
coverage and requested canvas together before changing its anchor. Rays map
through the submitted upright panel geometry, then use half-open native pixel
bounds and the current mask. Misses clear old coordinates, focus/tracking loss
clears selection, and hand fallback retains its original rules. Shortcuts and
the completed world's action snapshot remain available without another runtime
sample. Ordinary opaque modal panels retain their existing pointing behavior.

Native tests pass both hands at 1024x768, 1280x800 and 3840x2160, with controls
near all edges and the center, including transparent neighbours, black pixels,
pitch padding, cropping, negative clipping, overlap, focus loss, hand fallback,
mask withdrawal and invalid canvases. Actual renderer GPU tests pass covered
versus uncovered source pixels, keyed holes over earlier controls, noninteractive
opaque labels, current-input identity and one completed XR transaction. The
initial GPU run exposed a fixture activating a new hand with Select already
held. The existing release-before-rearm safeguard correctly suppressed it.
The corrected fixture releases first; no production input safeguard was weakened.

A fresh full recipe passes all native lifecycle/scene/input/panel checks, flat
surface/helper regressions and GPU XR transports in both RGBA/BGRA formats,
including brightness and device recreation. The accepted private candidate is
`build/vr/recipe-menu-coverage-accepted-20261010/` with SHA-256
`791b2cea785fe8b427695c5dc816b6b57522e21df03dcecbbf9da74f13ac7657`.
Native producer regressions using this candidate pass tooltip-only at 1024x768
and tooltip-only/caption-plus-tooltip at 1280x800, with zero RGB difference from
their desktop crops. The gates still explicitly override only panel ownership
and do not claim native room-menu capture or interactive game acceptance. Their
evidence stays ignored in `build/vr/tooltip-overlay-*-menu-coverage-regression/`.

The ordinary suite passes 3,102 tests with 20 skips and 402 deselections in
59.04 seconds while the renderer build was running. Lint and strict types pass.
No installed game, release, persistent XR registration, commit or push changed.
All private games closed normally. This completes the renderer-side coverage
prerequisite, not playable VR. Next is capturing the actual ActionMenu and
toolbar producers, including the native compositor path which does not always
use the shared final blitter, and connecting their current-frame publications
to this coverage-aware composition. Status fades, media/camera handling, text
entry, comfort/scale, real-headset acceptance, whole-game coverage and public
installation/Proton qualification remain unfinished.

### Native menu destination scope

Read-only native traversal inspection and a bounded private-game probe establish
that concrete ActionMenu/toolbar Draw receives an encoded destination bitmap
handle. Its resolved resource owns a full-canvas surface wrapper. Native children,
including the software compositor path, use that explicit resource destination.
This avoids intercepting unrelated room drawing or copying a rectangle of the
completed page.

`vr_menu.py` now supplies a disabled-by-default destination-scope primitive.
The ordinary native traversal remains intact. An explicitly enabled, visible,
concrete menu may additionally traverse into the caller's independently owned
CPU cache. The scope requires the current DirectDraw owner, matching canvas
dimensions, readable resource state and the actual current back-page identity.
It rejects a cache aliasing that back page. During the extra traversal only,
the resolved bitmap resource points to a private wrapper. Its copied lock is
marked uninitialized rather than borrowing a live critical section. The original
resource binding, return value, stack, nonvolatile registers and flags are
restored before returning. A busy guard prevents another scoped capture during
recursive native drawing.

The scope records a completed traversal counter and a native-derived physical
RECT. ActionMenu already publishes physical geometry. The room toolbar uses its
existing signed, height-relative affine about the authored 252x75 base centre,
including expanded panels. No pixel-colour heuristic determines its bounds.
The counter means the native call returned, not that every individual child
blit succeeded or that an XR frame was submitted.

The private gate now uses this exact package helper. At 1024x768, 1280x800 and
3840x2160, the basic toolbar, Graphics options, Advanced graphics options and
inventory ActionMenu icons match their settled normal desktop pixels within one
RGB level. Every tested footprint is a fully opaque rectangle and its native
geometry equals the independently observed raster bounds. Pointer movement
first settles both native pages, avoiding comparison against a stale highlighted
button. The basic toolbar also matches near all four screen corners at Deck and
4K canvas sizes. Its 1280x800 corner bounds include `[2,2,264,79)` and
`[1016,721,1278,798)`; 4K includes `[6,5,714,215)` and
`[3126,1944,3834,2154)`. The destination binding is explicitly checked after
each capture. Diagnostic magenta is only a clean-source test sentinel, not a
shipping transparency convention or a colour-derived interaction mask.

All captures, diagnostic allocation/COM calls and process controls remain ignored
under `build/vr/menu-destination-probe-*`. The native gate uses the accepted
menu-coverage renderer's ordinary flat Vulkan path with XR disabled. This
qualifies the original producer and destination scope, not stereoscopic menu
interaction or actual-headset play. It deliberately performs an extra traversal
and is not a VR menu performance benchmark. The installed game is untouched and
each private process is closed by the gate.

Portable instruction tests cover native/cached calls, positive/negative geometry,
all three canvas sizes, disabled/unknown/busy modes, hidden/foreign roots,
missing/stale/aliased caches, resource lifetime guards, return-state restoration
and counter wrap. The initial 36-test addition and the full ordinary suite pass
with 3,138 tests, 20 skips and 402 deselections in 37.11 seconds. The additional
counter-wrap and flags checks bring the dedicated scope suite to 37 passing
tests. Formatting, lint, strict types and spelling pass.

Next is owning reusable CPU cache creation/release and current-frame publication,
qualifying sibling resolution dropdowns and failure/withdrawal, and joining the
native parts to the already coverage-aware shared XR batch. Room-menu ownership
continues to use the existing opaque page fallback until those pieces are
verified together. Non-binary status fades, media/camera handling, keyboard text
entry, scale/comfort, real-headset acceptance, whole-game coverage and public
installation/Proton qualification remain unfinished. No commit, push, release,
installed game or persistent XR registration changed.

### Native menu cache lifetime and qualified readiness

The destination scope now optionally calls package-owned cache preparation.
Preparation creates an explicit RGB565 system-memory surface, bounded to
8192 pixels per axis and 16 million pixels total. It validates source/cache
descriptors, dimensions, format/masks and CPU-memory caps. A current matching
DirectDraw owner and extent reuse the buffer; changes release it before
replacement. Every capture starts with a successful clean black fill. Black
inside the previously qualified menu RECT is opaque content, not a key.
Preparation failure cannot retain old pixels as a valid menu. A release helper
clears ownership before calling COM and refuses release during a scoped draw,
including a tested reentrant release.

Optional result thunks temporarily replace only the owned CPU object's Surface1
table during native traversal. The original table and bitmap destination are
restored on normal return. Both Blt and BltFast retain their original arguments,
return results and flags. Any non-DD_OK child result, or no child transfers,
prevents readiness. A completed traversal counter is still diagnostic; a
separate publication counter advances only for qualified draws. Readiness
records the native successful-Flip generation rather than assuming Draw and
the pre-Flip callback have the same order as caption/tooltip production.

Before consumption, a validator checks enabled/busy state, current DirectDraw
owner, physical canvas, readable concrete root, visibility and page generation.
Stale pages withdraw readiness while retaining a reusable buffer. Hidden,
missing/foreign roots or changed owner/extent release it. An exact-root
destructor withdraws before tail-entering the existing runtime destructor.
Destruction of an older menu cannot release a newer root's publication.

The ignored private-game gate binds these package helpers to the actual menu
draw/destructor slots and chains a validation callback after the existing
pre-Flip presenter. Captures remain explicitly requested diagnostics, not an
automatic VR capture/install path. Tests at 1024x768, 1280x800 and 3840x2160
cover basic/expanded toolbars, all four screen corners and settled inventory
ActionMenu icons. Current captures retain the prior one-level maximum RGB
agreement, without room pixels outside the menu RECT. Replay does not allocate
a second surface; closing the initial toolbar withdraws readiness and releases
it. Native child calls succeed, and both destination bindings are restored.
No private wrapper allocates/borrows an inline critical section in these cases.
Evidence is ignored under `build/vr/menu-cache-probe-*`.

The dedicated scope/lifecycle suite has 95 passing instruction tests, including
format/caps failures, create/describe/fill recovery, owner/extent replacement,
stale page generations, hidden/foreign roots, exact-owner destruction, busy
guards, counter wrap and normal register/flag restoration. These are scoped
emulation/private flat Vulkan tests, not headset or controller acceptance.
The full ordinary suite passes with 3,197 tests, 20 skips and 402 deselections
in 39.08 seconds. All four existing native XR CTest checks pass in 0.09 seconds;
formatting, lint, strict types, spelling and whitespace checks pass too.

Next is a verified compiler/cache ABI and joining these qualified sources to
the existing interactive XR batch. Resolution-dropdown qualification, scoped
actual same-frame controller picking remain open. Native-exception cleanup is
qualified separately below.
The normal ownership path still uses the opaque room-menu panel fallback.
Non-binary HUD fades, media/scripted-camera handling, text entry, scale/comfort,
actual-headset acceptance, full-game coverage and public installation/Proton
qualification remain unfinished. No renderer binary source changed during this
increment, and the installed game remains untouched.

### Menu destination cleanup during native exceptions

The destination scope can now register a bounded x86 SEH termination handler
around only the isolated second traversal. The original native draw still runs
outside this registration. Normal completion restores the previous exception
chain and clears its active registration. First-pass dispatch continues the
search without changing the destination: a caller can resume a continuable
exception and complete drawing normally. Only actual unwind through the exact
active registration restores the bitmap destination and private COM table,
clears busy/readiness and root ownership, and marks the capture unsuccessful.
It never swallows the original exception or edits its context. Cleanup makes no
COM calls or allocations; ordinary validation performs any deferred release.
Duplicate or delayed unwind cannot clean up a later scope's registration.

The dedicated instruction suite now has 122 passing tests, including normal
chain restoration, first-pass dispatch, unwind variants, duplicate/delayed
cleanup and skipped capture. Instruction emulation does not emulate the OS
dispatcher, so an additional ignored x86 MSVC harness executes the actual
package-emitted bytes inside Windows structured exception handling. All five
cases pass: normal return, a noncontinuable software exception, a continuable
exception resumed by an outer filter, an actual access violation, and a native
C++ throw. Aborted cases restore both bindings and withdraw publication;
normal/resumed cases retain qualified pixels. Evidence/source remain under
`build/vr/menu_unwind_native.*`. The harness uses the game's absence of a SafeSEH
table; a future compiler must reject incompatible metadata or register the new
handler correctly, never disable process/system protection as a workaround.

With this handler bound, the private game again passes all ten menu captures at
1280x800, including expanded graphics menus, all screen corners, inventory
ActionMenu, reuse and closure. Maximum RGB difference remains one level and
there are no differences above it. This live gate checks normal game behavior;
exception injection is confined to the independent harness, not the game.
The full regression suite passes with 3,224 tests, 20 skips and 402 deselections
in 40.07 seconds; formatting, lint, strict types, spelling and whitespace
checks pass too.
The native menu compiler/cache ABI, automatic interactive XR integration,
resolution dropdowns and controller interaction are still unfinished. No
renderer binary, installed game or persistent XR registration changed.

### Automatic interactive native menus over the stereo world

`VRMenuCompiler` now exports a private typed cache/query ABI and installs dormant
ActionMenu/toolbar capture and destructor hooks. Before any write, it rebuilds
and verifies the complete original Runtime2D payloads and owned redirects in a
clone with only the menu/presenter bindings restored. Modified native helper
bytes or bindings are rejected. The compiler requires the verified deferred
world boundary, the supported x86 executable and compatible exception metadata.
It rejects NO_SEH or nonempty load-config metadata rather than erasing protection.
Postchecks rebuild every dormant byte and verify the new bindings too. This is
still a private compiler, absent from the public patch catalog and player CLI.

Capture is automatic on ordinary native menu draws, not a requested diagnostic
replay. The pre-Flip query validates both caches and walks the concrete room's
bounded, readable child array. It appends visible native menu roots in their
original ordering, and refuses duplicate classes, foreign roots, stale pages,
unreadable children or unqualified resolution dropdowns. Any late failure rolls
back the entire appended batch. Current physical cache dimensions, rather than
the previous XR frame's canvas, bound clipping. Each source crop and destination
share exactly the same clipped origin. No texture/color heuristic determines
coverage: the independently qualified native menu RECT is opaque, including its
black pixels. Cache ownership also follows the live XR enable switches before
validation, so disabling menus or the world releases allocations without needing
another native draw from a hidden root.

The private panel compiler queries these sources after ordinary UI composition
and can now submit interactive menus, then display-only captions and tooltips,
over the stereo world using the normal native ownership classifier. No ownership
override is needed. An incomplete menu batch retains the existing opaque room
panel for that frame, with no partial overlay parts. Modal interfaces keep their
opaque page panel. An empty room remains world-only. The renderer's existing
coverage shader and input adapter consume the exact published menu pixels and
physical coordinate system; no new renderer binary was required in this step.

The new compiler/composition suite passes 49 instruction tests, including
no-write dependency failures, full payload verification, native ordering,
atomic rollback, clipping, label ordering and actual emitted cache release after
either enable switch is disabled. The full default suite passes 3,273 tests,
with 20 skips and 402 deselections in 38.92 seconds. Before the two final release
checks were added, the complete slow-inclusive suite passed 3,673 tests with
20 skips in 199.03 seconds. All four native XR CTest checks pass in 0.09 seconds;
formatting, lint, strict types and spelling pass.

Ignored actual-GPU private-game gates now verify:

- Initial toolbar XR pixels match the native desktop exactly at 1024x768,
  1280x800 and 3840x2160. Alpha is 255 throughout its qualified RECT and zero
  outside it, with no room pixels copied into the isolated source.
- Controller pointing reaches native physical coordinates within one pixel.
  Settings, display, graphics and advanced graphics sections open via simulated
  Select press/release at all three canvas sizes. The native cache is reused
  across ordinary redraws; closure withdraws readiness and releases it.
- Toolbar pointing works near both sides and the center of menus at
  all four screen corners. Controller Back closes each menu and removes its
  source and hit coverage at all three canvas sizes. The desktop mouse is not
  moved by controller input.
- Both simulated hands select `R25CURTAINS` through the original world picker,
  hover its isolated ActionMenu, and invoke a native action. World input pauses
  while the menu owns pointing, then resumes after its source is withdrawn.
- Disabling menu capture while a menu is visible releases its cache, keeps the
  opaque fallback and allows fresh isolated publication after re-enabling at
  all three canvas sizes. Opening the resolution list at each size also selects
  the opaque fallback with an empty overlay batch, rather than partial menus.

Evidence and scripted gates remain ignored under `build/vr/menu-overlay-*` and
`build/vr/world-action-menu-*`. The candidate is still the accepted GPU menu
coverage recipe, with synthetic tracked poses and small test-runtime eye images.
These are not headset acceptance or a production VR performance benchmark.
Only the private game was run and closed; the installed Steam game, persistent
XR runtime registration, release assets and Git history were not changed.

Next is independent resolution-dropdown qualification and the remaining HUD/UI
producers, including non-binary fades and usable text entry. Media/scripted
camera comfort, scale/recentering/head-lean masking, actual physical headset
and controller acceptance, full-game coverage, public install/launch and Proton
OpenXR qualification remain unfinished. The goal is not complete or ready for
the user to put on a headset.

### Resolution-list coverage qualification

The first private resolution-list capture deliberately failed the old single-
rectangle fidelity gate. The list is a sibling deferred until after the toolbar;
the flat runtime expands the toolbar's bounds to retain its complete lifetime.
That union bounding rectangle contains room-visible gaps beside the lower list.
Treating the whole rectangle as opaque would cover those gaps with the cache's
black clear, even though every native transfer succeeded. This is a coverage
shape issue, not missing dropdown pixels or a Vulkan color/alpha conversion.
The automatic XR query rejects this lifetime, so the current build uses its
opaque-page fallback instead of submitting that incorrect isolated footprint.

A follow-up private gate reads the retained pre-union toolbar bottom and the
live concrete popup rectangle. It transforms both through the same toolbar
affine about its original 252x75 base center, with native signed truncation,
then clips to the current physical canvas. Under that two-rectangle union the
existing isolated cache matches the normal desktop within one RGB level at
1024x768, 1280x800 and 3840x2160. There are no differences greater than one level
and no nonzero pixels outside those two rectangles. At Deck size the physical
body is `(509,362)-(771,660)` and the popup `(621,458)-(762,800)`; using their
bounding rectangle instead incorrectly treats 16,940 gap pixels as menu content.
Evidence is ignored under `build/vr/menu-cache-probe-*-dropdown/`.

The next implementation can reuse that same qualified surface with separate
interactive toolbar/list crops in native final composition order. It must
validate the live popup identity/visibility, retained bottom, cache generation,
both clipped rectangles and batch capacity atomically. Drawing and picking must
share that exact union, preserve the room-visible gaps and withdraw popup hits
on Hide/destruction. This two-rectangle result is a private flat producer proof,
not completed interactive XR dropdown integration. No public behavior changed.

### Interactive resolution lists and a measured menu-performance gate

The private compiler now publishes separate interactive toolbar-body and popup
crops sharing one qualified cache. A post-draw helper snapshots the retained
pre-union bottom, native root/list identity and both geometries. Before use, the
normal cache validator checks lifetime, owner, extent and native Flip generation;
the footprint validator additionally checks that the popup and geometry have not
changed. Invalid publication requires a fresh complete capture. The bounded
room-child query requires the corresponding visible toolbar/list pair, appends
the deferred popup immediately after its parent body, reserves space for labels,
and atomically rolls back on incomplete or stale sources.

Actual-GPU private tests at 1024x768, 1280x800 and 3840x2160 now match the native
desktop RGB exactly inside that union, with alpha 255 inside and all channels
zero outside. Synthetic controller rays highlight three distinct native list
rows, map back to the intended physical points within one pixel, and cannot hit
the empty gap beside the list. Back first dismisses only the list, retaining the
body/cache and one part; another Back closes the toolbar, releasing the surface
and all hit coverage. The host pointer remains unchanged. The tests use only
the private game and close it afterward. Evidence remains ignored under
`build/vr/menu-dropdown-overlay-*`.

The newly rebuilt renderer candidate under
`build/vr/recipe-dropdown-performance-20261010/` passes its ordinary surface and
helper checks, native XR tests, and real-GPU transport in RGBA and BGRA formats,
including brightness and transparent-black-point checks. The fresh candidate
repeats the Deck/4K dropdown gate and the native controller/world/ActionMenu
transaction. The renderer build is not installed or published.

The user's low-frame-rate observation led to a separate performance experiment.
The synthetic GPU runtime normally snapshots both eyes and the full UI canvas
back to CPU memory on every frame. An explicit test-only no-pixel-readback mode
now retains layer/image/lifecycle validation but refuses pixel queries or file
capture requests. Pixel-fidelity tests continue to use the original mode.

At a 3840x2160 desktop canvas, with 256x256 synthetic eye images, short steady
windows measured approximately:

| Mode | With diagnostic pixel readback | Without diagnostic pixel readback |
| --- | ---: | ---: |
| Stereo room, no menu | 117 fps | 120 fps |
| Opaque menu fallback | 6 fps | 120 fps |
| Isolated basic toolbar | 5 fps | 62–63 fps |
| Isolated expanded resolution list | 4 fps | 32 fps |

These are lower-bound transport measurements, not headset frame-time acceptance.
The readbacks exaggerate the visible slowdown, but removing them does not solve
the isolated-menu cost. Diagnostic-only, result/register-preserving native timing
wrappers identify roughly 7–9 ms in XR overlay composition/upload/submission.
For the expanded list, ordinary desktop drawing takes about 12 ms and the extra
isolated native traversal about 4.5 ms; cache preparation/clear is only about
0.2 ms. Basic toolbar drawing is much cheaper. These wrappers exist only in the
ignored private game, not the package or installed game. Evidence is under
`build/vr/menu-profile-3840x2160-*` and `build/vr/menu_timing.py`.

Next is reducing measured menu composition/upload and duplicate native drawing
costs while retaining exact pixels, hit coverage, lifetime and atomic failure.
HUD fades, usable text entry, media/scripted-camera handling, physical pointing
UX, scale/comfort, full-game coverage, public VR installation/launch, Proton XR
and real-headset acceptance remain unfinished. VR is not ready for the user to
wear a headset. The installed Steam game, persistent XR registration, releases
and Git history remain unchanged.

### Reusable overlay buffers and larger-eye performance qualification

The renderer now reuses one CPU composition buffer per legacy device, under
the existing device bridge lock. At the start of a batch it clears the previous
clipped footprint and its input coverage, rather than allocating/zeroing a
full 4K BGRA canvas and picking map every frame. Dimension changes allocate a
validated replacement first. Source format/key, clipping, opaque black, native
part order and the all-or-nothing publication contract are unchanged. GPU
upload remains full-canvas, so this is not yet a dirty-region upload change.

Native tests compare reused frames against freshly composed images through
movement, edge clipping, changed opacity, keyed holes, label/control overlap,
empty frames and resizing. They cover independent device buffers and clearing
an abandoned valid prefix after a later part is rejected. The fresh renderer
under `build/vr/recipe-overlay-reuse-qualified-20261010/` passes all surface,
helper, XR lifecycle/scene/input/panel and RGBA/BGRA GPU transport checks,
including color/brightness, transparent black, resize, failure recovery and
device recreation. SHA-256:
`a48086c1c668f3ead37a4e508fd87aed949e1cb9da9f63f0b0cc0a949b2d75c6`.

The private resolution-list pixel/pointing gate passes again at 1024x768,
1280x800 and 3840x2160, with exact RGB and alpha outside/inside the two native
crops. Both Back transitions withdraw the appropriate hit coverage. Evidence
is ignored under `build/vr/menu-dropdown-reuse-*`. With the same new renderer,
both simulated hands also select a room object, hover the isolated ActionMenu,
invoke its native action and resume world input without moving the host cursor.

The test-only GPU runtime can now select an immutable recommended eye extent
using `GK3HD_XR_TEST_EYE_SIZE=WIDTHxHEIGHT`. Parsing rejects malformed, trailing,
overflowing or out-of-range values, with a 64–4096 bound per axis. Default
fidelity tests remain 256x256. The build clears this and the no-readback setting
for fidelity qualification and restores the caller's settings afterward.

With diagnostic readbacks disabled, a 4K desktop canvas and the same room/menu
workload, short steady windows measured:

| Runtime image per eye | Stereo room | Isolated toolbar | Expanded resolution list |
| --- | ---: | ---: | ---: |
| 256x256 before buffer reuse | 120 fps | 62–63 fps | 32 fps |
| 256x256 after buffer reuse | 120 fps | 91 fps | 45 fps |
| 1440x1600 after buffer reuse | 120 fps | 91 fps | 45 fps |
| 2048x2048 after buffer reuse | 119 fps | 92 fps | 45 fps |

The current engine adapter draws each eye into its 4K target before scaling to
the runtime image. Larger runtime images test transfer/composition load, not a
change to the game's eye render-target dimensions. These runs have synthetic
tracking and no real headset compositor, and only one representative room.
They are not an end-to-end or worst-case VR performance guarantee. Evidence is
under `build/vr/menu-profile-reuse-*-20261010/`.

XR composition/upload/submission falls from roughly 7–9 ms to 2.2–4.5 ms.
Expanded native menu drawing still costs about 7.5 ms plus 4.5 ms for the isolated
second traversal. With XR disabled, the expanded list reaches about 107–110 fps
and still spends roughly 6.7 ms in native drawing. The opaque XR fallback reaches
about 84–87 fps there. This confirms remaining native menu costs independently
of the isolated composition path, rather than blaming headset pixel count.

The default Python suite passes (3319 passed, 20 skipped, 402 deselected in
42.55 seconds), as do formatting, Ruff, strict ty and spelling checks. The
installed Steam game was not touched. Experiments close their private game and
restore temporary configuration. A stray diagnostic log was moved out of the
repository root into ignored `build/vr/`, not deleted.

Performance remains an acceptance gate. Next is reducing duplicate traversal
and upload/draw costs without changing mirror fidelity, text quality, hitboxes
or failure fallback. The other unfinished VR requirements listed above still
apply, and the goal remains active. No headset test is requested yet.

### Cropped GPU overlay uploads and first-release checklist

Transparent overlay batches now expose the clipped union of their explicitly
authored source rectangles. The CPU buffer and input coverage still use the
original complete canvas. Only that union is copied to the GPU upload texture,
at its local origin; the exact-size shader then places it at its original
canvas coordinates. A bounded, grow-only capacity avoids texture recreation
when a hover or label changes. Only initialized rows are marked dirty and
sampled. Each partial destination clears the rest of the panel to transparent
zero, so movement, shrinking and withdrawal cannot retain old menu pixels.
An entirely clipped batch uploads a transparent 1x1 pixel rather than passing
an empty rectangle with full-image semantics.

The first GPU qualification caught a neutral-ramp failure: the previous gamma
getter returned no drawing helper when no adjustment was needed. Cropped
overlays now explicitly require the exact placement/clear helper even in that
case; complete world eyes and ordinary opaque panels retain their neutral
transfer path. Gamma and premultiplied-alpha semantics are unchanged. That
failed development build is not a qualified renderer artifact.

The fresh `build/vr/recipe-cropped-overlay-qualified-20261010/` candidate passes
all ordinary surface/helper checks, four native XR suites and actual-GPU XR
transport in RGBA and BGRA formats. Added controls check moved, smaller,
edge-clipped, entirely offscreen and restored overlays on the same canvas,
unchanged panel geometry, opaque black, no capacity-padding leakage, exact
pointer coordinates and rejected malformed bounds. Existing brightness/reset,
failed-part recovery and device-recreation gates still pass. Candidate SHA-256:
`2423ffb1eacca327b4dc20fd0f28d36285c0ffdd570c533a560ab574a69e5afa`.

Private-game resolution dropdowns again match desktop RGB exactly at 1024x768,
1280x800 and 3840x2160, including alpha, gap rejection, three native hover rows
and both Back transitions. Evidence is under `build/vr/menu-dropdown-cropped-*`.
Both simulated hands also complete world selection, isolated ActionMenu
selection and the native action, then resume world input without moving the
host cursor. The extended 4K toolbar/corner gate initially stopped because the
host pointer changed during its no-mouse-movement assertion; its initial
toolbar pixels and three controller coordinates passed. This was not treated
as a completed extended gate or bypassed by relaxing the assertion.
The repeat passed without weakening that check, including disable/reopen,
settings/display/graphics/advanced sections, all four screen corners, Back
closure and interactive dropdown gap rejection. Its evidence is under
`build/vr/menu-full-cropped-repeat-3840x2160-20261010/`; the private game closed
and restored temporary configuration afterward. The initial pointer change's
cause was not established, so it is not attributed to the user or renderer.

In a short no-diagnostic-readback run with a 4K game canvas and 2048x2048 runtime
images per eye, world stereo reaches about 120 fps, the isolated toolbar about
116 fps (previously 92), and the expanded list about 49 fps (previously 45).
Overlay composition/upload/submission is approximately 0.65 ms for the toolbar
and 2.95 ms for the list. Native drawing of the expanded menu still takes
roughly 7.4 ms plus 4.5 ms for the capture traversal. Flat/opaque controls vary
between runs; these short synthetic samples are not sustained frame-time
acceptance. Evidence: `build/vr/menu-profile-cropped-2048x2048-20261010/`.

The user's requested [VR_CHECKLIST.md](VR_CHECKLIST.md) now groups implemented
milestones and outstanding first-enjoyable-release gates. Its checks mean local
implementation/testing, not physical-headset acceptance. Windows/SteamVR seated
play is the initial target; Proton and other runtimes remain follow-ups. Menu
performance, remaining HUD, text entry, media/comfort, calibrated physical
scale, public installation/launch and real-headset/full-game acceptance are
still incomplete. Nothing was installed or published; the Steam game and Git
history remain untouched.

### Exact batched overlay conversion

The overlay row converter now processes eight RGB565 pixels at once on the
renderer's SSE2 baseline, retaining scalar tails and a non-SSE2 fallback. It
expands the same channel bits as before, without resampling or color correction.
Color-key holes preserve both underlying pixels and independently authored hit
coverage. Display-only parts remain non-interactive. A fully clipped rectangle
returns before forming a row span, avoiding negative widths becoming unsigned
counts. The engine/renderer interface and panel geometry are unchanged.

Native tests compare every RGB565 value against an independent arithmetic
oracle. They also cover multiple keys, mixed holes across lanes and tails,
unaligned source/destination offsets, guard pixels, layered coverage and rows
without a hit buffer. The fresh pinned full build passes ordinary surface/helper
checks, four native XR suites and actual-GPU transport qualification. Candidate:
`build/vr/recipe-overlay-rows-qualified-20261010/`, SHA-256
`57bd6b78f9d370c569806e7b6dd1a29015abb0025177c87853fb92f3c3d5cc50`.

With the same short 4K-canvas / 2048x2048-eye synthetic benchmark, overlay
composition/upload/submission falls to approximately 0.39 ms for the toolbar
and 1.27 ms for the expanded list, previously 0.65 and 2.95 ms. World and toolbar
throughput remain about 120 and 116 fps; expanded-list throughput rises only
from about 49 to 51 fps. Its native desktop draw still takes about 7.8 ms and
the separate capture traversal about 4.9 ms. These are short, varying samples,
not sustained headset performance. Evidence:
`build/vr/menu-profile-rows-2048x2048-20261010/`. The native-menu overhead and
headset timing checklist gates remain unchecked.

The new candidate passes private-game resolution dropdown pixel, transparency,
hover, gap and Back checks at 1024x768, 1280x800 and 3840x2160, with zero RGB
error. The extended 4K gate passes toolbar disable/reopen, all settings sections,
four corners and dropdown pointing without changing the host cursor. Both
simulated hands complete native world selection, isolated menu selection and
the native action. Evidence: `build/vr/menu-dropdown-rows-*`,
`build/vr/menu-full-rows-3840x2160-20261010/` and
`build/vr/world-action-menu-{0,1}-20261010/`.

Actual native tooltip transport, tooltip plus caption layering, and three
stacked caption rows also pass with the new converter at 1280x800. The tooltip
pixel oracle reports zero RGB error. Caption clearing and inventory/room
ownership transitions pass. Tooltip tests deliberately override ownership only
to qualify transport, not full menu interaction. Evidence:
`build/vr/tooltip-overlay-1280x800-rows-20261010/` and
`build/vr/caption-evidence-1280x800-rows-20261010/`.

Formatting, Ruff, strict ty and spelling checks pass. Live experiments use only
the ignored private game, close it and restore temporary settings. The checklist
records the verified conversion milestone without claiming playable-headset
readiness. The goal remains active; no publication or Git history change was
made, and the installed Steam game was not touched.

### Single native menu traversal with qualified desktop mirroring

Further private instrumentation separates child transfers from the second
native traversal. The expanded resolution list makes about 355 Blt calls per
frame; roughly 3.3 ms of its 4.5–4.7 ms capture traversal is in those calls.
A bounded trace shows mostly keyed glyph transfers from one font atlas. Simply
removing the second traversal was not safe: the ordinary desktop draw receives
partial damage, whereas the isolated source requires complete current pixels.
Evidence: `build/vr/menu-profile-transfers-2048x2048-20261010/` and
`build/vr/menu-profile-transfer-shapes-2048x2048-20261010/`.

The private compiler now performs one complete native draw into its qualified
independent cache. After restoring the native bitmap binding and private COM
table, it qualifies child results and the authored footprint. A small mirror
helper copies the opaque body and optional deferred popup to the ordinary
desktop destination at identical clipped source/destination coordinates. It
never copies the whole canvas or the gaps beside lower popup rows. The native
widget traversal and its geometry/transforms remain the source of the pixels,
not a replacement menu renderer.

Failed allocation, validation, child transfer, footprint or desktop copying
retains ordinary Draw with the original destination and damage, and withholds
isolated publication. A partial mirror failure is followed by ordinary drawing,
not silent acceptance of incomplete desktop pixels. Native EAX, EDX, flags,
caller-preserved registers and stack cleanup survive helper calls. The exact
bound traversal retains SEH cleanup; exceptions are not swallowed or turned
into a successful frame. There is no new player-facing option or renderer ABI.
The duplicate-draw primitive remains only for diagnostic controls.

Machine-executed tests cover one complete draw, clipped crops and unchanged room
gaps, missing resources, failed children/footprints/mirroring, native return
values/flags and exception registration/unwind. All 261 menu-related tests pass.
A native x86 Windows harness also passes normal return, noncontinuable and
resumed software exceptions, access violation, C++ throw and failed mirroring
with restored bindings/exception chain and appropriate withheld publication.
It is under ignored `build/vr/menu_unwind_native.{cpp,py,exe}`; its `--single`
mode executes the package-emitted single-traversal bytes.

Private-game dropdowns at 1024x768, 1280x800 and 3840x2160 match submitted panel
pixels exactly, with correct alpha, gap rejection, native hover rows and both
Back transitions. An additional independent control disables isolation and
compares ordinary native desktop drawing with the single-traversal mirror:
zero RGB error at all three sizes. This avoids treating two outputs from the
same cache as an independent fidelity oracle. Evidence:
`build/vr/menu-dropdown-single-oracle-*-20261010/`.

The extended 4K gate also passes ordinary-draw comparison, disable/reopen,
settings/display/graphics/advanced controls, all four corners, Back closure,
dropdown pointing and unchanged host cursor. Evidence:
`build/vr/menu-full-single-oracle-3840x2160-20261010/`. Both simulated hands
again complete native world selection, isolated ActionMenu selection and the
native action before returning input to the world; evidence remains under
`build/vr/world-action-menu-{0,1}-20261010/`.

The reused qualified renderer is unchanged (SHA-256
`57bd6b78f9d370c569806e7b6dd1a29015abb0025177c87853fb92f3c3d5cc50`).
In short quiet samples with a 4K canvas and 2048x2048 runtime eyes, room stereo
remains about 120 fps, the isolated toolbar reaches about 110 fps and the
expanded list about 74 fps. A paired diagnostic duplicate-draw control with
the same DLL reaches about 104/51 fps for those menus. The remaining expanded
native draw takes about 4.5 ms, desktop mirroring about 0.8 ms and overlay
composition/submission about 1.4 ms. Earlier toolbar samples varied and were
sometimes higher; this is not a sustained headset performance guarantee.
An initial run overlapped the Python suite and is recorded separately, not used
as the quiet timing evidence. Evidence:
`build/vr/menu-profile-single-quiet-2048x2048-20261010/` and
`build/vr/menu-profile-dual-control-2048x2048-20261010/`.

The default Python suite passes: 3363 passed, 20 skipped, 402 deselected in
51.46 seconds. Formatting, Ruff, strict ty and spelling checks pass. The
checklist records elimination of duplicate qualified menu draws, but keeps
remaining menu cost and sustained headset timing unchecked. HUD, text entry,
media/comfort, public installation and physical-headset acceptance still need
work. The installed Steam game and Git history were not changed.

## Producer-owned overlay fades (10 October 2026)

The private renderer transport now accepts an explicit opacity per overlay
part, rather than attempting to recover transparency from already-blended
desktop pixels. The producer contract grows from 36 to 40 bytes per part and
from 768 to 832 bytes per overlay frame. Both current native menu and label
emitters publish opacity one explicitly. The matching fresh renderer recipe is
`build/vr/recipe-overlay-fades-qualified-20261010/`, with DLL SHA-256
`d01df6aea425b56b32a7d960d86ae04a54969bd0cb53199b94ee0777594c4941`.
Do not mix the new compiler with the older overlay-transport DLL.

Finite opacity in [0, 1] is validated before any batch mutation. Source-over
composition preserves real black, explicit color-key holes and ordered layers
in premultiplied BGRA8. Zero opacity contributes no pixels, footprint or picking
coverage. Fully opaque parts retain the optimized conversion path. Brightness
correction operates on unpremultiplied color before restoring premultiplication,
so a raised black level cannot tint an invisible pixel.

Native tests independently check all 256 quantized alpha values, ordered black
backing/white glyph fades, keyed holes, invalid opacity and next-frame cleanup.
The qualified build passes native and actual-GPU transport gates, including
fractional opacity under neutral/nonlinear/reset brightness, exact alpha,
placement and recovery after invalid submissions. Four native CTest gates pass.
Private-game dropdown pixels and ordinary native mirror controls match exactly
at 1024x768, 1280x800 and 3840x2160, including hover rows, transparent gaps and
Back withdrawal. Evidence: `build/vr/menu-fade-ABI-oracle-*-20261010/`.
The matching tooltip-only and caption-plus-tooltip GPU gates also match native
pixels exactly at 1280x800, including relocation and disappearance. These use
the established private transport ownership override and do not certify a
complete interactive menu flow. Evidence:
`build/vr/tooltip-overlay-1280x800-fade-ABI-20261010/`.

A separate flat-game probe follows the native room score/status TextBox rather
than assuming that generic label opacity represents its behavior. Its glyph
source weight remains one initially, then falls through about 0.825, 0.574,
0.324 and 0.075 while the destination weight rises correspondingly. Around
4.45 seconds the native text object is destroyed. The retained patch-owned
address is no longer proof of a live TextBox. Evidence:
`build/vr/status-source-probe-20261010/experiment.json`. The bounded probe
recognizes retirement and closes its private game normally.

This is a fade-compositor foundation, not completed HUD isolation. The producer
still needs separate unblended glyph/backing capture, current native fade
weights and lifetime-aware withdrawal. The checklist keeps these unchecked.
The default Python suite passes with 3363 passed, 20 skipped and 402 deselected
in 43.18 seconds. Formatting, Ruff, strict ty and spelling checks pass. Timing
has not been repeated for this new renderer, and no real-headset readiness is
claimed. The installed Steam game and Git history remain unchanged.

## Scoped native HUD glyph source (10 October 2026)

`vr_hud.py` now emits a private native TextBox capture scope. It admits only an
enabled, visible, exact widget during the caller's synchronous source-capture
transaction. Ordinary, foreign, recursive or unsupported-effect calls retain
the native target and its arguments. It records authored source/backing opacity,
temporarily draws opaque glyphs without backing, and restores all five font
option words and backing opacity afterward. Native return EAX/EDX, flags and
calling convention survive that cleanup. No FPU state is changed.

The scope registers its own x86 SEH cleanup. First-pass dispatch leaves a
resumable capture intact; actual unwind restores the borrowed fields and
withdraws partial publication, returning ExceptionContinueSearch rather than
swallowing an exception. Delayed or duplicate cleanup cannot affect a different
registration. Thirty-eight machine-executed behavioral cases cover normal
opacity values, fallback, return state, resumable dispatch and unwind. The
ignored native Windows harness `build/vr/hud_unwind_native.{cpp,py,exe}` also
passes normal return, noncontinuable/resumed software exceptions, access
violation and C++ throw with restored fields and exception chain. Its code
storage must be writable while receiving emitted bytes; the initial harness
failure was a read-only test-section configuration, not a widget cleanup fix.

The shared isolated cache preparation helper accepts an optional caller-owned
RGB565 key. It sets the actual DirectDraw source color key and clears to that
same value, rather than mistaking a clear color alone for a declared key. Failed
key setup releases/withdraws the cache and retries lazily. Seven additional
behavior tests cover boundary key values, reuse, failure/recovery and invalid
keys. Opaque menus continue using the existing unkeyed path.

The bounded `build/vr/hud_source_gate.py` experiment combines these package
primitives in the private game with a diagnostic query override and the
qualified fade-capable renderer. At 1280x800 it captures exactly 1624 opaque
status glyph pixels in [6, 8, 408, 22], with zero RGB error against the desktop
text and no pixels outside the top band. The key remains transparent and no
room pixels enter the source. As the native status expires, the diagnostic
query withdraws the part and readiness. Evidence:
`build/vr/hud-opaque-source-20261010/`.

This deliberately tests the unblended source at opacity one. It is not the
automatic HUD compiler, final fade/backing composition, modal lifetime handling
or destruction-hook qualification. The caller still must verify current native
identity, transfers, generation and lifetime before publication. Font effects
beyond the observed plain/fade modes are not inferred. These open requirements
remain unchecked, and real-headset readiness has not changed.

The default Python suite passes with 3408 passed, 20 skipped and 402 deselected
in 43.04 seconds. Formatting, Ruff, strict ty and spelling checks pass. The live
experiment closes the private game itself; the installed Steam game, public
renderer artifacts and Git history are unchanged.

## Automatic room HUD, native fades and destruction (10 October 2026)

`VRHudCompiler` now binds the verified Runtime2D TextBox Draw and native deleting
destructor. It is dormant and private, installed after the deferred world and
optional menu producer, before `VRPanelCompiler`. The panel synchronizes its
enable state, queries/withdraws it even during disabled presentation and appends
HUD backing/glyphs before menus, captions and tooltips. Unqualified HUD sources
retain the ordinary opaque-panel fallback rather than silently dropping text.
Full dependency/payload verification composes with existing menu hooks in a
clone, restoring only verified HUD bindings for the Runtime2D check.

Ordinary Draw executes exactly once. Subsequent capture-only transactions can
write only to independent keyed caches, never to the desktop, even on failure.
The default source draws opaque glyphs with no backing. A second source invokes
the native fill at full opacity with zero glyph contribution. It therefore
preserves the native color conversion rather than guessing that a backing is
black. Zero authored backing skips this second traversal/allocation. Both scopes
restore the original font/backing fields, result and exception state.

The publisher requires the currently visible, readable exact first TextBox of
RoomLayer, independently qualified source owner/size/native page/child transfers,
unchanged native fade options and geometry. Source rectangles use height/768
for both axes, signed floor/ceil edges and canvas clipping. Glyphs/backing retain
separate producer opacity and ordered premultiplied composition. Zero-opacity
sources append nothing and cannot create pointer coverage. Expiration, modal or
hidden state and disabling clear the owned identities before releasing sources.
An old unrelated destructor cannot release a newer object's cache.
Native fades must have the source-over complementary destination weight;
other blend equations retain fallback rather than approximating darker pixels.
The complement guard preserves XMM0, MXCSR and the x87 state and uses a local
masked, round-to-nearest environment. Invalid/noncomplementary destinations
are covered by machine-executed tests and the native exception harness.

Fifty-one compiler behavior tests execute native Draw preservation, separate
fade routing, atomic rollback, unreadable identity, stale sources, clipping at
reference/Deck/HD/4K sizes and exact destruction ownership. Existing source and
cache tests cover the actual child-transfer and native-page validators. The
actual Windows capture-only destination harness also passes normal return,
noncontinuable/resumed exceptions, access violation and C++ throw, restoring the
source binding and exception chain without an ordinary-draw fallback.

The bounded automatic private-game gate no longer writes a HUD owner or replaces
the production append query. It uses the matching qualified fade renderer. An
additional private callback copies the test runtime's already-read-back GPU
pixels on the game thread, because the file-capture fixture writes only once at
frame 32 and cannot prove later fades. The resulting samples contain exactly
1624 glyph pixels, with alpha 255, 204, 146, 93 and 40 and premultiplied RGB error
at most one level. Native deletion then withdraws the part, clears both owned
pointers/readiness and releases the source. The bridge returns to world-only
completion. Evidence: `build/vr/hud-integrated-20261010/`.

A separate backing oracle temporarily supplies controlled native TextBox
options only in the private game at an idle capture boundary. Its 7272 backing
pixels are native RGB [48, 7, 0], matching ordinary desktop pixels exactly.
At authored backing opacity 0.375 the GPU alpha is 96 with zero premultiplied
color error. Evidence: `build/vr/hud-backing-20261010/`. These checks qualify the
transient room status producer, not every HUD variant or real-headset readability.

The short no-readback paired timing uses a 3840x2160 canvas and 2048x2048 synthetic
runtime images per eye: about 119.8 fps without HUD and 117.0 fps with isolated
status text. These 1.5-second samples show modest added cost, not sustained
headset/compositor acceptance. Evidence: `build/vr/hud-timing-20261010/`.
Expanded menu overhead remains unresolved. The full default Python suite passes
with 3480 passed, 20 skipped and 402 deselected in 46.10 seconds. The installed
Steam game, published renderer and Git history remain unchanged.

## Native save-name text sink (10 October 2026)

The private, dormant `VRTextCompiler` adds a render-thread single-slot mailbox
after an explicitly identified final-page presenter. Printable ASCII characters
and Backspace/Delete/Left/Right/Home/End go through the original SaveEditBox
handlers. It does not mutate the native string or caret fields, synthesize host
input, or expose Enter, Escape or clipboard shortcuts. A delivered character is
still subject to the native font and editor limits. Saving remains a separate
explicit action on the game's Save button.

The live-game investigation distinguishes manager mouse capture (+0x60),
manager keyboard focus (+0x64), and SaveGame's own character routing. SaveGame
does not require either manager pointer: its native container dispatch gives the
first child the character event. The bridge therefore qualifies the actual
first child, its exact SaveEditBox class, embedded position, visible/enabled
state and SaveGame parent against the current layer. Native routing and both
editor handlers have verified byte/vtable anchors. Other editor classes are not
inferred from similar shapes or text-buffer fields and remain separate work.

Successful focused XR presentation with a tracked selected hand is also
required. The published epoch changes on layer/editor or controller handoff and
focus/tracking loss, invalidating pending requests. The producer publishes the
request last and must not overwrite an occupied mailbox. The consumer clears it
before calling native code, preventing duplicate dispatch during synchronous
painting or an exception. Nested paints retain ordinary desktop composition,
without another XR frame or text dispatch. Actual exception unwind retires the
target/request; first-pass and resumable exceptions do not. Editing keys are
rejected while host modifier flags would change their native meaning.

The bounded `build/vr/text_gate.py` gate runs only the private game copy with the
qualified fade renderer and synthetic tracked controller. It opens the existing
save editor, verifies eight actual native insert/caret/delete operations, rejects
pending text after XR focus loss, and retires the target on dialog closure. It
never presses Save or writes a save file. Evidence and the inspected editor
capture are in `build/vr/text-entry-20261010/`. The installed Steam game is
unchanged and the experiment closes its own process.

Fifty-one machine-executed behavior tests cover text/key delivery, invalid
characters/actions, native ownership, bounded child graphs, controller handoff,
stale epochs, focus loss, nested painting and exception cleanup. This establishes
the native save-name backend, not the visible controller keyboard, other text
fields or headset save/restore acceptance. Those checklist gates remain open.

The additional `build/vr/text_unwind_native.py` gate feeds the complete
package-emitted consumer into an x86 Windows harness. Normal return,
noncontinuable exception, resumed exception, access violation and C++ throw
all restore the native exception chain and consume the request exactly once.
Aborted calls retire the target and advance its epoch; a resumed exception
retains ownership and completes the native callback. The diagnostic harness
disables SafeSEH for its dynamically supplied handler, matching the legacy
injected-code test environment rather than changing any game security settings.

Formatting, Ruff, strict ty and spelling checks pass. The default Python suite
passes with 3531 passed, 20 skipped and 402 deselected in 46.47 seconds. No public
VR command, published renderer, installed game or Git history was changed.

## Controller keyboard foundation (10 October 2026)

The native renderer library now contains a renderer-owned keyboard with readable
system-font labels, letters/caps/symbols, space and the six editing keys accepted
by the verified text consumer. Together its modes cover all printable ASCII.
There is deliberately no Enter, Escape or automatic Save. The original game's
Save and Cancel controls remain separate explicit actions. No font files or
host input events are required.

The keyboard's image is 1200x456 and its aspect-correct geometry is anchored
below the editor panel, using that panel's orientation and position. Drawing
and ray picking share the same geometry. Key gaps consume keyboard selection
without typing or clicking through to game controls. The selected hand and
editor epoch must remain qualified; opening while held, focus/tracking loss,
hand changes and an occupied native mailbox cannot replay or duplicate text.
Modifier/layout changes reset on ownership loss. Stale rendered views are
rejected. Image allocation is reused and unchanged views avoid label redraws.

The runtime also has a separate keyboard swapchain, so displaying the keyboard
will not shrink, stretch or paint over the original editor panel. Its layer is
submitted together with the editor and optional stereo world at the same
predicted time. Written-image ownership, geometry, cancellation, resize guards,
partial creation and acquired-but-not-waited teardown are tested independently.
A keyboard layer cannot be submitted without its accompanying editor panel.

All five native CTest suites pass in about one second, with the added keyboard
behavior and runtime composition cases. The library builds with MSVC warnings
as errors. The generated keyboard preview in
`build/vr/keyboard-20261010/keyboard.png` was visually inspected. Native build
and test products are in `build/vr/keyboard-native-20261010/`.

This qualifies the keyboard model, pixels, pointing and runtime target lifecycle,
not yet the complete renderer upload/native-mailbox wiring or live in-game VR
typing. Those are the next integration step. The existing qualified prototype
DLL and installed Steam game remain unchanged. The first-release text-entry
and real-headset acceptance gates are still open.

## Controller keyboard integration (10 October 2026)

The renderer and native text consumer are now connected through the private
24-byte `Gk3hdXrTextV1` epoch/action bridge. The game publishes only its current
qualified editor epoch and mailbox availability, not a native widget pointer.
The renderer returns at most one character or editing key from the completed
panel frame. The consumer rechecks the current editor, layer, tracked hand and
epoch before invoking the original editor handler. Manual diagnostic requests
retain priority. Stale ownership, closed dialogs and unavailable mailboxes
cannot replay a renderer event.

The renderer uploads a separate keyboard image and submits it alongside the
unchanged editor panel. Keyboard selection is removed from that frame's native
UI input, while Back/Menu and the shared predicted tracking snapshot remain
intact. Closing or switching to a world/isolated overlay retires the keyboard.
The actual-GPU transport gate verifies keyboard labels, encoded colors, full
opacity, matching quad geometry, controller key selection, no held-key repeat,
stale-epoch rejection and layer withdrawal. Both RGBA and BGRA runtime images
pass, with the existing stereo, caption, menu and brightness checks retained.

The complete pinned recipe passed its native, flat-renderer and actual-GPU
gates. The private candidate is
`build/vr/recipe-keyboard-qualified-v2-20261010/`, with DLL SHA-256
`907efde77c07f2d28c3e7409bdcefa57afdbee015c814866d2ab4aeb6db80c92`.
This is a development artifact, not an installed or published player renderer.

`build/vr/keyboard_gate.py` then exercised the full renderer-to-native-editor
flow in the private game copy. Controller keys performed nine native edits,
including insertion at the start/end, Home, Delete and Backspace. Caps and
Symbols changed the visible keyboard without invoking editor actions. Holding
a key did not repeat it. Tracking and XR focus loss retired ownership, blocked
held-input replay on recovery, and allowed typing after release. Closing the
save dialog retired the editor. Save-file hashes were unchanged and the host
pointer was not moved by controller input. The test closed its own process.

Evidence and visually inspected captures are in
`build/vr/keyboard-native-20261010-evidence/`, including the actual GPU keyboard
image and original save-name field. The keyboard is 1.2 by 0.456 metres below
the 1.6-metre editor panel in this synthetic seated fixture. Comfort, actual
controller bindings and headset readability still need acceptance testing.
Other native editor classes are not inferred from SaveGame and remain work.

The current strict lint/format/type/spelling checks pass. The default Python
suite passes with 3546 passed, 20 skipped and 402 deselected in 47.92 seconds.
The actual x86 Windows text exception harness still passes all five return,
resume and unwind cases. Renderer provenance hashes match the current native
sources and artifact. The installed Steam game and Git history were untouched.

## Native SIDNEY text entry (10 October 2026)

SIDNEY's search editor receives characters even when the UI manager's focus
field is null. The original container dispatch walks its children in order and
stops at the first recipient. The text consumer now follows that verified
dispatch to qualify ordinary editors, without hardcoded SIDNEY widget offsets
or SaveGame-specific parent fields. It requires the known native character/key
handlers and a readable font map. Unknown handlers, unreadable state, excessive
depth or child counts and hidden/disabled recipient ancestry reject ownership.
A hidden first recipient cannot be skipped in favour of a later text field.
The resolver is bounded and does not modify the native widget tree.

The controller-only private-game gate typed `vampires` through eight native
character callbacks, selected Search and displayed the original game's results.
Returning Home retired the editor and keyboard. No host typing or pointer
movement was used for these interactions. The typed query and results were
visually inspected. Captures and the recorded outcome are in
`build/vr/sidney-keyboard-20261010/`. The save-editor regression also passed,
including focus/tracking loss, editing, closure and unchanged save files.

The actual Windows exception harness passes all five normal-return, resumable
exception and unwind cases for both SaveGame and nested ordinary editors. The
default Python suite passes with 3566 passed, 20 skipped and 402 deselected in
47.92 seconds. Strict lint/format/type/spelling checks pass. Native renderer
sources did not change, so the qualified keyboard renderer above remains the
current candidate. These checks do not qualify every custom editor, headset
readability or a complete save/restore flow. Those remain explicit checklist
gates. The installed Steam game and Git history were untouched.

## Controller save, restore and quit (10 October 2026)

The private-game controller gate types `vr controller save` through 18 native
editor callbacks, writes a valid native save slot, snap-turns the camera by
30 degrees and restores the saved room, timeblock and exact five-component
camera state. Inventory and Back work after restore. Back and No both cancel
Quit and return to interactive stereo. Yes exits with code zero. Controller
interactions do not move the host pointer. Test-created saves are removed and
the pre-existing private save files retain their original hashes.

This exposed an actual frame-ordering regression when dismissing Quit. Native
page repair can request two room draws before the completed-page presenter.
The second draw previously attempted another OpenXR world frame while the
first awaited completion, disabling stereo on the renderer's ordering guard.
A private bridge trace recorded one such duplicate attempt before the fix.
The game patch now retains a pending-frame boundary until the paired presenter
ends or cancels the frame. Additional room draws still perform their ordinary
flat page repair, without resampling the stereo view or invalidating published
picking. Native exception unwind clears the boundary too. The renderer's
ordering guard remains unchanged.

Unit regressions cover rendered and non-rendering XR frames, repeated native
draws, preserved picking, subsequent frame recovery and completion/cancellation
paths. The full running-game flow passes with the existing qualified keyboard
renderer. Evidence and captures are in `build/vr/save-restore-20261010/`.
This qualifies synthetic controller interaction, not physical-controller
comfort, headset readability, pause/resume or focus changes during file I/O.
Those remain unchecked release gates. The installed Steam game is untouched.

The default Python suite passes with 3572 passed, 20 skipped and 402 deselected
in 46.14 seconds. Strict lint/format/type/spelling checks pass. Both the
save-editor keyboard and SIDNEY search regression gates pass with the updated
scene/presenter patches. Each experiment closes its own game process.

## Controller pause and native movie playback (10 October 2026)

Back now invokes the original pause toggle when an unobstructed room owns input,
and resumes the native PauseLayer with the same toggle. Interfaces retain their
ordinary Escape behavior. The private-game controller gate verifies that pause
stops stereo-world drawing while XR submission continues. Focus loss disarms
Back, so a held button on recovery cannot resume the game until released.
Resuming restores interactive stereo without moving the host pointer.

Movies expose a different native input contract: their skip binding is handled
as a character event, not an Escape key-down. Controller Back now reads the live
configured skip character and invokes the verified engine character dispatcher.
This preserves the movie's original completion/continuation behavior instead of
forcibly popping its layer. Missing or unbound skip configuration is ignored.
Callback ownership changes cannot create a phantom key release or replay input.

An original Bink movie runs on the modal panel with stereo-world draws stopped
and XR submission continuing. Controller skipping, focus-loss release guards
and natural completion of a separate short original movie all return to the
native room with stereo enabled and successful frame completion. The natural
completion test records more than 800 continuing XR frames during playback.
Evidence is in `build/vr/pause-20261010/`, `build/vr/movie-skip-20261010/` and
`build/vr/movie-completion-20261010/`. These are synthetic controller tests in
the ignored private game, not headset comfort or audio acceptance. Focus loss
during save/restore file I/O and scripted-camera handling remain open gates.

The default Python suite passes with 3589 passed, 20 skipped and 402 deselected
in 48.19 seconds. Native renderer sources did not change, so the qualified
keyboard renderer remains the candidate. The installed Steam game and Git
history are untouched, and each experiment closes its own process.

## Native camera-glide ownership (10 October 2026)

An actual `GlideToCameraAngle` experiment exposed an unsafe assumption: the
original game stacks a scripted camera controller without setting its ordinary
camera input-lock flag. The previous VR ownership check therefore continued
immersive rendering while the authored camera moved. Input locks alone are not
a reliable cinematic-camera signal.

The patch now verifies the native controller stack and top-controller query.
Only a sole recognized user camera/scene controller owns immersive world
rendering and seated stick navigation. A stacked, scripted, missing or unknown
controller uses the floating screen and retires navigation. The original
camera motion, script completion and controller stack remain unmodified.
Navigation recovery requires neutral input, so holding a stick through a
scripted camera sequence cannot trigger a turn on completion.

The private-game gate runs the original glide from the starting hotel-room
camera to `FR_DU1`. It observes the scripted controller, actual camera movement,
stationary panel geometry, stopped stereo-world draws and continuing XR
submission with successful frame completion. Held turn input is blocked during
and after the glide. Releasing and pressing again performs one native snap turn.
The screen then returns to interactive stereo. Evidence and captures are in
`build/vr/camera-glide-20261010/`.

Unit regressions cover controller ownership, damaged/empty stacks, unknown
controllers and release-to-rearm recovery without changing native game state.
The default Python suite passes with 3609 passed, 20 skipped and 402 deselected
in 51.41 seconds. The qualified renderer is unchanged. These are synthetic
controller tests, not headset comfort acceptance. Camera cuts, other scripted
sequences, comfortable fades and real-headset validation remain open gates.
Only the ignored private game is launched, and each experiment closes itself.

The save/restore regression still saves and restores the exact native camera
state and resumes inventory interaction. However, one run failed to reopen
Quit after cancelling it with Back. An unchanged rerun completed Back, No and
clean Yes exit successfully. This intermittent failure is not yet explained
or fixed, so repeated Quit reliability has been reopened in the checklist.
The failure capture/state and successful rerun evidence remain under
`build/vr/save-restore-20261010/`. Strict lint, formatting, type and spelling
checks pass. The installed game and Git history remain untouched.

## Test input publication and file-I/O focus qualification (10 October 2026)

The intermittent Quit failure above is now reproduced and explained. The private
automation publisher uses an odd sequence while updating its shared input packet,
then publishes an even sequence when the complete packet is ready. The synthetic
runtime previously treated that intermediate state as session focus loss. If the
publisher was descheduled during the update, the real input consumer correctly
cancelled and disarmed a held Select, losing the intended click. This was a test
runtime publication race, not evidence that the native Quit button needs another
game patch.

The test-only sampler now retains the last complete packet during a bounded
publication interval, never torn bytes. A stalled publisher becomes unavailable
after 100 milliseconds. Explicit focus loss, malformed packets and missing
publishers still retire input immediately. Only complete packets are acknowledged.
The production OpenXR input and release-to-rearm guards are unchanged.

A deterministic counterfactual holds publication incomplete for 40 milliseconds
during Quit Select. The old runtime fails to open the first confirmation. The
fixed runtime passes 30 identical open/Back cycles. A separate complete native
save/restore regression passes 20 additional Quit cycles, No cancellation and Yes
exit with code zero. Evidence is in `build/vr/quit-pending-before-20261010/`,
`build/vr/quit-pending-fixed-20261010/` and
`build/vr/save-restore-io-focus-20261010/`.

The file-I/O gate uses bounded rendezvous hooks in the private process, verifying
the actual file handle before injecting synthetic focus loss. It catches
`WriteFile` on the newly created native save and `CreateFileMappingA` on an
existing save while the restore browser loads its catalog. Held Menu cannot
open another interface or dismiss the current one on recovery. Releasing and
pressing again works normally. The controller-typed save is valid, restoration
recovers the exact camera state, and subsequent inventory/world interaction and
Quit work. This qualifies restore-browser loading, **not** focus loss during the
final selected-slot restoration. That and physical-runtime lifecycle checks
remain open checklist gates.

A fresh native build passes all six CTest suites, including publication,
explicit-focus, malformed-input, timeout and clock-wrap regressions. Actual-GPU
transport passes in RGBA and BGRA images with the build's prescribed fidelity
configuration, retaining keyboard, pointer, composition, brightness, fade and
device-recreation checks. The unchanged old runtime and the new runtime both
fail the one-shot brightness check without that configuration. Disabling only
asynchronous shader compilation makes the new runtime pass. Cold asynchronous
shader readiness therefore remains an explicit shipping-configuration gate,
not an input-runtime regression or a reason to weaken brightness assertions.

The qualified renderer DLL and production rendering sources are unchanged in
this step. Diagnostic hooks and captures stay under ignored `build/vr/`. Test
processes exit, test-created saves are removed, and pre-existing private save
hashes remain unchanged. The installed Steam game and Git history are untouched.

## Exact first-use presentation pipelines (10 October 2026)

The asynchronous brightness failure above has a renderer cause. Sarek's dynamic
async compiler may temporarily reuse a compatible render-pass pipeline while
compiling the requested state. A previous presentation variant can have different
gamma or premultiplied-alpha specialization constants. Ordinary async can instead
skip a draw until its pipeline exists. Neither behavior is valid for the critical
copy that publishes an eye or interface image to OpenXR. The runtime cannot repair
already incorrect pixels or a missing copy.

The prototype now marks its internal presentation fragment shaders as requiring
an exact pipeline. A missing exact instance is compiled before that copy, without
an async fallback or skipped draw. Existing exact instances retain the original
fast lookup path. Ordinary game shaders keep their configured async policy, and
neither gamma curves nor alpha math changed. This also protects the same internal
presenter when it mirrors to the desktop.

The GPU fixture has a focused `--critical-copy` gate using clear-only producers,
so ordinary game-shader compilation is not confused with presentation correctness.
Its first-use assertions retain exact eye/panel colors, nonlinear brightness,
raised black points, transparent holes, cropped fractional fades and reset to
neutral. There are no warmup retries. It repeats device/session recreation and
both source bit depths. The unchanged previous DLL fails this gate at the first
nonlinear brightness variant. The fresh DLL passes under `dyasync` and `async`
in RGBA and BGRA runtime images. The build recipe now runs all four combinations,
in addition to the full native and synchronous GPU qualification, and restores
caller environment settings afterwards.

A fresh pinned build completed all qualification and provenance checks in
`build/vr/recipe-exact-present-qualified-20261010/`. Its candidate SHA-256 is
`286aa33913993250524cc91e2d95e6a2ff73d5bc2f71b86f0fb65629c1a12aa1`.
All current native input hashes match its manifest. The complete GPU regression
also passes with dynamic async enabled, including keyboard, pointers, isolated
composition, brightness and device recreation. Counterfactual logs are retained
as `build/vr/critical-copy-before.log` and `build/vr/critical-copy-after.log`;
the qualified build and full dynamic-async logs remain under `build/vr/`.

The new candidate passes the private-game controller save/restore gate with
actual save-writing and restore-browser focus-loss rendezvous, 20 post-restore
Quit/Back cycles, No cancellation and clean Yes exit. Native state is restored
exactly, held input is not replayed, test-created saves are removed and the host
pointer does not move. Evidence is in
`build/vr/save-restore-io-focus-20261010-exact-present/`.

A short paired 4K-canvas/2048x2048-eye timing check, without diagnostic readbacks,
stays near 120 fps both with and without isolated status text, matching the old
candidate in the same sample. Missing exact presentation variants may still incur
a one-time compile cost. This does not establish sustained headset timing or cold
ordinary-world-shader readiness across scenes. Those remain checklist gates.
Timing evidence is in `build/vr/hud-timing-20261010-exact-present-control/` and
`build/vr/hud-timing-20261010-exact-present-candidate/`. Only the ignored private
game was launched; processes closed and the installed game and Git history were
untouched.

Strict formatting, lint, types and spelling pass. The default Python suite passes
with 3609 passed, 20 skipped and 402 deselected in 51.93 seconds. The native build
passes all six CTest suites, existing flat-renderer qualification and the expanded
GPU gates. This closes the tested presentation-copy defect, not the remaining
real-headset, ordinary-world-shader, comfort, performance and release gates.

## Selected-slot restoration and Quit focus guards (10 October 2026)

The private lifecycle gate now distinguishes restore-browser catalog reads from
the actual selected-slot restore. A bounded file-mapping rendezvous is armed
immediately before activating Restore and accepts only the exact newly created
save filename. The trace confirms focus loss during `CreateFileMappingA` for that
chosen slot, rather than a preview bitmap or another catalog entry. Recovery does
not replay held Menu input. The room/timeblock and all five saved camera values
are restored exactly, editor ownership retires, and inventory/Back work normally.

This passes both a same-room camera-change case and a cross-room case. The latter
uses the native console only for scene setup, moving to the hotel lobby before
restoring the saved hotel room through controller interaction. This exercises
native room reconstruction, not only dismissal of the restore dialog. The lobby
and restored room captures were visually inspected. No production patch or
renderer changes were needed for these existing ownership guards.

The same flow presses and holds Quit Yes, loses focus, then recovers while still
held. Neither recovery nor its eventual release activates the button. A fresh
press and release exits with code zero. Back and No cancellation also pass, and
controller interactions do not move the host pointer. The final evidence is in
`build/vr/save-restore-io-focus-20261010-selected-restore-focus/` and
`build/vr/save-restore-io-focus-20261010-cross-room-restore-focus/`.

Each process closes itself and removes only its test-created save. Pre-existing
private save hashes remain unchanged. The installed game and Git history are
untouched. These are synthetic focus/controller qualifications, not proof of
real SteamVR lifecycle behavior, continuous tracking while native loading blocks
the render thread, physical-controller acceptance or complete-game coverage.
Those remain open release gates.

### Authored camera-cut fades and OpenXR image edges

`CameraTransition` detects an authored position change greater than half a
metre or a normalized camera-axis change greater than 15 degrees between
stereo renders. Tracking poses never enter the detector. Projection-axis scale
changes do not count as rotations. Ordinary gentle navigation remains visible,
while snap turns and larger scene jumps begin at opaque black and recover with
a 200 ms smoothstep fade, timed by OpenXR's predicted display time rather than
frame count, delays or wall-clock sampling. A second cut restarts the fade.

Both eyes keep their current predicted poses/FOVs and continue submission at
black. The GPU presenter applies one shared RGB visibility after the accepted
brightness ramp, preserving opaque eye alpha. Visibility is a push constant,
not a specialization that would compile a new pipeline each frame. The authored
camera and game simulation are not changed or delayed. World rays, picking and
target feedback are withheld until the view is fully visible. Floating interface
layers retain their independent opacity and interaction.

The new all-pixel GPU tests exposed an existing scaled-copy edge defect. The
desktop presenter's border sampler mixed outermost image pixels with black.
OpenXR copies now select a separate edge-clamped sampler; ordinary desktop
presentation keeps its previous sampler. Tests check every pixel in both eyes,
including the corners, across 1:1/scaled copies, neutral/nonlinear brightness
with a raised black point, RGB565/32-bit producers, RGBA/BGRA runtime images and
device recreation. Fades must not reapply gamma or make the projection
translucent. Unit checks cover matching eye visibility, continuing head tracking,
world-input gating/recovery, repeated cuts, failed draws, clock restart,
projection scaling and multiple frame rates.

The pinned fresh build `build/vr/recipe-camera-transition-final-20261010/`
passes all six native CTest targets, the renderer helper checks, both full GPU
format suites and the four asynchronous critical-copy combinations. Its DLL
SHA-256 is
`669816b514c82cc55a9e99ba37301d63230705d5d30dfdb75eb8a396fd28b7d6`.
The default Python suite passes 3,609 tests, with 20 skips and 402 deselections.

The private-game fixture `build/vr/camera_cut_gate.py` captures the first 21
stereo pairs after an actual `CutToCameraAngleX` and after `SetLocationTime`
moves from the hotel room to the lobby. Both begin at opaque black, progressively
reveal the new room and restore world rays when the fade finishes. Frame-pair
sequence numbers match; native scene/completion results remain zero. The
recovered room/lobby and intermediate-fade captures were visually inspected.
Evidence is in `build/vr/camera-cut-20261010/`. A fresh native glide check also
passes in `build/vr/camera-glide-final-20261010/`: the authored moving camera
still uses a stationary screen, XR continues and held navigation cannot replay
after returning to stereo.

A short no-readback check at a 4K game canvas and 2048×2048 images per eye reaches
120.3 fps without HUD and 119.9 fps with isolated status text. This is not a
sustained headset/compositor measurement or a cut-transition performance claim.
Evidence is in `build/vr/hud-timing-20261010-camera-transition-final/`.

This is a black-to-visible blink after detecting a cut, not a predictive fade-out
before an unknown native scene change. It does not prove continuous frame
submission during blocking loading, wall-lean protection, complete cinematic
coverage or physical-headset comfort. Those remain explicit release gates.
Only the ignored private game was launched, and each fixture stopped its process
and preserved existing private save hashes. No installed-game, commit or release
changes were made.

## Native wall-lean protection

The scene bridge now supplies a direct finite BSP segment query, not the
controller's selectable-object picker or a walker-boundary texture. The verified
renderer entry takes the room BSP handle and explicit world endpoints. Private
tests in R25 and LBY establish clear short segments, first surface hits, endpoint
clipping, and unchanged authored camera state. Native BSP intersections reject
back faces. The protection therefore always casts **outwards from the authored
interior**, never back from a headset that may already be beyond a wall.

Before either eye draws, cast towards each predicted eye and extend the segment
by the current physical near distance plus 10 cm. A smoothstep fade covers the
last 10 cm before the near plane reaches the surface. Use the lower visibility
for both eyes, with opaque black at/through that boundary. Retreat follows the
same distance curve. Predicted head/eye poses continue unchanged, the native
camera is never clamped, and obscured world selection/reticles are withheld.
Camera-cut visibility and wall visibility combine by their minimum. Invalid or
unavailable geometry cancels the frame and cannot publish completed world input.
The private x86 scene request is now 252 bytes, requiring a matching patch and
renderer build. This is not a released ABI compatibility promise.

`wall_visibility.h` implements the renderer-side geometry rule. The native
adapter in `VRSceneCompiler` uses profile-checked engine entries and no screen,
noun or action filter. Emulated x86 tests cover argument order, preserved
callee-saved state, endpoint/camera immutability, hits/misses and unavailable
dependencies. Native coordinator tests cover clear space, binocular fade,
through-wall head tracking, retreat, input gating/recovery and failed/invalid
queries without partial eye submission.

The fresh pinned build `build/vr/recipe-wall-safety-final-20261010/` passes all
six CTest targets, renderer helper checks, RGBA/BGRA GPU transport suites and
the four asynchronous critical-copy combinations. DLL SHA-256:
`376a6a12b65b1e98508e2e61964fda7524541bac9033075db2459f8644431a02`.
The default Python suite passes 3,621 tests, with 20 skips and 402 deselections.

`build/vr/wall_query_gate.py` drives synthetic HMD translation on the game thread
using a test-runtime-only export. It exercises the **production** geometry
adapter in the private game, approaches known room/lobby surfaces, crosses
them, then retreats to the original seated origin. Diagnostic eye captures
show matching opaque black for near/through-wall frames, attenuated approach
and retreat images, restored clear images, and zero world ray masks while
obscured. All authored camera bytes and saves remain unchanged. Evidence and
images: `build/vr/wall-lean-20261010/experiment.json` and adjacent PNGs. Native
R25/LBY near distance is approximately 12 game units with the current scale,
so the fixture derives its approach distance from that actual camera field,
not a guessed 5 cm near plane. Readbacks and synthetic HMD setters are absent
from the production renderer.

The native camera-cut fixture also passes again with wall protection enabled.
A short no-readback 4K-canvas/2048-eye room/HUD check remains approximately
120 fps in both cases (`build/vr/hud-timing-20261010-wall-safety-final/`). This
does not establish sustained headset timing. Broader scenes, movable actor/
door geometry, thin/transparent surfaces, cameras authored close to walls,
comfort/world-scale calibration and physical SteamVR acceptance remain open.

### Visible model geometry and hit-test independence

Wall queries now combine the nearest native BSP intersection with native model
triangle intersections. The engine enumerates generation-tagged model handles,
including valid slot-zero handles, and tests current model/mesh visibility.
Each nearer intersection shortens a private endpoint for subsequent queries.
This prevents a farther model from replacing a nearer model or BSP hit, without
changing the caller's endpoints, authored camera or gameplay selection state.
The existing 252-byte scene contract and qualified renderer remain compatible.

Private-game tests distinguish actual visibility from object selectability:
R25PIC01 remains solid after disabling its object hit test, becomes clear when
hidden and returns when shown. The R25 chair also remains solid when nonselectable.
A short segment through that chair is clear in the BSP-only query but hits in
the production combined query, becomes clear while the chair is hidden and hits
again after restoration. Original visibility, hit-test state, camera bytes and
private saves are preserved. Evidence is in
`build/vr/wall-visibility-policy-20261010/experiment.json` and
`build/vr/wall-production-model-game.log`.

Emulated production callbacks cover nearest-hit ordering, BSP/model occlusion,
hidden models, finite endpoints, full generation handles and calling-convention
cleanup. The default Python suite passes 3,630 tests, with 20 skips and 402
deselections, in 53.10 seconds; Ruff and ty checks pass. These tests do not
establish moving-door protection, alpha-transparent
holes, broad scene-loading correctness or headset comfort. Those checklist gates
remain open.

### Package-level VR composition

`gk3hd.vr.compiler` now composes the seated VR scene, menus, HUD, panels,
ownership, world picking, navigation, controller input and text editor bridges
on a clone of the recommended flat patch. All eight launcher-controlled
activation switches remain disabled on disk. Independent deterministic rebuild
verification checks the complete final image and presenter links, rather than
treating intermediate compiler layouts as the final program. This is an
installation foundation, not a public install or launch command.

Nineteen portable tests cover all supported executable profiles, deterministic
output, unchanged caller input on late failure, rejected code/control edits,
mismatched world calibration and missing flat dependencies. The focused suite
passes in 3.95 seconds after reusing immutable compiled fixture baselines.
Before that fixture optimization, the complete default suite passed with 3,997
passed, 20 skipped and 402 deselected in 60.12 seconds. Strict Ruff, formatting
and ty checks pass for the new package and tests.

The private game generated by this package compiler passed controller typing,
native saving, camera movement, exact saved-camera restoration, resumed
interaction, Quit cancellation and clean exit. Evidence:
`build/vr/save-restore-20261010-package-composition/experiment.json`.
A separate dormant-program check opened and closed the inventory with ordinary
keyboard input, with all eight switches disabled, no submitted XR frames and
no renderer XR bootstrap. Evidence:
`build/vr/program-flat-20261010/experiment.json`. These sampled flows do not
qualify all flat gameplay or clean uninstall. Public activation, matching
renderer artifacts, transactional installation/removal and physical-headset
acceptance remain open.

### Native puzzle-scene eligibility

The broader wall fixture exposed two ordinary world views incorrectly kept on
the floating screen. CS2 uses `LaserScene`, while BEC uses
`CoordinateDeviceScene`, rather than the exact `UserScene` vtable previously
required by the VR guard. Neither failure was an OpenXR submission error or a
native camera lock.

Inspection of the normalized supported executable identified eight direct
native subclasses: AngelScene, BridgeScene, ChessScene, CircleScene,
CoordinateDeviceScene, HolyScene, LangolierScene and LaserScene. All call the
same base scene constructor and inherit the ordinary input/picker entries.
The build profile now anchors those constructor calls, primary type assignments
and inherited virtual entries. A shared verified guard is used by ownership,
geometry, world picking and hover dispatch. Unknown scene types remain rejected,
and camera-manager, controller-stack and input-lock checks are unchanged.
This is native class eligibility, not filename or room-name allowlisting.

Tests exercise every accepted scene type through geometry, world rays and
controller hover, and apply the existing modal/lock/scripted-controller rejection
cases to each. Altered subclass anchors fail before patch writes on both supported
profiles, and invalidate installed-payload verification. The default suite
passes 3,953 tests, with 20 skips and 402 deselections, in 58.33 seconds; Ruff and
ty pass.

The private game now returns to stereo in CS2 and BEC. Their actual GPU eye
captures show visible rooms, partial wall-approach fades, matching opaque black
at/through the surface, retreat and recovered world rays, with unchanged native
camera bytes and saves. LHI/LHE, MCF, GRI and TE4 samples also pass those probes.
Evidence: `build/vr/wall-broad-11-20261010/`,
`build/vr/wall-broad-12-20261010/` and `build/vr/wall-broad-14-20261010/`.
The first directory is a successful single-scene run. The second retains LHI/LHE
results followed by the original BEC rejection, before the complete subclass
fix. The third is a successful four-scene run after that fix.

A fresh 4K-canvas/2048-eye no-readback measurement with combined geometry queries
reaches 119.7 fps without HUD and 120.5 fps with HUD, recording 182 completed
glyph captures during 182 submitted frames. The earlier one-shot HUD readiness
assertion sampled a transient flag cleared during source capture, so the timing
fixture now checks completed captures across its entire interval.
Evidence: `build/vr/hud-timing-20261010-visible-models-qualified/`.
This remains a short synthetic benchmark, not sustained headset performance.
The renderer DLL is unchanged because the 252-byte scene contract is unchanged.
Broad puzzle interaction, continuous tracking during blocking loads, moving-door
and transparent-surface protection and physical-headset acceptance remain open.

The complete first twelve ordinary medium-suite views now also pass the combined
scenery/model wall-crossing fixture: R25 room and portrait, LBY front desk and
buzzers, DIN, MOP, MS2, MS3, RC1 fountain and bookstore, POU and CS2. Together
with LHI/LHE and the successful BEC/MCF/GRI/TE4 run, this covers eighteen sampled
views, not eighteen complete gameplay scenarios. All twelve latest samples
recover visible stereo and world-ray eligibility after retreat. Near/through-wall
captures have matching opaque eyes and blocked world rays. The RC1 fountain's
intermediate approach/retreat frames remain unobscured, so this does not claim
that every sampled intermediate point must fade. Evidence:
`build/vr/wall-broad-0-20261010/experiment.json` and adjacent diagnostic captures.

Native camera-cut regression checks also pass with the updated shared scene
guard and combined geometry queries. Both the room-camera cut and the R25-to-LBY
transition begin with opaque eyes and blocked world selection, then restore
visible stereo and input through the expected cut fade. Evidence:
`build/vr/camera-cut-20261010/experiment.json`. These checks do not replace
continuous blocking-load, broader cinematic or physical-headset qualification.

### Live animated door geometry

The private-game moving-geometry fixture now drives the original wardrobe and
dumbwaiter door actions through the native animation player. Its temporary ANM
files reference only the original door ACT resources, excluding Gabriel's
movement, scripted cameras, gameplay events and sound actions. The fixture
removes those private files on exit and preserves all private saves.

For each door, 25 fixed finite segments intersect its closed position. The
production combined scenery/model query reports all 25 intersections, clears
all 25 after the door opens, and reports them again after the original closing
animation restores the door. Independent native single-model and BSP queries
confirm those results and nearest-hit ordering. Authored camera bytes and the
door's gameplay selectability remain unchanged throughout. This qualifies live
animated triangles and absence of stale obstacles, not full binocular comfort
or every door in the game.

An initial experiment sampled the closing animation before it finished, which
made sequential native and production queries observe different poses. The
fixture now waits for observable model bounds to settle across 32 submitted
frames, rather than assuming a fixed delay or completion from XR frame count.
The settled wardrobe and dumbwaiter runs pass. Evidence:
`build/vr/wall-moving-door-wardrobe-20261010/experiment.json` and
`build/vr/wall-moving-door-dumbwaiter-20261010/experiment.json`.

A permanent emulated production-adapter regression reuses one adapter and the
same finite segment across model movement, hiding and restoration. It verifies
that each query observes current geometry and never retains an earlier hit as
an active obstacle. All 34 geometry tests pass in 0.40 seconds; Ruff, formatting
and ty checks pass. Broader animated actor/door coverage, transparent holes,
thin surfaces and physical-headset comfort remain open checklist gates.

### Controlled keyed holes on thin model geometry

Inspection of the original model triangle query found a native per-hit UV/color-key
path. It resolves the current texture frame, interpolates the intersected UV,
wraps to native texture dimensions and rejects keyed texels through the original
bitmap predicate. The BSP query has an analogous native color-key path. The VR
adapter continues using those native queries, rather than substituting bounding
boxes or treating every triangle as opaque.

A controlled private-game fixture loads a uniquely named copy of the original
wardrobe door with a 128-by-128 opaque/magenta checker texture. The original
overlapping door is hidden in that private process. Native material inspection
confirms the new texture name, dimensions and active keyed flag, so this test
does not silently exercise the original opaque material. Of 25 finite probes
through the thin model, thirteen hit opaque texels and twelve pass through holes.
The production combined query agrees with the independent native model query
for every probe; the BSP-only query is clear on those local segments. Authored
camera bytes and native selectability are unchanged. A desktop capture shows
the intended cutouts. Evidence:
`build/vr/wall-keyed-door-20261010/experiment.json` and
`build/vr/wall-keyed-door-20261010/native-keyed-door.png`.

Initial attempts to override an already-loaded door did not load the proposed
material and are not acceptance evidence. Loading a uniquely named native prop
through the documented-in-game `AddModel` argument layout resolved that fixture
issue. The lab's installed-texture directory is a junction to the installed
game, so all further controlled assets are staged in a separate ordinary private
directory, temporarily prepended to the private INI. Earlier temporary files and
bitmap edits were restored, and the successful fixture removes its assets and
restores the private INI and save inventory on exit.

The scene compiler now verifies the native model/BSP keyed-material branches
and the shared bitmap predicate before writing a patch and during installed-hook
verification. Regression tests reject altered dependencies instead of silently
accepting geometry that no longer preserves holes. This does not qualify
arbitrary partial-opacity materials, BSP cutouts in all scenes, edge/near-plane
comfort or physical-headset presentation; those broader checklist gates stay
open.

Validation after the keyed-material dependency checks: the default Python suite
passes with 3,978 tests passed, 20 skipped and 402 deselected in 57.57 seconds.
The focused scene, geometry and native-scene tests pass (231 tests in 1.54
seconds), as do Ruff, formatting and ty checks for the changed files. The final
private-game experiment exited successfully; no game process or temporary
controlled-texture/animation assets remain.

### Neutral tracking at authored cameras

The private-game wall fixture now resolves all eight room and eight cinematic
camera definitions from the original `R25.SIF`, rather than relying only on
gallery framing. Each pose is applied using the native cut command. After the
cut fade completes, synthetic head translation is zeroed and both GPU eye images
are read once for qualification. All sixteen poses retain visible, opaque eye
images and the active right-hand world ray; geometry queries leave the authored
camera unchanged. This includes the dumbwaiter interior, window views and SIDNEY
seated close-up. The closest measured axis-aligned surface in these samples is
about 16.18 game units away (about 40 cm at the current provisional 40-unit
calibration), so this does not prove every possible near-wall camera is safe.
Evidence: `build/vr/wall-authored-cameras-20261010/experiment.json` and paired
`*-neutral-eye*.png` captures. The process exited normally and private saves were
unchanged.

A permanent native scene regression separately uses a translated authored
camera 25 cm from a surface at 20, 40 and 80 units per meter. It verifies neutral
visibility, the same physical fade curve on approach/retreat, black before the
near plane crosses, unchanged camera coordinates and immediate response to a
native transparent-hole result becoming opaque again. All six native CTest
suites pass in 0.43 seconds with the updated scene test. No production renderer
change was needed for these checks. Applying cinematic camera coordinates as
static poses does not qualify the corresponding animated sequences or their
headset comfort. Other rooms, closer authored cameras and real-headset acceptance
remain open.

### Verified prototype artifacts and build service

`gk3hd.vr.artifact` now requires the current prototype filename/version, x86
DLL identity, pinned renderer patch/toolchain, exact OpenXR source and test
inventory, successful native and actual-GPU qualification records, and the
separate OpenXR/JsonCpp notices. Source hashes normalize CRLF, while DLL and
companion hashes remain exact. Preflight assets can be rechecked for substitution.
The ordinary renderer gate explicitly rejects the prototype provenance flag,
including a prototype renamed to look like a flat release. The VR asset type
has no release-lock method and remains development-only.

`gk3hd.vr.build` runs the existing fixed native recipe with the explicit OpenXR
variant, validates output before recording success, and keeps its local build
record under the selected game's `gk3hd/vr/renderer/`. It never installs or
activates VR. Flat renderer records remain separate. Failed compilation,
artifact verification or a recipe change cannot replace the previous successful
prototype record; local reuse rechecks the DLL, its companions and the complete
recipe digest.

A fresh build in `build/vr/recipe-artifact-qualified-20261010/` passed all six
native CTest suites, flat renderer helper/surface checks and OpenXR transport
tests on the actual GPU. Qualification includes RGBA/BGRA runtime images and
first-use critical presentation copies under both async policies. Its prototype
DLL SHA-256 is
`7c0525256d8a73ebfb936bd3fc85636a50efa0d42f548d7eb928a4c6faa9ed72`.
The package artifact inspector and recorded-build lookup both accept this fresh
output without changing its provenance. Evidence:
`build/vr/artifact-qualified-build.log` and the build's `.json`/`.txt` companions.

The package-composed private game then passed controller typing, saving, exact
camera restoration, interaction recovery, Quit cancellation and clean exit with
this renderer. Evidence:
`build/vr/save-restore-20261010-artifact-qualified/experiment.json`.
The dormant program also passed sampled room/inventory keyboard input with all
eight switches disabled and no XR frames or bootstrap. Evidence:
`build/vr/program-flat-20261010-artifact-qualified/experiment.json`.
The focused Python compiler/build/artifact checks pass with 102 tests in 4.72
seconds; strict Ruff, formatting and ty checks pass for the changed Python files.
The full default suite passes with 4,038 passed, 20 skipped and 402 deselected.
Timing is not yet consistently within the earlier Windows 60-second budget:
the profiling run took 58.11 seconds and the final run took 75.47 seconds.
The ownership graph fixture now compiles an immutable baseline once and gives
each case a fresh image/emulator; all 225 ownership checks pass in 1.16 seconds,
with no cases removed. Full-suite timing variability remains an open gate,
not evidence that the speed requirement has been achieved.
Public installation/activation, transactional removal, supported-runtime
diagnostics and physical-headset acceptance are still unfinished.

### Isolated player and reversible installation

The native resource check requires the player executable beside the original
data. Nesting it under `gk3hd/vr/player/` failed that check and is not a supported
layout. A root-level `GK3-VR.exe` succeeds when its original DirectDraw import is
redirected to `gk3hd/vr/player/ddraw.dll`. The package compiler now emits and
independently verifies that binding for each supported executable profile.
All eight activation switches remain dormant. A private renderer configuration
must target `[GK3-VR.exe]`; an initial test without that section produced nearly
blank inventory/return frames and does not count as passing evidence.

With the correctly named configuration, private-game room/inventory input works
with VR disabled and no XR bootstrap. The isolated player also passes synthetic
controller typing, native saving, exact camera restoration, resumed inventory
interaction, Quit cancellation and clean exit. Flat executable, renderer,
configuration, INI and save hashes remain unchanged. Evidence:
`build/vr/program-flat-20261010-root-sidecar-configured/experiment.json` and
`build/vr/save-restore-20261010-isolated-player/experiment.json`. The compiler's
25 focused checks pass. These tests qualify the layout, not physical controllers
or a public launcher.

`gk3hd.vr.service` now prepares, installs, verifies, updates and removes a private
player using fixed relative filenames. It rejects unmanaged collisions and
externally modified owned files, verifies full installed renderer provenance
and notices, and rebuilds the player independently from its preserved supported
original. World calibration and file hashes are the only ownership data, with
no machine-specific resource paths. It does not alter registry values, the flat
patch/renderer manifests or texture installation.

The VR-only transaction uses the same game lock and running-process guard as
flat installation, including `GK3-VR.exe`. Before publication it rechecks the
source installation and renderer identities. Its durable journal contains only
the fixed VR target inventory and cached content hashes. Interrupted install,
update and removal are tested after every file publication; failed validation
also restores the preceding generation. Recovery validates every original
payload before changing any file, retains journals for missing/corrupted cache
or external edits, rejects invalid identities and links/junctions, and cannot
accept a partial generation as committed. Three symlink tests are skipped on
this host because symlink creation is unavailable; the actual Windows-junction
rejection test passes.

A separate new private target passed real supported-executable compilation,
prototype publication, independent disk verification, calibration update and
removal in 18 seconds. All original flat files were unchanged and no owned VR
files remained. Evidence: `build/vr/managed-install-20261010.json`.
This is package-service qualification, not the complete public install/launch
flow. Runtime diagnostics, the opt-in launcher, immersive qualification through
the managed service and physical-headset acceptance remain unfinished.

The focused compiler, build, artifact and installer checks pass; the new
service/state checks take 1.59 seconds and the recovery checks take 3.93 seconds.
Ruff, formatting, ty and spelling checks pass for the changed files. The full
default suite passes with 4,136 passed, 23 skipped and 402 deselected, but takes
127.78 seconds in this run. The default Windows test-time gate is therefore not
met and remains open for profiling, rather than being inferred from smaller
focused suites. No live game process remains, and none of these experiments
installed the VR prototype into the user's actual Steam game.

### Managed startup and development commands

The opt-in launcher creates the verified `GK3-VR.exe` suspended, checks all
eight dormant activation switches before any writes, enables and verifies them,
then resumes the primary thread. It owns only its child process. Activation
failure or cancellation stops that child, and a transient process-status error
cannot bypass the termination attempt. Cleanup failures retain the original
operation error. The executable on disk remains dormant.

Runtime selection validates the x86 OpenXR manifest and PE32 DLL. It respects
an explicit manifest, the inherited runtime selection and Windows' 32-bit
registry view. When no x86 registration exists, an installed SteamVR manifest
can be selected for the child only. Selection does not establish headset
availability. The launch supervisor verifies installed artifacts, strips stale
development controls from its child environment and requires submitted native
VR frames rather than accepting a silent flat fallback. No system runtime,
registry value or parent environment is changed by this launcher.

The first pre-startup experiment failed with Windows status `0xc0000135` because
the new private game copy lacked its original Bink DLL. With that fixture fixed,
the player reached the title screen. Host-mouse Restore automation then failed
because VR already owned pointer input. Replacing those actions with acknowledged
controller rays passed title Restore, native keyboard typing, saving, exact
camera restoration, inventory recovery, Quit cancellation and clean exit.
The test restored its temporary diagnostic executable before independently
verifying and removing the installed player. Flat files stayed unchanged and
no VR-owned installation files remained. Evidence:
`build/vr/save-restore-20261010-managed-suspended-launch/experiment.json`.
This qualifies the managed service/process flow with synthetic controllers,
not the complete public launcher or physical headset acceptance.

Development-only commands are now exposed explicitly, with a prototype warning:

```shell
uv run gk3hd vr build       # Build/test under <GAME>/gk3hd/vr/renderer/, without installing
uv run gk3hd vr install     # Use the verified local prototype, preserving flat play
uv run gk3hd vr verify      # Recheck owned artifacts and independently rebuild the player
uv run gk3hd vr launch      # Supervise an opt-in VR session with child-only runtime settings
uv run gk3hd vr uninstall   # Remove unchanged owned player files, retaining builds and logs
```

Every command accepts `--game-dir`. Install accepts an explicit verified `--dll`
and `--units-per-meter`; launch accepts a `--runtime` manifest override and
`--hand left` for left-handed pointing (right is the default). No
prototype is auto-downloaded, installed through the ordinary `install` command
or described as release-ready. Source toolchain requirements still apply to
building. Real runtime diagnostics, controller new-game startup, sustained
performance, comfort and physical-headset acceptance remain open.

The focused Python VR suite passes with 182 tests and three symlink-privilege
skips in 12.10 seconds. Ruff, formatting and ty pass for the changed VR files.
The complete default test-time budget has not been requalified by this focused
run. The actual installed Steam game is untouched and no live game child remains.

The actual public `vr install`, `vr verify` and `vr uninstall` commands also
passed in the fixed private target, without mocking their service/compiler or
artifact validation. The test verified unchanged flat files and complete removal
of the owned installation inventory. Evidence: `build/vr/cli-install-20261010.json`.
This does not close the public launch/headset qualification gate.

The full default regression run passes with 4,189 tests, 23 skips and 402
slow-test deselections in 70.87 seconds. The Windows under-60-second timing gate
remains open. A separate state regression now rejects oversized JSON calibration
integers as actionable validation errors rather than leaking an overflow.

### Public launcher qualification and fresh-game coverage

The actual public launcher now passes controller-only opening-movie skipping,
title interaction and clean Quit with the GPU test runtime. It uses the verified
installed executable without diagnostic binary changes, enables VR before
startup and exits through native controls. Independent disk verification and
removal pass afterward, with flat files unchanged. The private fixture adds
only the synthetic controller feed and observes the real owned process.
Evidence: `build/vr/public-launch-20261010/title-quit.json`.

Initial readiness failures were not evidence of a broken renderer. The startup
capture needed a live visible-window check, and a fresh game has a disabled
Restore button. The title detector now accepts the three enabled Intro, Play
and Quit controls only in their expected spacing, does not offer disabled
Restore as a target and still rejects incomplete title screens. Readiness
regressions cover 1024×768, 1280×800 and 4K. The focused readiness, supervisor,
process and CLI checks pass with 56 tests in 2.40 seconds; full lint passes.

The controller-only fresh-game experiment now passes opening-movie skipping,
Play, `r25/110a` stereo, native toolbar Options, Quit and Yes with a clean exit.
The earlier missing submenu was a fixture timing failure: native initialization
temporarily disables the Options button. Native input traces confirmed correct
pointer coordinates and press/release dispatch to that disabled button. The
fixture closes/reopens the toolbar until native enablement, without forcing
the button on or changing game behavior. The final passing run uses the exact
verified player without diagnostic binary changes. Independent verification
and removal pass, flat files stay unchanged and game preferences are restored.
Evidence: `build/vr/public-launch-20261010/new-game.json`. This is synthetic
controller/GPU-test-runtime qualification, not physical-headset acceptance.

A separate read-only native SteamVR discovery probe did not respond within
15 seconds. That does not diagnose a runtime incompatibility or establish a
working headset session. The public launcher was also tested against actual
SteamVR selection with a shortened six-second startup deadline: no VR frames
were submitted, the launcher reported the failure, terminated its owned child,
preserved player bytes and allowed independent verification and removal.
Evidence: `build/vr/runtime-discovery-20261010/probe.json` and
`build/vr/public-launch-20261010/real-runtime-failure.json`.
Successful real-runtime presentation, the normal startup deadline, reconnection,
sustained compositor performance and physical-headset acceptance remain open.
The actual installed Steam game is unchanged and no test game child remains.

### Isolated SteamVR virtual-headset workbench

On 11 October, the installed SteamVR runtime passed native x86 OpenXR discovery
with its built-in null driver. The probe reports SteamVR/OpenXR and two
1280×1280 eye targets in 1.12 seconds. The compositor log confirms creation of
its graphics device on the NVIDIA GeForce RTX 4090. This qualifies discovery
and the workbench, not game graphics/session rendering or headset presentation.

The fixture uses child-only `VR_PATHREG_OVERRIDE`, `VR_CONFIG_PATH` and
`VR_LOG_PATH` settings under the ignored `build/vr/` directory. It checks that
no SteamVR processes already exist, verifies the private paths before startup,
stops only newly started runtime components whose executable paths match the
installed SteamVR directory, and confirms that global SteamVR/OpenVR settings
remain byte-for-byte unchanged. Physical headset drivers and the Steam client
are not modified. Evidence: `build/vr/steamvr-null-20261011/probe.json` and its
private runtime logs. Physical-controller bindings, sustained compositor
performance, comfort and real-headset acceptance remain open.

The subsequent bounded game tests create a Vulkan OpenXR session through
actual SteamVR and submit title panels and native `r25/110a` stereo using the
independently verified installed player and renderer. No graphics/runtime
calls are mocked. The title test keeps all eight activation switches enabled;
the room graphics test disables controller input ownership in memory solely
to select Play with the host mouse, since the null driver has no controllers.
Disk bytes remain unchanged. These runs end by explicit owned-child cancellation,
not native/controller Quit, and are not complete public-launch acceptance.
Verification/removal pass afterward, preferences are restored and the flat
files remain unchanged. Evidence: `build/vr/steamvr-null-20261011/game.json`,
`world.json`, their wrapper records and private renderer/compositor logs.

The initial run submitted one panel then stopped progressing. SteamVR logged
the static virtual headset entering standby. Disabling compositor pausing on
standby, extending the screen timeout and disabling dashboard launch in the
private test configuration allowed continuous submission; no such settings
are applied to users or production installations. This isolates a workbench
condition but does not qualify real-headset idle/focus behavior.

Performance remains an open gate. The title sample submitted 98 frames over
3.04 seconds. The room sample has 98 stereo submissions at its end and roughly
the same submission rate, not twice that rate: panel and stereo counters must
not be added as independent display frames when they share a frame. SteamVR's
compositor logs report dropped/reprojected frames for these null-driver runs.
Consequently neither frame counters nor the desktop screenshot establish
correct headset presentation or refresh-rate performance. The next work is
to distinguish virtual-display timing/occlusion limitations from actual
OpenXR/game bottlenecks, inspect compositor output, and qualify continuous
presentation before requesting physical-headset testing.

### Real-runtime timing controls and display-mode comparisons

The independent x86 Vulkan/OpenXR timing fixture clears both real SteamVR eye
images, releases them and submits a projection layer using the same native
runtime implementation, without GK3 or the modified renderer's transport.
It records explicit completion metrics rather than accepting exit code zero
alone. Early zero-code exits were not passing tests: SteamVR's fresh private
configuration auto-launched Room Setup, sent an XR exit request and forcibly
terminated the probe when it did not stop. The probe now honors runtime exit,
and a generic universe-2 calibration in the private configuration prevents
that setup interruption. No user calibration is copied or changed.

With that fixture corrected, 180 binocular frames complete in about 1.60
seconds, approximately 112 frames/s, both with the virtual display onscreen
and at its earlier offscreen position. Mean frame-wait time is approximately
7.6 ms. Evidence: `build/vr/steamvr-visible-20261011/timing-run.json` and
`build/vr/steamvr-null-20261011/timing-run.json`; fixture sources and build
remain ignored under `build/vr/runtime-timing/`.

The corrected game fixture measures scene and panel counters separately:
they may describe shared frames and must not be summed as display throughput.
A 4K native-desktop hotel-room sample submits 309 stereo frames in 3.006
seconds, approximately 103 frames/s. The repeated 1280×800 sample submits
95 stereo frames in 3.003 seconds, approximately 32 frames/s; moving the
virtual display onscreen still gives approximately 32 frames/s. Recorded
active desktop modes retain 120 Hz in both fullscreen cases, disproving a
simple refresh-rate reduction. These are short submission samples, not
sustained headset-delivered performance. Compositor dropped/reprojection
reports remain unresolved. Evidence: `build/vr/steamvr-native-20261011/world.json`,
`build/vr/steamvr-null-20261011/world.json` and
`build/vr/steamvr-onscreen-20261011/world.json`.

A windowed 1280×800 comparison at the unchanged 4K/120 Hz desktop reaches
the native title screen but submits no VR frames, including after explicitly
foregrounding the game. This is a failing mode, not performance evidence and
not a supported-mode claim. Evidence:
`build/vr/steamvr-visible-20261011/world.json`. The next investigation must
separate the game's presentation hooks, focus/mode behavior and XR scheduling;
the 4K result alone cannot close low-resolution/background compatibility.
All game runs verify/remove the private installation, restore game preferences,
stop owned processes and preserve flat files and global SteamVR/OpenVR settings.

### Windowed presentation boundary and actual compositor images (11 October)

Native telemetry identified the windowed failure: zero Flip calls, zero panel
presenter calls and hundreds of thousands of ordinary blits. The VR finalizer
was linked only to the fullscreen pre-Flip callback. The new VR-only
`VRPresentationCompiler` hooks the verified windowed presentation entry at
`0x0055C51D`, before retry initialization rather than inside the blit loop.
It calls the live composed presenter, including text/input consumers, with
registers and flags preserved. Disabled producers remain dormant, but a pending
deferred world is finalized even after both producer switches are disabled.
The native blit, fullscreen path and real successful-Flip generations remain
unchanged. The complete deterministic player rebuild includes this hook.

The actual SteamVR windowed title test now submits 348 panel frames in
3.015 seconds (about 115 frames/s), where the same mode previously submitted
none. The latest fullscreen native-4K hotel-room test submits 335 stereo frames
in 3.009 seconds (about 111 frames/s), preserving existing fullscreen behavior.
These remain short submission tests, not headset-delivered performance claims.

The ignored `build/vr/compositor-capture/` helper uses SteamVR's actual OpenVR
compositor mirror API and a hardware D3D11 device to read both final eye images.
It requests both shared mirror textures first, then requires two compositor
frame advances before reading them. An initial diagnostic had read the newly
requested right-eye texture too soon and found black; synchronized captures
show populated, distinct views in both eyes. CPU readback occurs only in this
external diagnostic, never in the production VR transport or benchmark interval.
The helper does not replace OpenXR integration or introduce an OpenVR player
dependency. Both hotel-room images and the title panel were visually inspected.
Evidence: `steamvr-native-20261011/world.json` and
`world-compositor-{left,right}.bmp`, plus
`steamvr-visible-20261011/game.json` and `title-compositor-left.bmp` under
`build/vr/`.

Windowed desktop presentation is still black in GDI and WGC captures, while
SteamVR displays the title panel. Pixel-based Play automation therefore cannot
qualify windowed room/input flow yet. The initial native-button metadata probe
did not establish a valid title-button layout and is not acceptance evidence.
Low-resolution fullscreen pacing, continuous compositor quality, desktop mirror
presentation, background behavior and physical-controller/headset acceptance
remain open. Compositor timing in this null-driver fixture reports no physical
frame presents, so dropped-frame logs cannot establish physical scanout quality.

Focused Python regression: 230 passed, 3 skipped in 9.02 seconds. Formatting,
Ruff and strict type checks pass. New emulation tests cover dormant panel/world
ownership, mid-frame cancellation, a live callback replacement, missing callback,
native register/flags preservation, unchanged native generation and rejection
of altered source/installed hooks across the supported profiles. All actual
game runs verified removal and unchanged flat root files/global runtime settings.

### Windowed modal mirror and room qualification (11 October)

The title-screen desktop failure described above is now resolved. Strict legacy
presentation suppresses intermediate blits, but the windowed VR panel path also
needed to present its completed modal page. D3D9 Present reads the swapchain
backbuffer, which can differ from the game's current render target. The new
renderer helper copies that target to the backbuffer on the GPU before Present,
only after a successful ordinary modal-panel submission in nonexclusive mode.
It does not present partial overlays, change fullscreen behavior, introduce CPU
readback or access a borrowed OpenXR image after release. The ordinary desktop
brightness path is retained.

A fresh pinned build passes six native tests and the flat/OpenXR/async-copy GPU
qualification checks. Its SHA-256 is
`5c4c9e633b65cf02a2a984e58d788428715ad442a8207f69635459c1675b95b0`,
with provenance and qualification records under
`build/vr/windowed-mirror-copy-qualified-20261011/`.

The actual SteamVR title test submits 352 panels in 3.018 seconds, approximately
117 frames/s. Final desktop and compositor captures show the title panel.
Windowed Play automation also needed a fixture correction: WGC captures include
the window caption, whereas button coordinates are client-relative. The private
test now captures the exact client area through GDI rather than treating the
caption as game pixels. This is a diagnostic-fixture change, not a gameplay or
controller-coordinate change.

The windowed 1280×800 hotel-room sample reaches native `r25/110a` and submits
356 stereo frames in 3.008 seconds, approximately 118 frames/s. Actual compositor
captures contain both eye views. A repeat with the matching renderer at native
4K submits 335 stereo frames in 3.009 seconds, approximately 111 frames/s.
The world desktop mirror remains black, so modal-mirror success does not close
the world-mirror requirement. The Play test temporarily disables controller
ownership in the owned process to use the host mouse, and does not qualify
actual SteamVR controller input.

Minimizing the window exposes a remaining performance failure: six stereo
frames over two seconds, approximately 3 frames/s. Restoring it recovers 122
frames over one second. This does not yet distinguish native focus throttling,
desktop presentation or runtime scheduling, and background responsiveness stays
open. The earlier low-resolution fullscreen slowdown also remains unresolved.
These short virtual-headset submission samples are not sustained physical
headset performance or comfort acceptance.

Evidence: `build/vr/steamvr-visible-20261011-mirror/{game,world}.json`,
its `windowed-final.png`, `world-desktop.png` and compositor eye images, and
`build/vr/steamvr-native-20261011-mirror/world.json`. Each run removes the private
installation, restores game preferences and leaves flat files and global runtime
settings unchanged. Test-owned process cancellation is not native Quit evidence.
The focused 230-test suite passes again, with three skips; compilation contention
increased that repeat to 20.28 seconds. The full default suite has not been rerun
since these renderer changes.

### VR-only background presentation (11 October)

The minimized-window stall described above is now resolved in the isolated VR
player. Read-only native-thread sampling found the game waiting in `WaitMessage`
when its inactive-window counter was positive. Bypassing that wait alone was
insufficient: the completed-page routine also returned early while inactive,
leaving a deferred stereo frame unfinished.

The VR presentation compiler now hooks both verified boundaries. Active VR, or
a pending frame that needs cancellation, bypasses only the inactive-window wait.
The original DirectDraw cooperative-level check still blocks updates on device
failure. At the completed-page boundary, an inactive VR frame is finalized before
the original early return skips desktop presentation. Native focus state,
controller release safeguards, inactive counters and successful-Flip generations
are unchanged. With VR dormant, the original update/wait behavior is retained.
Normal active-window presentation does not invoke the callback twice.

Actual SteamVR tests now submit approximately 123 frames/s while minimized and
124 after restoration, for both the title panel and hotel room. The windowed
room submits 358 stereo frames in 3.006 seconds, approximately 119 frames/s,
before minimizing. Captures taken while minimized contain both distinct room
eye images, which were visually inspected. Controller ownership is re-enabled
after the host-mouse Play step and before measurement, but the virtual headset
has no physical controllers, so this is not controller acceptance.

A repeated native-4K room test submits 348 stereo frames in 3.011 seconds,
approximately 116 frames/s. The independently verified player SHA-256 is
`63843d5546f734297036fc61b57c880be3a21c2801a334b77b150b1f98449f01`.
The renderer recipe and qualified DLL remain unchanged from the modal-mirror
build. The separate 1280×800 fullscreen sample still submits approximately
32 frames/s, and the world desktop mirror remains black. These issues are not
resolved by the background fix.

Evidence is recorded in
`build/vr/steamvr-visible-20261011-mirror/{game,world}.json`,
`world-minimized-{left,right}.bmp`, and
`build/vr/steamvr-native-20261011-mirror/world.json`.
All runs verify private installation removal, unchanged flat files and unchanged
global runtime settings. Process cancellation is not native Quit acceptance.
These short virtual-headset samples do not establish sustained physical-headset
frame pacing, scanout, focus behavior or comfort.

Native emulation regression tests cover active/dormant producers, pending-frame
cancellation, inactive counters, missing callbacks, device-health failures,
register/flags preservation and rejection of modified hook bytes or surrounding
instructions across supported executable profiles.

The full default Python suite passes after these changes: 4,237 passed,
23 skipped and 402 slow-test deselections in 63.43 seconds. Full formatting,
lint, strict type and spelling checks pass. The under-60-second default-suite
timing gate remains open.

### 11 October: reported HUD residue and runtime shutdown

The experiment wrapper previously forcibly terminated SteamVR components after
cancelling the game. That can make the still-running monitor report an unexpected
runtime exit. The private workbench now posts a normal close request to windows
belonging to its verified, owned monitor process and waits for orderly shutdown.
Forced termination is only a bounded failure fallback, recorded separately.
Three actual-runtime runs complete without that fallback. The monitor logs
`ShutdownRequested`, orderly audio shutdown and the server's `Graceful exit`.
This fixes experiment cleanup, not yet the separate player-native Quit or
physical-headset lifecycle acceptance gates. Global runtime configuration and
flat installation hashes remain unchanged.

Read-only HUD time series and both-eye compositor captures now cover the score
hold, native one-second fade and disappearance. Windowed 1280×800 and two native
4K desktop runs retire the owner, release the source and publish zero HUD parts
after the fade. Inspected later eye images and the 4K desktop capture contain no
lasting score residue. Native source/destination fade weights are complementary,
and the source opacity decreases rather than snapping directly from one to zero.
A thin white line was visible in an earlier low-resolution fullscreen compositor
sample. That observation and the user's report remain open, since the later
captures do not establish its cause or prove all transitions are artifact-free.
No unsupported fade tolerance or speculative renderer change was introduced.

Evidence remains private under
`build/vr/steamvr-visible-20261011-mirror-score-lifetime/`,
`build/vr/steamvr-native-20261011-mirror-score-native-lifetime/` and
`build/vr/steamvr-native-20261011-mirror-score-fade-detail/`.
These include `score-trace.json`, successive left/right compositor images and
shutdown logs. Short native-4K samples continue submitting approximately
113–115 stereo frames/s, not a qualification of physical-headset delivery.

The VR release targets the runtime-recommended per-eye rendering dimensions,
not compatibility with 1024×768 or other legacy desktop modes. OpenXR swapchains
already use those recommended dimensions. Previously the engine drew each eye
through a desktop-sized intermediate and copied/resampled it to the swapchain.
The following change removes that dependence. Low-resolution fullscreen
reproduction is diagnostic work, not a new release requirement.

### 11 October: runtime-sized native eye rendering

The coordinator now uses each eye's OpenXR-recommended dimensions rather than
the desktop canvas. Reusable private color/depth targets preserve the game's
formats and support independently sized eyes without reallocating every frame.
Internal references avoid retaining their owning device in a cycle. Native
camera/projection, zero-origin clipping, viewport and full clears all match
the eye target. Render target, depth and drawing state are restored on success
and failure, without writing either eye into the desktop target.

Tests cover unequal eye sizes, invalid second-eye dimensions, draw/copy failure
restoration and native camera/clipping/clear scope. The actual-GPU fixture
preserves one-pixel detail at the final pixel outside its smaller desktop canvas
and verifies unchanged desktop pixels after successful and failed eye draws.
All six native tests, flat GPU checks, RGBA/BGRA XR transport and first-use
asynchronous-copy qualification pass. The targeted Python suite passes 616 tests
with three skips. Changed Python files pass formatting, lint and strict typing.

Qualified renderer:
`build/vr/headset-native-eye-detail-qualified-20261011/`.
DLL SHA-256: `21f41c66b5a3221f59c94f7ce50bfad33e4e227ec9db670ffb7c78aaee510155`.
Private player SHA-256:
`0df33137e5180659cd23d829cd31e18e44d7ce064361bc32ba3c6a9ed47699d9`.

Actual SteamVR records a 1568×1568 native engine eye target with both a 1280×800
desktop window and a 4K desktop. The compositor mirror captures are 1920×1920,
which is the mirror image size, not the application's eye size. Windowed
submission is 353 frames in 3.006 seconds, about 117 frames/s, and about 123
minimized/restored. Fullscreen submission is 269 frames in 3.015 seconds, about
89 frames/s. Correct native eye resolution is verified, but fullscreen desktop
cost and sustained physical-headset pacing remain performance work.

Evidence and both-eye captures:
`build/vr/steamvr-visible-20261011-mirror-headset-native-eye-detail-windowed/` and
`build/vr/steamvr-native-20261011-mirror-headset-native-eye-detail-fullscreen/`.
Both verify unchanged flat files/global preferences, private uninstall and
graceful workbench shutdown without forced runtime termination. The score-fade
regression and black windowed world mirror remain separate open items. These
tests do not qualify physical-controller, native-Quit or headset acceptance.

### 11 October: world mirror and real-runtime native Quit

The black desktop room was a presentation-routing defect. The windowed mirror
ran only after opaque modal panels, not after completed world or isolated
overlay frames. All successful completed windowed frames now upload pending
desktop CPU regions and mirror the restored desktop render target on the GPU.
Private eye targets are never copied into that desktop surface. Close, failed
and unsubmitted frames do not cause an extra presentation. Desktop occlusion
does not invalidate an already submitted XR frame.

The pinned renderer recipe in `build/vr/world-mirror-qualified-20261011/`
passes all native, flat-GPU, RGBA/BGRA XR and asynchronous-copy checks.
DLL SHA-256: `157443f09ed23d2ae4271ff6ada900a3d98c36bf01335cf60ac5d9f3376b3149`.
The player hash is unchanged from the native-eye build above.

Actual SteamVR renders a visible desktop room, both native-resolution eyes and
the native Quit dialog. The public launcher passes Quit → No → resumed stereo
→ Quit → Yes with exit code zero and no supervisor error. The wrapper then
requests orderly SteamVR shutdown, without forced server termination. These
tests explicitly use host keyboard/mouse with controller ownership disabled for
the UI actions, not synthetic claims of physical-controller qualification.

The same run submits 352 stereo frames in 3.002 seconds, approximately 117/s,
246 frames over two seconds minimized and 123 over one second restored.
The eye target remains 1568×1568, independently of the 1280×800 desktop mirror.
These are short submission samples, not delivered-headset performance.

Read-only native HUD samples show opacity one, then decreasing source opacity
and complementary destination weight, followed by retired owner/source pointers
after the native one-second fade. Eleven successive actual compositor captures
over ten seconds were inspected in both eyes. Enlarged glyph-area comparisons
show the text fading and no visible glyph residue after disappearance.
Ordinary animated-world differences prevent treating raw frame subtraction as
a pixel-exact residue detector. The earlier reported artifact still needs
broader reproduction, rather than claiming this sample proves every transition.

Evidence, derived inspection images and graceful shutdown logs stay in
`build/vr/steamvr-visible-20261011-mirror-native-quit-score-2/`.
Private uninstall, flat-file hashes and global runtime settings are unchanged.

### 11 October: public-launcher menu activation and HUD retirement

The broader actual-runtime UI test exposed a launcher integration omission:
native menu capture stayed disabled, although controller-independent HUD capture
was enabled. Consequently graphics menus fell back to an opaque completed-page
quad, including a flat room behind the menu. Earlier individually enabled
producer tests did not exercise this public activation boundary.

The final-page bridge now publishes both menu and HUD capture ownership before
ordinary UI composition. Both render halves must be active, independently of
input ownership. Disabling either half withdraws both producers. An executed
native-code regression covers all four ownership combinations across all three
supported executable profiles, including stale opposite producer flags.

The normal managed launch now renders isolated graphics and expanded graphics
menus over the stereo room. Actual compositor images were inspected without
the flat-background quad. Inventory, return to the world, Quit cancellation and
confirmed native exit pass. Runtime shutdown is graceful, with flat files and
global runtime settings unchanged. These actions use explicit host input, not
physical-controller acceptance.

The GPU transport regression additionally compares every eye pixel with its
clean-world snapshot through HUD opacity steps and verifies that retirement
removes the HUD quad from the submitted layer list. Native, flat GPU, RGBA/BGRA
XR and first-use asynchronous-copy qualification all pass.

Qualified renderer: `build/vr/hud-retirement-qualified-20261011/`.
DLL SHA-256: `f3b38be022110bd43119256ed628165b65c158dc93fe3e824c2cf8739f15cb84`.
Player SHA-256: `b6e9913efc036e082693dddf18a8deff834e194c2b21d408c008ed47a9668f92`.
Actual runtime evidence:
`build/vr/steamvr-visible-20261011-mirror-menu-ownership-fixed-20261011/`.
Focused Python tests: 525 passed, three skipped in 19.06 seconds. Strict typing
passes. This strengthens the sampled fade result but does not close the earlier
reported score-artifact or physical-headset acceptance gates.

A follow-up counter-only run samples the room for 12 seconds (119.08 stereo
submissions/s) and expanded advanced graphics for six seconds (118.33/s).
Both use the same 1568×1568 eye target, with no screenshots inside the measured
intervals. Inventory, return to stereo and native Quit pass afterward, followed
by graceful runtime shutdown and unchanged flat files/global runtime settings.
Evidence: `build/vr/steamvr-visible-20261011-mirror-menu-room-pacing-counter-20261011/`.
These measurements do not establish CPU/GPU frame-time percentiles, delivered
headset performance or the heavier 4K desktop-mirror case.

The preceding optional timing-API-layer attempt did not reach frame submission
and timed out. Its result is explicitly excluded from performance evidence.
The private player was stopped, owned installation removed and recorded flat
display settings restored. Subsequent workbench runs persist their original
registry snapshot before installation so interruption recovery has exact data.
The counter-only run uses no timing API layer. Physical runtime startup and
failure-recovery qualification remain open.

### 11 October: actual-runtime driving map and SIDNEY coverage

The driving-map modal and three location-hover captures were inspected in actual
SteamVR compositor images. The sampled overlays retain appropriate size and
placement, without an enlarged-location regression. Quit cancellation resumes
the same modal and confirmed Quit exits with code zero, followed by graceful
runtime shutdown. Escape does not dismiss the native debug-opened map, so the
fixture no longer invents an Escape-close requirement. Evidence:
`build/vr/steamvr-visible-20261011-mirror-driving-map-hover-20261011/`.

SIDNEY is entered through the native day-two Grace setup script. Home, email and
opened email content render as modal panels and were inspected. Quit cancellation
resumes modal presentation and confirmed native exit returns zero, with orderly
SteamVR shutdown. However, two `DDERR_INVALIDRECT` transfers are logged during
final shutdown. This is partial qualification, not an error-free gameplay pass.

A private, memory-only native-error tracer verifies no reported DirectX errors
at the captured home/email/content pages or the first Quit dialog. A diagnostic
100 ms delay on failing calls allows observation before final process teardown.
The final two callers return to `0x0054FA81`, the shared final-bitmap transfer.
Their sampled destination rectangles extend above/below the 1280×800 surface,
and their source contains a 4096×576 dense raster with logical source geometry.
Precise ownership, source transformation and clipping still need correction.
The tracer is not part of the production player or performance qualification.

Evidence:
`build/vr/steamvr-visible-20261011-mirror-sidney-email-20261011/` and
`build/vr/steamvr-visible-20261011-mirror-sidney-exit-error-callers-20261011/`.
The private game's error log changes, so its full-file equality check correctly
reports false. This must not be described as an unchanged complete file set.
VR-owned files are removed and global runtime preferences restored. The installed
Steam game is not used or modified by these runs.

The first tracing attempt had a diagnostic-buffer boundary defect and crashed
the private player before presentation. The trace buffer was corrected and
bounded, recovery completed and subsequent traced gameplay/exit completed.
This diagnostic failure is not attributed to the unmodified VR player. The
workbench now retains exact pre-run registry/file snapshots and performs
fixed-scope interruption cleanup without allowing a file-check failure to skip
runtime shutdown.

### 11 October: SIDNEY final-Quit ownership corrected

The captured native call stack identifies a synchronous SIDNEY root traversal
while ConfirmQuit's retained input affine is still published. The shared high
blitter applied the dialog's centered affine first, then SIDNEY's final blitter
applied the laptop's height fit. That double transformation placed the dense
top and bottom frame images outside the physical surface. Earlier out-of-process
scope reads were taken after the traversal and were not evidence that SIDNEY
was inactive at the failing transfer.

The shared dispatcher now defers destination fitting to a live SIDNEY draw
scope, while preserving the source-density helpers and the separate console
and tooltip owners. It does not clear the modal's input state, clamp arbitrary
rectangles, swallow DirectDraw errors or change dense artwork. Eighteen
emitted-code regression cases verify top/bottom frame fitting, nested laptop
draws, retained Quit input, unchanged caller/source rectangles and ordinary
dialog fitting when no laptop traversal is active. The complete patch and VR
compilers pass for all three executable profiles.

The fresh unmodified launcher passes SIDNEY home, email, opened email, Quit →
No → resumed modal and Quit → Yes → exit zero. Compositor captures were
inspected. No native-error hook or artificial error delay is present in this
qualification run. All original private-game files, including its error log,
remain unchanged, owned VR files are removed and SteamVR stops gracefully
without forced components or global preference changes.

Evidence: `build/vr/steamvr-visible-20261011-mirror-sidney-shutdown-production-qualified-20261011/`.
Player SHA-256: `c6bdadf14b8cafff0fd8a575952feb6c8652b60139ab24b0f93faa3ded1cae46`.
Renderer remains the qualified HUD-retirement build above. Focused Python
regressions: 1,731 passed, three skipped in 27.73 seconds. Ruff and strict typing
pass. These are host-input virtual-headset samples, not physical-controller,
headset readability or broad gameplay acceptance.

The full default suite also passes: 4,267 tests, 23 skips and 402 deselections
in 66.45 seconds on this Windows machine. This run exceeds the earlier desired
60-second fast-suite target, so it is not a successful test-duration gate.
The complete `poe lint` task passes formatting, Ruff, strict typing and spelling.

### 11 October: sustained submission timing and expanded-menu profiling

The private workbench now verifies 32-bit runtime discovery before starting the
game, rather than treating the appearance of `vrserver` as runtime readiness.
Both frame-timed runs use the current qualified renderer/player hashes above,
the public launcher and the runtime-recommended 1568×1568 eye targets. The
desktop canvas changes independently. Diagnostic compositor captures and
thread-suspension samples are outside the timed intervals.

| Desktop canvas | Room submissions/s | Room interval p95/p99 | Expanded menu submissions/s | Menu interval p95/p99 |
| --- | ---: | ---: | ---: | ---: |
| Windowed 1280×800 | 118.58 | 12.24 / 14.92 ms | 112.49 | 11.46 / 13.14 ms |
| Fullscreen 3840×2160 | 118.08 | 9.51 / 11.24 ms | 57.99 | 18.52 / 19.85 ms |

The room interval is twelve seconds and the expanded-menu interval six seconds.
These are application submission intervals, not physical-headset delivered
frames or GPU timestamps. The null driver's reported 90 Hz period does not
explain the approximately 120 submissions/s ceiling, so delivered pacing and
missed/reprojected frames must still be qualified independently. The earlier
short fullscreen result near 89 frames/s must not be generalized to the warmed
room interval. OpenXR calls account for approximately 0.74 ms per expanded-menu
frame at 4K, leaving about 16.54 ms elsewhere in the frame.

A separate 240-sample primary-thread profile identifies legacy desktop CPU
readbacks, uploads and large memory copies among the repeated hot paths. The
renderer load base is derived from the captured exported panel bridge, not
guessed. A diagnostic relink supplies symbols with identical `.text` bytes to
the qualified DLL and does not replace that DLL or its qualification record.
This profile narrows the menu investigation but is not a measured speedup.

The timing runs complete native Quit with exit zero, remove owned VR files,
preserve all original private-game files and global SteamVR settings, and stop
SteamVR gracefully without forced components. The installed Steam game remains
untouched.

Evidence stays ignored under `build/vr/`:
`steamvr-visible-20261011-mirror-windowed-frame-timing-20261011/`,
`steamvr-native-20261011-mirror-native-frame-timing-20261011/` and
`steamvr-native-20261011-mirror-native-menu-profile-20261011/`.

A same-process isolation test temporarily replaces only the two private menu
mirror helpers with successful no-copy returns, leaving native capture, stereo
rendering and overlay submission active. This is memory-only diagnostic code,
not a renderer fix or a passing desktop-mirror acceptance test. The helpers are
restored before normal inventory and Quit checks. In this run, expanded-menu
submission rises from 53.16 to 59.66 frames/s, with interval medians changing
from 17.87 to 16.59 ms. One 165.97 ms outlier affects the original interval's
mean. The remaining cost is substantial: omitting desktop menu copies alone
does not recover room performance and is not an acceptable shipping solution.
Both intervals retain the same 1568×1568 eyes and two submitted composition
layers. Native exit, complete private-file equality and graceful runtime
shutdown pass after restoring the helpers.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-menu-copy-isolation-20261011/`.

### 11 October: bounded fast 2D transfers improve expanded-menu performance

A private memory-only trace filters `DownloadSurfaceData` to the live desktop
back surface. Its 164 recorded calls include 109 small `Blt` rectangles and 55
`BltFast` destination downloads with no rectangle. Disassembly identifies the
latter as the destination call, not a source save-under download. The native
tooltip presenter uses `BltFast` for its small completed cache, but that renderer
path previously downloaded and dirtied the entire 4K target every time.

All five DirectDraw surface interfaces now pass the source crop into readback,
derive a bounded destination rectangle and use it for destination readback and
upload damage. Invalid, missing, empty, overflowing or out-of-bounds geometry
retains conservative synchronization and native error handling. Transparent
transfers still read the required background. No desktop copies, native draws,
eye pixels or overlays are omitted, and no diagnostic hook ships in the DLL.

The source-only experiment did not recover menu performance, so it was not
reported as an improvement. The complete regional-transfer build passes native
and GPU/OpenXR qualification. Added tests cover exact crop translation, the
last canvas pixel, invalid/overflow inputs, GPU cursor save-under, keyed cursor
drawing and restoration after subsequent GPU invalidation.

| Desktop canvas | Room submissions/s | Room interval p95/p99 | Expanded menu submissions/s | Menu interval p95/p99 |
| --- | ---: | ---: | ---: | ---: |
| Windowed 1280×800 | 119.16 | 10.22 / 14.75 ms | 117.49 | 9.61 / 14.65 ms |
| Fullscreen 3840×2160 | 118.50 | 9.50 / 11.28 ms | 78.32 | 13.88 / 15.39 ms |

Both runs retain runtime-recommended 1568×1568 eyes. The 4K expanded-menu mean
interval improves from 17.28 to 12.76 ms relative to the previous qualified
baseline, but remains over the null driver's 90 Hz budget. These are submission
intervals, not GPU timestamps or delivered physical-headset frame rates.
Compositor captures were inspected in both fullscreen eyes and the windowed
left eye. Native Quit cancellation/resumption and confirmed exit zero pass.
All original private-game files remain unchanged, VR-owned files are removed,
global SteamVR configuration is unchanged and both runtimes stop gracefully.
The installed Steam game remains untouched.

One source-only run required the workbench's forced runtime recovery after its
seven-second shutdown allowance. SteamVR logs show its web helpers and orderly
teardown were still progressing. The workbench now allows fifteen seconds for
normal shutdown before bounded recovery. The two complete-transfer runs above
need no forced components. This does not establish physical-headset lifecycle
acceptance or resolve every previously reported SteamVR error.

Renderer SHA-256:
`3bb1d194ef95363cf235e1371bf9e99b5f1d1e8ef06a167e436fdc79ddcfd845`.
Player remains
`c6bdadf14b8cafff0fd8a575952feb6c8652b60139ab24b0f93faa3ded1cae46`.
Renderer/VR Python regressions: 264 passed, three skipped in 12.31 seconds.
Complete formatting, Ruff, strict typing and spelling checks pass.

Ignored evidence:
`build/vr/fast-cursor-region-qualified-20261011/`,
`build/vr/steamvr-native-20261011-mirror-native-fast-cursor-region-timing-20261011/`,
`build/vr/steamvr-visible-20261011-mirror-windowed-fast-cursor-region-timing-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-back-target-readback-focused-20261011/`.
Earlier unfiltered trace/time-limit and foreground-readiness failures are
diagnostic failures, not production acceptance evidence. Their private files
and runtime settings were recovered. The focused trace terminated its owned
child intentionally and is likewise not clean native-Quit qualification.

An additional opaque-copy experiment passes GPU tests but does not improve the
timed 4K expanded menu: both it and the regional baseline submit about 78.32
frames/s. Its extra synchronization shortcut was removed. The current renderer
recipe again matches the qualified regional build byte for byte. The added
behavior tests remain: all five DirectDraw surface interfaces must preserve the
surrounding scene after an opaque partial copy and subsequent GPU drawing,
including rejection of an invalid source rectangle. Those tests also pass
against the retained regional DLL. This is stronger correctness coverage, not
an additional performance improvement.

Evidence: `build/vr/fast-region-cross-interface-readback-20261011.log` and
`build/vr/steamvr-native-20261011-mirror-native-opaque-fast-region-timing-20261011/`.
The focused Python regressions pass 264 tests with three skips in 13.21 seconds;
complete lint, formatting, strict typing and spelling checks pass.

### 11 October: cropped CPU-cache copies and remaining interface work

A fresh 240-sample thread profile of the regional renderer confirms remaining
CPU copies, fills and RGB565 stretches. Thirteen sampled copy stacks pass through
`TryGPUCopy` into `UploadSurfaceData`: the accelerated copy can upload an entire
dirty offscreen cache before using only a small source rectangle. Diagnostic
symbols come from a separate relink whose executable section is verified
identical to the sampled qualified DLL. Sampling is outside timed intervals.

The renderer now leaves a cropped, dirty, non-render-target CPU source on its
existing bounded CPU copy path. Clean and GPU-authored sources retain accelerated
copies. The ordinary guards, native error handling, source readback and bounded
destination synchronization remain in place. No drawing, mirror or pixels are
omitted. GPU behavior tests exercise both `Blt` and `BltFast` through all five
surface interfaces, repeatedly dirtying the source and invalidating the target,
then checking the complete surrounding scene after a further GPU draw.

The new build passes native, flat and OpenXR GPU qualification, including both
color layouts and first-use asynchronous critical-copy tests. Two real SteamVR
4K samples retain 1568×1568 runtime-sized eyes and unchanged player code:

| Interval | Room submissions/s | Expanded menu submissions/s | Menu p95 / p99 |
| --- | ---: | ---: | ---: |
| First run | 118.33 | 82.16 | 13.33 / 13.74 ms |
| Repeat | 118.33 | 79.49 | 13.60 / 14.53 ms |

The gain is modest and variable relative to the previous 77.66–78.32 samples.
It does not meet the sustained-refresh release gate. Both runs pass menu and
inventory interaction, native Quit cancellation/resumption and exit zero,
unchanged flat files, complete VR-owned removal and graceful runtime shutdown.
The installed Steam game remains untouched.

The inspected compositor menu remains physically small. A higher eye image
resolution cannot solve that angular-size problem. The next interface change
must increase menu readability while applying the identical inverse transform
to controller picking, keeping captions and HUD placement independent. This is
an open implementation/comfort milestone, not a request for headset testing.

Renderer SHA-256:
`2560db17fb261e62b23055d293cd352a0afd616dc99c5504313d62abc0269609`.
Focused Python regressions pass 264 tests with three skips in 11.05 seconds;
complete formatting, Ruff, strict typing and spelling checks pass.

Ignored evidence: `build/vr/partial-cpu-cache-qualified-20261011/`,
`build/vr/steamvr-native-20261011-mirror-native-regional-menu-profile-20261011/`,
`build/vr/steamvr-native-20261011-mirror-native-partial-cpu-cache-timing-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-partial-cpu-cache-repeat-20261011/`.

A matching windowed-mirror run keeps the same 1568×1568 eyes and samples 118.91
room and 118.49 expanded-menu submissions/s. Menu p95/p99 are 9.36/16.57 ms,
including six intervals over 16.67 ms. Native Quit, unchanged flat files,
complete private removal and graceful runtime shutdown pass. The outliers and
physical-headset delivery remain open performance gates. Evidence:
`build/vr/steamvr-visible-20261011-mirror-windowed-partial-cpu-cache-timing-20261011/`.

### 11 October: readable native menus and independent display overlays

Successful native menu captures explicitly request readable placement. The
menu's physical canvas is enlarged 2.5× on both axes and its initial visible
top center is anchored slightly above the seated eye line. The initial anchor
remains fixed while submenus expand, so existing buttons and glyphs do not
move merely because the occupied footprint grows. The source image retains
its original canvas coordinates and pixels. Controller rays use the submitted
quad's exact pose/size to return those original game coordinates.

Menu-associated tooltips follow this plane without acquiring input coverage.
Score/status and dialogue captions use a separate transparent quad with the
original canvas geometry, rather than inheriting menu magnification. Retiring
display content omits that auxiliary layer. Ordinary modal interfaces and
world-only labels retain their existing behavior. Desktop rendering is unchanged.

The fresh pinned renderer passes native math/lifecycle tests, ordinary renderer
GPU checks and all OpenXR GPU variants. The GPU suite now checks both-hand
selection, keyed holes, display-only tooltip/caption rejection, all pixels on
both independent planes, stable submenu growth, atomic failed-source recovery,
auxiliary-layer withdrawal and unchanged world eyes. Its test-only runtime now
allows the second quad to be transparent display content, rather than imposing
keyboard-specific dimensions and opacity on an otherwise valid OpenXR quad.

A real SteamVR virtual-headset run passes graphics/advanced graphics, inventory,
return to stereo, native Quit cancellation and confirmed exit zero. Both
compositor eyes show the enlarged menu, with identical placement before and
after submenu expansion. The windowed desktop remains unmodified. Eye targets
remain the runtime-recommended 1568×1568, independently of the diagnostic
1280×800 desktop canvas. This does not add a legacy-resolution VR requirement.

The twelve-second room interval samples 118.75 stereo submissions/s and the
six-second expanded-menu interval 118.15. Menu p95/p99 are 9.71/16.17 ms, with
three intervals over 16.67 ms. These are submission measurements with a virtual
headset, not physical display delivery or sustained-refresh acceptance.

The first real-runtime attempt exceeded the workbench's 75-second outer bound.
Its exact private files and registry snapshot were recovered unchanged. A
bounded repeat completed the game checks in 54.58 seconds, then shut SteamVR
down gracefully without forced components. Global runtime settings and the
installed Steam game remain untouched. No headset testing is requested yet.

Renderer SHA-256:
`d5b43b94d1b7d60cff483b97854ad08457b0ae3a3d04cbe1ff642a458d2b2042`.
Player SHA-256:
`c8fff13dcc882d7865ff8cf469bff2e653f2da1bd5f1802ea1590d9ad435a89d`.
Focused Python regressions pass 390 tests with three skips in 51.32 seconds;
the additional menu-ownership retirement regression passes in the 50-test
menu suite. Formatting, Ruff, strict typing and spelling checks pass.

Ignored evidence: `build/vr/readable-menu-layers-qualified-20261011/`,
`build/vr/readable-menu-layers-build-20261011.log`, and
`build/vr/steamvr-visible-20261011-mirror-readable-menus-windowed-repeat-20261011/`.

A matching 4K-desktop run passes the same menu/inventory/Quit flow in 55.35
seconds, including unchanged flat files and graceful runtime shutdown. Both
actual compositor eyes show the enlarged controls and menu-linked tooltip.
The menu geometry is unchanged when advanced graphics expands. The runtime
again selects 1568×1568 eye targets. Room pacing samples 118.41 submissions/s
(p95/p99 9.38/11.06 ms) and expanded menus 80.33 (13.50/14.72 ms). This retains
the known 4K desktop/menu cost and is not a claimed performance improvement.
Evidence: `build/vr/steamvr-native-20261011-mirror-readable-menus-native-20261011/`.

### 11 October: status ownership through open menus

The native toolbar can precede the room-status TextBox in RoomLayer's child
vector. VR's former first-child assumption withdrew the status source even
while the native desktop continued to draw and fade it. The VR probe now
validates the complete bounded vector and requires a unique concrete status
class. Reordering is accepted, while unreadable pointers, oversized vectors
and ambiguous matching children reject publication. It never authorizes a
stale retained pointer. Capture-only text scopes explicitly own and restore
their glyph/fill scaling depth on normal and exception paths.

The GPU suite covers independent HUD opacity steps, zero-alpha retirement,
reappearance at a different position, unchanged primary menu pixels and
unchanged world eyes. Additional full-canvas cases verify every auxiliary pixel
and physical geometry on 1280×800 and 3840×2160 diagnostic desktop canvases.
Those desktop sizes are test inputs, not VR compatibility requirements.

Actual SteamVR virtual-headset runs show the toolbar-open status fade and
disappear without visible glyph residue in either compositor eye. Both desktop
mirror modes retain runtime-recommended 1568×1568 eye targets, pass native
Quit cancellation/return/confirmed exit zero, restore private files and
registry state, and shut the isolated runtime down gracefully.

A late 4K screenshot initially suggested missing/small glyphs. A bounded
snapshot of the isolated RGB565 source proved native glyph scaling correct,
full-canvas GPU checks proved upload placement correct, and an API-layer
trace proved submitted quad pose/size correct. The desktop screenshot had
delayed compositor capture into the native fade. Starting earlier and capturing
eyes first resolved that diagnostic failure without changing layer geometry.
Capture timings now record actual begin/end, not just the preceding state read.
Pixel differences against an animated scene are diagnostic only. Visual glyph
inspection and explicit producer retirement are the relevant sampled evidence.

Focused HUD/compiler/font regressions pass 155 tests in 9.95 seconds.
Formatting, Ruff, strict typing and spelling checks pass. Broader status/modal
coverage, sustained performance and physical-headset readability/lifecycle
remain first-release gates. No headset wear is requested yet.

Ignored evidence: `build/vr/hud-menu-fade-qualified-20261011/`,
`build/vr/steamvr-visible-20261011-mirror-hud-menu-sibling-fixed-20261011/`,
`build/vr/steamvr-native-20261011-mirror-hud-menu-early-native-20261011/`,
`build/vr/steamvr-native-20261011-mirror-hud-isolated-source-native-20261011/`,
`build/vr/steamvr-native-20261011-mirror-hud-quad-geometry-native-20261011/`
and `build/vr/large-hud-gpu-20261011.log`.

The fresh `build/vr/hud-membership-qualified-20261011/` build passes all native,
flat-renderer, OpenXR RGBA/BGRA and asynchronous critical-copy qualification
checks with the permanent full-canvas regression. A final real SteamVR run
using that exact artifact repeats the 4K toolbar-open fade and clean native
Quit flow in 35.58 seconds. Both inspected glyph strips show disappearance
without visible residue. Player files and global runtime settings are restored.
Evidence: `build/vr/steamvr-native-20261011-mirror-hud-membership-final-native-20261011/`.

Renderer SHA-256:
`e10bdbf1c796f470c93da73aaa4aae9fcf187f5b48c2c227b4cb1665517f82eb`.
Player SHA-256:
`4ef88f86cb99cb2861eae8f677ee3993570980938f06f2047a2f8bef91752075`.
The full default suite passes 4,284 tests with 23 skips and 402 deselected.
The 78-second run overlapped full native renderer compilation. A subsequent
repeat without renderer compilation passes the same suite in 64.89 seconds.
That remains slightly above the desired 60-second fast-suite ceiling and is
not a test-speed acceptance claim.

### 11 October: broader modal and native save/restore samples

VR eye targets remain the runtime-recommended 1568×1568, independently of the
windowed or 4K desktop mirror. Those desktop sizes are diagnostic inputs, not
legacy-resolution requirements for VR. Modal readability is a separate
angular-size and headset-acceptance concern, not something eye resolution alone
can establish.

Actual SteamVR virtual-headset samples cover museum inventory inspection,
binoculars, fingerprint inspection and return to stereo, plus driving-map
highlights and the Cuiza station tooltip. Native Quit cancellation and
confirmation pass. The map samples do not constitute exhaustive geometry,
hitbox or physical-controller qualification.

The save-editor visual helper had clicked below the real empty-slot name box
and accepted an unchanged field as a typed-name screenshot. It now reads the
bounded live slot list, chooses the empty row's native bounds, and requires the
exact requested text in the concrete native editor before capturing. Hidden,
invalid, unreadable or unexpected widgets fail instead of producing misleading
evidence. A real 4K-mirror modal run verifies the typed name and cancel flow in
44.92 seconds. The visual-helper regression suite passes 93 tests in 3.40 seconds.
This is an automation correction, not a game-input or renderer change.

A separate actual SteamVR run writes a native save, moves to the hotel lobby,
opens the native Restore browser and returns to the saved hotel room. Successive
left/right compositor captures show score retirement without visible residue.
Native Quit → No → resumed stereo → Quit → Yes exits with code zero. The run
finishes in 54.41 seconds, removes only its owned test save, restores private
flat files and registry state, and shuts SteamVR down gracefully without
changing global configuration. Input in these samples is host-driven, not
physical-controller acceptance.

Two other save/restore attempts time out. The first exposes a workbench
assumption that catalog-readable save bytes were already final, although native
writing later completes the file. A bounded file-completion check addresses that
assumption, but the final repeat still stalls after the restored-score trace,
before the next interface capture completes. The exact cause of that remaining
stall is not established. Recovery stops owned processes, removes the private
VR installation, restores its registry snapshot and preserves the test-created
save in the ignored evidence directory. Private flat-file equality passes after
that recovery. Neither failed attempt is release-acceptance evidence, and the
single passing run does not close repeatable real-runtime lifecycle gates.

The qualified renderer/player artifacts are unchanged by these experiments.
The installed Steam game remains untouched. No headset wear is requested yet.

Ignored evidence under `build/vr/`:
`steamvr-native-20261011-mirror-special-typed-native-20261011/`,
`steamvr-native-20261011-mirror-map-gameplay-native-20261011/`,
`steamvr-visible-20261011-mirror-native-save-restore-observed-20261011/`,
`steamvr-visible-20261011-mirror-native-save-restore-20261011/` and
`steamvr-visible-20261011-mirror-native-save-restore-complete-20261011/`.

### 11 October: diagnostic flush delays and larger modal interfaces

A stack-instrumented save/restore repeat catches repeated waits in
`os.fsync` inside diagnostic `atomic_write` calls, including transient progress
markers and a copied save. It times out, is recovered with private flat-file
equality restored, and stops SteamVR gracefully without changing global
configuration. This proves a workbench delay mechanism, not a game-rendering
deadlock, and does not retrospectively prove every earlier timeout had this
cause.

Replaceable progress/trace observations now use ordinary buffered writes.
Installer crash journals and new rollback cache content keep their durable
publication. The VR transaction also reuses existing content-addressed rollback
bytes only after checking both size and SHA-256. Missing/corrupted content still
requires durable replacement, and failure does not accept the cache filename
as proof. Its 54 passing regression tests and three permission-related skips
cover interrupted publication/recovery, external edits and the new cache
reuse/repair behavior. That run takes 70.99 seconds while the slow-flush runtime
experiment is active, so it is not a fast-suite timing acceptance result.

With buffered diagnostics and cache reuse, another real SteamVR native
save → different room → restore → score trace → native Quit run completes in
52.69 seconds. The private flat files, registry and global runtime configuration
are unchanged afterward and SteamVR shuts down gracefully. Sustained runtime
lifecycle and physical-controller acceptance remain separate gates.

Inspection also confirms that the ordinary modal plane leaves save text too
small in the compositor. The native bridge now publishes a 2.4 m-wide canvas
for opaque modal pages, retaining its 1.6 m distance and source aspect ratio.
World/menu/caption/HUD paths reset to the original 1.6 m base width each frame.
The renderer consumes that same published geometry for drawing and inverse
controller picking. No desktop pixels, native coordinates or eye extents change.

A real SteamVR 4K-desktop sample completes the typed save-editor/cancel,
museum inspection, binoculars, fingerprint inspection and native Quit flow in
51.97 seconds. Published modal geometry is 2.4×1.35 m and return-to-world
geometry is 1.6×0.9 m. Both actual compositor save-editor eyes are inspected.
Player SHA-256 is
`23ebb0fc7ef23899802f86054d96b1d5fbf2c32f6d9a952d4381f203c05f8726`.
The renderer in this sample remains the previous qualified artifact. The
focused panel/overlay/service suite passes 174 tests in 2.29 seconds. Larger
glyphs are an implementation improvement, not headset-readability acceptance.

Ignored evidence: `build/vr/steamvr-visible-20261011-mirror-native-save-restore-stack-20261011/`,
`build/vr/steamvr-visible-20261011-mirror-native-save-restore-buffered-20261011/`
and `build/vr/steamvr-native-20261011-mirror-readable-modals-native-20261011/`.

The fresh `build/vr/readable-modals-qualified-20261011/` renderer passes all
native, flat-renderer, OpenXR RGBA/BGRA and asynchronous critical-copy
qualification. New native panel cases repeatedly switch between 1.6 and 2.4 m
widths on both diagnostic canvas sizes, checking aspect/distance, both-hand
center/edge picking and rejection just outside the current panel. Geometry
must not retain the previous size's inverse transform.

An initial real-runtime confirmation is invalidated by a diagnostic assertion:
the native frame's mutable renderer-output/input area can be cleared between
publications, so an unsynchronized geometry read sees all zeros. It is not a
record of the submitted quad. The workbench now checks the persistent producer
size request rather than treating that transient area as authoritative geometry.
Actual compositor images and native drawing/picking tests remain separate
evidence. The rejected run is recovered with unchanged private files and global
settings and graceful runtime shutdown.

The corrected repeat uses the exact fresh renderer and current player. Native
Save → lobby → Restore → hotel room → score trace → Quit cancellation/resume →
confirmed Quit passes in 53.00 seconds. Both final compositor eyes show score
retirement without residue. Private flat files are unchanged, owned VR files
and the test-created save are removed, and SteamVR stops gracefully without
changing global configuration. Host-driven input remains explicitly distinct
from physical-controller/headset acceptance.

Current renderer SHA-256:
`9e018f80e2b5ee929fdb852e2be30d2c0e53560e7a4f872d05986af3bd0bf908`.
Current player SHA-256:
`23ebb0fc7ef23899802f86054d96b1d5fbf2c32f6d9a952d4381f203c05f8726`.
The rollback suite repeats with 54 passes and three skips in 3.45 seconds,
without the earlier slow flush behavior. The complete default suite passes
4,311 tests with 23 skips and 402 deselected in 67.88 seconds. That full run
overlaps part of the real-runtime workbench and is not a test-speed acceptance
result. Formatting, Ruff, strict typing and spelling checks pass.

Evidence: `build/vr/readable-modals-build-20261011.log`,
`build/vr/steamvr-visible-20261011-mirror-readable-modals-save-restore-20261011/`,
`build/vr/steamvr-visible-20261011-mirror-readable-modals-save-restore-repeat-20261011/`
and `build/vr/vr-default-regressions-20261011.log`.

### Independent VR mirror and native brightness control, 11 October 2026

The VR world uses the OpenXR runtime's recommended per-eye size, including its
distortion and supersampling requirements. It does not target 1024×768 or depend
on supporting legacy desktop resolutions. The public prototype launcher now
uses the game's native `-window -width 1280 -height 800` arguments for a cheaper
desktop mirror and native interface source canvas. Those arguments do not set
or cap the stereo world's eye targets. Interface source quality remains a
separate readability acceptance check, not a claim that all panels are rendered
at headset resolution.

A diagnostic native-argument run proved the game otherwise persists the mirror
width, height and fullscreen setting into the flat game's registry preferences.
The isolated VR compiler now guards the native DWORD writer only while VR is
active. It suppresses exact, case-insensitive Screen Width, Screen Height,
Full Screen, Game Width and Game Height writes. Other names, types and sizes
forward through the original API with its original arguments, error result and
stack cleanup. Reads and key lifetime are unchanged. This avoids restoring stale
preferences after launch or intercepting the system registry API globally.

Image inspection then found a windowed regression: GK3 skips its native gamma
interface query outside fullscreen, leaving a blank brightness row. A guarded
VR-only branch now reaches the original capability checks and COM query in
windowed mode. The real gamma interface, native adjustment logic and reference
lifetime remain in place. Both actual SteamVR compositor eyes show the restored
slider. The later end-to-end native-input tests below qualify GUI adjustment
and non-default startup/reset values separately from the renderer transport
tests. Physical-controller and headset acceptance remain open.

The final matching-player run passes title Play, room stereo, graphics and
advanced options, inventory, Quit cancellation/resumed stereo and confirmed
native exit in 51.95 seconds. The mirror is 1280×800, the world eye targets are
1568×1568, and the separate compositor mirror is 1920×1920. Flat display
preferences remain unchanged before cleanup. Private flat files are unchanged,
owned VR files are removed, and owned SteamVR components stop gracefully without
forced termination or changing global runtime configuration. This uses the
actual SteamVR virtual headset and host-driven menus, not physical controllers.

Counter-only intervals measure 119.66 room and 117.66 advanced-menu stereo
submissions/s, without diagnostic captures inside those intervals. A matched
4K-mirror diagnostic measured 118.08 room and 79.33 advanced-menu submissions/s
with the same eye targets and renderer. The shorter mirror reduces observed menu
overhead, but these bounded samples do not establish delivered headset frame
rates, sustained frame times or physical-headset comfort.

Current renderer SHA-256 remains
`9e018f80e2b5ee929fdb852e2be30d2c0e53560e7a4f872d05986af3bd0bf908`.
Current player SHA-256 is
`4e857f44ae27c311ce11c3c851521b205dd42c179789665f806ebd89b1cc0a6e`.
Focused VR/mirror regressions pass 252 tests with three skips in 10.32 seconds.
The full default suite passes 4,364 tests, with 23 skips and 402 deselections,
in 60.64 seconds. The under-60-second timing gate remains open. Full formatting,
lint, strict typing and spelling checks pass.

Evidence: `build/vr/steamvr-native-20261011-mirror-isolated-mirror-brightness-20261011/`,
`build/vr/steamvr-native-20261011-mirror-isolated-mirror-baseline-20261011/`,
`build/vr/isolated-mirror-brightness-default-tests-20261011.log` and
`build/vr/isolated-mirror-lint-20261011.log`.

### Native brightness interaction qualification, 11 October 2026

Two bounded actual-SteamVR virtual-headset runs use the production windowed
1280×800 mirror, with independent 1568×1568 recommended eye targets. Native
slider input, not a console gamma command or memory write, produces these values:

| Startup gamma | Adjusted gamma | Returned gamma | Left/right return RGB error |
| --- | --- | --- | --- |
| 1.0000 | 1.9897 | 1.0276 | 3.00 / 3.00 |
| 2.0000 | 1.0276 | 2.0208 | 0.86 / 0.87 |

Errors are mean absolute RGB-channel differences on a fixed ceiling region in
actual compositor-eye captures, measured on the 0–255 scale. Raising gamma from
1 brightens that region by approximately 59 channel levels in both eyes.
Lowering startup gamma 2 toward 1 darkens it by approximately 57 levels. Return
values are approximate because the native slider has discrete positions. This
is not evidence of bit-exact neutral reset or headset brightness calibration.

The earlier failed return drag was a diagnostic-input error. Native drag capture
hides/recenters the physical mouse and consumes signed relative movement.
Repeated absolute positions to the right of that center kept supplying positive
deltas even during a nominal leftward drag. Read-only native hitbox observations
and bounded temporary motion logging confirmed the presses were correctly
positioned. Replacing only the ignored test driver's input with relative mouse
events resolves the failure. No extra production patch, renderer change or
synthetic call to the gamma setter was needed. Temporary logging was absent
from both passing runs.

Both complete flows pass graphics/advanced menus, inventory, native Quit
cancellation/resumption and confirmed exit in approximately 38 seconds each.
Private flat files and the five flat display preferences remain unchanged,
owned VR files are uninstalled, and SteamVR stops gracefully. Startup gamma is
an explicit private-test preference and the recorded original setting is
restored on cleanup. The user's installed flat game is untouched.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-gamma-relative-input-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-gamma-startup-two-20261011/`.
The renderer/player hashes are unchanged from the preceding qualification.
Physical-controller slider operation, sustained headset pacing, comfort and
broader gameplay coverage remain acceptance gates.

### Native status fading across scene transitions, 11 October 2026

A matching production-player run covers hotel room (`R25`), lobby (`LBY`) and
hotel exterior (`RC1`), all at time block `110a`. The diagnostic driver moves
the host pointer into the native status activation area, then away, without
writing opacity, forcing destruction or calling a synthetic fade routine.
Read-only samples record intermediate native fade weights, followed by zero
source ownership and zero submitted overlay parts. Both actual compositor eyes
are captured at visible, fading, retired and later settled stages.

Visual inspection shows the text disappearing in all three scenes. In the
lobby and exterior, detected glyph-region pixels in the retired captures match
their settled backgrounds exactly. The room's animated scenery produces small
pixel differences, so those are not claimed as a zero-error background result.
The exterior's bright sky makes the text's dark outline more useful for
detection than its white interior. Pixel inspection supplements, rather than
substitutes for, native ownership and submission observations.

The first exterior attempt failed because scene identity and the Room layer
were already present while a native scripted action still owned input. The
driver now waits for the native busy/action cursor to release input and sends
a fresh away-to-top hover transition. No production rendering or fade change
was necessary to pass this sample.

The complete run takes 52.87 seconds and passes native Quit cancellation,
resumed stereo and confirmed exit zero. Private flat files and display
preferences are unchanged, owned installation files are removed, and SteamVR
stops gracefully without forced components or global configuration changes.
Renderer/player hashes match the preceding brightness qualification.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-status-ready-scenes-20261011/`,
including per-scene native traces, both-eye captures, enlarged glyph reviews
and `status-pixel-review.json`. These are host-input virtual-headset samples.
Broader score-artifact reproduction, physical-controller operation and
headset acceptance remain open.

### Multi-scene pacing baseline, 11 October 2026

With the same qualified renderer/player, recommended 1568×1568 eyes and the
independent 1280×800 desktop mirror, counter-only intervals produce:

| Scene | Interval | Stereo submissions/s |
| --- | --- | --- |
| Hotel room | 12 seconds | 111.91 |
| Lobby | 12 seconds | 116.58 |
| Hotel exterior | 20 seconds | 88.20 |

Captures occur after each interval, not during it. Native Quit cancellation,
resumed stereo, confirmed exit and graceful owned-runtime shutdown pass.
These bounded samples expose an exterior performance gap. They do not establish
sustained headset-delivered frame rates or pass the release performance gate.

A separate exterior run enables the diagnostic OpenXR timing layer and samples
the primary thread only after its measured interval. It measures 78.25
submissions/s, so it is not substituted for the uninstrumented baseline.
Mean combined WaitFrame/BeginFrame/EndFrame/acquire/image-wait/release call time
is approximately 0.81 ms per submitted frame. Most elapsed time is outside
those calls. The primary-thread samples concentrate in native room rendering,
legacy primitive/state translation and temporary vertex-buffer handling,
with some resource waits. This narrows investigation toward game/renderer work,
but does not by itself determine CPU/GPU critical-path causality or quantify
the benefit of any proposed optimization.

Renderer symbols come from a diagnostic relink whose entire `.text` bytes and
RVA match the qualified renderer. That relink is never installed. No production
rendering behavior is changed for this baseline or profile.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-scene-pacing-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-exterior-profile-20261011/`.
Both runs preserve private flat files/display preferences, remove owned VR files
and shut down SteamVR without forced components or global configuration changes.

### Native transform regression and rejected optimization, 11 October 2026

The next candidate skipped exactly equal D3D9 transform writes after state-block
recording, to avoid redundant fixed-function constant invalidation. It preserved
changed inputs and compared bytes instead of float equality. It passed a fresh
build, native tests, flat/GPU checks and the new native primitive regression.
However, the repeated actual-SteamVR timing does **not** support keeping it:

| Renderer/run | Room | Lobby | Exterior |
| --- | --- | --- | --- |
| Unchanged, earlier baseline | 111.91 | 116.58 | 88.20 |
| Candidate, first run | 118.75 | 119.41 | 101.20 |
| Unchanged, follow-up | 118.58 | 119.58 | 103.95 |
| Candidate, repeat | 118.33 | 119.49 | 102.20 |

Values are stereo submissions/s, over uncaptured 12/12/20-second intervals.
The unchanged renderer's later improvement invalidates attribution of the
candidate's initial increase to its code. The candidate is removed from the
production recipe. No exterior speed-up is claimed from this experiment.

The historical renderer is checked against its archived source inventory and
original provenance, not misrepresented as matching the modified recipe. Its
DLL is the qualified `9e018f80e2b5ee929fdb852e2be30d2c0e53560e7a4f872d05986af3bd0bf908`.
The rejected candidate is `8982592f75615e9ee26dbbfa9d02cb2d4c9fa564b2ca2547c6d7b8e80c3f353c`.
All runs use the same production player and runtime-recommended eye sizes.
Native Quit, unchanged private flat files and graceful SteamVR shutdown pass.

The retained GPU regression renders actual native triangles, reads native
transform values and checks target pixels after repeated setters, world
translation, inverse view translation and projection narrowing. It supplements
the earlier clear-only eye-transport tests. Separate fixed scenery regions in
both compositor eyes match the unchanged renderer byte for byte. Actors, fans
and water animate, so full-frame equality is not asserted.

Evidence: `build/vr/exact-transform-qualified-v2-20261011/`,
`build/vr/steamvr-native-20261011-mirror-native-exact-transform-pacing-20261011/`,
`build/vr/steamvr-native-20261011-mirror-native-pre-transform-repeat-pacing-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-exact-transform-repeat-pacing-20261011/`.
The artifact/build regression subset passes 84 tests in 2.25 seconds.
Sustained headset-delivered performance and the exterior critical path remain open.

The final recipe, with the candidate removed and the primitive regression retained,
passes a fresh complete renderer build, native tests and flat/OpenXR GPU checks.
The qualified DLL is
`f0f2950ba1ffbc35e667d8187f735294f86d47d92573321d02f0e7aeda789d0a`.
Its code/data sections match the earlier unchanged renderer byte for byte. The
only two differing bytes are the link/debug timestamp in `.rdata`, not rendering
logic. The public player remains
`4e857f44ae27c311ce11c3c851521b205dd42c179789665f806ebd89b1cc0a6e`.

A matching actual-SteamVR run repeats the three-scene native score fade, retirement,
Quit cancellation/resumption and confirmed exit in 53.58 seconds. Both compositor
eyes show no text residue. Lobby/exterior retired glyph pixels exactly match the
settled samples. The room's animated ceiling fan changes background pixels between
captures, so its pixel differences are not claimed to be zero. Flat files/display
preferences remain unchanged, owned VR files are removed and SteamVR closes
gracefully. This is still virtual-headset qualification, not physical-headset
acceptance.

Evidence: `build/vr/native-transform-regression-qualified-20261011/` and
`build/vr/steamvr-native-20261011-mirror-native-transform-final-status-20261011/`.

A further current-build actual-SteamVR run measures 119.66 stereo submissions/s
in the room over 12 seconds and 115.65/s with advanced graphics options open
over 6 seconds. Captures are outside the measured intervals. Both compositor
eyes are inspected for the advanced menu and inventory. Inventory returns to
stereo, native Quit cancellation/confirmed exit pass, and the runtime closes
gracefully. Flat files/preferences and global runtime configuration remain
unchanged. This is not an expanded resolution-list benchmark or sustained
physical-headset performance acceptance.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-menu-pacing-current-20261011/`.

### Actual-runtime movie transitions, 11 October 2026

The current verified player/renderer now repeat movie transitions under actual
SteamVR, rather than only the GPU test runtime. `day2-2.bik` completes naturally;
`205PEND.BIK` is skipped with the native host Escape key. Both movies appear on
the opaque virtual screen, with both compositor eye images inspected. Native
stereo-world counters stop during the observed movie interiors while XR
submission continues: 1,388 additional XR frames for the completion sample and
118 for the skip sample. Boundary reads are not treated as atomic snapshots.
Both transitions resume native room input and stereo submission.

The complete run takes 50.70 seconds, passes native Quit cancellation/resumption
and confirmed exit, and shuts SteamVR down gracefully without forced components.
Flat files/display preferences and global runtime configuration stay unchanged;
the private VR installation is removed. The earlier synthetic-controller movie
checks remain separate. This host-input virtual-headset run does not establish
physical-controller skipping, audio synchronization or movie-screen comfort.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-movie-transitions-current-20261011/`,
including `movie-transitions.json`, both-eye playback/returned-world captures
and `world-run.json`.

The full default Python suite passes 4,364 tests, with 23 skips and 402
slow-test deselections, in 66.42 seconds. Its duration profile is retained in
`build/vr/default-suite-profile-20261011.log`. The under-60-second gate remains
open; no behavior coverage was removed or reclassified to achieve a timing
claim.

### Actual-runtime scripted camera glides, 11 October 2026

The current matching player/renderer pass authored glides to the room camera
`FR_DU1` and cinematic camera `OPEN_WINDOW` under actual SteamVR. Read-only
native traces observe a stacked moving-camera controller (`0x6691ac`) and
changing camera poses. During each observed glide interior, stereo-world
draw counters remain stationary, published panel geometry is constant and XR
submission advances by 14 and 11 frames respectively. Both glides return to
stereo, with returned-world compositor captures, native Quit cancellation and
confirmed exit. SteamVR closes gracefully, with flat files/display preferences
and global configuration unchanged and the private VR installation removed.

The first diagnostic assumed a longer interior than the native roughly
0.16-second glide permits. It failed its observation-length assertion after
the game had already returned correctly. The revised driver excludes 25 ms
handoff edges, requires a nontrivial observed interval and several published
nonzero transforms, and does not treat cleared publication buffers as submitted
geometry. No production behavior or camera speed was changed for this test.
Moving-panel compositor snapshots are not claimed by the returned-world
captures. Physical-controller operation, other scripted controller types,
dialogue sequences and actual headset comfort remain open.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-glide-short-interval-current-20261011/`.

### Actual-runtime controller bindings, 11 October 2026

An isolated diagnostic OpenVR driver supplies two virtual Index-profile devices
to actual SteamVR. It uses the official OpenVR SDK v2.15.6 and SteamVR's installed
Index input profile. Devices, poses and component updates enter through the
driver API. Production OpenXR actions and native game input remain unchanged,
without injected action snapshots or direct calls to native button handlers.
The driver is ignored workbench material, not a distributed asset or globally
registered driver. Private runtime configuration disables unrelated hardware
drivers and leaves global SteamVR configuration unchanged.

Discovery verifies both controller roles, exact diagnostic serials and valid
tracked poses. Gameplay then qualifies each hand independently through tracked
hand fallback: Inventory opens, its actual native Exit rectangle is projected
onto the displayed physical panel, the delivered ray matches that button within
two canvas pixels, and trigger selection returns to stereo. Inventory reopens
and the right-hand Back binding also returns to stereo. The host mouse does not
move. Native Quit cancellation and confirmed exit pass, SteamVR closes gracefully,
flat files/preferences remain unchanged and the private VR installation is removed.
The complete trigger-selection run takes 38.35 seconds. Both-eye inventory
captures and returned-world imagery are inspected in the preceding binding run.

This exposed a usability limitation, not a missing runtime binding: the original
router preferred the right hand while it remained tracked and ignored the other
hand's shortcuts. The subsequent shared-shortcut correction below resolves that
limitation without changing the pointing hand. Host input operates Play and final
Quit in this earlier sample. Complete gameplay, physical hardware and headset
comfort remain open.

The first test pressed left A while the preferred right hand was tracked and
correctly failed its inventory assertion. A second attempt exposed an observation
race in the workbench's title-window lookup, fixed only in the ignored driver.
The first trigger diagnostic misread native rectangles as widths/heights instead
of left/top/right/bottom and failed before sending selection. The revised test
uses the existing authored-canvas projection and verifies the delivered pointer,
without altering production hitboxes or manufacturing a successful click.

Evidence: `build/vr/virtual-controller/`,
`build/vr/steamvr-null-20261011-controller-driver-discovery-20261011/`,
`build/vr/steamvr-native-20261011-mirror-native-runtime-controller-handoffs-v2-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-runtime-controller-select-v2-20261011/`.

### Both-hand shortcuts and controller startup, 11 October 2026

The production panel router now accepts Back, Menu and Inventory shortcuts from
either tracked hand, in both world and modal modes. It keeps the preferred
pointing hand and its Select trigger independent, so pressing left A/B does not
steal the right ray or manufacture a click. Focus rejection, lost tracking,
release-to-rearm safeguards and native shortcut priority remain intact.
Native regression tests cover both selected hands, both presentation modes,
shortcut edges, foreign-trigger rejection and focus/tracking loss.

The fresh renderer passes all six native tests and complete flat/OpenXR GPU
qualification. Independent provenance verification passes. The focused Python
suite passes 269 tests with three skips in 12.67 seconds, and full lint passes.
The renderer SHA-256 is
`3f5cb3767f8763ec27cfb16e151529eb35ec1c0a46f6eacff31b28919d6d0385`;
the player remains unchanged.

Actual SteamVR qualifies left Inventory and Menu while both virtual devices
remain tracked, right Back, and either-hand trigger selection through tracking
fallback. Both compositor menu eyes are inspected. The complete sample takes
41.71 seconds, exits natively and closes SteamVR gracefully without forced
components. Flat files and global runtime configuration remain unchanged.

A subsequent 39.83-second run also skips the opening movie with right Back,
aims at the live native Play button and selects it through SteamVR/OpenXR with
controller ownership enabled. The delivered pointer matches `(737, 733)` within
0.001 canvas pixels; the host mouse remains unchanged. Hotel-room stereo uses
runtime-recommended 1568×1568 eye targets, separately from the 1280×800 mirror.
Both-hand shortcuts and either-hand inventory selection repeat successfully.
Final Quit still uses host input in this sample, so it does not establish the
complete controller-only lifecycle or physical-controller acceptance.

Two initial startup tests failed their screenshot readiness checks because
desktop occlusion or nonclient window decorations displaced the sampled buttons.
Actual compositor output and native button geometry showed a correctly rendered
title screen. The revised workbench reads the four visible native title buttons
and verifies the delivered controller ray, without changing their hitboxes or
calling button handlers. These diagnostic failures are not claimed as game fixes.

Evidence: `build/vr/shared-shortcuts-qualified-20261011/`,
`build/vr/steamvr-native-20261011-mirror-native-both-hand-shortcuts-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-controller-title-rects-20261011/`.

The actual-runtime controller lifecycle subsequently passes in 44.45 seconds:
movie skipping, Play, both-hand shortcuts, either-hand inventory trigger
selection, native Options → Quit → No → resumed stereo → Options → Quit → Yes.
All interaction events enter through the diagnostic hardware driver and
production OpenXR actions, not host mouse/keyboard events or native handler
calls. Each menu selection verifies the delivered ray against the current
physical panel. Normal native control enablement is respected.

Both-eye Quit captures and the options menu are inspected. The public supervisor
returns zero, SteamVR closes gracefully with no forced components, flat files
and display preferences remain unchanged, global runtime configuration is
unchanged and the private installation is removed. Diagnostic setup switches
controller ownership between test phases; this is not a test of uninterrupted
physical-controller ownership or focus transitions. Keyboard entry, preferred
pointing-hand selection, broader gameplay and physical acceptance remain open.

The first Quit diagnostic mistakenly used right Back, which correctly pauses
the world rather than opening the toolbar. It failed its toolbar assertion and
cleaned up safely. The corrected test uses the existing left Menu binding and
requires no production change. Evidence:
`build/vr/steamvr-native-20261011-mirror-native-controller-full-flow-v2-20261011/`.

### Actual-runtime controller keyboard, 11 October 2026

The unchanged qualified player/renderer pass native save-name typing under
actual SteamVR in 38.46 seconds. Virtual Index trigger events select keys on
the separately rendered keyboard through production OpenXR actions. Read-only
native editor observations verify each exact result: `vr test`, followed by
Home, Delete, End, Backspace, Caps and `D`, yielding `r tesD`. Held triggers do
not repeat keys. Layout switches do not submit native characters.

Both compositor eyes show the keyboard, hovered key, capitalization and the
matching native editor text. Cancel returns to stereo and retires text ownership.
The host mouse remains unchanged. The same run cancels and confirms native Quit
through controller actions, returns zero and closes SteamVR gracefully without
forced components. Flat files/preferences and global runtime settings remain
unchanged, and the private installation is removed. No save slot is written in
this typing/editing sample.

The workbench now waits for a completed nonzero panel snapshot before deriving
the keyboard's physical geometry, rather than reading its transient cleared
buffer. Final Quit release does not wait for more game frames or read process
memory after the player starts exiting. Failed diagnostics are retained, not
treated as passing evidence. These are observation fixes, not production changes.
Physical controls, headset text readability and other editor routes remain open.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-runtime-keyboard-v4-20261011/`,
including `runtime-keyboard-actions.json`, typed/edited compositor eyes and
`world-run.json`.

A further actual-SteamVR run writes a real native save with the controller-typed
name `GK3HD visual comparison`, turns the camera 30 degrees through the right
controller stick, selects the matching slot in Restore and recovers the exact
five native camera floats. Save/Restore selections also use production rays and
trigger events. The native file is parsed and its declared total length checked
before it is accepted as complete. The keyboard retires and room stereo resumes.

The 42.75-second run completes controller-operated Quit cancellation and
confirmation, returns zero and closes SteamVR gracefully without forced
components. The temporary native slot is preserved as ignored evidence and
removed only from the private game after verifying its test description. Flat
files/preferences and global runtime configuration remain unchanged, and the
private installation is removed. Both-eye typing/restored-world captures are
inspected. This does not qualify cross-room restore, file-I/O focus changes,
physical controllers, other text editors or headset comfort.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-runtime-keyboard-save-20261011/`,
including `runtime-controller-save.gk3`, `world.json` and `world-run.json`.

### Actual-runtime SIDNEY search, 11 October 2026

The unchanged qualified player/renderer pass a 54.08-second actual-SteamVR
session with virtual Index controllers. Console commands stage Grace's day-two
room and run the retail SIDNEY entry script. From the settled laptop home
screen onward, production OpenXR rays and trigger actions select Search, type
`vampires`, invoke the native search, return Home and select native Exit.
Read-only editor observations verify all eight characters and reject repeated
input from a held trigger. Application-content readiness checks distinguish
real search results from a changed cursor or tab hover.

Compositor images show the keyboard, query and the native vampire-result list.
Home retires the editor and keyboard; Exit returns to stereo after its scripted
action releases normal controls. Controller Options → Quit → No resumes stereo,
then Quit → Yes exits with code zero. The supervisor returns zero without
errors. SteamVR shuts down gracefully with no forced components. Flat files,
display preferences and global runtime configuration remain unchanged, and the
private installation is removed. The host mouse is unchanged during the
controller interaction. This does not qualify physical-controller usability,
headset readability, all SIDNEY puzzles or sustained performance.

Earlier diagnostic attempts exposed setup assumptions, not production defects:
a scene transition left the console open, a generic non-room-layer check
accepted the help screen, Back was incorrectly assumed to close SIDNEY, and
Quit was attempted before the native laptop-exit script enabled Options. The
workbench now verifies the settled home screen, closed console and native input
readiness, and uses SIDNEY's actual Exit button. No game or renderer changes
were needed for this qualification. Failed runs remain preserved as evidence.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-runtime-sidney-v4-20261011/`,
including `runtime-sidney-actions.json`, typed/results compositor images,
`world.json` and `world-run.json`.

### Explicit pointing preference and tracking handoff, 11 October 2026

`gk3hd vr launch --hand left` selects the left controller for world, interface
and keyboard pointing. Right remains the default. The suspended-child launcher
validates both original pointing defaults and every dormant switch before any
activation write, sets the world and panel preference together, verifies those
writes, then resumes. Invalid choices or mismatched/unapplied settings never
resume the game. Executable bytes and renderer configuration remain unchanged.
Existing renderer tracking fallback and native release-to-rearm guards are used,
not replaced. Menu, Inventory and Back retain their established button bindings.

The actual SteamVR virtual-controller workbench passes left-handed title Play,
SIDNEY search typing and keyboard retirement, native Exit, Quit cancellation and
confirmed clean exit in 54.83 seconds. All eight native search characters match
the controller input, held keys do not repeat and the host mouse is unchanged
during controller interaction. Console commands only stage SIDNEY's scene.

A separate 35.34-second left-preferred sample opens native Inventory, loses
left-hand tracking and verifies right-hand pointing at the actual Exit button.
After left tracking recovers, the right trigger cannot select the left-owned
interface. Losing left tracking again while that right trigger remains held
does not click Exit. Releasing and pressing again does click it. Restoring left
tracking returns pointing to the preference, and left-trigger Exit works.
Native controller Quit cancellation/confirmation, zero exit, graceful SteamVR
shutdown, unchanged flat files/preferences and global configuration, and private
installation removal all pass. These are virtual devices, not physical-handset
usability or headset acceptance. Neither sample establishes sustained pacing.

The symmetric right-preferred handoff sample also passes in 37.60 seconds:
left fallback, no foreign/held-trigger selection, release-to-rearm, right
preference recovery, clean controller Quit and graceful runtime shutdown.
Both cases preserve flat files and global settings and remove the private
installation afterward.

Focused Python checks pass 553 tests with three privilege-related skips in
14.68 seconds, including the unapplied-setting regression. Full formatting,
lint, strict typing and spelling checks
pass. The renderer and compiled player remain byte-identical to the earlier
qualified artifacts, so no renderer rebuild is required for this launch option.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-left-hand-sidney-20261011/`
and the left/right samples at
`build/vr/steamvr-native-20261011-mirror-native-{left,right}-hand-handoff-20261011/`.

### 11 October: controller map labels and native travel

VR continues to use runtime-recommended eye targets independently of the
desktop mirror. These samples render the world at 1568×1568 per eye with a
1280×800 native interface source. Legacy desktop resolutions are not VR release
requirements. This does not establish physical-headset readability or sustained
performance.

An actual SteamVR virtual-controller map test exposed missing location labels.
The native location artwork highlighted and controller selection traveled to
Cuiza, but stationary pointing did not produce a tooltip. The bridge sent the
same native mouse-move event every rendered frame. GK3's ToolTip::MouseMove
restarts its appearance animation while hidden, preventing that animation from
finishing under continuous synthetic movement. An unchanged native mouse point
must not become a new movement event merely because another XR frame completed.

The bridge now remembers the last delivered point, layer and hand. Unchanged
points skip only native pointer movement. Changed coordinates or ownership
still deliver movement, Select press/release and native world noun picking
continue, and cancellation invalidates the cache so recovery delivers a fresh
move. Native execution regressions cover stationary points, both coordinate
axes, hand/layer changes, tracking recovery and continuing world hover. This is
an executable-side input correction, not a renderer or artwork change.

Right-preferred and left-preferred actual SteamVR samples pass in 44.24 and
43.75 seconds. Both require highlighted artwork and the delayed label at Cuiza
and Rennes-les-Bains, preserve the retail map's response to Back, select Cuiza,
complete native travel to TR1/110a and recover stereo. Controller-operated Quit
→ No → resumed stereo → Quit → Yes exits with code zero. The public supervisor
reports no error, SteamVR shuts down gracefully without forced components, flat
files and global settings are unchanged, and the private installation is removed.
The original scene setup uses the debug console only to open the driving map.
Subsequent hovering, travel and Quit use actual SteamVR controller actions, not
host mouse events or writes to a fake XR action frame. Physical-controller and
complete-map acceptance remain open.

The first diagnostic attempts incorrectly demanded a highlight from the current
Rennes-le-Chateau location, and immediate Quit availability during station
arrival. Those are not production fixes: the qualifier now samples selectable
destinations and waits for the native Options button to enable. Failed samples
remain in the ignored evidence folder and are not counted as passing tests.

Both-eye captures show the restored station and Rennes-les-Bains labels. The
renderer remains SHA-256
`3f5cb3767f8763ec27cfb16e151529eb35ec1c0a46f6eacff31b28919d6d0385`.
The generated player is now SHA-256
`ec176c4e5f6632db40eb3b619212a2def19ff548d93409d6fd237e6a8d9bc887`.
Focused regressions pass **558 tests, three skipped, in 14.20 seconds**.
Full formatting, lint, strict typing and spelling checks pass.

### 11 October: native Inspect Undo with both controller hands

The actual SteamVR qualifier now separately exercises the native Inspect Undo
action. After Inspect moves to WINDOW's authored close-up camera, the selected
virtual controller re-aims at the previously observed native world hit, opens
the object's action menu and selects its first Undo cell. It does not invoke
UnInspect through the console, write the camera, or treat Back as Undo.

Left-preferred and right-preferred runs pass in **40.19 and 39.96 seconds**.
Both restore the original camera position and full projection/view matrix with
zero measured error. The menu retires, then controller pause/resume, native
stick movement, 30-degree snap turning, held-input rejection and neutral
rearming pass. Compositor captures show the inspected window and returned
room views without a retained action menu. Controller Quit cancellation and
confirmation exit zero through the public supervisor. Flat files and global
SteamVR settings are unchanged, private VR installations are removed and
SteamVR closes gracefully without forced components.

Both use the current readable-subtitle renderer/player recipe. Stereo eye
targets remain **1568×1568**, as recommended by this virtual-headset runtime;
the independent desktop mirror remains **1280×800**. These sizes are not a
fixed resolution requirement for physical headsets. Runtime-recommended eye
targets, rather than legacy 1024×768 compatibility or physical panel dimensions
alone, remain the VR default. No physical-headset comfort or sustained delivered
frame-rate acceptance is claimed by this short interaction qualification.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-left-inspect-undo-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-right-inspect-undo-20261011/`.
Each contains `runtime-world-actions.json`, `world.json`, `world-run.json` and
both-eye Undo menu/restoration captures. Renderer SHA-256:
`0537e12f1bc83dcee18c073940c11ffdc9ccd2dbf6502e17d93e3293b834cc8c`.
Player SHA-256:
`6063e48881475bc0aaf4433f0f1af8b45231cf9dfaee76f1eba0aa492f395ba6`.

### 11 October: readable dialogue without raising eye resolution

The native window Look caption was only about 17 source pixels high on the
ordinary 1.6 m-wide interface canvas. Increasing headset render resolution
would not correct that small angular size. Dialogue now explicitly selects an
independent transparent, noninteractive subtitle layer, with a stable
bottom-center anchor below the view. Its physical scale is independent of menu
expansion, score placement, caption line length and the desktop mirror.
At the default source size, that yields roughly two degrees of glyph height.
Native font pixels, layout, authored caption timing and flat play are unchanged.
This is a readability improvement, not a higher-resolution font reconstruction.

The renderer composes world eyes, menus, ordinary HUD labels and dialogue in
one predicted frame, using independent GPU targets. No extra frame wait or
desktop readback is introduced. Sources are lazily allocated and reused, and
only current producers submit layers. Native lifecycle/geometry tests and real
GPU pixel tests cover simultaneous layers, unchanged menu picking, transparency,
retirement, reappearance and teardown. The fresh recipe passes all flat/native
and six OpenXR GPU qualification runs. Focused Python checks pass 394 tests,
with three skips, and full lint/strict typing pass.

Actual SteamVR with the null headset and tracked virtual Index controllers then
passes original WINDOW Look voice-over, the new producer flag, caption
appearance/retirement, Back pause/resume, movement, 30-degree release-armed snap
turns, and controller Quit No/resume/Yes in 44.06 seconds. Both compositor eyes
were visually inspected live and after retirement, against the earlier small
caption capture. Text is substantially larger and no residual glyphs remain.
The runtime-recommended eye targets remain 1568×1568, independently of the
1280×800 mirror. The private flat files are unchanged and the prototype is
uninstalled after testing. SteamVR closes gracefully with ten close requests,
no forced components, and unchanged global configuration; no owned game/runtime
process remains. Physical-headset comfort, broader dialogue and
multiline coverage remain open. This does not establish delivered headset FPS.

Renderer SHA-256: `0537e12f1bc83dcee18c073940c11ffdc9ccd2dbf6502e17d93e3293b834cc8c`.
Player SHA-256: `6063e48881475bc0aaf4433f0f1af8b45231cf9dfaee76f1eba0aa492f395ba6`.
Build: `build/vr/readable-subtitles-accepted-20261011/`.
Evidence: `build/vr/steamvr-native-20261011-mirror-native-left-readable-subtitle-20261011/`.
Earlier failed invalid-flag and missing-test-export builds are retained as
diagnostic evidence, not counted as qualified builds.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-runtime-map-v5-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-left-map-stationary-hover-20261011/`.

A left-preferred actual SteamVR SIDNEY regression also passes with this exact
player in 52.29 seconds: controller typing of `vampires`, held-key rejection,
native search results, Home/editor retirement, Exit to stereo and controller
Quit. The supervisor returns zero, runtime shutdown is graceful without forced
components, and flat files/global configuration remain unchanged. Evidence:
`build/vr/steamvr-native-20261011-mirror-native-left-sidney-stationary-hover-20261011/`.

### 11 October: packaged world-pointer feedback

VR resolution is chosen per eye from OpenXR's recommended view configuration,
which accounts for the headset and runtime render settings. It need not equal
the physical panel's pixel count: distortion compensation and runtime scaling
can require a different render target. The desktop/interface source remains a
separate implementation detail, not the eye resolution or a 1024 compatibility
requirement.

Actual SteamVR controller testing found that the packaged world compiler left
the stereo scene's picking callback disconnected. Native hover/action picking
still ran, but the renderer could not query a hit for its aiming beam/marker.
The world compiler now installs and verifies that callback, rejects an occupied
slot before mutation, and rejects a disconnected/replaced callback afterward.
Native execution tests invoke the installed callback rather than directly
calling its otherwise disconnected entry point.

The corrected package-generated player, SHA-256
`8596e2ab2f50df8db78adcf69c10050ab10b17f0c3ef3de6db79010bd8c5bab1`,
uses the unchanged qualified renderer. A right-preferred actual SteamVR sample
completes in 35.10 seconds: a tracked ray produces a native scenery hit, the
beam/marker appear in both inspected compositor eyes, trigger Select opens the
original action menu, and native Inspect moves to the window close-up. Controller
Quit cancellation/confirmation exits zero, with no supervisor errors, unchanged
flat files/global settings, graceful SteamVR shutdown and private uninstall.

A stronger follow-up initially demanded that Back restore the pre-Inspect camera.
Reviewing the actual action-bar capture shows another test-label mistake:
the first button is Inspect, followed by the eye-shaped Look button. Inspect
uses WINDOW's authored room camera at `(114, 60.81, 200)` in `R25.SIF`.
Look's separate `R25_ALL.NVC` action uses `WalkToSee` followed by a voice-over.
Back pauses/resumes the room rather than invoking the separate Inspect Undo
action. No production control-routing change was needed for this finding,
and inspection undo still needs its own qualification.

Corrected left-preferred and right-preferred actual SteamVR runs pass in 37.35
and 37.15 seconds. Both select scenery, invoke the authored Inspect camera,
pause/resume without changing that camera, and prove returned control through
actual stick translation. The right-preferred run also measures a 29.9998-degree
native snap turn, rejects repetition while held, and rearms after neutral to
restore the original heading with the opposite turn. Neutral is supplied after
the comfort fade restores world input, not during its deliberate input lock.
Both runs complete controller Quit cancellation/confirmation, exit zero, retain
flat files and global settings, uninstall privately and close SteamVR gracefully
without forced components. These remain virtual-controller tests, not headset
comfort or physical-controller acceptance.

Focused regressions pass **561 tests, three skipped, in 14.49 seconds**.
Full formatting, lint, strict typing and spelling checks pass. Physical-headset
acceptance, complete gameplay coverage and sustained delivered performance
remain open.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-runtime-world-linked-v5-20261011/`,
`build/vr/steamvr-native-20261011-mirror-native-left-world-look-control-v9-20261011/`
and `build/vr/steamvr-native-20261011-mirror-native-right-world-look-navigation-v11-20261011/`.
Failed samples with the incorrect Back assertion and premature neutral input
remain separate and are not counted as passing qualifications.

### 11 October: native Look dialogue and subtitle retirement

The corrected qualifier distinguishes Inspect (the first action-bar cell) from
Look (the eye-shaped second cell). Earlier window camera checks called the
first cell Look, which was a test-label error. Inspect changes the camera and
does not invoke the Look voice-over. Selecting it while waiting for subtitles
therefore cannot establish a caption defect. A direct-console diagnostic with
the original `StartVoiceOver("1LL9644QR1", 1)` first confirms the native subtitle
transport, but is deliberately not counted as controller interaction proof.

Selecting the actual Look button with a left-preferred SteamVR controller now
passes end to end in 43.12 seconds. The original voice-over's caption, “Nice
view. If there was anything to look at, that is.”, appears in both compositor
eyes. Native caption count/cache readiness change from one/ready to zero/not
ready, and inspected retirement captures contain no subtitle. Navigation then
continues: Back pause/resume, actual stick translation, a 29.9956-degree snap
turn, held-input rejection and neutral rearming all pass. Controller Quit
cancellation/confirmation exits zero through the public supervisor. SteamVR
closes gracefully, no components are forced, global configuration and flat
files are unchanged, and the private installation is removed.

Captions are enabled only for this diagnostic run and the original preference
snapshot is restored afterward. Renderer/player hashes are unchanged. These
captures expose small subtitle glyphs, so appearance/retirement does not imply
comfortable headset readability. That remains separate work, along with broader
dialogue coverage and inspection undo. No physical-headset check is claimed.

Evidence: `build/vr/steamvr-native-20261011-mirror-native-left-world-look-voice-v16-20261011/`.
The direct-cue diagnostic is `...native-left-world-caption-cue-v14-20261011/`.
Earlier failed Inspect-as-Look and Look-as-camera expectations remain recorded
separately, not counted as production regressions or passing qualifications.
Full formatting, lint, strict typing and spelling checks pass.

### 11 October: process-identified timing and center-draw cost isolation

A new read-only background observer records SteamVR compositor frame timings,
focus/statistics process IDs and cumulative presentation counters. It neither
requests mirror textures nor performs GPU readbacks. Native OpenXR call timings
and the package's completed stereo counters are recorded in the same owned
session. Every timing sample is associated with the actual game process, and
captures happen outside the measured intervals.

The matching readable-subtitle renderer/player passes a 103.76-second private
run covering 20-second intervals in the hotel room, lobby and exterior. Each
steady-state summary excludes one second at either interval edge, retaining
the complete raw data. This avoids labeling late loading history as ordinary
rendering. For example, the exterior's raw compositor data contains a roughly
1,041 ms loading-frame duration received just after observation begins. It is
retained, not silently classified as a steady-state GPU stall.

| Scene | Stereo submissions/s | Median interval | 95th percentile | 99th percentile |
| --- | ---: | ---: | ---: | ---: |
| Hotel room | 117.25 | 8.35 ms | 9.99 ms | 15.34 ms |
| Lobby | 117.49 | 8.30 ms | 9.97 ms | 16.60 ms |
| Hotel exterior | 85.10 | 11.48 ms | 13.55 ms | 15.46 ms |

The virtual runtime predicts approximately 11.11 ms periods. Median time
outside the intercepted OpenXR calls is about 7.7 ms indoors and 10.9 ms
outside. The exterior's reported pre-submit GPU interval is about 10.7 ms
median. These GPU intervals can include scheduling and gaps between submitted
work, so they are not proof of GPU saturation or pure device-busy time. The
exterior does not meet the current sustained refresh-rate goal.

An independently configured virtual-headset stress sample requests 2880×2880
base views. SteamVR recommends **3524×3524** render targets, which the actual
player uses. Its desktop/source canvas remains **1280×800**. The same exterior
measures 89.55 submissions/s, with median/95th/99th intervals of
11.07/13.05/14.32 ms. Both compositor eyes were inspected using small previews
of the retained 4320×4320 raw captures. This is a larger-eye stress test, not
measurement of any physical headset's actual distortion profile. It also does
not establish pixel throughput as the primary limitation.

The null-driver counters require explicit calibration. An initial minimal
OpenXR baseline starts before compositor graphics initialization and fails to
select the Vulkan GPU. Its failed/idle output remains separate evidence.
Readiness now requires an initialized adapter and advancing compositor frames,
not merely a server process. The corrected minimal program completes **1,800
binocular Vulkan clear frames** on the RTX 4090 in 15.14 seconds, approximately
118.88 submissions/s. Its observer identifies the correct process. Nonetheless,
present and dropped totals rise together, with asynchronous reprojection flags,
just as in GK3 and idle null output. Consequently these virtual-display
counters cannot establish physical scanout FPS or a physical missed-frame rate.
The raw counters are retained; the headset-delivered performance gate remains
open rather than being declared successful or interpreted as 100% game drops.

A reversible private-child diagnostic then isolates the ordinary center-view
world draw. The production path renders two headset eyes and the separate
native center world. The diagnostic verifies the generated outer call site,
suspends only the owned primary thread to replace/restore that call, preserves
its argument cleanup, and never changes disk bytes or either eye callback.
Suppressing this draw is deliberately **not** a shipping mirror solution.

The first same-session sequence measures 87.41 → 118.08 → 97.50 submissions/s
for ordinary → isolated → restored rendering. A second sequence measures
87.00 → 117.66 → 105.00 → 119.07 → 99.08 across repeated restored/isolated
12-second intervals. Initial/warmed variation prevents claiming a universal
35% improvement. The warmed restored intervals still support an approximately
13–20% benefit from removing this duplicated work in this scene. Code is
restored before compositor captures and native controller Quit. Both runs exit
zero, preserve flat files/settings, remove the private installation and shut
down SteamVR gracefully without forced components.

Next implementation: replace the center geometry draw with a correctly owned
GPU mirror/update path, retaining native page history, save previews, overlays,
native picking and ordinary failure recovery. A stale desktop or skipped native
responsibilities is not an acceptable performance fix. No renderer/player
optimization has been adopted solely from this cost-isolation experiment.

Evidence folders under ignored `build/vr/`:

- `steamvr-native-20261011-mirror-sustained-compositor-timing-v1-20261011/`
- `steamvr-native-20261011-mirror-high-eye-compositor-timing-v1-20261011/`
- `steamvr-null-20261011-clear-compositor-calibration-v2-20261011/`
- `steamvr-native-20261011-mirror-center-draw-cost-isolation-v1-20261011/`
- `steamvr-native-20261011-mirror-center-draw-cost-isolation-v2-20261011/`

The first two include `timing-summary.json` and raw compositor/OpenXR CSVs.
`summarize_compositor_timing.py` reproduces those summaries. The baseline has
explicit frame-count evidence in `timing-metrics.json`. All successful sessions
record unchanged global settings and owned-runtime shutdown. Renderer/player
hashes remain `0537e12f1bc83dcee18c073940c11ffdc9ccd2dbf6502e17d93e3293b834cc8c`
and `6063e48881475bc0aaf4433f0f1af8b45231cf9dfaee76f1eba0aa492f395ba6`.

### 11 October: qualified GPU eye mirror primitive

An opt-in scene flag now copies the completed left engine eye to the independent
desktop canvas on the GPU, before presentation gamma. A centered crop preserves
aspect ratio without stretching. The desktop dimensions do not control either
headset eye. No additional geometry pass or CPU pixel readback is required.
Both eyes must complete before the copy. Failed eye draws and mismatched native
targets preserve the existing desktop and allow a subsequent valid frame.

Native surface ownership is updated after a successful copy. Preview copies and
CPU reads see the new pixels instead of the previous cached surface. Real-GPU
tests cover wide, tall and square targets, non-neutral presentation gamma,
render-target restoration, failed-frame preservation and recovery. A fresh
public build passes all six native tests, flat qualification, both full RGBA/BGRA
transport suites and four critical-copy policy/layout suites. The focused
Python tests pass with 305 passed and three skipped, and all lint checks pass.

The ordinary engine adapter does not enable this flag or remove its third draw.
A reversible diagnostic enables it only in the private child and suppresses
only the outer center draw. Both compositor eyes and the desktop are captured
and visually inspected while that diagnostic is active. The exterior measures
87.41 submissions/s initially, 117.99 with the mirror and suppressed center,
and 98.83 after restoring the warmed ordinary path. This supports approximately
19% improvement against the warmed comparison, not a universal gain or a claim
about physical headset scanout. Controller input is disabled in these timing
intervals, so they do not qualify native controller picking.

The private run exits normally in 73.17 seconds, preserving flat files and
global settings and stopping its owned SteamVR gracefully. Normal engine code
is restored before native Quit. Permanent adoption still requires native page
history, picking, previews, ownership and transition coverage. In particular,
the raw desktop eye mirror does not yet apply the OpenXR comfort visibility
fade. A populated mirror alone is not sufficient to ship center-draw removal.

Evidence: `build/vr/steamvr-native-20261011-mirror-eye-mirror-center-isolation-v1-20261011/`.
The fresh qualified build is `build/vr/eye-mirror-qualified-20261011/`.
Renderer SHA256:
`8a748709970cb3a94dc43f299688774b1ec12976598bb38cb148df5b45e9ce6e`.
The player remains
`6063e48881475bc0aaf4433f0f1af8b45231cf9dfaee76f1eba0aa492f395ba6`.
Nothing is installed into the user's ordinary Steam game or released.

Two additional actual SteamVR runs qualify the controller route with the same
GPU mirror and suppressed center draw throughout the world interaction. Right
and left hands each select the native window, open its action menu, Inspect it,
select it again and invoke native Undo. Restored camera position and matrix
errors are both zero. Controller Back pauses and resumes without changing that
camera. Stick movement returns, snap turning is approximately 30 degrees, a
held stick does not repeat, and neutral input rearms the opposite turn.
Host mouse position remains unchanged. Both compositor eyes are visually
inspected in the restored room and inspected-window menu samples.

The right/left runs take 39.87/39.49 seconds. Both restore ordinary code before
native Quit cancellation, stereo resumption and confirmed exit. They exit zero,
preserve flat files/settings, remove the private installation and stop the
owned runtime gracefully without forced components. These qualify the sampled
native picking/camera path, not all page history, previews, transitions or
physical controllers. Permanent center-draw removal remains unchecked.

Evidence under ignored `build/vr/`:

- `steamvr-native-20261011-mirror-eye-mirror-right-inspect-undo-v1-20261011/`
- `steamvr-native-20261011-mirror-eye-mirror-left-inspect-undo-v1-20261011/`

Each includes `runtime-world-actions.json`, both-eye captures, the scoped mirror
diagnostic in `world.json`, and lifecycle evidence in `world-run.json`.

### 11 October: integrated mirror and native page preparation

The complete prototype compiler now enables the qualified GPU mirror. Unlike
the earlier in-memory cost diagnostic, it retains the transition patch's actual
page-preparation logic. That logic publishes native room ownership and seeds
each handoff page once per successful presentation generation. It runs before
the eye copy so it cannot overwrite the new mirror with the previous page.
The ordinary transition wrapper is byte-for-byte unchanged. Both adapters are
generated from the same page-preparation implementation, not separate policy.

Only a successful stereo bridge result omits the third center geometry draw.
Hidden frames, an unavailable bridge and failed eyes still enter the original
draw. A test caught the initially zero bridge status being mistaken for success
when the export was missing. Every new transaction now starts with an explicit
failure status until the actual bridge returns. After a successful mirror the
native cached-center mode is invalidated, ensuring later fallback draws fresh
geometry rather than using a bitmap that no longer represents the visible page.
Camera/projection restoration and paired-frame ownership remain intact.

Executable behavior tests verify pair-only replacement, unavailable/failed
fallback, unchanged authored camera and stack cleanup, ownership before the
copy, and ordered seed → invalidate → mirror operations on exactly two handoff
generations, including a repeated setup within one generation. The focused
suite passes with 419 tests and three skips in 15.03 seconds. All formatting,
lint, strict typing and spelling checks pass. The renderer remains the already
GPU-qualified `8a748709970cb3a94dc43f299688774b1ec12976598bb38cb148df5b45e9ce6e`.
The new complete player is
`01a8dd0e0e0fe1627aa3974ed02f80a83b7f88f74962df475dcba178c71f5b37`.

Actual SteamVR right/left controller runs pass in 41.62/41.28 seconds without
memory edits to skip drawing. Both select, Inspect and Undo the original window,
restore the camera exactly, pause/resume, move and snap turn, then complete native
Quit cancellation/resumption/exit. A separate 53.93-second native save cycle
creates a real slot, changes to the lobby, restores the room, captures score
fade/retirement, and quits normally. Inspected compositor images show a populated
save preview and no visible score residue in the sampled retired frame. This
does not establish physical-headset readability or resolve every earlier fade
report. The save UI uses host input; startup and Quit use actual runtime virtual
controllers. All successful runs preserve flat files/global settings and stop
owned SteamVR gracefully without forced components.

An initial left repeat times out before the player starts. Private installation
recovery succeeds. Cleanup encounters a stale CIM row for an already-exiting
component with no executable path; the workbench now refreshes that inventory
before validating ownership. The retry passes. This failed observation remains
separate and is not evidence of a successful game run or a rendering defect.

Evidence under ignored `build/vr/`:

- `steamvr-native-20261011-mirror-owned-eye-mirror-right-world-v1-20261011/`
- `steamvr-native-20261011-mirror-owned-eye-mirror-left-world-v2-20261011/`
- `steamvr-native-20261011-mirror-owned-eye-mirror-save-cycle-v1-20261011/`

The integrated path still needs broader modal/map/movie/scene handoff coverage,
sustained pacing and headset acceptance. No ordinary installed game or release
is changed. The raw desktop mirror does not reproduce OpenXR's comfort fade,
as noted above; headset images retain that fade.

A subsequent counter-only pacing run measures **119.83 stereo submissions/s**
in the room and **118.33/s** in the exterior over separate 12-second intervals.
The same integrated player and qualified renderer are used, without in-memory
draw suppression or pixel captures during the intervals. Both exterior
compositor views are inspected afterward. The full run completes in 60.22
seconds with native Quit cancellation/resumption/exit, unchanged flat files and
global settings, and graceful owned-runtime shutdown. This verifies that the
integrated path retains the cost-isolation benefit in this short sample. It
does not qualify sustained physical-headset frame times or scanout FPS.
Evidence: `build/vr/steamvr-native-20261011-mirror-owned-eye-mirror-pacing-v1-20261011/`.

### 11 October: integrated mirror through native interfaces and movies

The same complete player (`01a8dd0e`) and GPU-qualified renderer (`8a748709`)
now pass four additional actual-SteamVR qualification runs. No center-draw
suppression or mirror diagnostic is applied in memory.

- Map: 43.54 seconds. Actual virtual-controller rays reach the station and
  Rennes-les-Bains hover targets, reveal their native highlights/tooltips,
  preserve the map on Back, and select the station to enter TR1/110a stereo.
- SIDNEY: 53.70 seconds. Actual virtual-controller keyboard rays type
  `vampires` character by character without held-key repeats, submit native
  search, retire the editor and return from SIDNEY to the room.
- Movies: 52.14 seconds. `day2-2.bik` completes naturally and `205PEND.BIK`
  is skipped with actual virtual-controller Back, through the native character
  handler rather than a host keyboard event. Holding Back across the handoff
  does not pause the restored room. World draws stop while movies submit 1,401
  and 111 XR frames respectively, then stereo resumes.
- Glides: 40.35 seconds. The original `FR_DU1` and `OPEN_WINDOW` moving-camera
  controllers route to stationary panels, stop immersive world draws, keep XR
  advancing, and recover stereo at their actual native destinations. The
  read-only observer records 86 and 62 interior moving samples respectively.

Map hover/travel, SIDNEY typing/search/return and movie playback/return images
were visually inspected in actual compositor eyes. All successful runs preserve
flat files and global settings, finish native Quit cancellation/resumption/exit,
and stop the owned runtime gracefully, with no forced components. Input actions
do not move the host mouse. These are synthetic runtime controllers, not worn
headsets or physical-controller acceptance.

The first glide attempt fails the observation gate for insufficient nonzero
panel publications in the second short glide. Its requested 3 ms `Event.wait`
actually samples approximately every 15.6 ms on Windows, missing the buffer's
short publication window. A 1 ms high-resolution sleep in the ignored read-only
workbench observer fixes that sampling problem. The retry retains every original
rendering/ownership assertion and passes without changing production artifacts.
The failed run is retained as a failed observation, not a rendering pass.

Evidence under ignored `build/vr/`:

- `steamvr-native-20261011-mirror-owned-eye-mirror-map-v1-20261011/`
- `steamvr-native-20261011-mirror-owned-eye-mirror-sidney-v1-20261011/`
- `steamvr-native-20261011-mirror-owned-eye-mirror-movies-controller-v1-20261011/`
- `steamvr-native-20261011-mirror-owned-eye-mirror-glides-v1-20261011/` (failed observation)
- `steamvr-native-20261011-mirror-owned-eye-mirror-glides-v2-20261011/`

Runtime-recommended eye targets remain independent of the 1280×800 native
interface/mirror canvas. These runs use 1568×1568 engine eye targets, as returned
by SteamVR during rendering. The earlier discovery probe's 1280×1280 dimensions
are not substituted for the live session's recommendation. No legacy desktop
resolution is required for VR acceptance. Formatting, lint, strict typing and
spelling checks still pass.

### 11 October: integrated mirror at a larger runtime eye target

The unchanged integrated renderer/player also pass a 93.86-second actual
SteamVR run with runtime-recommended **3524×3524 engine eye targets**. The native
interface/mirror remains **1280×800**, demonstrating that it does not limit eye
resolution. No pixel captures or draw-suppression edits occur inside the two
20-second room/exterior measurement intervals. The process-matched, read-only
compositor observer succeeds for each interval.

| Scene | Stereo submissions/s | GPU median | GPU p95 | GPU p99 | GPU maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| R25 room | 119.90 | 3.46 ms | 4.66 ms | 5.11 ms | 6.16 ms |
| RC1 exterior | 118.70 | 6.77 ms | 8.06 ms | 8.89 ms | 15.28 ms |

GPU statistics discard the observer's first pre-interval history batch and one
second at each measurement edge. There are 2,160/2,136 unique steady-state frame
rows, all matching the game's process. Raw outliers remain in the evidence.
Client-interval p95/p99 is 8.86/10.74 ms in the room and 9.47/11.67 ms outside.
These are sampled application/compositor measurements, not physical delivered
FPS or proof that every frame meets a 120 Hz budget. The exterior's tail exceeds
8.33 ms despite its improved average cadence. Null-headset scanout/drop counters
remain unsuitable for physical-headset acceptance.

Both exterior compositor eyes are captured after the timing intervals. Normal
controller Quit cancellation/resumption/exit passes, flat files/global settings
remain unchanged, and owned SteamVR stops gracefully without forced components.
Evidence: `build/vr/steamvr-native-20261011-mirror-owned-eye-mirror-large-pacing-v1-20261011/`.

The prototype's center-draw replacement milestone is now qualified across the
tested native ownership, page preparation, failure recovery, save-preview,
both-hand picking, map, SIDNEY, movie and glide paths, with a measurable benefit
at runtime-recommended eye sizes. Broader gameplay, long-session stability and
real-headset readability, comfort and sustained frame-time acceptance remain
unfinished. No normal installed game or release is changed.

### 11 October: native loading and controller recovery across five scenes

The matching integrated player/renderer pass a 72.05-second actual SteamVR
session through CS2/212p, BEC/312p, TE4/309p, RC1/110a and R25/110a. Host console
commands stage the chapter and authored camera. In each scene, actual runtime
controller input opens inventory and returns with Back after stereo resumes.
Controller Quit cancellation, resumption and final exit also pass. There are no
supervisor errors, the player exits normally with code zero, private flat files
and display preferences remain unchanged, and owned runtime processes close.
The cave's left-eye and temple's right-eye compositor captures were inspected.
This is synthetic-controller qualification, not physical-headset acceptance.

The initial probes incorrectly treated native room publication as completed
loading. The game can publish that layer before starting a chapter movie or
accepting inventory input. A later host key and controller retry both worked in
the cave. Reusing the visual suite's rendered-room/cursor readiness and authored
camera staging makes the first controller inventory attempt pass in all five
scenes, without changing native locks or production input code. Earlier failed
probes are retained rather than counted as passing qualification.

The read-only observer still records maximum submission gaps of approximately
302 ms in CS2, 309 ms in BEC, 278 ms in TE4, 537 ms in RC1 and 198 ms in R25.
These observations cover the whole staged exercise, including console commands,
native loading, controller transitions and compositor capture. They do not yet
isolate loader latency or establish smooth continuous headset presentation.
That performance/comfort requirement remains open, independently of successful
scene and input recovery. A following timing probe should label phases and
exclude diagnostic image captures before attributing the gaps to the game.

Evidence: `build/vr/steamvr-native-20261011-mirror-owned-eye-mirror-loading-v7-20261011/`,
including per-scene samples, controller hardware publications, both-eye captures,
`scene-loading-transitions.json`, `world-run.json` and `world.json`.

### 11 October: eliminate blocking native button feedback in VR

A capture-free follow-up labels native loading, camera staging, stereo recovery
and controller recovery separately. A diagnostic thread sampler identifies two
blocking waits in the original native button activation path: 70 ms followed by
50 ms, before its callback. These waits explain the repeated roughly 140 ms
inventory-return gap. Eye targets are already cached; this is not evidence of
reallocating eye targets during each transition.

The VR input patch replaces only that button's local sleep target. It omits those
two feedback waits when the panel is enabled, has submitted frames and reports
successful presentation. Dormant VR, missing frames, hidden/failed presentation
and other wait durations retain the original Windows sleep. Native repainting,
callbacks, locks and animation remain unchanged. No extra simulation or OpenXR
submission is performed inside the callback, and the global sleep import is not
modified.

The updated player and unchanged qualified renderer pass a 69.22-second actual
SteamVR session covering the same five scenes. Capture-free maximum intervals
within the controller inventory/Back phase improve as follows:

| Scene | Before | After |
| --- | ---: | ---: |
| CS2 laser scene | 136.49 ms | 22.31 ms |
| BEC coordinate device | 133.97 ms | 20.07 ms |
| TE4 temple | 141.88 ms | 27.65 ms |
| RC1 exterior | 143.34 ms | 30.52 ms |
| R25 room | 136.70 ms | 22.41 ms |

Native chapter/loading pauses of roughly 0.2–0.6 seconds remain a separate open
issue. These measurements establish removal of the button feedback stall, not
continuous low-latency loading or physical-headset frame delivery. Controller
Quit cancellation/resumption and normal exit pass, compositor eyes are visually
inspected after those actions, private flat files/display preferences remain
unchanged and owned runtime processes close gracefully.

Behavioral regressions cover all three executable profiles, stack/argument
preservation, inactive/failed-session fallbacks and patch-anchor validation.
The focused compilation/input run passes 235 tests in 8.16 seconds. The broader
VR regression run passes 578 tests with three skips in 12.70 seconds. Formatting,
lint, strict typing and spelling checks pass.
The complete default suite passes 4,425 tests with 23 skips and 402 slow-test
deselections in 78.46 seconds, with no live-game experiment running. This does
not meet the separate under-60-second test-duration gate.

Ignored evidence under `build/vr/`:

- `steamvr-native-20261011-mirror-owned-eye-mirror-loading-timing-v1-20261011/` (baseline)
- `steamvr-native-20261011-mirror-owned-eye-mirror-loading-stacks-v1-20261011/` (diagnostic sampling, not timing qualification)
- `steamvr-native-20261011-mirror-vr-button-waits-loading-timing-v1-20261011/` (updated player)

The updated player SHA256 is
`42f02aa02ad125dc545774f8b1d38d0203542decab67fabb717e27e574839e6b`.
The renderer remains
`8a748709970cb3a94dc43f299688774b1ec12976598bb38cb148df5b45e9ce6e`.

A separate 47.83-second diagnostic repeat with the updated player samples the
remaining cave/exterior loading gaps. The cave sample executes the native
24-bit BGR-to-RGB565 conversion loop at `0x54f087`; the exterior sample waits
inside `CreateFileA`, called from the native resource-open path at `0x55da27`.
One earlier location-command sample is inside SteamVR's client through the
renderer. These are distinct observations, not proof that one call accounts
for the entire gap or that a renderer target is repeatedly recreated.

The diagnostic run passes stereo recovery, actual controller inventory/Back,
normal controller Quit and cleanup for both scenes. Thread suspension is
explicitly marked as diagnostic and excluded from timing qualification.
Evidence: `build/vr/steamvr-native-20261011-mirror-vr-button-waits-loading-stacks-v2-20261011/`.
Pixel conversion and file loading remain unchanged pending a measured,
faithful optimization or a safe loading-presentation design. Native callbacks
are not made reentrant just to increase the frame counter.

### 11 October: score retirement across ordinary and puzzle scenes

The updated private player and qualified integrated renderer pass a 92.19-second
actual SteamVR exercise through R25, LBY, RC1, CS2 and BEC. Native pointer hover
opens the status line and moving away starts the original fade timer. This part
uses host input with VR controller ownership disabled, not synthetic writes to
text opacity/timers or a claim of physical-controller acceptance. Actual runtime
controllers handle Play and the final Quit cancellation/resumption/exit.

Each scene captures visible, intermediate-fade, retired and settled images in
both compositor eyes, alongside a read-only native ownership/alpha trace. All
ten measured glyph regions have zero pixel difference between retirement and
the later settled image. The cave's right-eye and exterior's left-eye enlarged
glyph strips are visually inspected: text fades and disappears without the
previous residual text pattern in those captures. This alone does not exclude a
persistent mark present in both late captures, so a separate clean-before-hover
comparison is needed before treating this as complete artifact reproduction.

The first attempt passes its first three scene fades but stops before CS2
because the test's chapter-staging loop waits for the destination without
skipping the native introduction. Reusing the already-qualified introduction
handling makes the retry pass all five scenes. No production-code change or
relaxed fade/retirement assertion is used, and the failed attempt is retained.

The passing player exits normally with no supervisor errors, private flat
files/global runtime preferences remain unchanged, and owned SteamVR processes
close. Evidence under ignored `build/vr/`:

- `steamvr-native-20261011-mirror-integrated-mirror-five-scene-score-v1-20261011/` (failed staging)
- `steamvr-native-20261011-mirror-integrated-mirror-five-scene-score-v2-20261011/` (passing five-scene run)

The passing folder includes source traces, both-eye BMP captures,
`status-suite.json`, `status-pixel-review.json` and enlarged review strips.

A 58.15-second clean-baseline repeat strengthens that evidence in the bright
RC1 exterior and dark BEC cave. After initial status retires, it captures both
eyes before triggering a fresh native hover/fade. Each retired image is compared
with that original clean image across the entire padded glyph rectangle, not
only selected white text pixels. All four eye/scene rectangles match exactly,
with maximum channel difference zero and no changed surrounding pixels. This
excludes a persistent residual inside those tested score regions, rather than
merely observing agreement between two late images.

Native controller Quit cancellation/resumption and final exit also pass, private
flat files/runtime preferences remain unchanged and owned SteamVR shuts down
gracefully without forced components. Evidence:
`build/vr/steamvr-native-20261011-mirror-integrated-mirror-clean-score-v3-20261011/`.
Physical-headset readability and the broader first-release gates remain open.

### Fingerprint held-input qualification, 11 October 2026

The new actual SteamVR virtual-controller fingerprint test uses native
`ShowFingerprintInterface("MIRROR")` only for scene staging. Controller rays
then select the brush, apply powder and make 48 held-trigger strokes across
the native print rectangle. Native dust count increases from zero to 47 and
print opacity from zero to approximately 0.94. After release, eight further
motions leave both values unchanged. Putting the brush down also succeeds.
Both compositor eyes and the desktop mirror are captured.

An initial false failure came from the diagnostic rig releasing Select in
each `point` publication. Its movement helper now accepts explicit held button
and trigger values. This did not require a production drag-handler change.
The diagnostic also distinguishes left B (Menu) from right B (Back).

The initial return failure is resolved. Native delivery tracing identifies a
temporary script/dialogue child that consumes the first Back press and blocks
ordinary Exit activation. The next Back closes the workstation. Once the
temporary child is dismissed, pointing at the visible Exit button and selecting
it also returns to the room. This is ordinary native behavior, not a missing
controller event, and requires no production input-routing change.

The collection test then selects tape, lifts the print and places it on paper.
Its first tape attempt aimed the tool's top-left pointer anchor at the print
center. Native lifting instead checks the tape's center, adding half its authored
33×54 dimensions. Aligning that contact center makes lifting succeed. Placing
the lifted print on paper closes the native workstation automatically and
returns to stereo. The test stops reading that retired layer after collection.
No forced layer pop, fabricated print opacity or inventory write is used.

Two subsequent uninstrumented public-launcher runs qualify the complete
collection flow and the separate visible-Exit flow through actual SteamVR
virtual-controller actions. Controller Play, native Quit cancellation/resumed
stereo and confirmed normal exit also pass. The host mouse does not move.
These tests stage the MIRROR workstation through the native console; they are
not a full story playthrough or physical-controller acceptance.

Evidence is under ignored
`build/vr/steamvr-native-20261011-mirror-fingerprint-hold-v7-20261011/`, including
per-step native state, runtime hardware publications, compositor captures and
the failed return assertion. The sample takes 37 seconds. Failure recovery
stops the owned child, removes its private VR installation, restores the
registry snapshot and verifies unchanged flat files. SteamVR closes gracefully
without forced components; global runtime configuration remains unchanged.
The ordinary installed game and production renderer are not modified.

Passing collection evidence is in
`build/vr/steamvr-native-20261011-mirror-fingerprint-collection-v15-20261011/`
(40.72 seconds). The separate visible-Exit repeat is in
`build/vr/steamvr-native-20261011-mirror-fingerprint-exit-v16-20261011/`.
Both use the same qualified renderer/player, headset-recommended 1568×1568
eyes and separate 1280×800 native canvas. Both-eye compositor captures, native
tool states, runtime controller publications and normal player exit are
recorded. Flat files and global runtime preferences remain unchanged; SteamVR
shuts down gracefully without forced components. The focused controller/tool
regression suite passes 192 tests in 1.73 seconds, with one slow test deselected.

### Native puzzle controls and a missing coordinate HUD, 12 October 2026

Actual SteamVR controller rays select the CS2 laser head at its live native
world position and open its original verb menu. A turn changes the first
head setting from 2 to 3, leaving the other four unchanged. The opposite turn
restores all five original settings. Native action/camera locks are respected,
interactive stereo returns and controller Quit exits normally. The 54.63-second
repeat is under
`build/vr/steamvr-native-20261011-mirror-runtime-laser-inverse-v3-20261012/`.
This qualifies sampled turn controls, not the complete staircase puzzle.

A BEC coordinate-device run reproduces a separate rendering omission. Native
`ShowCoord`/`on` staging displays the GPS in the desktop mirror, but neither
compositor eye contains it. Its bitmaps, power button, coordinate text and
animated coordinate image are siblings under RoomLayer, not an action menu or
toolbar. The current package's room-overlay producers omit these widgets.
Evidence is in
`build/vr/steamvr-native-20261011-mirror-runtime-coordinate-v1-20261012/`.
That run's successful process exit is not a rendering pass for this HUD.

An ignored, reproducibly compiled native experiment captures those actual
drawing routines into an independent RGB565 source, without copying a room
page or changing original device/gameplay state. It includes the owned animated
coordinate image, text, crosshairs and power control. Physical crop bounds use
the same corner height/768 affine as Runtime2D, rather than the smaller raw
object rectangle. The native source appears over the stereo world in the
compositor; the device does not require replacing stereo with a desktop quad.

Controller testing also exposes a package input-routing defect: a qualified
interactive overlay hit still takes the world route unless an action menu or
toolbar is visible. The router now gives a completed interactive hit priority,
while retaining failed-world-frame rejection. Ownership handoff cancels old
presses and requires a released trigger before selecting the new control.
Navigation similarly requires neutral sticks before returning from UI ownership.
Regression fixtures now distinguish ordinary world rays from actual UI hits,
instead of claiming both simultaneously.

With that input fix, the experimental device's controller power button hides
the original native widgets, withdraws overlay ownership and restores stereo.
Native Quit cancellation/resumption and confirmed exit pass. The 49.72-second
run records an experimental private-player hash, not a shipping composition:
`build/vr/steamvr-native-20261011-mirror-coordinate-overlay-v8-20261012/`.
Its renderer is unchanged. Normal-game files and global runtime preferences
remain unchanged; SteamVR shuts down gracefully without forced components.
The focused input/navigation suite passes 237 tests in 2.57 seconds, with lint
and strict typing passing for the changed files.

At this experimental milestone the coordinate source was **not integrated into
the package**. The subsequent package integration and qualification below
supersede that implementation gap, not the full-story or headset acceptance
gates. The experimental trampoline remains under ignored `build/vr/`.

The ordinary, unaugmented public VR composition also passes a 42.48-second
controller world-Select → native Look → pause/resume → stick movement/snap turn
→ Quit exercise after the general pointer-priority change. No GPS diagnostic
hooks are installed in that repeat. It exits normally without supervisor errors,
preserves flat files/global runtime preferences and shuts SteamVR down gracefully:
`build/vr/steamvr-native-20261011-mirror-overlay-priority-world-v9-20261012/`.
The broader selected VR regression run passes 1,710 tests with three skips in
27.89 seconds; this is not the entire default suite or physical-headset acceptance.

One earlier laser attempt stops before graphics when SteamVR's server watchdog
aborts during a settings write. A later observation also times out starting
PowerShell/CIM. The lab now uses native process snapshots and handle-based
identity checks, retaining the rule never to stop an unverified foreign process.
A first sampled inventory takes 26.6 ms. These are workbench improvements, not
a claim that every SteamVR runtime failure is fixed.

### Package coordinate-device source and lifecycle, 12 October 2026

The ordinary VR compiler now installs a dormant `.gk3vg` producer, without the
experimental menu-query or ownership trampolines. Its native GPS adapter export
is checked through the full Runtime2D composition. Public deterministic rebuild
and verification cover the new hooks, payload and producer-owned activation.
The panel combines the device with stereo and appends menus above it, retaining
the shared physical drawing/picking coordinates. No renderer rebuild is needed.

Capture runs the actual owned siblings in the RoomLayer's native reverse draw
order. Unique live ownership, concrete classes, bounded current child lists,
unchanged source bounds, successful transfers and the current page generation
are required before publication. Changed, missing, hidden or replaced sources
withdraw their interactive footprint. Busy captures defer surface release;
destruction cannot release a newer owner's source. The crop uses signed floor
rounding on all four edges, exactly as the native GPS transfer does.

The uninstrumented package-generated run passes in 49.66 seconds, including
both-eye GPS images, native controller power-off, Quit cancellation/resumption
and confirmed exit:
`build/vr/steamvr-native-20261011-mirror-gps-package-v10-20261012/`.
An expanded 59.02-second run verifies toolbar coexistence, Back, power-off,
reopening and replacement by the hotel room. Two created caches are each
released, and no GPS source remains after replacement. Native Quit and graceful
SteamVR shutdown pass, with private flat files and global preferences unchanged:
`build/vr/steamvr-native-20261011-mirror-gps-lifecycle-v11-20261012/`.

The expanded run includes a bounded, one-shot snapshot of the independent CPU
source. Its temporary diagnostic hook is restored before controller actions.
Every one of the 78,315 compared visible source pixels differs from the desktop
by at most one RGB level, consistent with RGB565 conversion rounding. The four
outer desktop columns darkened by Windows' window shadow are excluded, not
treated as game pixels. Both compositor eyes contain the map, crosshairs, text
and power control; closing the device removes it. The two-second uncaptured GPS
sample measures 119.17 stereo submissions/s at runtime-recommended 1568×1568
eyes and an independent 1280×800 canvas. This is not headset-delivered FPS.

The new native execution tests cover current/foreign/damaged source probes,
floor rounding, existing-part preservation, stale/cold/busy caches, changed
owners/extents/bounds, capacity failure, exact-once/deferred release, native
destruction behavior, dormant capture and actual reverse child order. The GPS
and public composition tests pass 178 cases in 14.60 seconds. Changed-file lint
and strict typing pass. The broader selected VR regression run passes 1,851
tests with three skips in 32.06 seconds; this is not the full default suite.
Physical-controller readability/comfort, acquiring and
using the device through the full story, and sustained headset pacing remain
unfinished acceptance gates. All game experiments use the private workbench.

### SIDNEY browsers and a native analysis sequence, 12 October 2026

The expanded package-player/controller run covers Search typing, opening an
email, opening the native analysis file list and parchment, and browsing the
translation file list. Non-editor pages retire text focus without showing an
irrelevant keyboard. Controller Home/Exit returns to the room; Quit cancellation,
resumed stereo and confirmed exit pass. Both-eye captures and native tree/input
observations are retained in the 75.62-second run:
`build/vr/steamvr-native-20261011-mirror-sidney-browse-v3-20261012/`.
Its many diagnostic captures are not a performance benchmark.

A subsequent controller sequence starts the parchment's native recognition,
dismisses its explanation, selects Extract Anomalies, chooses French and reads
the original result. Popup controls are selected from their current native
button rectangles, including ancestor visibility, rather than reusing a fixed
point from another message. The test verifies class, live bounds and selected
controller delivery before clicking. It waits for the original narration/action
lock to retire before closing the result, then returns through Home and Exit to
interactive stereo and normal Quit. The successful 66.83-second run is:
`build/vr/steamvr-native-20261011-mirror-sidney-analysis-v7-20261012/`.
Its renderer/player match the GPS integration's qualified composition. SteamVR
shuts down gracefully with no forced components, and private flat files and
global preferences remain unchanged.

Earlier attempts are retained as failures. One reused the shorter map message's
OK position, which missed the taller parchment message. Another selected the
result while native narration still owned input (`C_PLAYACTION`). Waiting for
that native state to retire succeeds without changing production input routing
or forcing a lock clear. This is not proof that every possible stationary-pointer
handoff is correct. Anagram parsing, other analysis actions and the remaining
required editor routes still need qualification; no full-SIDNEY completion is
claimed from this sequence.

The first browser run instead fails during unusually slow preparation: the
workbench's child-creation deadline expires before its launcher thread creates
the child, and a PowerShell cleanup call races the child's exit. Fixed-scope
workbench recovery now inventories processes natively and binds identity,
termination and wait to the same handle. Exact private installation removal,
registry restoration and unchanged flat files are verified after that failure.
No foreign process or ordinary installed game is stopped. The next run reaches
gameplay; its separate diagnostic graph failure is repaired before the passing
browser repeat. These are workbench corrections, not renderer improvements.

Compilation behavior tests now reuse an immutable per-profile compiled baseline
and give each case a fresh cloned mutable image. Actual compilation/rebuild,
calibration rejection and isolated renderer binding tests remain. The focused
37 tests pass in 7.19 seconds, with changed-file lint/strict typing passing.
The full default Windows suite passes 4,570 tests, with 23 skips and 402 slow
cases deselected, in 74.46 seconds. The under-60-second fast-suite gate remains
open, as do physical-controller/headset acceptance and the broader game coverage.

### Native text confirmation, 12 October 2026

The Arcadia translation puzzle exposes a real input gap: its missing-word
editor has no OK button and requires Return. Printable typing and ordinary
editing intentionally could not submit it. The controller keyboard now has
an explicit Enter key. Its separate confirmation action reaches the verified
native text-key handler only after the same editor, layer, epoch, tracking and
modifier checks. It does not synthesize a host key or reinterpret Return as a
character. The native mailbox is consumed before dispatch; callbacks may close
the editor or paint synchronously without repeating the input.

A fresh public renderer build passes its native and real-GPU qualification.
The actual SteamVR controller run stages the original Arcadia scanner file,
selects Latin to English, answers the native incomplete-sentence prompt, types
`s`, `su`, `sum` into the actual editor buffer, then selects Enter. Both-eye
captures show the original updated translation and appended `SUM`; the editor
and keyboard retire. Held letters and Enter do not repeat. Home, native Exit,
Quit cancellation/resumption and confirmed exit pass. The 72.56-second run
has no supervisor errors, graceful SteamVR shutdown, unchanged private flat
files/preferences and verified VR uninstall:
`build/vr/steamvr-native-20261011-mirror-sidney-arcadia-enter-v14-20261012/`.

The renderer SHA-256 is
`a242102b45d0a8cbabc781b9f4d330cf10d9e51920a7397227039cace6b333c4`.
The focused native text tests pass 111 cases in 1.11 seconds. Combined text and
public composition tests pass 148 cases in 8.36 seconds; lint and strict typing
pass. Earlier attempts that sought a nonexistent OK button are retained as
failed diagnostic runs. No UI buffer or solved-puzzle flag is written by the
successful interaction. Scanner acquisition is fixture staging, not proof of
the full story route. Anagrams, other editors and physical-headset acceptance
remain open, and the ordinary installed game is untouched.

### Multiline notes and caret alignment, 12 October 2026

SIDNEY's Suspects notes field inherits the ordinary character handler but uses
a separate native multiline key handler. The previous qualifier correctly
rejected the unrecognized handler, leaving this page without a VR keyboard.
Read-only analysis of the normalized retail executable verifies its wrapper:
Home/End retain multiline line-list behavior, while Return and ordinary editing
delegate to the existing base key handler. The multiline Return callback inserts
the original newline. The VR qualifier now admits these two explicitly anchored
key handlers, validates the larger multiline object, and calls the recipient's
verified native handler rather than substituting single-line behavior.

Controller typing and reopening pass in a 56.30-second run, but its images expose
an incorrectly positioned caret in the desktop and both eyes. This is not an
OpenXR transform error: multiline drawing uses a distinct native FillRectangle
call site that bypassed the existing SIDNEY caret affine. Both single-line and
multiline calls now share that scoped adapter. Native colors, original argument
storage, null rectangles and offscreen/inactive drawing remain unchanged.
Twelve executed behavior cases cover these boundaries and the shared coordinate
mapping. The 56.75-second repeat shows the caret correctly beside `NOTE` in the
desktop and both eyes:
`build/vr/steamvr-native-20261011-mirror-sidney-suspects-caret-v5-20261012/`.

The expanded 57.77-second repeat types `note`, uses Home and End to verify native
caret indexes zero and four, presses Enter to create the native newline, types
`ok` on the second line and verifies the exact `note\nok` buffer after leaving
and reopening Suspects. Every key is controller-driven and held events do not
repeat. Both-eye captures show the two lines and aligned caret. Home retires the
keyboard, native Exit returns to stereo, Quit cancellation/resumption and
confirmed exit pass. SteamVR shuts down gracefully, with no supervisor errors,
unchanged private flat files/preferences and verified VR uninstall:
`build/vr/steamvr-native-20261011-mirror-sidney-suspects-multiline-v6-20261012/`.

The renderer remains the freshly qualified Enter build above; the notes and
caret changes are game-side. Native text tests cover multiline dispatch,
unreadable line state, stale/hidden/changed ownership and handler tampering.
Text/caret tests pass 148 cases in 1.11 seconds. Combined text/caret/public VR
tests pass 355 cases with three skips in 14.79 seconds. Complete compilation
and composition checks pass all three supported binary profiles. Changed-file
lint, formatting and strict typing pass. Early notes attempts selecting the
wrong page or no suspect are diagnostic setup failures, not rendering failures.
The verified keyboard gap and caret defect are separately identified and fixed.
Further puzzle routes, sustained performance and physical-headset acceptance
remain incomplete. The ordinary installed game has not been changed.

### Native anagram discovery and a faster workbench, 12 October 2026

The next sample covers Arcadia text recognition and the anagram parser's
discovery/open/exit lifecycle, not its complete solution. A private copy of the
archived real-story save immediately after adding `SUM` supplies the actual
chapter, inventory and progress state. Its SHA-256 is
`503493f97e2bee2b613ff6c36e09aaab0f3c7c12225497b06f29e39955940060`.
The file stays under ignored `build/vr/`; the archived original is read-only.
No prerequisite or solved-puzzle flags are overwritten in the passing run.

Controller rays select the live Arcadia file label, start its native text
analysis, dismiss recognition, select Anagram Parser and wait for the original
discovery/action lock to finish. Both compositor eyes show the phrase, available
words, phrase-building slots, instructions and footer controls without an
irrelevant keyboard. Controller Exit returns to analysis and Home, native Exit
returns to stereo, and Quit cancellation/resumption and confirmed exit pass.
The 78.22-second run has no supervisor errors, unchanged private flat
files/preferences, verified VR uninstall and graceful runtime shutdown:
`build/vr/steamvr-native-20261011-mirror-sidney-anagram-story-v13-20261012/`.
Word selection, scrolling, Erase and a completed result remain open. This run
does not establish the route for acquiring all prerequisite story progress.

Earlier diagnostic setups are retained as failures. The analysis file browser
differs from the translation browser, with indented labels and additional files.
Recognition is required before the text commands are usable. Page-change checks
also cannot substitute for the native anagram discovery lock. Invented chapter
prerequisites did not reproduce the real saved story state; using the archived
pre-puzzle state succeeds. The precise missing prerequisite in those invented
states is not proven, so no renderer/input fix is claimed from that difference.

Two attempts instead fail because the standalone screenshot observer hangs in
OpenVR shutdown after its image work. Client logs reach `VR_Shutdown` and the
experiment's cleanup still completes; these are retained as observer failures,
not silently counted as passing runs. The private observer now maintains one
OpenVR connection and owned capture process per experiment, with bounded request
replies and explicit exit reporting. It closes after the game exits. Three
intermediate runs and the passing anagram run report observer exit zero without
forced termination. This avoids repeated per-image initialization/shutdown and
reduces observer overhead; it is not a production renderer or runtime-shutdown
fix. A generated native save also allows quick fixture retries without repeating
scanner/translation setup, but the passing run uses the real story save instead.
No screenshot helper, diagnostic fixture or game binary is shipped.

### Native anagram solution, 12 October 2026

The expanded controller-only interaction sample passes in 105.59 seconds,
including the game's original discovery and solution narration. It selects
`Academia (University)` and erases it, scrolls the native word list, then selects
`Arcam (Tomb)`, `Dei (God)` and `Tango (I Touch)`. The game supplies the remaining
word and both inspected compositor eyes show `Arcam Dei Tango, Iesu`,
`Complete rebus confirmed` and `I touch the tomb of God, Jesus`.
This supersedes the earlier open word-selection/scrolling/Erase/solution checks.

The diagnostic selector follows the current native list viewport and arrow
bounds. Earlier attempts incorrectly chose the scroll direction for a partially
clipped word and oscillated between two rows. Comparing the word's bottom edge
with the viewport bottom fixes that test logic; no production scrollbar or
controller-input change was necessary. Offscreen labels may be inspected to
find the direction, but selection requires current visible bounds and native
visibility. Puzzle buffers, prerequisites and solved flags are not written by
the interaction helper.

Controller Exit/Home and native SIDNEY Exit return to interactive stereo. Quit
cancellation/resumption and confirmed exit pass. There are no supervisor errors,
private flat files and display preferences are unchanged, VR uninstall passes,
the persistent capture observer exits zero without forced termination, and
SteamVR shuts down gracefully. Evidence:
`build/vr/steamvr-native-20261011-mirror-sidney-anagram-solve-v18-20261012/`.
The session uses runtime-recommended 1568×1568 application eye targets with a
separate 1280×800 desktop mirror. Its 1920×1920 compositor captures are not the
application's eye resolution. Full-story prerequisite acquisition, other puzzle
routes, sustained pacing and physical-headset acceptance remain open.

### Native SIDNEY map controls, 12 October 2026

The next controller-only sample opens the map file through the native analysis
browser, opens/closes its Map menu and pans the magnified view by holding the
trigger while moving the ray across the overview. Releasing the trigger before
moving again leaves the inspected magnified-pane pixels unchanged. The real
SteamVR run passes in 48.31 seconds, including normal controller Quit and
graceful runtime shutdown:
`build/vr/steamvr-native-20261011-mirror-sidney-map-drag-v3-20261012/`.

Point entry initially fails with an earlier story save. Read-only native-code
inspection identifies the magnified pane's required point-entry mode, and
observations show that the earlier state never enters that mode. Scripted host
mouse selection in the same private session does not enter it either. A later
archived real-story save succeeds through controller-only selection: native
mode changes from one to four, placing a point adds 30 bright-green overview
pixels, and Clear Points restores the zero-marker baseline and mode zero.
Both eyes show the new point and native latitude/longitude feedback, then its
removal, with the locked circle, square, grid, lines and points preserved.
No puzzle mode, geometry, prerequisites or progress flags are written by the
interaction helper. The precise prerequisite difference is not established,
so no production input or renderer fix is claimed from the failed early-state
attempts. Points belong in the magnified pane, not the overview.

The expanded point-entry sample passes in 49.86 seconds. Native Exit returns
to stereo; controller Quit cancellation/resumption and confirmed exit pass.
There are no supervisor errors, no host-pointer movement, unchanged private
flat files/display preferences, successful VR uninstall, capture-observer exit
zero without forced termination and graceful SteamVR shutdown. Evidence:
`build/vr/steamvr-native-20261011-mirror-sidney-map-later-points-v10-20261012/`.
The private later-story fixture's SHA-256 is
`1e75ed2836b2fe51a6bd3a7f4904f2aab8dd6fb43519d1dc50ac0c48fa70d015`.
Archived originals are read-only and test copies stay under ignored `build/vr/`.
Input/text behavior regressions pass 328 tests in 2.67 seconds. This qualifies
sampled pan and point controls, not shape manipulation, the full map-puzzle
sequence, sustained pacing or physical-headset readability/comfort. The ordinary
installed game remains untouched.

## Libra return qualification correction, 12 October 2026

The previously reported return failure is no longer reproduced by the corrected
native-action qualification. Two workbench assumptions needed correction:
the computer menu's second cell is Look, not Type, and the room camera can
resume before the original completion narration/action ends. `VERBS.TXT` maps
Type and desk Use to `I_OPERATE`; the visible tool-icon cell is the third cell
in this sampled menu. The test now uses that actual controller action, including
the original approach/animation, rather than invoking the start script directly.
The console stages only the saved scene and its authored camera.

A three-second Inventory assertion immediately after a resumed room was too
early. The replacement has a fixed 35-second bound, records native layer,
cursor and scene, and retries the real controller shortcut. It does not clear
locks, alter puzzle/model values, call end scripts or reset timeblocks. Only
actual Inventory ownership passes, followed by real Back and resumed stereo.

The complete sampled sequence passes in **99.12 seconds**:
native computer entry → SIDNEY → Virgo → editable hexagram manipulation →
Libra recognition → original narration/chapter transition → Inventory → Back →
Quit/No/resumed stereo → Quit/Yes. The native sequence moves from `r25/307a`
to `hal/310a`; controls become available around 30 seconds after the early
room-camera return. The score is 565. Both eyes were visually inspected for
the returned inventory panel and hotel-hall stereo. No renderer/player change
was needed. This resolves the sampled test failure, not every possible story
transition or physical-headset acceptance gate.

Evidence:
`build/vr/steamvr-native-20261011-mirror-sidney-native-type-recovery-v13-20261012/`.
The inner game run exits zero, stderr and supervisor errors are empty, native
Quit exits zero, capture observers stop normally, private flat files/preferences
remain unchanged, uninstall succeeds and SteamVR shuts down gracefully without
forced components. Failed earlier camera/menu controls and dormant-baseline
attempts remain diagnostic evidence only, not qualified gameplay runs.
Focused regression checks also pass **566 tests with three skips in 17.66
seconds**. The complete zodiac acquisition path, headset comfort/readability and
sustained physical-display frame pacing remain open.

An independent fresh repeat also passes in **97.37 seconds**:
`build/vr/steamvr-native-20261011-mirror-sidney-native-type-repeat-v14-20261012/`.
Its explicit result records native computer entry through cell 2, settled
SIDNEY home, `hal/310a` after completion and actual Inventory recovery after
29.73 seconds. Native Quit and the inner run both exit zero, stderr and
supervisor errors are empty, observers stop normally, files/preferences remain
unchanged, uninstall succeeds and SteamVR shuts down gracefully. This repeat
uses the same qualified renderer/player and needs no center-draw workaround.

## Explicit 120 Hz pacing and rectangular eye targets, 12 October 2026

The earlier isolated SteamVR workbench modelled a 90 Hz headset, even while
the desktop and game submitted near 120/s. It now accepts a bounded private
refresh-rate setting. An additional lab-only manual supersampling setting
prevents SteamVR's automatic GPU calibration from changing a controlled target.
Neither setting changes global SteamVR configuration or the public player:
the player always consumes the actual runtime's recommended per-eye dimensions.

Two actual-runtime room/exterior runs use 20-second intervals with no captures
during timing. Both complete controller Quit/No/resume and Quit/Yes, exit zero,
preserve flat files/preferences, uninstall, stop capture observers normally and
shut SteamVR down gracefully without forced components. Both exterior eyes
were visually inspected. These are short virtual-headset samples, not sustained
physical-display acceptance.

| Recommended eye target | Room submissions/s | Exterior submissions/s | Exterior GPU p99 |
| --- | ---: | ---: | ---: |
| 4316×4316 | 119.95 | 118.40 | 9.18 ms |
| 2016×2240 | 119.85 | 119.35 | 8.43 ms |

The rectangular run explicitly fixes virtual-runtime supersampling at 100%.
Its OpenXR timing layer observes an approximately **8.333 ms predicted display
period**, confirming 120 Hz rather than inferring it from submission counts.
Its inter-submission p99 is 11.06 ms in the room and 11.23 ms outside. At the
larger target, 5.75% of sampled exterior GPU intervals exceed 8.333 ms. Thus
mean rates alone must not turn the performance gate green. Counting tiny
inter-submission deviations around 8.333 ms is not a missed-display-frame
measure. Null-driver presents/drops and CPU submission counts are not physical
delivered FPS; actual display pacing remains unverified.

Evidence is retained in
`build/vr/steamvr-native-20261011-mirror-headset-120hz-high-eye-pacing-v1-20261012/`
and `...-headset-120hz-rectangular-eye-pacing-v2-20261012/`. The latter includes
the frame-level OpenXR trace; both include process-matched compositor timings.
These use the unchanged qualified renderer/player, not a new renderer build.

New native runtime regressions require projection swapchains and submitted
rectangles to match each eye's recommendation, including unequal rectangular
eyes and recommendations below the runtime maximum. Zero/overflow dimensions
must fail without leaked resources. All **six native test groups pass in
1.91 seconds**, freshly compiled against the current source in
`build/vr/runtime-resolution-tests-20261012/`. This is test coverage, not a
claim that a particular physical headset has been qualified.

Additional native SIDNEY inspection confirms the sampled ID page and file list
are selection/read-only routes, not unimplemented filename/ID text editors.
The Make ID/Home sample and file-list exploration quit normally, but a later
`202p` ID-printing setup did not reach settled SIDNEY. That fixture/approach
path remains under investigation and is not qualified printing acceptance.
An additional native-entry camera sample also missed the computer; its bounded
failure is retained rather than treated as a passed interaction. No game state
or renderer workaround has been added for either diagnostic.

The new native-test source intentionally invalidates the earlier renderer's
reviewed-source receipt. A complete fresh recipe build, including native and
GPU checks, passes in `build/vr/recommended-eyes-qualified-20261012/`.
The candidate SHA-256 is
`e836b9c46cb0a5d02508206407b2a4508051ddcada77f0599d2bbfa53e62db50`.
It changes test coverage, not runtime drawing policy. It is not installed into
the ordinary game or published.

Actual SteamVR qualification of that fresh artifact passes in **48.48 seconds**:
`build/vr/steamvr-native-20261011-mirror-sidney-id-selectors-qualified-v6-20261012/`.
Controller selections change the ID preview between Grace and Gabriel, open
and close the category menu, return Home, open/close the file list and return
to interactive room stereo. Read-only controls keep text ownership absent.
Both Grace-preview compositor eyes were inspected. Native Quit/No/resume and
Quit/Yes exit zero, with empty stderr/supervisor errors, normal observer stop,
unchanged flat files/preferences, uninstall and graceful SteamVR shutdown.
The player hash remains
`483d7b585f851a0920c6f3127769f9e6b3a87300381f3abc468f1f4378c8abc5`.
This is selector/browser qualification, not completed ID printing or the full
story-acquisition path.

An early negative-provenance test exposed a workbench cleanup race: the initial
monitor process/window inventory can be empty while SteamVR is still starting.
The workbench now re-discovers verified owned monitor windows during bounded
shutdown and requires a stable empty process interval. It does not kill a live
server before asking its monitor to close. Repeating the intentionally stale
recipe preflight rejects the renderer before a game child launches, then shuts
the owned runtime down gracefully without forced components and leaves global
configuration unchanged. Evidence:
`build/vr/steamvr-native-20261011-mirror-early-stale-recipe-cleanup-v1-20261012/`.
The inner exit code one is the expected provenance rejection, not gameplay
success. This fixes the sampled private-workbench race, not every physical
SteamVR failure path.

### SIDNEY shape motion and client-only captures, 12 October 2026

Controller selection adds a square but the earlier motion path leaves it in
place and displays the rotate cursor while the ray is inside it. A bounded
read-only callback trace in the owned private player shows the native shape
picker receiving screen coordinates against authored map bounds. Its first
button traversal has the correct inverse, but the trailing mouse-motion
dispatcher omits SIDNEY from its owner classification. That omission also
affects the shared flat interface path; it is not an OpenXR eye-resolution
problem or a reason to rebuild the renderer DLL.

The second traversal now recognizes the current SIDNEY root alongside the
current TimeBlock owner before its desktop-size shortcut. A retained laptop
beneath another layer cannot claim input, and null roots do not become matches.
The same existing inverse maps the point once and restores it on return. Delta,
flags, callback, object offset and nonvolatile registers remain intact. The
emitted adapter stays within its reserved slot, and the presentation layout is
version 103. Twenty-four executed regressions cover current, retained, absent
and null owners, hover/held flags and three diagnostic source sizes. These are
shared flat-interface regression cases, not legacy-resolution requirements for
VR. All three executable profiles compile.

Windowed Windows Graphics Capture also included the title bar and borders
before normalization, making screenshot-derived input targets inaccurate.
Capture now removes the independently measured client rectangle before
normalization. Pixel tests preserve both client corners exactly with and
without chrome, including a negative desktop origin; stale dimensions and
unavailable bounds fail explicitly. Actual native captures show the client-only
image. Compositor eye capture and headset rendering are unaffected.

After the coordinate correction, a drag update must follow the native
drag-start event before a shape moves. The corrected controller gesture moves
the square from `(711, 340, 816, 445)` to `(736, 358, 841, 463)` in the normalized
mirror, preserving its dimensions. Both inspected eyes show the relocated
green square and its magnified counterpart over the unchanged locked circle.
Right-click deselects it and also opens the game's toolbar; Back closes that
toolbar before Home. The complete uninstrumented run passes in 49.52 seconds:
`build/vr/steamvr-native-20261011-mirror-sidney-map-square-close-v25-20261012/`.
Native Quit cancellation/resumption and confirmed exit pass, with no supervisor
errors, unchanged private flat files/display preferences, no host-pointer
movement, successful uninstall, capture-observer exit zero without forced
termination and graceful SteamVR shutdown. The private pre-square story
fixture's SHA-256 is
`a29202d45b425a726884123fdc7d0d52b9feffd6441a0dc940998c11bab579fd`.

The earlier menu-switch failure is separately explained by native capture: a
click on another header first dismisses the still-active dropdown. An explicit
click-away step resolves that test setup issue without changing the pointer
transform. Right-click's visible toolbar is still clipped over SIDNEY in the
captured sample, so that rendering defect remains an explicit checklist item.
Its closure and square movement are qualified; complete toolbar presentation,
rotation/resizing, full puzzle sequences and physical-headset acceptance are
not. No native button-cache modification was needed. Focused checks pass 249
tests in 0.89 seconds; broader VR/compiler/capture checks pass 321 tests with
three skips in 13.09 seconds. Changed-file lint, formatting and strict typing
pass. The ordinary installed game remains untouched.

## SIDNEY toolbar capture ownership, 12 October 2026

The isolated toolbar sample reproduced a cropped panel and black backing
rectangle in the desktop mirror and both actual SteamVR eyes. This is not a
headset eye-resolution defect. SIDNEY retains the session's world-enabled
flag while its authored laptop canvas is current. The VR room-menu wrapper
therefore captured the nested toolbar into an independent surface, then copied
only a room-affine crop back. SIDNEY's fitted child drawing lies outside that
crop, so the successful copy discarded part of the toolbar.

Isolated menu drawing and frame publication now share one ownership predicate:
XR menus and world rendering must be enabled, and the current readable native
layer must be a room. SIDNEY, other modals, absent/unreadable roots and disabled
sessions retain the ordinary destination. Their complete fixed-interface panel
captures the native composition, without a room crop or a second widget
traversal. Publication also withdraws isolated cache ownership on leaving the
room, even if the previous menu does not Draw again. Native thiscall arguments,
registers, flags, return value and stack cleanup are preserved. No renderer DLL
rebuild, texture change or eye-size override is needed.

The final private controller run opens, hovers and closes the toolbar at the
center, the exact earlier failing source position `(737, 733)` and near the
right edge. The complete score/day/time row and all buttons are visible, with
no clipped backing. Both inspected compositor eyes show the complete panel.
The isolated toolbar enable/ready words remain zero throughout these SIDNEY
samples. The same run places, selects, moves and deselects the native square:
its source bounds move from `(711, 340, 816, 445)` to `(736, 358, 841, 463)`
without changing size. Home, SIDNEY Exit, room recovery, Quit cancellation and
confirmed Quit all pass.

Evidence is retained in
`build/vr/steamvr-native-20261011-mirror-sidney-toolbar-owner-publication-v4-20261012/`.
The run passes in 52.49 seconds with empty stderr and no supervisor errors.
Private flat files and display preferences are unchanged, uninstall succeeds,
the capture observer exits normally and SteamVR shuts down gracefully without
forced components. The private player SHA-256 is
`8f014997d46ae10febab8e73b207f8f7d2074039e560906504694cb7758bc7de`.
The existing qualified renderer remains
`a242102b45d0a8cbabc781b9f4d330cf10d9e51920a7397227039cace6b333c4`.

The workbench uses runtime-recommended 1568×1568 eye targets and an independent
1280×800 mirror. These observations do not introduce a legacy-resolution VR
requirement. Focused menu, SIDNEY, capture and VR service regressions pass
550 tests with three skips in 17.56 seconds. Changed-file lint, formatting and
strict typing pass. Expanded toolbar operations, remaining shape/puzzle modes,
headset readability, comfort and sustained physical-headset frame pacing remain
open acceptance gates. The ordinary installed game remains untouched.

## SIDNEY square resize/rotation and coherent drag deltas, 12 October 2026

The remaining square-control sample now exercises native resizing and rotation,
not just placement and movement. Selection alone does not deliver another hover
event at an unchanged pointer. The initial test's `C_POINT` observation was a
test-target issue, resolved by aiming at the edge derived from the live shape
model. Native ready cursors then identify Resize and Turn correctly. The
unmodified native engine increases the square from 400×400 to 499×499 without
moving its `(696, 668)` center, and rotates it to 13 degrees without changing
that center or size. Released ray motion leaves all geometry unchanged.

Inspection exposed a real remaining transport defect despite those visible
operations working: the second motion adapter converted the current POINT but
left its delta physical. Native `SmallMap::Drag` reconstructs the previous
point as `current - delta` when rotating/resizing. A mixed-domain pair therefore
uses an incorrect previous position. This supersedes the earlier assumption
that keeping the physical delta argument was sufficient. The original durable
delta must stay physical, but the synchronous native callback's delta must
match its adapted point.

The adapter now snapshots the physical current endpoint in its own stack
frame. Only current SIDNEY receives a stack-local delta equal to
`inverse(current) - inverse(current - physical_delta)`. The inverse uses the
same live height and centered integer pillar as the POINT adapter, including
signed truncation. It does not independently round a scaled delta, write
MouseManager's original objects or change other interface owners. Zero and
nullable point/delta arguments preserve their native meaning. Callback, flags,
object offset, result, nonvolatile registers and callee stack cleanup remain
intact. The presentation layout is version 104. The enlarged thunk occupies
the bounded unused tail after software-alpha composition, without increasing
the segment or displacing its portrait helper.

Actual native drag observations confirm the change. For the same controller
gesture, the callback at logical `(652, 393)` now receives `(17, 13)` instead of
the old physical `(18, 14)`. The rotation callback at `(729, 417)` receives
`(-10, 17)` rather than `(-10, 18)`. Resizing's sampled endpoint rounding happens
to leave its delta unchanged. These observations are retained in
`build/vr/steamvr-native-20261011-mirror-sidney-shape-logical-delta-v4-20261012/`.
The trace restores its exact native hook before teardown. No model geometry,
puzzle mode or story flags are written by the test.

The final uninstrumented run is
`build/vr/steamvr-native-20261011-mirror-sidney-shape-modes-qualified-v5-20261012/`.
It passes in 50.81 seconds with empty stderr and no supervisor errors. Both
actual compositor eyes show the rotated overview shape and matching magnified
outline. Move, resize, rotate, release, native right-click deselection, Home,
SIDNEY Exit, room recovery, Quit cancellation and confirmed exit pass. Private
flat files and display preferences remain unchanged, uninstall succeeds, the
capture observer exits normally and SteamVR shuts down gracefully without
forced components. The private player SHA-256 is
`483d7b585f851a0920c6f3127769f9e6b3a87300381f3abc468f1f4378c8abc5`.
The existing qualified renderer DLL is unchanged.

Executed pointer transport covers 192 combinations of current/retained/absent/
null owners, hover/held flags, signed/fractional-scale endpoints, zero/positive/
negative/null deltas and null points. The original event storage remains
unchanged. Complete generated VR profiles still compile and verify. This is
shared interface regression coverage, not a legacy-resolution requirement for
VR. Focused menu, SIDNEY, capture and VR service checks pass 841 tests with
three skips in 18.02 seconds. Changed-file lint, formatting and strict typing
pass. Other shape types, full puzzle solutions, physical-controller feel,
headset readability/comfort and sustained headset frame-time acceptance remain
open. The ordinary installed game remains untouched.

## Native Aquarius completion and circle controls, 12 October 2026

Circle editing now has an actual SteamVR controller qualification, including
the prerequisite map-analysis step. A circle cannot simply be added in every
story save: the original engine rejects it before Aquarius or after Pisces.
The previously used square fixture has already completed Pisces. The earlier
real save is before Aquarius and lacks Church Pamphlet/LSR inventory items,
which the original 205P point-entry handler requires.

The private test loads the unchanged real pre-circle save and uses native
`SetInvItemStatus` console calls to stage those two inventory prerequisites.
It does not write puzzle flags, geometry, modes or solved-state memory. This
is a controlled puzzle-interface fixture, not qualification of acquiring the
items through the full story. All subsequent map actions use actual SteamVR
virtual-controller rays and ordinary game callbacks.

The test enters points, pans the overview, and confirms the native magnified
viewport origin before placing each point at its visible center. Native map
coordinates are top-left based. The G-Engine reference is bottom-left based,
so its Y coordinates must not be reused unchanged. The original executable's
checker independently confirms RLC `(267, 415)` and CDB `(652, 307)`. The
observed viewport centers are `(264, 416)` and `(652, 304)`, within native
acceptance. A proper held update must follow drag-start; the earlier short
gesture stopped before that update and left the viewport at its start point.
These were test-setup issues, not new renderer defects.

Start Analysis now produces the original confirmation that the line between
the two points intersects the meridian and Arques. Both points become locked,
the sunrise line appears, and the native score increases from 442 to 447.
The test waits for the original narration lock to end before pressing OK,
then verifies the dialog has actually disappeared. It adds the now-eligible
circle and dismisses the separate native “select points” instruction before
trying to manipulate it. A rendered circle is not evidence that its modal
instruction has released input.

Read-only native model observations show the circle starting at `(600, 600)`
with radius 200, moving to `(692, 668)` with unchanged radius, and resizing to
radius 311 with unchanged center. Released ray movement leaves geometry
unchanged. Native right-click deselects it, Back closes the accompanying
toolbar, and both inspected compositor eyes show the resized overview circle
and its matching magnified arc over the unchanged confirmed line/points.
Home, SIDNEY Exit, room recovery and native Quit cancellation/confirmation
then pass.

Evidence is retained in
`build/vr/steamvr-native-20261011-mirror-sidney-aquarius-circle-instruction-v9-20261012/`.
The run passes in 58.86 seconds with empty stderr and no supervisor errors.
Private flat files/display preferences remain unchanged, uninstall succeeds,
the capture observer exits normally and SteamVR shuts down gracefully without
forced components. The private player and qualified renderer are unchanged
from the preceding square/delta milestone. Runtime-recommended eye targets
remain independent of the 1280×800 mirror.

Later hexagram controls, the rest of the zodiac sequence, full-story inventory
acquisition and physical-headset controls/readability/comfort/frame-time
acceptance remain open. The triangle shown in the early shape list is not
evidence of an available manipulation route: its original game logic explicitly
rejects that choice. No new production workaround, renderer rebuild or texture
change was needed for this milestone. The ordinary installed game remains
untouched.

## Broader high-resolution scene pacing, 12 October 2026

The real-SteamVR workbench now covers Castle Serres (`CS2/212p`), the cave
entrance (`BEC/312p`) and Temple 4 (`TE4/309p`) using the visual catalog's
authored cameras. Original chapter introductions are skipped only during
fixture staging. The measurement starts after native visible-room/script
readiness and camera setup, not at the first transient room-layer publication.
No puzzle state, game geometry or shader policy is changed to obtain a result.

The unchanged qualified renderer and layout-104 player render the independent
1280×800 windowed mirror and the **4316×4316** application eye targets actually
recommended by OpenXR in this run. The virtual-driver input size was 3524²,
but that is not the final recommendation, so it must not be reported as the
application's eye size. Compositor evidence is separately 5284². None of these
test sizes is a fixed requirement for physical headsets.

Each scene has a separate 20-second counter-only interval. No desktop or
compositor screenshots occur inside it. A process-matched compositor observer
and the OpenXR timing layer retain raw measurements. Steady-state statistics
discard one second at each interval edge and the compositor's first historical
retrieval batch, without removing subsequent outliers.

| Scene | Stereo submissions/s | Submission interval p99 | Total GPU p99 |
| --- | ---: | ---: | ---: |
| Castle Serres | 119.80 | 10.18 ms | 5.50 ms |
| Cave entrance | 119.95 | 9.81 ms | 3.20 ms |
| Temple 4 | 119.95 | 9.95 ms | 4.47 ms |

Maximum total GPU times are respectively 6.86, 5.30 and 5.69 ms. The virtual
runtime reports an approximately 11.11 ms predicted display period. Submission
intervals exceed that period for 0.37%, 0.05% and 0.05% of steady-state frames;
they exceed the stricter 120 Hz budget much more often. Mean throughput near
120 does **not** prove uniformly paced 120 Hz presentation. The null driver's
presents/drops counters rise together with asynchronous flags, as established
by the earlier independent baseline. They still cannot establish physical
headset-delivered frame rate or pass the release performance gate.

Both compositor eyes of all three scenes were inspected. The original full-size
evidence is retained alongside bounded inspection copies, rather than replacing
or shrinking the source captures. This is static stereo/scene inspection, not
temporal flicker qualification or headset comfort/readability acceptance.

Evidence:
`build/vr/steamvr-native-20261011-mirror-demanding-high-eye-pacing-v1-20261012/`.
`world.json`, `world-run.json`, `xr-call-timing.csv` and the three
`compositor-timing-*.csv` files identify the actual artifacts, scenes, cameras
and measurements. The complete run passes in 116.82 seconds with empty stderr,
no supervisor errors, native controller Quit cancellation/confirmation and
exit code zero. Private flat files and display preferences remain unchanged,
uninstall succeeds, the capture observer exits normally, and SteamVR shuts down
gracefully without forced components. Renderer/player hashes remain
`a242102b45d0a8cbabc781b9f4d330cf10d9e51920a7397227039cace6b333c4` and
`483d7b585f851a0920c6f3127769f9e6b3a87300381f3abc468f1f4378c8abc5`.

This broadens the earlier room/exterior performance sample. Moving actors,
effects, cold ordinary-world shaders, extended sessions, loading pauses and
physical-headset presentation still need qualification. No production renderer
change or rebuild was required. The ordinary installed game remains untouched.

## Native Virgo completion and hexagram controls, 12 October 2026

The later map fixture is now qualified in its actual `307a` chapter rather than
using a console timeblock change. Read-only observation of the original native
flag getter's verified name table and bitset layout shows `Leo=true`,
`Virgo=false`, `Libra=false` before analysis. The earlier `SetLocationTime` test
setup advanced these puzzle flags as part of native chapter initialization:
`Virgo` and `Libra` both became true, and the already-solved hexagram became
uneditable. That setup cannot qualify interactive hexagram controls. Likewise,
the earlier generic “connecting grid points” result was not Virgo completion.

The corrected fixture loads the unchanged real save and enters SIDNEY through
its original scene script. It does not change chapters, inventory, puzzle flags,
geometry or solved-state memory. Subsequent actions use actual SteamVR
virtual-controller rays and native callbacks. Four overview pans position the
magnified view before placing points. The original executable independently
checks the temple corners near `(745,174)`, `(970,266)`, `(381,1077)` and
`(606,1168)` with its native tolerance.

Start Analysis displays **“Points define 4-to-1 rectangle.”** The native score
increases from 555 to 560, `Virgo` and `PlacedWalls` become true, and `Libra`
remains false. The confirmation is dismissed only after narration releases
input. The test then chooses the now-eligible hexagram, dismisses its separate
instruction and selects its overview outline.

Read-only native model observations confirm:

- center `(600,600)`, radius field 100, angle 0 initially;
- center `(692,668)`, unchanged radius/angle after movement;
- unchanged center, radius field 112 after resizing;
- unchanged center/radius, angle 8 after rotation.

The hexagram's radius field uses overview units, unlike the circle's radius
field. The test uses the actual polygon edge for resizing rather than treating
these fields as interchangeable. Released ray motion preserves geometry after
each operation. Native right-click deselection and toolbar Back pass, followed
by Home, SIDNEY Exit, room recovery and native Quit cancellation/confirmation.
Both inspected compositor eyes show the rotated hexagram over the unchanged
locked map geometry. This qualifies those operations, not exact physical-hand
feel or the complete Libra solution.

Evidence:
`build/vr/steamvr-native-20261011-mirror-sidney-virgo-native-hexagram-v11-20261012/`.
The complete run passes in 56.56 seconds with empty stderr, no supervisor errors,
unchanged private flat files/display preferences, successful uninstall and exit
code zero. The capture observer exits normally and SteamVR shuts down gracefully
without forced components. The qualified renderer and layout-104 player hashes
are unchanged. OpenXR-recommended eye targets remain independent of the
1280×800 mirror.

The private workbench now rejects already-completed prerequisite fixtures and
checks the actual native completion flag after analysis. It also verifies
hexagram eligibility before attempting placement, rather than treating a
rendered shape or any analysis popup as evidence of puzzle progress.

This supersedes the earlier open **hexagram-control** qualification item, not
the full zodiac sequence. Libra completion, full-story acquisition, broader
native puzzles and physical-headset control/readability/comfort/frame-time
acceptance remain open. No production renderer change, rebuild or texture
change was required. The ordinary installed game remains untouched.

The updated native-state guards also pass an independent fresh run:
`build/vr/steamvr-native-20261011-mirror-sidney-virgo-hexagram-guarded-v12-20261012/`.
It repeats Virgo completion and all hexagram operations in 56.50 seconds, with
empty stderr, no supervisor errors, unchanged flat files/preferences, successful
uninstall, normal observer exit, native Quit zero and graceful SteamVR shutdown.
Both post-analysis and post-rotation observations retain `Libra=false`; this is
not an accidental pre-solved fixture. Focused SIDNEY transport, VR menu compiler,
VR service/launcher and Windows capture checks pass **566 tests with three skips
in 14.12 seconds**. This is a focused regression result, not a full-suite timing
or physical-headset acceptance claim.

## Native Libra recognition and unfinished return, 12 October 2026

Libra itself now completes through actual SteamVR controller input. Starting
from the real `307a` fixture, the test completes Virgo normally, selects the
newly eligible hexagram and performs the already-qualified movement, resize and
rotation gestures. Bounded, read-only model feedback then aligns the shape using
the same controller rays. No model coordinates, modes or puzzle flags are
assigned by the test.

The original executable's completion code at `6399D2..639A85` checks center
near `(676,672)`, radius within four units of 121 and angle modulo 60 within
four degrees of **27**, not the 33-degree value in the G-Engine reference. The
reference must not replace native behavior as an oracle. Observed controller
alignment reaches center `(676,672)`, radius 120 and the accepted angle region;
the native checker snaps the solved geometry, withdraws selection and locks the
hexagram. The screenshot shows the correct blue locked star and score 565,
after the earlier Virgo score 560. Read-only native observations confirm both
`Libra` and `LockedHexagram` are true.

This is **not yet a qualified complete return path**. The native completion
script forces SIDNEY closed. A room layer and stereo rendering return, with a
single user-camera controller and no camera input lock. The action cursor
persists, and Inventory does not open through the actual controller shortcut.
Waiting for a single transient cursor change was an invalid readiness check;
the workbench now observes stable native camera/ownership state and tests real
Inventory/Back, rather than accepting a room image as recovered gameplay.

Two controls narrow the cause without changing production behavior:

- Restoring the ordinary center-view draw after successful eye mirroring does
  not restore Inventory. This owned-child-only, reversible code diagnostic is
  not a shipping change or a qualified public-player run.
- Disabling VR input routing temporarily and sending ordinary foreground `I`
  also leaves the native room active without Inventory. The failure is not
  established as a controller-route defect. This diagnostic is explicitly not
  controller-only acceptance evidence.

Evidence is retained in
`build/vr/steamvr-native-20261011-mirror-sidney-native-libra-v1-20261012/`,
`...-sidney-native-libra-controller-recovery-v4-20261012/`,
`...-sidney-libra-native-center-control-v5-20261012/` and
`...-sidney-libra-native-inventory-control-v6-20261012/`.
The recovery observations record the live layer, cursor, scene, native camera
depth/type/lock, render ownership and advancing frame counters. The controller
route is armed and unblocked, while the ordinary-keyboard control also fails.
These experiments terminate at an explicit functional failure and therefore
do not prove native Quit or full story-transition acceptance. Their owned
processes/capture observers are cleaned up, private flat files/preferences stay
unchanged, uninstall succeeds and SteamVR shuts down gracefully without forced
components.

Next isolate the original script/fixture behavior with a VR-disabled native
control, including its actual action/animation state. Do not clear locks, force
another timeblock, run an end-script manually or weaken the recovery check to
make this path appear finished. Post-puzzle gameplay recovery, the complete
zodiac sequence and the release acceptance gates remain open. No production
renderer or player change has been made for these diagnostics. The ordinary
installed game remains untouched.

## Windowed VR presentation performance audit, 12 October 2026

VR continues to consume OpenXR's recommended per-eye dimensions, including
distortion/supersampling requirements. Neither legacy 1024×768 nor the
independent 1280×800 interface/mirror canvas caps the stereo eye targets.

Read-only native-thread sampling finds GPU-to-CPU waits during the native
windowed primary Blt. Verified call arguments cover the complete 1280×800
client rectangle at its desktop origin. Symbolic diagnostic relinks match
the qualified DLL's executable bytes; raw stack candidates are not treated
as fully unwound call chains. Reversible cursor-draw and cursor-bounds controls
show no meaningful performance gain. No cursor suppression is shipped.

The renderer now recognizes the current render target by its shared surface
identity across DirectDraw/Direct3D interface versions. Its existing GPU
presentation path runs before CPU downloads. Actual later Lock, preview and
save-under reads still synchronize, and CPU-authored overlays still upload.
Real-GPU regressions cover all five surface aliases, Blt/BltFast, repeated
GPU-only frames, partial CPU overlays, retained pixels and device recreation.
An extra presentation previously performed on VR frame completion is removed:
the subsequent native primary Blt owns windowed desktop presentation.

Three counter-only, 20-second exterior samples at 2016×2240 per eye and 120 Hz
separate the changes. Captures and thread sampling occur outside timing.

| Candidate | Stereo submissions/s | Median compositor GPU time | Submission p99 |
| --- | ---: | ---: | ---: |
| Previous qualified baseline | 118.50 | 6.67 ms | 12.56 ms |
| Cross-interface presentation plus duplicate VR mirror | 59.90 | 6.16 ms | 24.05 ms |
| Single native GPU presentation | 118.75 | 5.25 ms | 16.14 ms |

Moving the old branch alone does not resolve the missing cross-interface
match. Restoring that match exposes duplicate desktop presentation, which
must not be retained as a performance improvement. Removing the extra VR
present restores throughput and lowers median GPU time in this sample, but
does **not** establish improved tail latency or a passed 120 Hz budget.
Remaining CPU reads now appear in native page preparation. Mean submissions
and virtual-runtime drop counters are not physical delivered frame rates.

The current full native/GPU-qualified recipe is
`build/vr/single-present-qualified-v2-20261012/`, candidate SHA-256
`40c5459d004d3dcc16b3cd8ac0bd72a0b87872f774e0eaadefd6e678c65030f1`.
The player SHA-256 remains
`483d7b585f851a0920c6f3127769f9e6b3a87300381f3abc468f1f4378c8abc5`.
The six native groups and all real-GPU qualification checks pass. Focused
Python artifact/build/VR checks pass **277 tests, 3 skipped in 15.09 seconds**;
full lint passes. Nothing is installed into the ordinary game or published.

Actual SteamVR evidence is retained in
`build/vr/steamvr-native-20261011-mirror-headset-120hz-single-present-profile-v3-20261012/`.
Both exterior compositor eyes were inspected. Native Quit cancellation/resume
and confirmed Quit pass; private flat files/preferences are unchanged,
uninstall succeeds and runtime shutdown is graceful. The submitted eye
targets remain the runtime's recommendation, not the compositor capture size.

SIDNEY selectors/browser regression evidence is in
`build/vr/steamvr-native-20261011-mirror-single-present-sidney-selectors-v5-20261012/`.
Both inspected compositor eyes show the ID page correctly. Portrait selections,
category-menu closure, Home, file-list closure, room recovery and controller
Quit pass in **65.35 seconds**, with unchanged private files/preferences,
successful uninstall and graceful SteamVR shutdown without forced components.
This is not ID-printing or full story-acquisition acceptance.

The preceding SIDNEY attempt completes gameplay/Quit but stalls in SteamVR
shutdown, then its shell-based recovery times out. It is not a clean shutdown
qualification. The ignored workbench now persists terminal evidence even when
cleanup fails and uses a verified process handle for last-resort recovery,
avoiding shell startup delays/PID reuse. Forced recovery is recorded as
non-graceful, never as a passed runtime lifecycle. The successful repeat does
not explain every intermittent SteamVR stall or establish headset acceptance.

A second single-presentation run uses actual runtime-recommended **4316×4316
eyes at 120 Hz**, independently of the unchanged 1280×800 source/mirror. Separate
20-second room/exterior intervals submit 120.05/118.80 stereo frames per second.
Median compositor GPU times are 3.27/5.29 ms, with p99 4.92/8.46 ms. Exterior
submission p99 remains 16.20 ms and includes a retained 37.33 ms maximum, so
this repeat does not pass the sustained frame-time gate. Both exterior eyes
were inspected, and native Quit, observer shutdown, uninstall, unchanged flat
files/preferences and graceful runtime shutdown pass in 107.04 seconds.
Evidence:
`build/vr/steamvr-native-20261011-mirror-headset-120hz-single-present-high-eye-v7-20261012/`.
The virtual driver requested 3524²; the actual OpenXR recommendation after GPU
calibration is 4316² and is the size rendered by the game. The larger compositor
capture dimensions are not substituted for that recommendation. An earlier
4316² raw-driver request is rejected by the bounded workbench before launching
SteamVR; that setup rejection is not a renderer failure.

Next isolate the remaining page-preparation reads and CPU frame-time outliers,
preserving required native background/history consumers and modal recovery.
Do not bypass GPU synchronization, reduce the recommended eye resolution or
accept mean submission counts as proof of smooth headset delivery. The goal
and first-release gates remain active/open.

## Windowed ownership without failed fullscreen seeds, 12 October 2026

The remaining sampled readback is a failed fullscreen handoff seed, not a
necessary cursor or screenshot read. Live windowed state has no successful
native Flips, a two-page seed budget that stays pending, and `DDERR_INVALIDRECT`
(`0x88760096`) from the primary-to-back copy. The primary describes the desktop,
not the smaller game canvas. The failed copy is retried on every room draw.
A reversible owned-child control suppresses this preparation for 12 seconds,
then restores it before captures/Quit; that control is not shipped or taken
as page-history acceptance. Its first diagnostic attempt has a workbench
state-read length error; a second refuses to call a failed seed "settled".
Neither is a production renderer failure or a passing gameplay qualification.

The private VR scene compiler now checks the byte-anchored native fullscreen
mode. A windowed complete eye mirror publishes room ownership without reading
the desktop primary or seeding physical flip pages. Fullscreen mode, unknown
mode and ordinary fallback keep the original repair. No successful native Flip
is fabricated, and pending fullscreen repair is not falsely consumed. Executed
tests verify windowed rendering, switching back to real fullscreen repair,
register/stack preservation and hidden/failed/missing-bridge fallback in both
modes. All three executable profiles compile. An initially incorrect mode
anchor is rejected before installation and corrected against the normalized
executable's actual long branch, not by weakening the verifier.

Actual SteamVR exterior qualification at recommended **2016×2240 eyes and
120 Hz** passes in 66.16 seconds. The 20-second interval submits 119.85 stereo
frames/s, with compositor GPU median/p99 **5.09/8.03 ms**. Submission p99 is
10.66 ms, maximum 25.22 ms; the full performance gate still does not pass.
The matching read-only 240-sample profile contains no GPU-resource readback
waits, unlike the preceding profile. Required synchronization remains enabled.
The old seed-error field can remain historical from ordinary startup work;
it is not presented as a fresh failed copy in this qualified interval.
Evidence:
`build/vr/steamvr-native-20261011-mirror-windowed-page-ownership-profile-v5-20261012/`.
The renderer stays the reviewed `40c5459d...` single-presentation recipe.
Only player compilation changes, to SHA-256
`2be670cb84d23f444ecc66e13e7def0af1beefe3f185cd9271597129f31539bd`.

Save → different room → native restore → score retirement → controller Quit
passes in **46.55 seconds**, with populated native preview and both compositor
eyes inspected. The repeat without the readiness probe passes in **46.62
seconds**. Private flat files/preferences stay unchanged, owned saves are
removed, uninstall succeeds and SteamVR closes gracefully without forced
components. Evidence:
`build/vr/steamvr-native-20261011-mirror-windowed-page-save-readiness-v7-20261012/`
and `...-windowed-page-save-restore-uninstrumented-v8-20261012/`.
The earlier save attempt has an invalid native row-list observation before
typing. The readiness probe's first read is already valid, so no delayed
constructor or product fix is established. That intermittent observation is
retained as unresolved; strict row validation has not been weakened.

Focused executed/compiler checks pass **245 tests in 1.99 seconds**. Broader
VR/compiler/artifact checks pass **513 tests, 3 skipped in 16.54 seconds**;
full lint passes. No ordinary installed game, release or Git history is changed.
Representative modal/controller coverage and physical-headset acceptance still
need completion, alongside the remaining frame-time tails.

### Playable-loop priority and native ID printing, 12 October

The next-milestone order now favors required gameplay routes and the complete
player flow before more frame-time-tail refinement. Prototype setup, controls,
logs and limitations are summarized at the top of this document. The first
headset acceptance gates are unchanged, not relaxed to make the tracker green.

Actual SteamVR qualification with the current `2be670cb...` player and
`40c5459d...` renderer passes in **64.82 seconds**. Synthetic Index-controller
actions select Gabriel's portrait, select Reporter → N.Y. Times, press the real
Print Identification button, return through Home/Exit, cancel native Quit and
resume stereo, then confirm native Quit. The displayed score changes from
000 to 002 after printing. Both completed-print compositor eyes were inspected.
No inventory state, print callback or completion flag was forced in memory.
Console commands stage the chapter and character, so this is a required-action
sample, not a natural story playthrough or printed-ID use at the vineyard.

G-Engine's independently reconstructed
[ID-printing implementation](https://github.com/kromenak/gengine/blob/master/Source/GK3/UI/Sidney/SidneyMakeId.cpp)
also restricts printing to Day 2, 2pm and identifies the N.Y. Times card as a
valid choice. Its source is supporting context, not an oracle replacing the
original executable's observed behavior.

The native inventory query captures did not expose readable query results.
Consequently the record still explicitly withholds independent inventory-item
verification. Do not infer a successful before/after ownership query from the
empty console captures. Inventory presence/use and physical controls remain
acceptance work, despite the observed native score award and clean return.

Evidence:
`build/vr/steamvr-native-20261011-mirror-playable-sidney-id-inventory-v18-20261012/`.
The owned player exits zero, uninstall removes its files, private flat files and
mirror preferences remain unchanged, the capture observer exits normally and
SteamVR closes gracefully with no forced components. No owned game or runtime
process remains afterward. Focused CLI/launcher/process tests pass **44 tests
in 1.08 seconds**.

Earlier attempts are retained as negative evidence: the redundant startup
observer times out before gameplay, the first gameplay-only configuration
rejects its inconsistent focus flag, unverified console typing fails to stage
the scene, and an immediate restored-window capture receives a stale minimized
frame. Staging now proves the console is open before typing, and accepts only a
fresh correctly sized image. SetEgo restores Gabriel's authored location, so
the workbench restages the computer room afterward. Native callbacks may still
change the chapter's current room while SIDNEY is open; the original printing
restriction is the timeblock, not an invented requirement that the room name
remain R25 throughout.

The printing outcome is not a tab change, so the tab-content-change oracle was
inappropriate for that side effect. The passing run instead captures the native
action and score award, while preserving the independent inventory caveat.
A preceding selector run also misses the second Quit target after cancellation.
The later full pass does not establish the cause or erase that intermittent
observation. The gameplay-only option explicitly omits the redundant startup
observer and focus/minimize cycle; each gameplay screen still requires actual
compositor capture. Startup/focus qualification is not claimed for this run.

### Public commands and independently verified printed inventory, 12 October

The next actual SteamVR run passes in **55.82 seconds**, using the unchanged
current player and renderer. The workbench invokes the public Typer commands
for `vr build --output <verified-recipe>`, `vr install` with its default local
build, `vr verify`, `vr launch --hand right` and `vr uninstall`. Build reuses
the already qualified recipe; this is not another cold compiler qualification.
The normal command callbacks and services execute, rather than replacing CLI
actions with fake return values. Instrumentation observes the launcher-owned
child and delivers synthetic controller hardware through the isolated runtime.

Printing is now independently verified without console-output interpretation:
the original name table maps `FAKE_ID_NYT_REP` to noun 451 and inventory index
38. The verified native getter reads the progress manager's status at
`+0x19b0 + index*4`. Its actual ego-sensitive ownership comparison accepts
status 3 for Gabriel and status 4 for both characters. Read-only snapshots show
status **0 before → 3 after**, with the same progress manager and Gabriel ego
507. The debugger neither calls this getter in the game nor writes inventory.
The relevant original code/table anchors are checked against the compiled
player before interpreting memory; the earlier blank-console evidence remains
unqualified, not retroactively reclassified.

Controller Inventory opens the real native screen and its captured image
visibly includes the selected N.Y. Times press card. Back returns to stereo,
followed by normal Quit cancellation/resumption and final confirmation. The
game exits zero, the supervisor returns normally, uninstall removes all owned
files, the capture observer exits normally, private flat files and mirror
preferences stay unchanged, and SteamVR shuts down gracefully without forced
components. Evidence:
`build/vr/steamvr-native-20261011-mirror-public-cli-id-inventory-v19-20261012/`.

Broader VR/compiler/input/native-scene regressions pass **582 tests, 3 skipped
in 18.21 seconds**. The next story-use sample reaches the château and renders
its courtyard correctly. The first ray observation was unsynchronized with the
renderer publication; polling the completed target then correctly picks the
door through the original world-hit path. The subsequent menu-label selector
finds no readable cached captions, and deliberately does not activate an
unidentified choice. That failed run is retained, with clean recovery, rather
than claiming that the ID has already been used in the story. Investigation
now follows the live native menu choice identities. Story-use, repeatability,
remaining gameplay/comfort and physical-headset gates remain open.

### Printed-ID story completion and corrected content timing, 12 October

The original native ActionMenu buttons store their verb enum in the callback
payload at `+0x8c`. Read-only interpretation, guarded by verified constructor
and verb-name-table anchors, identifies `KNOCK` and `T_BUS_CARD` without guessing
button indices or relying on delayed tooltip captions. Actual SteamVR virtual
controller rays select the courtyard door, Knock and the reporter-card topic.
The original story awards **five points (002 → 007)** and advances into the
wine-tasting barn. Inventory, actors, callbacks and completion flags are not
written or forced by the observer.

The initial post-arrival checks incorrectly allowed only the introduction's
57.26 seconds of speech plus 15 seconds. Captures at 21 and 61 seconds show
different authored cameras and actor poses: the sequence is advancing. Native
desktop focus, XR focus and tracking also stay valid in the diagnostic sample.
Reading the original `CS8202P.SHP` instruction boundaries reveals separate
waits for sitting, turning, pouring wine and other animations. Their referenced
ANM/MOM/ACT content contributes a conservative **52.8-second animation bound**,
including some concurrent calls. The revised workbench counts speech plus
those animations and bounded transition slack, but moves on immediately when
the real native inventory becomes available. It does not bypass the story or
patch native locks to satisfy a deadline.

With the unchanged current player and renderer, the complete sample passes in
**203.53 seconds**, including the earlier courtyard story content, compositor
captures and cleanup. After barn arrival, native inventory becomes available
at about **87 seconds**. Both inspected compositor eyes show the N.Y. Times
card in the real inventory. Controller Back returns to stereo; native Quit
is canceled and reopened before confirmed exit. The public supervisor returns
zero, uninstall completes, flat files and mirror preferences remain unchanged
without corrective cleanup, the capture observer exits normally, and SteamVR
shuts down gracefully with no forced components or global configuration change.
Evidence: `build/vr/steamvr-native-20261011-mirror-id-story-complete-content-v32-20261012/`.

This test loads a native save genuinely produced after the earlier controller
printing sample, then uses console commands only for courtyard/camera staging.
It qualifies this required story route, not natural chapter acquisition, every
conversation, physical controllers or headset comfort. The earlier dormant
flat control did not reach equivalent story input and provides no basis for
a VR-versus-flat comparison. Its files/preferences were restored. The short
failed VR runs remain retained as failed workbench attempts, not evidence of a
fixed engine deadlock. First-release acceptance remains open.

### Native controller action skipping, 12 October

The original ActionSkipper (`0x67a34c`) appears under the room during native
scripted actions and disappears after completion. Its key-down callback is
`0x49dc78`, which compares against the player's configured `UIKeyType_SkipAction`
binding at the native key-definition object's `+0xf8`. A private actual-runtime
Look/keyboard-Escape diagnostic confirms native skipping and subsequent room
recovery, with no action state or callbacks forced by the observer.

The VR Back router now selects that configured native key only while a visible,
enabled ActionSkipper owns the current room. Open action menus/toolbars retain
priority. Other interfaces, movies and ordinary room pause/resume retain their
previous respective native routes. Missing or unassigned skip bindings do not
invent an Escape press, Pause or unmatched release. Skipping still executes the
original game's guard checks and callbacks. Held Back cannot become Pause after
the skipper retires; the player must release and press again.

The new player's SHA-256 is
`3bd3175f123d6cca5a7e1bad4e4dcd7aaae4bc770cac80265b430fa392dc18d3`.
Renderer `40c5459d004d3dcc16b3cd8ac0bd72a0b87872f774e0eaadefd6e678c65030f1`
is unchanged. **680 regression tests pass, 3 skip, in 18.80 seconds**, including
configured/unassigned/missing bindings, held rejection, menu priority, retirement
and altered native-anchor verification. Ruff lint/format and strict ty pass for
the changed production/test files. No ordinary-game files or Git history change.

Actual SteamVR virtual-controller Look → Back/Skip → Pause/Resume → translation
→ snap turn → Quit cancellation/confirmation passes in **38.18 seconds**, through
the public command flow. Both returned compositor eyes are inspected. Native
room ownership and stereo submissions persist after Skip; ActionSkipper is
withdrawn. Game/supervisor exit zero, private flat files and mirror preferences
remain unchanged, uninstall completes and SteamVR shuts down gracefully.
Evidence: `build/vr/steamvr-native-20261011-mirror-controller-action-skip-v36-20261012/`.

An initial attempt fails before skipping because the workbench leaves its world
aiming ray nearly parallel to the floating menu. The world-to-menu test now
physically re-aims the synthetic controller before solving its panel hit rather
than translating a parallel ray or accepting stale pose feedback. This is a
workbench correction, not a production renderer/picker fix.

The longer printed-ID story test reaches the barn, skips its introduction in
**0.14 seconds**, rejects held-Back pause replay and recovers real inventory and
stereo control in **5.69 seconds** including captures. It then reproduces the
earlier intermittent second-Quit ray miss at `(730, 478)`. The native screenshot
visibly contains Quit at that point, but the workbench observes no completed
panel hit. This **119.75-second attempt fails** the complete lifecycle gate;
successful story recovery is not relabeled as successful Quit. Owned processes,
private files/preferences and SteamVR clean up correctly. Evidence:
`build/vr/steamvr-native-20261011-mirror-controller-story-skip-v37-20261012/`.
Next diagnose panel source ownership, geometry publication and the observer's
pose/target snapshot. The image alone does not establish a production defect.
Physical-headset acceptance and the full first-release gates remain open.

### Scene-changing Skip and native menu investigation, 12 October

Further public-command actual-SteamVR samples skip both the native courtyard
arrival action and the barn introduction with separate controller Back presses.
Courtyard Skip takes about **0.22 seconds** and advances CSE to CS8; the barn
introduction skips in about **0.14 seconds**. Native ID ownership, score award,
inventory recovery and stereo continue. These samples still fail their later
Quit interaction and are not complete lifecycle passes.

The failure is reproducible on the first as well as second Quit attempt. In v40,
an independent reconstruction of the actual controller ray and physical panel
plane lands at the requested `(730, 478)` both before and after failure. The
native Quit button's rectangle contains the corresponding inverse-mapped point.
The submenu then becomes hidden and its interactive coverage contracts. This
sample does not demonstrate a controller-ray transform error.

A transparent, restored native-button observer in v43 verifies that both Down
and Up reach the preceding Options button. Moving toward Quit subsequently
delivers a native Move to Options, which still owns hover capture. The submenu
retires before a Quit Down is observed. Hover capture can be normal game behavior;
its presence alone is not proof of a defect. The native virtual slots are
`+0x44` Down, `+0x50` Move and `+0x54` Up. The earlier v42 observer incorrectly
called `+0x50` Up, so its second event must be interpreted as Move, not release.
All observed callbacks are forwarded without replacing native control behavior,
and all temporary vtable changes are restored before owned-process cleanup.

The v44 attempted desktop-mouse comparison does not open the toolbar and has no
button trace. It therefore provides no equivalent flat/native baseline and no
evidence that desktop input reproduces the Quit failure. Private files,
preferences and owned processes are restored, and SteamVR shuts down gracefully
throughout these failed attempts. No ordinary Steam-game files are changed.

Evidence: ignored `build/vr/quit-native-geometry-v40-20261012.json`,
`build/vr/quit-native-release-v43-20261012{,.buttons}.json`, and the corresponding
`steamvr-native-20261011-mirror-quit-*` run directories. The current release
priority is reliable gameplay/menu recovery through clean Quit, not further
per-frame visual tuning. Renderer and player hashes remain unchanged in these
diagnostic samples. Physical-headset acceptance remains open.

### Playable story loop, native interruptions and capture-free testing, 12 October

The read-only native trace narrows the Options withdrawal further. The original
action lifecycle near `0x407045` emits native notification 7 and identifies its
action as `NVC Action`. Toolbar notification handling at `0x4ebdb2` routes that
notification through `0x4ebf8b` to `0x4ed402`, which hides its Options panel.
In v48 and v49, the Quit button actually receives Down before that notification;
the subsequent VR release is correctly canceled outside the withdrawn control.
This is not evidence that the renderer misplaced the ray. The native action
guard is retained rather than forcing a successful Quit callback or a visible
submenu during an action.

The workbench now treats only an observed withdrawn submenu under the same live
room/toolbar as a recoverable native interruption. A still-visible control's
miss remains a failure. Normal controller Back dismisses the interrupted
toolbar; a fresh menu attempt can proceed. A separate Back/Skip is used only if
the original visible, enabled ActionSkipper is present. Attempts are bounded.
No game flags, action completion, native picking or callbacks are forced.

The complete public-command courtyard Knock → reporter ID → courtyard Skip →
barn introduction Skip → recovered inventory/stereo → Quit No → resumed stereo
→ Quit Yes flow passes in **67.27 seconds** in v52. Both returned compositor
eyes are inspected. The game and supervisor exit zero, uninstall completes,
private flat files and mirror preferences remain unchanged, the capture observer
exits normally and SteamVR shuts down gracefully without forced components.
No native menu retry is needed in this particular captured sample.

A capture-free repeat in v54 passes in **70.36 seconds**, including **one actual
native menu interruption** and its controller-only recovery. No ActionSkipper is
present at that interruption, so the workbench does not invent a second Back
that would pause the room. The fresh menu succeeds, Quit cancellation and exit
pass, and private files/preferences and graceful runtime shutdown pass. Native
ownership and stereo/panel counters remain checked even with diagnostic imagery
disabled. This repeat is behavior/lifecycle evidence, not visual qualification.
The same player and renderer hashes are used; no production change is made to
the native action guard.

The intervening captured v53 repeat **does not pass**. It reaches the first
ConfirmQuit capture, writes the left-eye image and stalls before the right-eye
capture finishes. Its outer deadline expires. SteamVR's compositor log reports
a swapchain-present watchdog timeout during shutdown. The observer, runtime or
graphics interaction remains to be isolated; the passing capture-free repeat
does not prove which component caused the stall. There is no new game exception
in the private crash file, which contains older 11 October entries.
Only the verified test-owned compositor/monitor are stopped in final recovery.
The VR transaction journal is recovered through the package API, the private
installation is removed and all pre-run flat-file hashes match. Its orphaned
temporary journal is archived with the failed run rather than discarded.
The ordinary Steam game and Git history are untouched.

The v46 sample creates a genuine native post-story save using the console after
controller gameplay completes. Its subsequent Quit passes, but the extra
console interaction is a setup difference, not a production fix. Reloading that
save in v47 qualifies the isolated menu/Quit flow in **33.36 seconds** and makes
future comparison setup cheaper. The v50 diagnostic waits on an invalid
readiness assumption: native camera policy byte `+0x1c4` need not become zero
after a story. It times out without proving a game deadlock. Do not interpret
that field as a general camera/action lock.

Evidence: ignored `build/vr/steamvr-native-20261011-mirror-` directories ending in
`quit-hide-observer-v46-20261012`, `post-story-quit-repeat-v47-20261012`,
`story-quit-hide-v48-20261012`, `story-menu-notify-v49-20261012`,
`story-native-idle-v50-20261012`, `story-native-menu-recovery-v52-20261012`,
`story-native-menu-recovery-v53-20261012` and `story-capture-free-v54-20261012`.
The failed v45 ASCII-input setup and v51 workbench naming error are not game
regressions. The current workbench files pass undefined-name/redefinition checks.
The longer action-skip/controller gameplay milestone now has passing samples,
while capture/runtime repeatability and the first-release acceptance gates
remain explicitly open. Next prioritize dependable full sessions and missing
required gameplay routes, then setup/controls, comfort and sustained performance,
before minor visual polishing or exhaustive variants.

### Physical keyboard input and completed-focus ownership, 13 October

The native keyboard dispatch slots are independently anchored at `0x67a04c`
(Down), `0x67a050` (Up) and `0x67a038` (Character). The opt-in input bridge now
routes physical keyboard typing/editing and native key actions only while the
last completed XR producer owns focus. Dormant flat behavior remains native.
Controller shortcuts still call the unchanged original handlers directly.
No host mouse motion is introduced.

Accepted strokes are tracked by scan code plus the extended-key flag, not by
translated character value. Ordinary autorepeat remains native. Focus loss
withdraws those permissions and releases held native Shift/Ctrl/Alt through the
original key-up methods, even when their physical releases go elsewhere.
Native key-up is always forwarded. A queued character can follow its key-up,
which is legitimate Win32 ordering, without being dropped. After focus recovery,
held repeats remain rejected until a fresh physical press.

Raw output flags can be observed as zero while the renderer constructs its next
frame. The keyboard gate therefore caches focus only after the producer returns;
window dispatch during that producer retains the previous completed focus.
Modifier retirement runs inside the existing protected, non-reentrant native
transaction. Regression tests exercise transient output, native releases, held
rearming, extended scans, altered slot ownership and unchanged dormant behavior.
**240 input tests pass**. The broader current VR/input/navigation/text/world
suite passes **703 tests, with 3 skips, in 19.17 seconds**. Changed files pass
Ruff lint/format and strict ty.

The current player SHA-256 is
`24c59de14693ae60882292aca5d8815453857e8dde165f0663b9476676688ef9`.
Renderer `40c5459d004d3dcc16b3cd8ac0bd72a0b87872f774e0eaadefd6e678c65030f1`
is unchanged; these native input changes do not require a renderer rebuild.

Actual SteamVR qualification v62 types `vampire` into the real SIDNEY Search
field with scripted Win32 keyboard events, then holds Shift/A across the
runtime's own modal keyboard. Its successful modal API call withdraws completed
XR input focus; native modifiers clear and additional typing does not alter the
game. After closing the runtime keyboard, an explicit native autorepeat message
is rejected while A is still held. Physical releases and a fresh Backspace edit
work, then the controller keyboard adds `s` and invokes the original search.
Home/Exit, returned stereo and controller Quit cancellation/confirmation pass.
Both compositor eyes after keyboard recovery are inspected.

The public-command flow passes in **48.92 seconds**. Game/supervisor exit zero,
private flat files and mirror preferences remain unchanged, uninstall completes,
the observer exits normally and SteamVR shuts down gracefully without forced
components or changes to global runtime configuration. This qualifies the
runtime-modal path with scripted inputs, not a worn headset or physical-device
bindings. The retained v62 result field `physical_keyboard_and_dashboard` is an
old workbench label: the actual focus source is SteamVR's modal keyboard, not
the dashboard. Subsequent workbench output names the source explicitly.

Earlier v58-v61 dashboard attempts are not passing focus qualification. The
initial v58 check mistakes a raw transient zero for dashboard ownership; later
authoritative OpenVR dashboard queries show that the isolated dashboard does
not open, despite accepted registration/launch requests. Their failures do not
prove that native keyboard cleanup is broken. All owned processes and private
files/preferences are recovered. The dashboard-specific acceptance gate stays
open; the successful modal-keyboard test does not silently replace it.

Separately, the diagnostic compositor reader now uses bounded, non-blocking
GPU readback and phase logging, following
[Microsoft's Map-flag contract](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/ne-d3d11-d3d11_map_flag).
It retains one mirror per eye until shutdown, consistent with
[Valve's mirror-lifetime guidance](https://github.com/ValveSoftware/openvr/issues/1888).
The v55 short post-story cycle passes in **40.83 seconds** and the v56 complete
captured story/Skip/Quit cycle in **91.92 seconds**, with clean observer/runtime
shutdown. These repeats improve the workbench evidence but do not establish
the cause or complete resolution of v53's watchdog/shutdown failure. The reader
is ignored development infrastructure, not part of the installed player.

Evidence: ignored `build/vr/steamvr-native-20261011-mirror-` run directories
ending in `post-story-bounded-capture-v55-20261012`,
`story-bounded-observer-v56-20261012`, `physical-keyboard-launch-v57-20261012`,
the failed `physical-keyboard-dashboard-v58-20261012` and v59-v61 variants, and
`physical-keyboard-modal-focus-v62-20261013`. The original Steam game, Git history
and release assets are untouched. Independent mouse/world input, broader
gameplay/comfort/performance and physical-headset acceptance remain unfinished.

The current `24c59d…` player also requalifies the full printed-ID courtyard/barn
story and controller Skip/inventory/Quit loop in **65.45 seconds** in the
capture-free v63 run. Normal canceled/reopened/confirmed Quit, zero game and
supervisor exit, unchanged private flat files/preferences, uninstall and
graceful SteamVR shutdown all pass. Native button vtables are not instrumented
in this qualification. This is end-to-end behavior evidence with the latest
keyboard guard, not new visual or physical-headset acceptance.
Evidence: `build/vr/steamvr-native-20261011-mirror-keyboard-guard-story-v63-20261013/`.

## Complete puzzle sessions and terminal runtime handling, 13 October 2026

The current `24c59d…` player passes the native computer-entry → Virgo analysis →
hexagram move/resize/rotate → Libra completion → original chapter transition →
Inventory/Back → Quit/No/Yes sequence in **95.87 seconds**. It advances to
`hal/310a` through the original scripts, without puzzle/model writes or forced
completion. This capture-free v65 run uses actual SteamVR virtual controllers
and the previous qualified `40c545…` renderer. Flat files/preferences remain
unchanged, uninstall succeeds and SteamVR shuts down gracefully. It is current
player gameplay evidence, not new visual or physical-headset acceptance. The
v64 setup mistakenly requested a circle without the requisite fixture and is
retained as a failed workbench attempt, with clean recovery.

The VR-only launcher previously checked initial rendering but had no explicit
terminal-session signal after successful startup. The renderer now distinguishes
runtime-requested exit and session/instance loss from temporarily stopped or
hidden sessions. Its private transport emits a specific diagnostic instead of
quietly returning "no frame" forever. Session-loss API results are rejected even
when OpenXR uses a positive loss-pending grace-period result. The supervisor
recognizes that diagnostic, stops only its owned child and gives relaunch advice.
It also checks the final log after child exit so a concurrent terminal error
cannot be mistaken for healthy Quit solely because the exit code is zero.

This follows the [OpenXR session-state contract](https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrSessionState.html).
It does not automatically reconstruct a lost graphics session or preserve
unsaved gameplay. Temporary stopping can still resume; ordinary focus/visibility
changes remain nonterminal.

A fresh complete public prototype build succeeds, including all six native test
groups, flat behavior checks and real-GPU OpenXR transport/gamma/alpha checks.
New native regressions cover terminal EXITING/LOSS_PENDING events, temporary
STOPPING → READY recovery and session/instance-loss frame-wait results. Focused
Python input/navigation/world/service checks pass **572 tests with three skips**
in **18.71 seconds**; that run precedes the added final-log-race test. The latest
launcher-only repeat passes **17 tests in 0.32 seconds**, plus changed-file lint,
formatting and strict typing. Skips are not passing qualification.

The fresh renderer SHA-256 is
`43b6e8def8e45310142bec23e755d7d67d68301db21f432c895e8d8d2970209e`.
The recipe is `build/vr/session-loss-qualified-20261013/`. Nothing is published
or installed into the ordinary Steam game.

Actual SteamVR user-requested shutdown after stereo now qualifies in v68:
the complete run takes **36.28 seconds**, including **7.08 seconds** for runtime
closure and supervisor verification. No runtime components are forcibly stopped.
The game exits zero, the supervisor returns, private flat files/preferences and
global runtime settings stay unchanged, and uninstall succeeds. SteamVR closes
the native game window before an XR terminal event is observed. This therefore
qualifies its normal shutdown route, **not** the renderer's hard session-loss
branch. Native and Python tests cover that branch separately; physical headset
disconnection/reconnection remains open. The earlier v67 workbench incorrectly
required an error for this valid clean exit, and v66 omitted its required flow
selector. Both failures are retained with clean cleanup, not claimed as passes.

Evidence is in `build/vr/steamvr-native-20261011-mirror-` directories ending in
`keyboard-guard-puzzle-v65-20261013` and `terminal-runtime-stop-v68-20261013`.
First-release priorities remain complete playable sessions, dependable controls
and setup, comfort-critical transitions, then sustained performance and physical
headset acceptance. No release gate is marked complete by these synthetic tests.

The newly qualified `43b6e8…` renderer then passes the complete château
printed-ID/Skip/inventory/stereo/Quit-cancel/reopen/confirm loop in **70.56 seconds**
in v69. The supervisor and native Quit exit zero, private flat files/preferences
remain unchanged, uninstall succeeds and SteamVR shuts down gracefully without
forced components. Player identity remains `24c59d…`. This capture-free test
requalifies ordinary gameplay after the lifecycle change, without claiming new
visual or physical-headset evidence.
Evidence: `build/vr/steamvr-native-20261011-mirror-session-loss-story-v69-20261013/`.
Full repository formatting, lint, strict typing and spelling checks pass in
`build/vr/session-loss-full-lint-20261013.log`.

## Cinematic conversations without stacked cameras, 13 October 2026

The native Jean conversation exposes a real gap in the previous comfort rule.
During the actual Talk → Rennes-le-Chateau topic → Cancel sequence, the original
game keeps a single `UserSceneController`, leaves its camera-input flag clear
and makes four authored camera poses. Read-only observation shows the original
conversation owner active throughout. The prior classifier therefore kept most
of that sequence immersive, with individual cuts handled only by the blink.

Native binary evidence identifies the current conversation through
`Engine → services +0x60 → scene owner +0x0c → conversation context +8 → active
conversation`. The getters are at `47BEC4`, `47BEC0` and `46C03E`. The original
cinematics setter at `44B993` stores its policy at camera-manager `+0x1c4`.
These exact original instructions are now profile anchors, checked before
compilation. The VR classifier reads the native graph without changing any
conversation, camera or script state. An active conversation with cinematic
cameras enabled selects the stationary panel, regardless of the sole controller
class. Ordinary voice-over captions alone do not select this route. Cinematics
disabled still permits stereo. The existing `+0x1c5` guard also covers the
original forced-camera-cuts setting, whose setter is `44C0F5`; it is not confused
with the adjacent cinematics preference.

The current player SHA-256 is
`b3c3590774ac720312d9f0820e51e92cb0b7d56a5fdd510566b963849d16b85c`.
The renderer remains the qualified `43b6e8…` build. No renderer rebuild or ordinary
Steam installation change is required for this camera-ownership correction.

Captured actual-SteamVR v79 passes in **63.02 seconds**, through controller
selection of Jean's actual Talk verb, topic `T_RENNES_L_C`, native Cancel,
Inventory/Back, recovered stereo and Quit/No/Yes. In the interior active-
conversation interval, **5,505 samples** all have panel-only ownership; the
world counter stays at 1,169 while XR advances by **2,906 frames**. All **3,721**
nonzero panel-geometry publications have one identical transform, despite four
native camera poses. Left and right compositor images were visually inspected.
The raw images are preserved; their separately generated inspection copies do
not replace source evidence. Eye captures are sequential, not a synchronized
stereo pair or temporal-flicker qualification.

The cinematics-disabled v80 control passes in **59.47 seconds**. The native
conversation stays stereo, has one authored camera pose and advances XR by
2,769 frames, then returns to inventory and normal Quit. Both runs exit zero,
preserve private flat files/preferences and global runtime settings, uninstall
and shut down SteamVR gracefully without forced components. Scripted tracking
and controllers do not establish physical-headset comfort.

The earlier v75 controller conversation passes with the former ownership rule
in 64.32 seconds; v77 and the read-only native-owner v78 capture-free controls
pass in 59.38 and 59.41 seconds. The v70/v71 staging/capture failures and
v72/v73 wrong ray nominees remain failed workbench evidence. A ray aimed above
the original `JEAN_INIT` placement still requires native actor picking and the
actual Talk verb, rather than an assigned hit or actor position. The v74 menu
aiming attempt paired an older reported direction with the newly published raw
pose; its panel transform is unchanged, but direction changes across the
recorded samples. The workbench now supports bounded physical re-aiming against
the displayed ray, without assigning pointer/hit state. The v76 early Inventory
attempt ran before native cancellation finished; bounded real-shortcut retries
qualify recovery instead of accepting cursor artwork as completion. No native
script completion or lock is forced to obtain a pass.

Emitted ownership and complete composition checks pass **320 tests in 8.29
seconds**, including supported profiles, altered anchors, native-state
preservation, missing conversation nodes, disabled cinematics and forced-camera
safety. Input/navigation/service checks pass another **310 tests in 5.26
seconds**. Full repository lint/type/format/spelling checks pass.

**Remaining blocker for this dialogue presentation:** the opaque native panel
currently contains its original baked captions. They are visibly smaller than
the existing enlarged independent VR subtitle plane. Preserve that subtitle
plane during cinematic presentation, without duplicate text, before declaring
the conversation experience complete. This readability gap is explicitly open
in the checklist. Other scripted controllers, full story coverage, sustained
performance and physical-headset acceptance also remain unfinished.

Evidence is in `build/vr/steamvr-native-20261011-mirror-` directories ending in
`native-dialogue-menu-v75-20261013`, `native-dialogue-recovery-v77-20261013`,
`native-conversation-owner-v78-20261013`, `cinematic-conversation-v79-20261013`
and `conversation-cinematics-off-v80-20261013`. Native instruction observations
and all other diagnostic material remain ignored under `build/vr/`.

The current conversation-guard player separately requalifies ordinary window
Look voice-over, enlarged subtitle publication/retirement, pause/resume, stick
movement, opposite snap turns and normal controller Quit in **35.11 seconds**
in v81. Private flat files/preferences remain unchanged, uninstall succeeds,
the supervisor exits zero and SteamVR closes gracefully without forced
components. This confirms that voice-over text alone is not mistaken for a
cinematic conversation. The run is capture-free; it does not resolve the
cinematic-panel subtitle readability gap described above.
Evidence: `build/vr/steamvr-native-20261011-mirror-conversation-guard-voiceover-v81-20261013/`.

## Readable subtitles during native cinematic conversations

The opaque cinematic screen now keeps the independently enlarged VR subtitle
plane. The producer publishes only a fresh, ready native caption from the same
presentation callback. It never routes dialogue from a stale caption cache or
manufactures world ownership to obtain the text layer.

The private renderer operation combines the complete opaque game page with the
isolated subtitle source in one predicted frame. A GPU-only black matte removes
the smaller baked glyphs from the private XR copy, without modifying the native
page or its controller picking. The enlarged text carries a black contrast
backing within its explicit source bounds. Glyph colors remain native, and
neither the backing nor the subtitle becomes an interactive control. Normal
world subtitles retain their existing presentation. Retirement withdraws both
the text quad and its private matte.

The freshly qualified renderer is in
`build/vr/modal-subtitles-qualified-v8-20261013/`, with DLL SHA-256
`2364aad9148b3c0fe29e955086a8ee3ea9adcfaf67f32fc5b9eec62720e42069`.
All six native test groups and the complete flat/OpenXR GPU qualification pass.
GPU tests cover RGB565/32-bit native pages, RGBA/BGRA runtime targets, one-frame
composition, independent layers, exact private matte bounds, unchanged native
page bytes/picking, black contrast backing, malformed-source rejection and
clean retirement. They do not establish physical-headset readability or comfort.

The earlier v82 actual-SteamVR run reached Talk/topic/Cancel/inventory/stereo,
but failed an overly broad retirement assertion: a normal room HUD part is not
a surviving subtitle. The workbench now checks the subtitle flag specifically.
Both-eye inspection also found that enlarged text without its contrast backing
overlapped a bright shirt, motivating the explicit backing above. v82 remains a
failed end-to-end run, not a clean-Quit pass.

The fresh-build work encountered an incomplete SDK clone and intermittent
parallel MSBuild worker failures. The SDK download now shallow-clones its
release tag and verifies the unchanged pinned commit. A failed parallel native
compile receives one serial retry, still followed by all independent tests;
neither a compile failure nor a test failure can publish a verified artifact.
Failed build directories and diagnostic iterations remain ignored evidence.

Focused Python checks pass 466 panel/overlay/ownership/composition tests in
8.96 seconds, 492 VR/input/navigation tests with three skips in 16.20 seconds,
and 23 build-service tests in 0.62 seconds. These sets overlap and should not be
summed as unique coverage. Full lint/type/format/spelling checks pass.

Actual-SteamVR v83 passes the complete controller Talk/topic/Cancel/inventory/
stereo/Quit-No/Yes flow in **63.36 seconds**, using player SHA-256
`68af732643ff9f71e79ef9ca54667fd2308a469070f914c9dc20316728ee9307`
and the fresh renderer above. All **5,397** interior active-conversation samples
are panel-only, with one fixed world count and one published screen transform.
**5,368** samples publish the separate subtitle part. XR advances by **2,908**
frames while the native camera uses five poses. Both compositor eyes show the
enlarged high-contrast text, without the former small duplicate. Their captures
are sequential, not a temporal-flicker test or physical-headset acceptance.

The v84 control passes ordinary window Look voice-over, separate subtitle
publication/retirement, pause/resume, stick movement, opposite snap turns and
controller Quit in **35.28 seconds**. It is capture-free and does not add visual
acceptance beyond the preceding voice-over captures. Both runs exit zero,
preserve private flat files/preferences, uninstall and shut down SteamVR without
forced components. No ordinary Steam installation was changed.

The checklist implementation milestone is checked. Broader scripted gameplay,
sustained performance, physical controls/readability and headset comfort remain
open. Evidence is in `build/vr/steamvr-native-20261011-mirror-` directories ending
in `modal-subtitles-v83-20261013` and `modal-subtitles-world-v84-20261013`.

### Representative pacing after the cinematic-subtitle milestone

The matching player/renderer completes controller startup, native staging of
dining-room and museum cameras, two screenshot-free 20-second measurement
intervals and controller Quit in **82.02 seconds** (v86). Each eye is
2016×2240; the desktop mirror is separately 1280×800. SteamVR is configured for
120 Hz with virtual tracking/controllers. There are no captures inside the
measured intervals. Flat files/preferences remain unchanged, uninstall passes,
the game/supervisor exit zero and SteamVR closes without forced components.

| Scene | Stereo submissions/s | Compositor client interval median / p95 / p99 |
| --- | ---: | --- |
| Dining room | 119.95 | 7.27 / 7.77 / 8.96 ms |
| Museum | 120.00 | 7.56 / 7.86 / 8.11 ms |

The compositor analysis excludes one second at each interval edge and its
initial pre-interval retrieval. Each scene has 2,160 unique timing frames with
the expected matching focus/statistics PID. These are stationary authored
cameras, not a moving-camera stress test or headset scanout qualification.
The dining-room p99 exceeds the 8.33 ms budget, and sustained performance stays
unchecked. No renderer optimization is claimed from this measurement.

The v85 attempt did not reach its requested scene through the old unverified
console helper and remains a failed workbench run. The repeated workbench uses
bounded, visibly verified native console staging outside measurement, then
requires the actual loaded scene. No scene pointers or script completion are
assigned to obtain a pass. Evidence is in
`build/vr/steamvr-native-20261011-mirror-representative-pacing-v86-20261013/`.

The authored hotel-exterior v87 control completes in **56.79 seconds**, with
the same player/renderer, eyes, mirror and refresh target. Its 20-second interval
reaches **118.99 stereo submissions/s**. After the same edge/history exclusions,
2,145 unique compositor timing frames have matching focus/statistics PIDs;
client-interval median/p95/p99 is **7.58 / 9.27 / 15.83 ms**. Clean controller
Quit, flat/preference preservation, uninstall and graceful SteamVR shutdown all
pass. The camera is `CutToCameraAngleX(-45,-3,3430,100,-2520)` with 60-degree FOV.
This is not a controlled comparison against the older exterior camera samples.

The next performance priority is the reproducible exterior tail, not merely a
higher nominal submission rate. Record matched API/compositor timings and
profile outside the measured interval before choosing an optimization. Keep
the current comfortable-camera, controller and presentation behavior as
regression requirements. The first enjoyable release remains unqualified for
physical-headset delivery and moving-camera stress. Evidence is in
`build/vr/steamvr-native-20261011-mirror-representative-exterior-v87-20261013/`.

## Exterior performance isolation and desktop-preview pacing

The v88 profile repeats the authored hotel-exterior camera with matching
application/compositor timing and primary-thread sampling outside measurement.
The published player remains `68af73…`; the qualified renderer is `2364aa…`.
The 18-second interior interval contains 2,148 API frames and 2,145 unique
compositor frames with matching focus/statistics PIDs. Submission rate is
119.25/s; submission-interval p99 is 16.30 ms and time outside OpenXR p99 is
15.48 ms. Runtime frame-wait p99 is only 1.41 ms. Most of the large delay is
therefore outside that wait, not evidence of a slow headset wait alone.

A separately relinked symbol map is verified to have exactly the qualified
renderer's `.text` bytes. Of 240 primary-thread samples, 154 include the stereo
scene bridge, 38 include submission-queue synchronization and 24 include runtime
frame begin. Sampling is outside the timed interval and is not a precise
time-allocation profile; raw stack candidates are not trusted as unwound calls.

The batched-release candidate passes all native/flat/OpenXR GPU checks, then an
actual SteamVR controller startup/exterior/Quit run (v89). It postpones image
release to the common frame boundary, preserving pixels and queue ordering.
The before/candidate/baseline-repeat comparison does not support retaining it:

| Variant | Stereo submissions/s | Outside-OpenXR median / p95 / p99 |
| --- | ---: | --- |
| Baseline v88 | 119.25 | 6.87 / 9.47 / 15.48 ms |
| Batched release v89 | 119.00 | 7.00 / 9.04 / 15.46 ms |
| Baseline repeat v90 | 119.15 | 6.88 / 8.98 / 15.24 ms |

That production change was removed, and the original renderer passes current
recipe inspection again. Its candidate artifacts remain ignored evidence.
The v90 historical-baseline inspection uses the exact archived source inventory,
not a weakened production verifier or a claim that old source matches a new one.

Minimizing the private window improves headroom in v91: 120.00 submissions/s,
outside-OpenXR median/p95/p99 5.63/6.61/8.13 ms and compositor client-interval
p99 9.44 ms. However, the v92 controller dialogue check cannot obtain its new
world ray after minimization. Minimized submission alone is not playable VR,
and minimization is not adopted as the launcher default.

The v93 reversible WSI isolation keeps the private window visible. Only its
verified desktop `D3D9SwapChainEx::PresentImage` entry is temporarily suppressed
in owned-process memory; original code is restored before controller Quit.
The disk DLL and player are unchanged. The same session measures baseline,
suppressed WSI and restored WSI, preserving XR input focus:

| Desktop presentation | Outside-OpenXR median / p95 / p99 |
| --- | --- |
| Baseline | 7.09 / 8.14 / 9.50 ms |
| Suppressed, diagnostic only | 4.87 / 5.90 / 6.56 ms |
| Restored | 7.02 / 7.97 / 8.63 ms |

Nominal submission rate is about 120/s in all three intervals. The within-session
median difference supports about 2.2 ms of desktop-presentation headroom, not a
claim that every exterior spike has one cause. Later restored p99 is lower than
the earlier v88/v90 samples even without a production change. Warm/state/load
effects still require separation. Null-driver present/drop/reprojection counts
are not physical-headset delivery evidence.

The retained improvement paces only the desktop preview to approximately 30 Hz using
OpenXR's existing predicted time. It does not sleep, minimize the window, reduce
eye resolution, change simulation/input, or lower headset rendering/submission
rate. Missing prediction retains ordinary presentation. Native cadence tests
cover different headset rates, repeated predictions, skipped intervals, clock
restart, ordinary presentation and overflow limits. Native/GPU qualification,
actual controller gameplay, both-eye inspection and measured benefit must all
pass before retaining it as a first-release improvement. The local qualification
below now meets that implementation milestone, not the overall performance or
physical-headset release gates.

Evidence: `build/vr/steamvr-native-20261011-mirror-` folders ending in
`exterior-profile-v88-20261013`, `batched-release-profile-v89-20261013`,
`exterior-baseline-repeat-v90-20261013`, `exterior-minimized-v91-20261013`,
`minimized-controller-dialogue-v92-20261013` and
`desktop-present-isolation-v93-20261013`. No ordinary Steam game was changed.

The fresh recipe `build/vr/mirror-pacing-candidate-20261013/` passes all six
native groups and complete flat/OpenXR GPU qualification. DLL SHA-256 is
`5a21c417bcd7277bf1a7069e5a60a311e0eb3317b035fa7ea62641e3e2ec0dc3`;
the player remains `68af73…`. Native cadence checks cover 80/90/120/144 Hz,
duplicate predictions, missed intervals without catch-up bursts, restart,
missing prediction and integer limits. Ordinary flat rendering is unaffected.

The matching actual-SteamVR v94 exterior run passes in **55.56 seconds**. Its
20-second interval reaches **120.00 stereo submissions/s**; outside-OpenXR
median/p95/p99 is **5.37/6.63/7.55 ms**, and compositor client-interval
median/p95/p99 is **5.80/7.16/8.41 ms**. This corroborates the desktop-cost
isolation and provides useful frame headroom without changing resolution or
scene quality. Submission-interval p99 remains 10.55 ms; stationary virtual
tracking and null-driver counters do not prove real headset delivery or every
frame meeting the budget. Longer/moving/load-transition qualification is open.

The captured controller dialogue v96 completes in **62.37 seconds**, including
native Talk/topic/Cancel, separate high-contrast subtitle retirement, inventory,
stereo and Quit-No/Yes. Both eye images are inspected and retain the expected
scene and readable text. The v95 attempt remains a failed workbench run: its
ray observer could accept transient pose/ray data while the render callback was
rewriting that buffer. The successful repeat changes the observer, not the
production renderer. The probe now requires coherent complete reads, valid
unit-quaternion/ray data and the newly delivered direction before accepting
native picking. It does not assign hits, change camera state or loosen the
direction-alignment requirement. The earlier minimized v92 used that older
probe too, so it does not independently establish a production focus defect.
Minimized controller gameplay remains unqualified rather than a default.

The capture-free v98 native SIDNEY sequence passes in **93.57 seconds**:
COMPUTER_SCREEN picking → its actual Type action → map analysis/browser →
Virgo point entry and native confirmation → hexagram move/resize/rotate →
Libra center/radius alignment and native completion → chapter transition to
HAL/310a → inventory/stereo → Quit-No/Yes. The v97 entry attempt used the old
panel scratch pose and an unverified new ray; the workbench now shares a
coherent world-ray observer and visibly verifies its native camera staging.
All callbacks and progression remain native. v98 adds functional coverage, not
new visual acceptance for the puzzle screen or physical controllers.

v94/v96/v98 exit zero, preserve flat files/preferences, uninstall and close
SteamVR gracefully. Python VR/panel/overlay checks pass **356 tests with three
skips in 16.15 seconds**, and full lint/type/format/spelling checks pass.
Evidence folders end in `mirror-paced-exterior-v94-20261013`,
`mirror-paced-dialogue-v96-20261013` and
`mirror-paced-sidney-puzzle-v98-20261013`. The checklist now checks the paced
preview implementation milestone and keeps overall release readiness open.

### Moving gameplay and native loading qualification, 13 October 2026

The current `5a21c417…` renderer and `68af73…` player pass the v99 moving-camera
exterior run in **55.14 seconds**. During its capture-free 20-second measured
interval, actual SteamVR synthetic-controller stick input produces **1,931
native movement calls and two snap turns**, staying within 18.77 game units
of the staged camera origin. Stereo submission is **120.00/s**. Outside-OpenXR
median/p95/p99 is **5.83/7.24/8.17 ms**, compositor client interval is
**6.26/7.80/8.92 ms**, and total GPU is **4.63/6.45/8.01 ms**. This extends the
stationary benchmark to native controller movement. It does not qualify real
head motion, physical controls, sustained sessions or delivered headset frames.

The capture-free v100 session loads **CS2, BEC, TE4, RC1 and R25**, recovers
stereo and exercises actual runtime-controller Inventory/Back after each one.
It passes in **61.71 seconds**, with maximum observed submission gaps of
**426/569/491/512/210 ms**, respectively. Recovered controller transitions
have maxima of **33/15/27/28/20 ms**. Scene staging uses the visibly verified
native console and host Escape skips introductions. No camera, picking or
native lock state is overwritten to obtain recovery. This qualifies recovery,
not continuous low-latency loading or headset comfort during those pauses.

A separate read-only v101 BEC/R25 profiling repeat also passes. Its one BEC
stall stack is inside the native game's RGB24-to-RGB565 bitmap conversion,
not inside OpenXR or the renderer. The normalized native function rounds
channels and recognizes a masked color key, so a replacement would need exact
color/key semantics, not a generic truncating converter. One sample does not
prove the dominant loading cost. **Defer that optimization while connected
gameplay and remaining first-release capabilities have higher priority.**

All three sessions exit zero, preserve private flat files/preferences,
uninstall and close SteamVR gracefully. No ordinary Steam installation changes.
Evidence remains in ignored `build/vr/steamvr-native-20261011-mirror-` folders
ending `moving-exterior-v99-20261013`, `loading-current-v100-20261013` and
`loading-profile-v101-20261013`.

### Connected playable session, 13 October 2026

Prioritize the larger experience over converter optimization or visual polish.
The matching current renderer/player passes v105 in **67.80 seconds** through
public install, verification, launch and removal. Inside one running game:

1. Actual runtime-controller rays type a save name, save the native slot,
   snap-turn the camera and restore the exact saved camera.
2. Stage the SIDNEY chapter through the native console, then use actual
   controller world picking and Type to enter the computer. Type `vampires`,
   search, return Home and select the original Exit control.
3. Reload the save created in step 1 through the native loader, preserving its
   Gabriel story state. Open the driving map through the console, then use
   controller rays to highlight Cuiza and Rennes-les-Bains, select native
   station travel and arrive at TR1/110a.
4. Skip the original station introduction through controller Back only when
   its real enabled ActionSkipper owns input. Open inventory, return through
   Back, perform native stick movement and one snap turn, then cancel and
   confirm native Quit through controller selection.

The save/restore, SIDNEY and map stages take **5.72/23.08/5.19 seconds**. The
connected in-game flow takes **37.66 seconds**, with startup, installation and
cleanup included in the larger session time. Flat files and display preferences
remain unchanged, removal passes and SteamVR closes gracefully. Synthetic
controllers exercise actual runtime actions, not direct assignments to picking,
camera, gameplay flags or completion callbacks. No new production fix is
needed for this combined sample. It has no new compositor captures and does
not qualify physical-device controls, headset comfort or a natural whole-story
playthrough.

Failed attempts remain recorded, rather than counted as passes. v102 tried
Gabriel-only station travel from the staged Grace chapter. v103 also used the
wrong diagnostic button bit for Inventory. v104 corrected that bit but attempted
Inventory before the native station introduction released input. v105 restores
the actual saved story state and skips the introduction through its original
enabled control, rather than weakening native ownership or forcing the camera.
These were workbench sequencing defects, not evidence requiring game patches.
Evidence is in ignored folders ending `connected-session-v102-20261013` through
`connected-session-v105-20261013`, with reusable helpers under `build/vr/`.

After this qualification, focused Python VR/panel/overlay regressions pass
**356 tests with three skips in 14.89 seconds**. All owned game/runtime
processes are stopped. No commits, release changes or ordinary game changes
are made in this milestone.

### Gravity-aligned recentering and safe head-tracking recovery, 13 October 2026

Extend the isolated workbench with an optional raw head tracker and SteamVR's
documented `TrackingOverrides` mapping. The tracker provides poses to the
runtime, which supplies the application's real OpenXR views and compositor
poses. It does not overwrite app-returned poses or another driver's device
index. Registration, universe and override settings exist only in the private
lab configuration, and the ordinary runtime configuration is hash-checked
unchanged after shutdown.
[Valve's tracking-override documentation](https://github.com/ValveSoftware/openvr/wiki/TrackingOverrides).

The initial v107 actual-runtime sample verifies three 10 cm translations and
yaw/pitch/roll through raw SteamVR and the native eye matrices, without changing
the authored camera. Its snapshot-only tracking-loss check is insufficient:
the native ray buffer has transient zeroes while being republished. Do not
count that as a passing held-input recovery test. v106 had also mistaken
integer viewport fields for floating-point values in its observer; neither
workbench defect needs a production patch.

v108 then demonstrates a real comfort defect: recenter with a 15° sideways
head tilt, return upright, and the world remains banked by **15°**. The scene
origin had copied the full head quaternion. The retained fix centers position
and horizontal heading only, preserving gravity just as the stationary panel
anchor already does. Looking straight up/down retains the previous heading
instead of choosing yaw from noise. Native tests first fail on the old code,
then pass for startup, explicit and controller recentering, pitched/rolled/mixed
poses, asymmetric projections, binocular separation, shared controller rays,
vertical-heading fallback and unchanged authored cameras.

The first extended v109/v110 recovery attempts uncover a second real defect.
SteamVR's raw tracker is invalid, but `xrLocateViews` keeps **VALID** last-known
poses while clearing **TRACKED** flags. The read-only API trace observes flags
`15` while tracked and `3` during loss. The player previously treated validity
as permission to interact, allowing a held Inventory action to replay after
recovery. OpenXR explicitly permits this valid-but-untracked distinction.
[OpenXR view-state flags](https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrViewStateFlagBits.html).

The retained runtime guard keeps legal last-known-view rendering, but clears
interaction and resets action latches whenever either head tracking component
is absent. Recovery requires release/neutral input before fresh activation.
Native tests first reproduce the old unsafe behavior, then verify legal stereo
presentation with no interaction, partial/complete tracking loss, suppressed
held buttons/stick on recovery and fresh-input rearming. The GPU fixture now
reports fully tracked poses for its ordinary positive cases.

The fresh `build/vr/head-comfort-qualified-20261013/` renderer passes all six
native groups and complete flat/OpenXR GPU qualification. DLL SHA-256 is
`4d2937f4d1147e28a54e4da24e76d1dd2a5d7f496bc1beee079f5eb8a05a2b34`;
the compiled player remains `68af73…`. The v111 actual-SteamVR public-command
flow passes in **39.30 seconds** with both fixes:

- Native eye transforms follow raw leaning and yaw/pitch/roll, while the
  authored camera remains unchanged.
- Tracking loss retires completed interaction permission. Inventory held
  during loss does not replay on recovery; release and a fresh press work.
- The inventory panel stays anchored while the viewer leans and turns.
  Controller pointing reaches the original Exit button and returns to stereo.
- Recenter while rolled, return upright, and the measured horizon error is
  **0°** rather than 15°. Restore upright centering through the controller.
- Cancel and confirm native Quit, exit the supervisor with zero, preserve flat
  files/preferences, uninstall and close SteamVR gracefully without forced
  components. Global runtime configuration is unchanged.

Inspect both compositor eyes for moved-head inventory pointing and upright
recenter. The immediate tracking-recovery captures include SteamVR's transient
gray recovery fade; later recenter images are bright in both eyes. This is
sampled rendering evidence, not proof that every transition is artifact-free
or physical-headset comfort is qualified. The null display and synthetic
tracker/controllers remain diagnostic hardware. Source, binaries, observations
and failed attempts stay in ignored `build/vr/` folders ending
`head-motion-v106-20261013` through `head-comfort-v111-20261013`.

v112 extends performance sampling to **combined smooth head motion and actual
runtime-controller camera navigation**, with the matching `4d2937…` renderer.
The raw tracker supplies translational/angular velocity to SteamVR prediction,
not synthesized app poses. Its capture-free 20-second hotel-exterior interval
publishes **1,913 head poses**, produces **1,935 native movement calls and two
snap turns**, and averages **119.70 stereo submissions/s**. Outside-OpenXR
median/p95/p99 is **5.89/7.60/8.47 ms**, compositor client interval is
**6.33/8.16/9.20 ms**, and total GPU is **4.74/7.20/8.47 ms**. Submission
interval p99 is 10.46 ms. Those tails still exceed the 120 Hz budget; neither
the average nor null-display compositor counters prove physical delivery.
The complete run passes in **55.02 seconds**, including normal Quit and cleanup.

v113 repeats the connected public-command save/restore/SIDNEY/map/travel/
introduction-Skip/inventory/navigation/Quit session with the new renderer.
It passes in **66.55 seconds**, including **37.85 seconds** of connected in-game
flow. Supervisor result is zero with no errors, flat files/preferences and
global runtime configuration are unchanged, removal passes and SteamVR closes
gracefully. The connected baseline is therefore no longer only an older-renderer
qualification. Scene staging remains explicit; this is not natural story
acquisition, physical controls or whole-game completion.

Focused Python VR/panel/overlay regressions pass **356 tests with three skips
in 14.02 seconds** and full lint/type/format/spelling checks pass. The new
renderer is a local prototype only, with no release/commit changes. All owned
game/runtime processes are stopped. Evidence ends in
`head-and-controller-moving-v112-20261013` and
`head-comfort-connected-v113-20261013`; raw timings and motion traces are
retained in those ignored folders.

### Real-runtime geometry protection and native draw-state coherence, 13 October 2026

v114/v115/v116 extend geometry protection from the native test runtime to raw
head poses delivered through actual SteamVR in **R25, LBY and BEC**. Sample the
coherent native eye snapshot and the completed input router, not a transient
zero in the ray-publication buffer. Find a nearby protected surface without
inventing a hardcoded collision plane, locate protection onset, move beyond
it, then retreat. Eye positions continue to follow tracking at the calibrated
scale, authored camera bytes stay unchanged and stereo submission continues.

The three complete public-command sessions pass in **33.47/35.62/37.45 seconds**.
Protection starts at approximately **45–47 cm backward** in R25, **30–31 cm
backward** in LBY and **91–94 cm downward** in BEC. Both compositor eyes are
black at crossing. R25/BEC have no nonblack pixels in the sampled capture;
LBY retains only its independent small status text, about 0.016% of pixels.
Retreat restores the scene in both eyes. The stronger LBY/BEC checks confirm
native Select stays blocked with a held trigger on return, until release,
without an action-menu replay. Scene staging uses the native console and host
Escape for introductions; actual protection uses only raw tracker/controller
input. Physical comfort remains unqualified.

v117 qualifies two native camera glides during smooth raw-runtime head motion.
Observe the original moving controller, suppressed immersive draws, a stationary
screen pose, continuing XR submission and recovered stereo. Its sampled
interior glide intervals contain **16 and 15 XR frames**; the tracker publishes
**532 poses** across the complete staged flow. The public-command run passes in
**34.35 seconds** with normal controller Quit, unchanged flat files/preferences,
removal and graceful runtime shutdown. This is functional comfort-routing
evidence, not a worn-headset comfort result or new visual acceptance of every
glide frame.

**The BEC wall test is not a clean-rendering pass.** Eye inspection reveals a
large black ground rectangle in otherwise visible scenery. The v118 control
runs the same `4d2937…` renderer and package player with every VR switch dormant
and OpenXR disabled. It passes in **15.67 seconds**, with native Quit, removal
and unchanged flat files, and its flat image has no black rectangle. This
distinguishes the regression from ordinary game content or texture policy.

The eye transport restored an old `D3DSBT_ALL` state block after each native
draw. GK3 maintains its own write-eliding graphics-state cache, so the GPU was
rolled back behind that cache. A new actual-GPU regression simulates cached
alpha enabling across eyes and repeated frames: the old bridge turns a
translucent black quad opaque, while the corrected bridge preserves the
expected blended pixels. This is a behavior test, not an assertion of the
bridge's internal implementation.

The retained fix restores only the target, depth, viewport and scissor state
changed by the VR eye binding. Native draw-state changes remain in sync with
the native cache. The separate VR beam/marker still restores its own temporary
draw-state changes, which the game did not make. Desktop pixels and target/
clipping restoration on success/failure remain covered by GPU tests. Do not
describe this as abandoning native state restoration: it avoids over-restoring
state whose native owner has already committed an update.

Fresh recipe `build/vr/native-draw-cache-qualified-v2-20261013/` passes all six
native groups and complete flat/OpenXR GPU qualification, including both runtime
color formats and copy policies. DLL SHA-256 is
`e2ffb4de23b3a1a6965af29c322f4c54e3655ca6de33f97f0e86899930118eb9`;
the player remains `68af73…`. The first fresh build stopped on a test-ordering
problem: inserting extra scene submissions before an existing exact counter
check changed that check's setup. Run the independent cached-state test after
those older counted sequences, preserving their checks. No failed build is
published as verified.

v119 repeats the actual-SteamVR BEC protection/retreat/controller-Quit flow with
the corrected renderer in **38.38 seconds**. Both returned compositor eyes
now show normal ground with **no black rectangle**. Geometry protection still
passes and normal cleanup is unchanged. This is a retained correction of a
demonstrated VR rendering regression, not a claim that all shadows/content or
headset graphics acceptance are complete.

All observations stay in ignored `build/vr/` folders ending
`raw-head-wall-v114-20261013` through `native-draw-cache-puzzle-v119-20261013`,
plus `bec-flat-control-v118-20261013/`. Failed workbench attempts and the failed
first renderer build are retained. No ordinary Steam installation, release or
commit is changed.

### Current-build connected play, tracked controls and pacing, 13 October 2026

The same `e2ffb4…` draw-cache-corrected renderer passes v120's raw SteamVR
head/control flow in **34.07 seconds**. One-to-one translation and rotation,
unchanged authored camera, tracking-loss held-input rejection, anchored inventory
pointing/Exit and upright recenter all pass. The measured recenter horizon error
is **0.0 degrees**. Both moved-inventory compositor eyes and the returned upright
world are visually inspected. The panel stays anchored while the viewer moves;
this does not establish worn-headset aiming or comfort.

v121 repeats connected controller save/change-camera/exact restore → native
SIDNEY entry/search/Exit → saved-story reload → map highlights/travel → native
introduction Skip → inventory/navigation → Quit-No/Yes. It passes in
**66.10 seconds**, including **37.80 seconds** of connected in-game flow. This
is a current-build functional repeat without compositor capture, not a new
visual qualification of every intermediate screen or natural story acquisition.

v122 repeats simultaneous raw head movement and controller exterior navigation
at 2016×2240 recommended pixels per eye and 120 Hz, without screenshot capture.
Its twenty-second interval averages **119.95 stereo submissions/s**. Outside-XR
median/p95/p99 is **5.48/7.05/8.04 ms**, compositor client interval is
**5.89/7.58/8.72 ms** and total GPU is **4.26/5.94/8.03 ms**. Submission-interval
p99 is **10.39 ms**, so the 120 Hz budget is not consistently achieved. Null
display counters do not prove physical headset delivery. The complete run
passes in **55.09 seconds**, with normal controller Quit and cleanup.

All three runs preserve flat files/preferences, remove the private VR player,
leave global SteamVR configuration unchanged and stop owned runtime components
gracefully. Independent artifact inspection still accepts the matching source
inventory and renderer. Focused Python VR/panel/overlay tests pass **356 tests
with three skips in 14.78 seconds**; full lint/type/format/spelling checks pass.
Evidence folders end in `native-draw-cache-head-controls-v120-20261013`,
`native-draw-cache-connected-v121-20261013` and
`native-draw-cache-moving-v122-20261013` under ignored `build/vr/`.

The first headset tryout is scoped to a dependable, enjoyable seated session,
not exhaustive whole-game qualification. Continue prioritizing required controls,
safe start/restart, connected play and demonstrated comfort/rendering blockers.
Optional mouse/world ownership and native bitmap micro-optimization remain
follow-ups. Physical scale, aiming, readability, comfort and delivered frame
pacing must still be accepted in a headset before a release claim.

### Quit and relaunch without restarting SteamVR, 13 October 2026

v123 exercises **two public build-reuse/install/verify/launch/uninstall cycles in
one live SteamVR session**, not two isolated runtime startups. The workbench
holds its same virtual head/controller device mappings for both, and stores
separate complete outcomes. Both recover controller Play, raw head translation/
rotation, held-input rejection after tracking loss, anchored Inventory/Exit,
upright recenter and native Quit-No/Yes. No source/runtime state is forced to
simulate a restart.

The cycles pass in **43.40 and 31.62 seconds**, totaling **75.02 seconds**. Both
supervised children exit normally, flat files/preferences remain unchanged and
private player removal passes. Owned SteamVR then closes gracefully with no
forced components, and global runtime preferences stay unchanged. This proves
normal application relaunch with a continuing synthetic runtime, not physical
headset reconnection or recovery after a hard runtime crash. Evidence is in
ignored `build/vr/steamvr-native-20261011-mirror-native-draw-cache-restart-v123-20261013/`
and its `-session1`/`-session2` siblings. The retained renderer/player are unchanged.

### Moving-head dialogue and loading qualification, 13 October 2026

v124/v125 keep publishing raw head motion throughout the native Talk/topic/
Cancel/inventory/stereo flow. v124 fails its anchor observation on one partially
written output rectangle, not a demonstrated moving anchor. The producer
clears/rebuilds that scratch geometry, and the invalid sample has zero height.
The corrected observer retains raw samples but accepts only repeated, finite,
unit-orientation rectangles with positive dimensions and the actual canvas
aspect ratio. It still requires an exactly constant displayed conversation
anchor. No production state or anchor assertion is weakened.

v125's functional flow passes in **62.49 seconds**, with **2,986 raw head poses**,
four native camera poses and **2,915 XR frames** during conversation. However,
both-eye image inspection reveals subtitle breakup/disappearance during head
motion. This is **not a clean visual pass**. The native screen and enlarged
subtitle quad are coplanar; a depth-separated candidate is being tested while
preserving angular size and leaving original game glyphs/picking untouched.
The suspected runtime composition issue is not yet a confirmed root cause.
OpenXR requires submission-order layer composition, so a successful workaround
would not prove the application's previous ordering was invalid. Reference:
[OpenXR composition layers](https://registry.khronos.org/OpenXR/specs/1.0-khr/html/xrspec.html#compositing).

v126 moves the raw head through four native loads, **CS2/BEC/TE4/R25**, with the
same `e2ffb4…` build. All four recover stereo and actual runtime-controller
Inventory/Back; no locks, camera ownership or story flags are cleared to force
success. The complete run passes in **53.76 seconds**, with **2,273 head poses**
across its 25.07-second transition interval. This capture-free functional pass
does not establish continuous low-latency loading or visual transition comfort.
Normal cleanup preserves flat/global settings and closes the runtime gracefully.
Evidence folders end in `native-draw-cache-moving-dialogue-v124-20261013`,
`native-draw-cache-moving-dialogue-v125-20261013` and
`native-draw-cache-moving-loads-v126-20261013` under ignored `build/vr/`.

### Retained moving-head subtitle correction, 13 October 2026

Fresh recipe `build/vr/subtitle-depth-candidate-20261013/` passes all six native
groups and complete flat/OpenXR GPU qualification, including both runtime color
formats and copy policies. Its independently accepted renderer SHA-256 is
`2af1c773eed95f696f7345c267e97e6e87ce810ba7e67ef3926cb9dd1e9c6d79`.
The package player remains `68af73…`; it retains the native draw-cache correction.

The subtitle plane is placed slightly in front of the stationary native cinema
screen. Scaling its size and vertical offset about the anchored viewer preserves
its angular footprint, rather than changing fonts or enlarging text further.
Native behavior tests require positive depth separation, unchanged apparent
size/bottom anchor, unchanged ordinary UI geometry and no movement when the
viewer turns/translates. The private native-page matte and controller picking
are unchanged.

v127 repeats the actual SteamVR moving-head conversation on that fresh build.
The complete Talk/topic/Cancel/inventory/stereo/Quit flow passes in **62.58
seconds**, with **2,946 raw head poses**, four native camera poses and **2,892 XR
frames** during conversation. Both compositor eyes now show clear enlarged text
and a solid contrast backing, without the earlier striped breakup or missing
glyphs. Normal cleanup preserves flat files/preferences and global runtime
configuration and closes SteamVR gracefully. This supports coplanar runtime-layer
interference as the cause and retains the small separation as a compatibility
correction, not a change to required OpenXR layer ordering. It remains sampled
synthetic-device evidence, not physical-headset acceptance.

Full lint/type/format/spelling checks pass; focused Python VR/panel/overlay
regressions pass **356 tests with three skips in 16.64 seconds**. Current source
and metadata match the new renderer. Keep the earlier `e2ffb4…` performance and
connected-play evidence labeled as that earlier build, not silently attributed
to this one. The first enjoyable-session priority remains demonstrated blockers
and connected controls/gameplay, before optional modes or exhaustive coverage.

v128 also repeats the connected save/change-camera/exact restore/SIDNEY search/
saved-story reload/map travel/introduction Skip/inventory/navigation/Quit-No/Yes
flow with this exact `2af1c7…` renderer. It passes in **67.42 seconds**, including
**37.83 seconds** of connected in-game flow. Supervisor errors are empty, flat
files and engine preferences are unchanged without preference cleanup, private
player removal passes and SteamVR closes gracefully without forced components.
This is capture-free functional integration evidence, not new visual acceptance
of every intermediate screen. Evidence ends in
`subtitle-depth-moving-dialogue-v127-20261013` and
`subtitle-depth-connected-v128-20261013` under ignored `build/vr/`.
All owned game/runtime processes are stopped; ordinary Steam files, commits and
releases remain untouched. The active VR goal and six release gates remain open.

### Moving-head SIDNEY editor and keyboard, 13 October 2026

v129 is a **read-only control test**, not a notes-typing pass. The editor-probe
flag selects Make ID/file controls and returns before the notes branch; that
flow passes during raw head motion, but cannot support the originally intended
multiline claim. Keep this evidence separate rather than treating a successful
outer command as qualification of an unexecuted route.

The corrected v130 workbench selects the actual Suspects notes route directly.
It enters SIDNEY through native controller object/verb selection, focuses the
native multiline editor, types `note`, exercises native Home/End, enters a
newline through the controller keyboard's Return and types `ok`. Exact native
contents and caret positions are verified, held keys do not repeat, and closing
then reopening Suspects retains **`note\nok`**. Keyboard/editor ownership retires
at Home; native Exit and controller Quit-No/Yes complete normally. No editor
buffers, caretaker positions or game callbacks are written by the test.

The current `2af1c7…` build passes in **77.15 seconds**, with **3,990 raw head
poses** over its 41.87-second SIDNEY interval. Both compositor eyes are inspected:
the original notes and floating keyboard are clear, correctly highlighted and
separate from the native computer page during moving-head pointing/typing.
The workbench uses the actual SteamVR virtual devices; physical input,
readability and aiming acceptance are still open.

Supervisor errors are empty, native engine preferences and flat files remain
unchanged, private player removal passes and SteamVR/global configuration cleanup
is graceful. Evidence ends in `subtitle-depth-moving-sidney-v129-20261013` and
`subtitle-depth-moving-notes-v130-20261013` under ignored `build/vr/`. Only private
workbench routing and evidence documentation changed during these samples.

### Current-build sixty-second moving performance interval, 13 October 2026

v131 extends the current `2af1c7…` renderer's RC1 test to a **sixty-second**
uncaptured interval at recommended 2016×2240 pixels per eye and a 120 Hz runtime.
It includes **5,718 raw head poses**, **6,144 native movement calls** and two
actual controller snap turns. Camera motion stays within 19.04 game units of
the staged start; original room gameplay remains active. No simulation,
tracking, scene rendering or eye resolution is reduced for this test.

The interval averages **119.93 stereo submissions/s**. Matching steady-state
analysis covers 6,957 API frames and 6,954 compositor observations, excluding
one second at each edge rather than re-labeling loading history. Outside-XR
median/p95/p99 is **5.64/7.03/8.11 ms**, compositor client interval is
**6.07/7.50/9.08 ms**, and total GPU is **4.40/5.78/7.90 ms**. Submission-interval
p99 is **10.50 ms** and its maximum is 15.31 ms. There is no sustained collapse,
but the tails still exceed the 120 Hz budget. Neither the average nor null
display present/drop counters prove physical headset delivery.

The complete public-command run passes in **95.59 seconds**, including native
controller Quit, unchanged flat files/engine preferences and private player
removal. SteamVR/global configuration cleanup is graceful and no owned runtime
is left running. Evidence ends in
`subtitle-depth-sustained-moving-v131-20261013` under ignored `build/vr/`.
The workbench now accepts a bounded measurement duration instead of requiring
a copied helper to extend an interval. No production source changed in this run.

### Safe supervision of an abruptly stopped SteamVR server, 13 October 2026

v132 intentionally terminates **only the uniquely identified server of the
isolated null-headset runtime**, after stereo begins. The existing supervisor
can remain waiting while the native game is blocked inside an XR call. Its
five-second workbench deadline fails, so this is a real lifecycle gap, not a
clean Quit or a passing crash-recovery test. Private failure recovery stops the
owned player, removes its installation and restores/validates private flat files
and preferences. Runtime teardown also encounters a temporarily unqueryable
terminating process; a later authoritative inventory confirms it is gone.

The retained package fix observes the selected SteamVR server's **exact process
handle** once submitted frames establish the session. The handle is opened with
query/synchronize rights only and verified against the runtime's executable
path, not a name-only PID. It remains bound to that lifetime even if a PID is
reused or a replacement server starts. Server termination causes an actionable
supervisor error and cleanup of only its owned game child. The package does not
terminate SteamVR, set a frame-inactivity timeout, or mistake focus/standby/slow
native loading for a crash. Other selected runtimes retain OpenXR lifecycle
supervision. No renderer/player binary changes are needed.

v133 shows that the fix stops the game and prints the correct CLI diagnosis, but
the workbench loses that diagnosis behind its generic failed-command assertion.
It is not a complete passing pipeline. Preserve CLI stderr in the workbench's
failure evidence, without accepting an unexplained nonzero result. Also allow
the existing runtime cleanup observation longer to resolve an inaccessible
terminating PID; do not infer disappearance from access denial or kill a
replacement process.

v134 repeats the actual public-command crash test successfully in **29.53
seconds**. After intentional server exit, the launcher/game stop in **0.21
seconds**, with a nonzero launch result and explicit **restart SteamVR / launch
VR again / unsaved progress cannot be recovered** guidance. Private uninstall,
flat-file/preferences preservation, global runtime configuration preservation
and orderly remaining-component cleanup all pass. This is deliberate crash
injection, not native Quit, physical headset disconnection or automatic
reconnection. Evidence ends in `subtitle-depth-runtime-crash-v132-20261013`,
`runtime-watch-crash-v133-20261013` and `runtime-watch-crash-v134-20261013` under
ignored `build/vr/`. Failed attempts are retained, not overwritten.

Full lint/type/format/spelling checks pass. The focused Python VR suite passes
**217 tests with three skips in 13.60 seconds**, including deferred server
binding, server death before/after binding, release of observation handles,
fresh-lifetime binding on relaunch, exclusion of unrelated runtime layouts and
owned-child cleanup on supervisor failure. Independent artifact inspection
still accepts the unchanged `2af1c7…` renderer and its complete qualification
record. The active goal and first-release acceptance gates remain open.

v135 starts a **fresh runtime and public-command game session after the crash**.
It passes controller Play, raw head movement, head-tracking-loss held-input
rejection, anchored Inventory/Exit, upright recenter and native Quit-No/Yes in
**31.29 seconds**. No source changes or failed-operation cleanup are needed
between the successful crash handling and relaunch. Ordinary flat files and
engine preferences remain unchanged, private removal passes and global runtime
cleanup is graceful. This verifies manual relaunch, not automatic reconnection
or preservation of unsaved game state. Evidence ends in
`runtime-watch-relaunch-v135-20261013`. All owned game/runtime processes are
stopped; no ordinary Steam installation, commit or release changed.

### Moving-head movies and cinema-content sizing, 13 October 2026

v136 does **not** qualify movies: an unrecognized workbench flow name fell through
to ordinary graphics/interface checks. Reject unknown flow names before game
installation rather than accepting a successful command for an unexecuted test.
v137 selects the correct native movie route on the then-current `68af73…`
player and `2af1c7…` renderer. Its complete public-command run passes in
**48.58 seconds**, with **1,785 raw head poses**. `day2-2.bik` completes naturally
while world draws stop and **1,460 XR frames** continue; controller Back skips
`205PEND.BIK`, and holding Back across return does not pause the room. Both
recover stereo and native Quit/normal cleanup pass. Both movie compositor eyes
are inspected. Audio synchronization and physical comfort remain unqualified.

Inspection reveals that the native **320×240** movie occupies a centered
**667×500** rectangle on the 1280×800 source page. The existing flat patch
correctly preserves the reference movie's relative size, but copying the whole
padded page into a 2.4 m VR panel makes that content unnecessarily small.
v139 reads the live native MovieLayer/Bink-player rectangles and modes; they
agree exactly and do not require a filename or nonblack-pixel heuristic.
v138's first metadata probe incorrectly compared a vtable address to its first
method; its failed attempt is retained and not counted as qualification.

A VR-only emitted helper now fits verified fullscreen software-movie content
uniformly into a **2.4×1.5 m cinema area**, independently of desktop size/aspect.
It changes only the private panel's physical scale, leaving native centering,
rectangle data, decoder, audio, timing, pixels and the desktop page unchanged.
The helper validates the live UI root/deque, movie/Bink classes, visibility,
fullscreen/default/software modes and agreement of bounded source rectangles.
Unknown, embedded, custom, overlay or invalid movie content keeps ordinary size.
Its calculation is idempotent, and ordinary UI resets to its original scale.

Emitted-code tests pass **48 cases** for landscape/portrait/aspect fitting,
different source canvases, cached/current/previous-block roots, repeated calls,
subtitles and safe non-movie/invalid fallback, preserving native object bytes.
Focused VR/panel/overlay/movie regressions pass **411 tests with three skips in
18.00 seconds**; full lint/type/format/spelling checks pass. No renderer rebuild
is required: the current accepted renderer remains `2af1c7…`, while the new
compiled player is `4a96f2…`.

v140 displays the larger cinema content, but the old workbench assertion insists
every modal's entire padded page be 2.4 m wide. Replace that implementation lock
with movie-content aspect/physical-fit checks, retaining unchanged ordinary-modal
checks. v141 verifies **2.001×1.500 m** movie content and both-eye imagery, natural
completion, controller skipping and stereo recovery, but final confirmed Quit
does not finish within its deadline. **It is not a passing complete pipeline.**
v142 exits normally but fails the host-cursor invariant; v143 fails its startup
frame-readiness gate, and v144 fails startup host-cursor preservation. Preserve
these failures instead of claiming the new player has the older connected-play
qualification. Their private player removal, flat-file recovery and owned runtime
cleanup pass.

The physical-fit transformation is implemented/visually verified, but full-flow
qualification is pending. A private suspended-process control bypasses only the
new sizing helper, records that diagnostic mutation explicitly and leaves the
installed player bytes/renderer/global configuration unchanged. This control
cannot qualify improved cinema size; it distinguishes the new helper from
startup/cursor/Quit failures before deciding on a production change. All evidence
remains under ignored `build/vr/` in the v136–v145 folders.

v145's controlled bypass still fails **startup host-cursor preservation**, with
the desktop cursor changing from `(3328,1114)` to `(3389,1331)`. The sizing helper
is replaced by an immediate return in the private suspended process, with the
original prefix verified and instruction cache flushed before resume. The disk
player/renderer remain unchanged and the diagnostic mutation is recorded.
This refutes that helper as the cause of this particular startup cursor change;
it does not establish the source of the movement or settle the separate Quit
deadline. Private failure recovery and global/runtime cleanup pass. No owned
game/runtime is left running.

The next useful qualification step is to distinguish external desktop input
from native-game cursor changes, rather than weaken cursor invariants or keep
restarting an unchanged experiment. A short read-only cursor/last-input sample
with no game/runtime running is stable; that alone does not prove the desktop
remained idle during the failing sessions. The improved cinema remains locally
implemented with unit/visual evidence, while dependable complete-flow acceptance
on the new player remains open. No release, commit or ordinary Steam game changed.

## Current cinema player: connected play and complete movie flow

To keep the first enjoyable experience on the critical path, stop repeating
unchanged cursor experiments without source evidence. The private workbench now
has a read-only, background raw mouse observer. It records only mouse-device
motion/buttons/times, never keyboard content or exclusive input. An injected
mouse-motion self-test confirms event delivery and bounded observer shutdown.
Cursor-preservation assertions remain unchanged. This workbench code stays in
ignored `build/vr/`, not the shipped runtime.

With the current unmodified player `4a96f2…` and renderer `2af1c7…`:

- **v146, 67.60 s:** public build reuse/install/verify/launch, controller-typed
  save, changed camera and exact restore, native SIDNEY entry/search/Exit,
  saved-story reload, driving-map highlight/travel, introduction Skip,
  inventory/navigation, canceled/reopened/confirmed Quit, verify/uninstall.
- **v147, 48.89 s:** current enlarged cinema fitting under moving raw head
  poses, original movie natural completion and controller skip, stereo return,
  canceled/reopened/confirmed Quit, verify/uninstall. Actual content measures
  **2.001×1.500 m**, with unchanged aspect ratio. Inspect both compositor eyes.

Both exit normally, preserve the host cursor and private flat files/preferences,
and shut down the isolated runtime gracefully with global configuration unchanged.
The observer records **zero raw mouse events** in both runs. No helper bypass is
enabled. Full-flow qualification now applies to the current cinema player, not
only the earlier smaller-screen build.

This does not identify the cause of the earlier intermittent cursor/startup/Quit
failures, prove physical headset comfort, or close release acceptance. Keep that
distinction explicit. Next prioritize connected representative puzzle/transition
behavior, comfortable loading and sustained moving performance over exhaustive
screen variants or renderer micro-optimizations. Evidence remains under ignored
`build/vr/steamvr-native-20261011-mirror-movie-cinema-{connected-v146,fit-v147}-20261013/`.

**v148, 95.49 s**, extends the current cinema-sizing player to a connected,
native interface-heavy puzzle sequence. Enter SIDNEY through its computer's
ordinary Type action; select/confirm Virgo's corners; add, move, resize and
rotate the hexagram; complete Libra through its native handler; return through
the chapter sequence to inventory and interactive stereo; cancel/reopen/confirm
Quit. Native script callbacks and completion are not forced. The prerequisite
story save and console staging are explicit, not a natural whole-game playthrough.

Raw runtime head tracking publishes **6,260 poses over 66.25 s** through this
sequence. The test is capture-free, so do not infer fresh visual/headset acceptance
from its native-state results. It exits zero, records no raw desktop mouse events,
preserves flat files/preferences and global runtime configuration, uninstalls,
and closes the isolated runtime gracefully. Current first-session capabilities
have connected functional evidence; prioritize loading/transition comfort and
sustained moving performance rather than enumerating every puzzle variant.
Evidence: ignored `build/vr/steamvr-native-20261011-mirror-cinema-player-moving-puzzle-v148-20261013/`.

### Moving representative scenes: performance without capture overhead

Keep performance in the first-session critical path, without returning to
micro-optimization before the required gameplay works. Two fresh, bounded
current-player samples cover dining-room actors, museum actors and the village
exterior, twenty seconds each. Runtime/controller inputs, native page counters
and actual compositor timings are observed without screenshots in the intervals.

**v149** requests a 90 Hz null headset and verifies an OpenXR predicted period
of approximately **11.11 ms**. Raw head movement continues in every interval,
but no controller navigation is enabled in this particular run. Submissions
average 123.70/124.00/120.30 per second: the null runtime's prediction frequency
does not imply corresponding physical scanout or exact application throttling.
GPU p99 is 4.58/3.70/8.16 ms; outside-XR p99 is 6.50/6.84/7.91 ms. This is a
90 Hz prediction-budget observation, not a 90 Hz headset delivery qualification.

**v150** requests 120 Hz and combines raw head movement, original-engine
controller navigation and two snap turns in each interval. Each publishes
about 1,900 head poses and 1,900 native movement calls. Native Quit, player
verification/removal, private flat files/preferences and global runtime state
all pass; the owned runtime closes gracefully. Whole sample: **108.52 s**.

| Scene | Stereo submissions/s | GPU p99 | Compositor client-interval p99 |
| --- | ---: | ---: | ---: |
| Dining room | 121.15 | 5.34 ms | 6.74 ms |
| Museum | 121.70 | 4.69 ms | 6.29 ms |
| Village exterior | 120.50 | 8.13 ms | 9.16 ms |

v150 has genuine compositor timing but no XR API trace, because that opt-in
instrumentation was not enabled for this invocation. Do not manufacture
outside-XR/submission-interval timings or repeat a complete successful game
flow merely to fill those fields. The private summary now explicitly identifies
missing API timing and omits those metrics; the pacing task enables the trace
for future runs and exposes an explicit moving-input switch.

These samples show no severe performance collapse during representative
movement. The exterior has less headroom, and its client-interval tail exceeds
the 8.33 ms 120 Hz budget. Null-driver presentation/drop counters still cannot
prove delivered headset FPS. Keep the sustained/physical performance gate open.
Do not lower eye resolution, force a user's headset refresh rate or infer that
90 Hz physical acceptance has passed. Next address comfortable loading and
dependable pacing, with larger experience features ahead of optional variants.
Evidence remains in ignored `build/vr/steamvr-native-20261011-mirror-cinema-player-moving-scenes-{90hz-v149,120hz-v150}-20261013/`.

Focused cinema-fitting/runtime-watch behavior regressions: **54 passed in
0.43 s**. No renderer rebuild, commit, release or ordinary Steam installation
change was needed for these qualifications. All owned game/runtime processes
are closed after the experiments.

## Loading comfort: retire the outgoing world before blocking work

The original UserScene destructor at `0x004FFD4E` releases camera/assets and
later clears the active-scene global. A checked native entry/context now wraps
that boundary only when both VR render halves are enabled and the retiring
object is the current recognized scene. Native registers, flags, SEH setup,
destruction and story work are preserved. Dormant/unowned/null/unknown cases
take the unchanged original path.

`VRLoadingCompiler` calls the existing resolved renderer bridge's explicit
Blank operation before native teardown. The shared scheduler uses an already
pending frame or starts one if idle, then ends with **no world, panel, keyboard
or subtitle layers**. It never captures game pixels or submits the outgoing
pending world. The [OpenXR frame-submission specification](https://registry.khronos.org/OpenXR/specs/1.0-khr/html/xrspec.html#xrEndFrame)
requires a submission without layers to clear the display. Native old hits,
pending frame state, editor ownership and character requests are retired while
keeping ABI sizes, native editor contents and activation switches unchanged.

The new renderer passes all six native groups and full flat/OpenXR GPU and
critical-copy qualification, with its source inventory independently accepted:

- Renderer SHA-256: `14fadb4128bd93fee5f6de2fd11a7bc8b254349bf634bc10543cfd6f12131f42`.
- Player SHA-256: `cb4eb61cafe9f68290a63f2ef0f88d4db0f4da6989892e4f370001724732d32b`.
- Recipe: ignored `build/vr/loading-comfort-candidate-20261013/`.

Native scheduler tests cover idle, ready/incomplete pending worlds, hidden
frames, failed submission cleanup and later stereo recovery. Actual-GPU tests
verify zero submitted layers and no game-pixel capture, with both runtime color
formats. Python emitted-code checks preserve native forwarding and test disabled
halves, inactive/unknown scenes, unavailable bridge/device, successful/hidden/
failed clear results and rejection of changed hooks. Focused regressions:
**450 passed, 3 skipped in 17.15 s**. Full formatting/lint/strict typing/spelling
also pass.

**v151, 56.00 s**, is an unmodified current-player actual-SteamVR run through
CS2, BEC, TE4 and R25, with 2,363 moving raw head poses over 26.08 s. Every native
retirement increments both attempted and successfully cleared frame counts;
all four return success. Each scene recovers interactive stereo and native
Inventory/Back; normal Quit, verification/removal, flat files/preferences and
global runtime state pass. Loading submission gaps remain **347/261/231/256 ms**.
Do not call this an asset-loading speedup or continuous tracking/submission fix.

**v154, 36.58 s**, adds a private, bounded one-shot hold after the real clear
but before native destruction, solely to inspect the compositor. The dormant
player on disk and renderer are unchanged; the diagnostic jump is installed
in the owned suspended process and explicitly recorded. While held, outgoing
panel/world output is zero. Captures finish before the hold expires; release,
native loading, controller recovery, normal Quit and cleanup pass.

Both inspected captures contain no old GK3 world. The left is black; the right
already shows SteamVR's waiting environment and runtime controller. These are
sequential captures during an artificially prolonged stall, not proof of
simultaneous eye asymmetry or continuously black physical output. **Longer
loading-time presentation remains unfinished**: a single clear cannot keep
app frames flowing while the original game thread blocks. Preserve that as the
next comfort feature rather than claiming the waiting environment is solved.

v152 fails before resume because the private branch-encoding helper was called
with positional rather than keyword arguments. v153 obtains the compositor
images but incorrectly compares a returned tuple with a list, rejecting an
otherwise unexpired hold. Both retain failure evidence, stop the owned child,
remove private installed files, restore preferences and close the runtime.
Neither is a passing complete flow or a production loading failure.

**v155, 64.54 s**, requalifies the unmodified current pair through public
install/verify/launch, controller-typed save/change-camera/exact restore,
native SIDNEY entry/search/Exit, saved-story reload, driving-map highlights/
travel, introduction Skip, inventory/navigation and Quit-No/Yes. Exit zero,
disk verification/removal, unchanged host cursor (zero outside raw mouse events),
flat files/preferences and graceful global-preserving runtime shutdown all pass.
No inspection hold or helper bypass is active. The main reusable private scripts
now select the current qualified recipe.

All evidence stays under ignored `build/vr/steamvr-native-20261011-mirror-`
folders ending `scene-loading-clear-v151-20261013`,
`scene-loading-clear-inspection-v152/v153/v154-20261013` and
`loading-comfort-connected-v155-20261013`. No ordinary Steam installation,
commit, release or user headset session was changed.

## Continuous loading frames without moving game rendering to another thread

`LoadingFrames` adds one exclusive, temporary owner of XR frame submission
after the outgoing scene has been cleared. Its callback runs runtime event,
tracking/input sampling and empty-frame submission only. It never ticks game
simulation, calls original rendering/picking, acquires swapchain images or
delivers events to native widgets. Ordinary rendering stops and joins this
owner before using runtime state again. Device destruction joins before GPU
draining/resource teardown; worker failures are retained, reported to the
public supervisor and rethrown on handoff. The mirror's predicted-time read is
atomic, rather than racing the loading frame's updates.

The [OpenXR Vulkan concurrency requirements](https://registry.khronos.org/OpenXR/specs/1.0-khr/html/xrspec.html#vulkan-enable2-concurrency)
require synchronization of queue-accessing begin/end/acquire/release calls.
The loading path uses DXVK's submission synchronization for begin/end, but
waits for frame timing outside that queue lock. Asset uploads remain available
while the runtime throttles the helper. No game or D3D draw runs on the worker.
Normal frame scheduling and dormant flat behavior are unchanged.

The new renderer passes all native groups, flat/OpenXR GPU qualification and
critical presentation-copy checks, with its current source inventory accepted:

- Recipe: ignored `build/vr/loading-frame-pump-candidate-v2-20261013/`.
- Renderer SHA-256: `b7fc48510ec3bfaa7f217851d88148e37c15466368f1e564beff8f7bd5061a64`.
- Player SHA-256: `23f229e3919e7db00f0fb679b3ce73b3856dcd89928c8de3538055069f29198d`.

Native tests exercise exclusive ownership, joining an in-flight callback,
restart, invisible-frame accounting, sticky failure reporting and cleanup.
GPU tests observe counters only after joining, then verify continued empty
frames, no stale world/UI submission and later normal stereo recovery in both
runtime color formats. The first build fails strict native compilation on
unreachable test-lambda return statements; explicit throwing return types fix
that without suppressing warnings. That incomplete output remains unqualified.
Focused Python regressions: **450 passed, 3 skipped in 17.90 s**; full lint,
strict typing, formatting and spelling pass.

**v157, 36.31 s**, qualifies a private held native load with actual SteamVR.
Both compositor eyes are exactly RGB zero, replacing the earlier waiting-room
capture. The native hold remains active through capture. After the game's
diagnostic file handle closes, the API trace shows **64 empty frames over
0.528 s**, with a maximum observed gap of **9.96 ms**. Native loading, controller
Inventory/Back, normal Quit and cleanup all pass. This remains an explicitly
recorded one-shot inspection hold, not production delay or physical acceptance.
v156 obtained the same black-eye images but failed its workbench by trying to
read the diagnostic CSV while the game held it exclusively. Preserve that
failure; the corrected observer records interval bounds and reads after exit.

**v158, 57.66 s**, removes the hold and repeats CS2/BEC/TE4/R25 under 2,506 raw
head poses over 27.65 s. All four recover interactive stereo/Inventory/Back
and normal Quit. The game thread still blocks during asset work, so its native
page counter is not the XR submission counter. Actual API timings distinguish
the frame helper's work from native drawing:

| Scene | Empty XR frames in the observed interval | Largest actual XR gap |
| --- | ---: | ---: |
| CS2 | 32 | 45.48 ms |
| BEC | 25 | 48.91 ms |
| TE4 | 20 | 82.53 ms |
| R25 | 27 | 65.16 ms |

The earlier native blocking gaps of about 0.23–0.35 s are largely covered.
Do not call this faster asset loading, physical headset delivery, or continuous
refresh-rate-budget presentation in every transition. The remaining larger
intervals cross ordinary main-frame/modal presentation, not just the empty
loading frames. Initial Play and other loading routes, helper-active runtime
failure and hardware acceptance remain open.

**v159, 65.22 s**, requalifies the unmodified matching pair through public
install/verify/launch, controller-typed save/change-camera/exact restore,
native SIDNEY entry/search/Exit, saved-story reload, map highlights/travel,
introduction Skip, inventory/navigation and Quit-No/Yes. Exit zero, removal,
unchanged host cursor (zero raw outside input), private flat files/preferences
and graceful, global-preserving runtime shutdown pass. No hold or diagnostic
mutation is active. Reusable private scripts select the current qualified pair.

Evidence remains in ignored `build/vr/steamvr-native-20261011-mirror-` folders
ending `loading-frame-pump-inspection-v156/v157-20261013`,
`loading-frame-pump-native-v158-20261013` and
`loading-frame-pump-connected-v159-20261013`. No ordinary Steam install,
commit, release or user headset session changed. The complete VR goal and its
release acceptance remain unfinished.

### First Play joins the continuous-loading route (13 October 2026)

The first scene has no outgoing UserScene, so a destructor-only loading hook
cannot cover it. The private VR compiler now also hooks the shared UserScene
constructor at `0x004FFA43`, before it initializes assets or publishes the
active global. Both VR halves must be enabled and no scene may be active.
The hook deliberately does not dereference the incoming object's uninitialized
vtable. It preserves registers, flags and the original SEH prologue, then uses
the same checked renderer call and interaction-retirement routine as teardown.
It changes neither native construction nor ordinary flat behavior. No renderer
rebuild is needed for this player-only change.

Native behavioral tests cover both loading boundaries across all three supported
binary profiles, successful/hidden/failed renderer calls, absent device/bridge,
dormant switches, live scene ownership, unchanged objects and full register/flag
preservation. Independent verification rejects changes to either native context
or entry. Focused regressions: **483 passed, 3 skipped in 18.89 seconds**.
The loading-specific suite passes **72 tests in 1.25 seconds**, including the
expanded register-preservation checks. Full lint/typing/format/spelling passes.

**v163, 65.08 seconds**, confirms the first Play produces exactly one successful
native loading request before stereo, then completes controller text-entry/save,
camera change/exact restore, native SIDNEY entry/search/Exit, saved-story reload,
map highlights/travel, introduction skipping, inventory/navigation and Quit.
The public supervisor returns zero without errors. Flat files and preferences
remain unchanged before cleanup, uninstall succeeds, and owned SteamVR exits
gracefully with global configuration unchanged. This is actual SteamVR with
synthetic tracking/controllers, not physical-headset acceptance.

- Renderer remains `b7fc48510ec3bfaa7f217851d88148e37c15466368f1e564beff8f7bd5061a64`.
- Player is `1d349016509ff5226aea79d12fb0e24ddf6bf5eb3c32d82de122740de54c410d`.
- Evidence: ignored `build/vr/steamvr-native-20261011-mirror-initial-play-connected-v163-20261013/`.

The runtime-failure-during-loading probe remains **unqualified**. v160 mistakenly
entered an unrelated graphics-menu fallback. v161/v164 did not reach the
inspection hold while console staging ran on an observer thread. v165 moved
staging to the main thread but failed a process-memory observation before
recording the hold or performing the intended server crash. Its failed observer
also attempted cleanup after the process handle was unavailable. None of these
is evidence of a successful loading-time shutdown or identifies a production
failure cause. Their ignored evidence is retained and private cleanup restores
files/preferences and global runtime configuration. v162 similarly failed only
its test's tuple/list comparison after observing the successful initial request;
v163 fixes that assertion and completes the entire route.

These narrowly scoped experiments do not supersede connected gameplay or turn
optional variants into release prerequisites. Remaining priorities are safe
transitions, sustained moving frame pacing and a bounded first headset tryout.
No ordinary game installation, commit or release changed.

### Natural loading shutdown and a fresh moving baseline (13 October 2026)

The loading-time shutdown probe now uses a normal same-chapter room change,
not a synthetic asset-loading hold. Its observer prepares an exact, lifetime-bound
handle to the uniquely identified private null-driver SteamVR server before
staging the command. It waits for the production successful-loading counter,
observes twenty milliseconds with unchanged native render counters and retired
interaction, then deliberately stops only that server. The public launcher must
stop its owned player and report actionable restart guidance. There is no native
callback bypass, forced game state, injected renderer operation or physical device.

**v170 (29.17 seconds)** and **v171** both pass that route. v171's API trace
independently confirms **six successful empty XR submissions over 20.64 ms**:
balanced wait/begin/end, zero layers and no acquired/released swapchain images.
Ordinary flat files/preferences and global runtime configuration remain unchanged.
The terminal message explicitly says to restart SteamVR and relaunch, and that
unsaved progress cannot be recovered. Native clean Quit is not claimed for an
intentional server crash. Remaining owned runtime components shut down gracefully.

The ignored timing layer now records `xrEndFrame` results and flushes empty-frame
rows immediately, so an abruptly stopped child cannot erase this short interval
from its diagnostic buffer. It does not change runtime behavior. Its ordinary
frame rows still use the existing buffered cadence. The standalone diagnostic
summary rejects failed/incomplete XR transactions rather than counting them as
successful presentation.

Failed probes remain evidence, not production-defect claims. The original
inspection hold was installed after the primary thread resumed; it is now installed
before activation/resume. v166 improves process-memory diagnostics but still fails
before the intended crash. v167 verifies that the unheld CS2 route works normally
in 34.87 seconds. The v168 trace shows that a chapter-changing command is still
presenting its native introduction before scene retirement, while the workbench's
premature observer join causes cleanup. The revised same-chapter route reaches
the real loading boundary. v169 then fails only its prepared server-image recheck:
the prior query's output length was reused as the next buffer capacity. Resetting
that capacity before the independent recheck fixes it without relaxing ownership
validation. v170/v171 establish the actual shutdown result.

**v172 (95.28 seconds total)** starts a fresh private runtime/player after the
crash and records sixty seconds in the exterior, without compositor capture,
profiling or diagnostic draw suppression. It includes **5,726 raw head poses**,
**6,155 native controller-movement calls** and two snap turns, then normal
controller Quit, uninstall and graceful runtime shutdown. The current renderer
and player remain the `b7fc485...` / `1d349016...` pair recorded above.

| Moving exterior observation | Result |
| --- | ---: |
| Stereo submissions per second | 120.38 |
| Submission interval p99 / maximum | 10.68 / 13.98 ms |
| Outside traced XR calls p99 | 8.62 ms |
| Process-matched GPU time p99 / maximum | 8.17 / 10.74 ms |
| Runtime prediction period | approximately 11.11 ms (90 Hz) |
| Intervals over 11.11 ms | 48 of 7,222 |
| Intervals over 16.67 ms | 0 |

The virtual runtime can accept more submissions than its advertised prediction
rate. These are not 120 delivered headset frames/s. Its present/drop/reprojection
statistics are not hardware acceptance evidence either. The tails remain visible,
and 120 Hz's 8.33 ms budget is not proven. The sample establishes a sustained
moving baseline and dependable restart, not perfect pacing or physical comfort.

Ignored evidence folders end `natural-loading-worker-crash-v166/v168/v169/v170/v171-20261013`,
`native-loading-without-hold-v167-20261013` and
`current-player-moving-exterior-90hz-v172-20261013`. `loading-shutdown-timing.json`
contains the successful transaction audit. No ordinary Steam installation,
commit, release or physical-headset session changed. The full VR goal remains active.

### Earlier scene-owner boundaries and ordinary travel (13 October 2026)

Attributing the older v158 API gaps to their native/staging phases shows that
its largest 45–83 ms intervals mostly occur during console/camera staging.
Their traced XR-call costs are below roughly one millisecond, leaving the
remaining time outside those calls. This does not prove that all such pauses
are diagnostic artifacts, or that ordinary transitions are already smooth.
It prevents treating a mixed staging interval as an isolated headset wait.

The map test now brackets the actual virtual-controller destination selection
and native station arrival, with no desktop/compositor capture inside that
interval. **v175, 64.63 seconds**, completes connected gameplay and records a
0.359-second native transition with 36 successful XR frames, 28 empty. Its two
large gaps are **50.45 ms before empty frames** and **42.24 ms returning to the
world**. This establishes a production-path pause independent of console staging.

Native disassembly explains why UserScene-only hooks start late: the shared
scene owner constructs graphics/assets before allocating UserScene, and its
destructor unregisters the scene and invokes UserScene's exit callback before
calling its deleting destructor. The compiler now also guards these earlier
entries at `0x0051DF4C` / `0x0051E660`. Construction requires null scene/owner
globals and never reads the uninitialized incoming object. Retirement reads the
owner's UserScene at `+0x14`, requires it to match the active room global and a
recognized native type, then starts the existing renderer helper. Existing
UserScene boundaries remain fallbacks. Native objects, registers/flags, SEH,
simulation and dormant flat behavior are unchanged. The renderer is unchanged.

**147 loading behavioral tests** cover all four boundaries and all supported
profiles, including missing scenes, live owners, unreadable incoming objects,
disabled VR halves and changed contexts/entries. The focused suite reports
**558 passed, 3 skipped in 19.87 seconds**; full lint/typing/format/spelling passes.

**v176, 67.33 seconds**, completes the entire connected session with this player,
including initial Play, controller-typed save/exact restore, native SIDNEY,
map highlights/travel, introduction skipping, inventory/navigation and normal
Quit. Its capture-free native travel interval lasts 0.362 seconds and contains
39 successful frames, 31 empty. The pre-blank gap is **35.16 ms**, compared with
v175's 50.45 ms; returned-world is **40.36 ms**, compared with 42.24 ms. Treat this
as one matched sample, not a universal fifteen-millisecond speedup. Native asset
loading takes essentially the same total time; the helper covers more of it.

Current player SHA-256:
`931166110496a0f5545e9c82422da0a9fab8403fe48c0bc527ae80b075d96ef9`.
Renderer remains the qualified `b7fc485...` loading-frame-pump build.

**v177, 49.19 seconds**, requalifies natural movie completion, controller skipping
under moving raw head poses, both-eye cinema/world recovery and controller Quit
on this same player. Inspect both compositor movie/returned-world captures:
the movie remains on the stationary fitted screen and the room returns without
that screen or the old movie imagery remaining. The sampled movie frame is a
dark night scene; it is not a gamma/readability acceptance test. Both passing
runs leave flat files/preferences and the host cursor unchanged, uninstall,
and shut down the owned runtime gracefully with global configuration preserved.

Workbench failures are retained. v173 aborts an otherwise genuine restore when
its observer dereferences a temporarily absent camera graph. The observer now
waits for a readable, correctly typed, stable graph before demanding exact saved
coordinates. Saving also starts from a deliberate controller turn, so a default
scene reset cannot satisfy the restore check accidentally. v175/v176 restore
that non-default pose exactly. v174's abbreviated map-only staging does not open
a stable map within its bound, so it qualifies no travel; the complete connected
route supplies the successful capture-free interval. Neither failure is silently
counted as a passing game run.

Ignored evidence folders end `connected-transition-timing-v173/v175-20261013`,
`native-map-travel-timing-v174-20261013`,
`early-owner-loading-connected-v176-20261013` and
`early-owner-loading-movies-v177-20261013`. Transition summaries and all imagery
remain there. Source and ordinary-game separation is unchanged; no commit,
release or physical-headset session changed. Remaining transition/pacing and
headset acceptance gates stay open.

### Current-player puzzle progression check (13 October 2026)

**v178, 94.96 seconds**, repeats the representative native SIDNEY/shape-editing
and Virgo/Libra sequence on the early-scene-owner player `93116611...` and the
qualified `b7fc485...` renderer. It reaches the original puzzle completion and
locked-hexagram state, progresses through the original chapter sequence,
recovers inventory/stereo and finishes with controller-operated normal Quit.
The native solution report explicitly records no puzzle model or completion-flag
writes. Story prerequisites are staged from the saved fixture; this is not a
natural whole-game playthrough.

Actual SteamVR virtual controllers are used with tracked head poses. The requested
`GK3HD_VR_PUZZLE_HEAD_MOVEMENT` name was not a consumed workbench option, so this
run does **not** claim moving head poses. The reusable puzzle wrapper now selects
the current qualified renderer and the real `GK3HD_VR_SIDNEY_HEAD_MOVEMENT`
option for future runs; that script change is not retroactive evidence. Earlier
moving-puzzle evidence remains tied to its earlier cinema-sizing pair.

Exit zero, no supervisor errors, unchanged flat files/preferences before cleanup,
uninstall and graceful global-preserving runtime shutdown pass. Evidence remains
in ignored `build/vr/steamvr-native-20261011-mirror-early-owner-loading-puzzles-v178-20261013/`,
including the native solution and chapter/inventory recovery observations.
The checklist now has a concise local-versus-headset overview. No first-release
acceptance gate is checked merely because this software route passes. No ordinary
game installation, commit, release or physical-headset session changed.

### First-session priorities and moving actor-heavy gameplay

Keep connected playable capabilities ahead of isolated polish. The checklist's
next milestones now separate dependable play, transition comfort, sustained
performance and the eventual first physical-headset tryout. Routine-test speed,
optional mouse control, automatic reconnection and exhaustive puzzle variants
must not become invented prerequisites for the first enjoyable session.

The default regression suite initially exposes three stale menu-composition
expectations. Modal pages now keep fresh dialogue on their separate readable
subtitle plane rather than baking it only into the opaque page. The tests now
observe that caption surface and still reject world-tooltip leakage onto modal
or fallback pages. All **83 menu compiler tests pass in 3.10 seconds**.
The complete default suite passes **5,171 tests, 23 skipped, 402 deselected in
73.88 seconds**, and full formatting/lint/typing/spelling passes. The under-60s
routine-test target remains open; no behavioral coverage is removed to hit it.

**v181, 101.47 seconds total**, extends the current qualified pair to thirty
seconds each in the dining room and museum. Both use native controller
navigation, two snap turns, continuously moving raw head poses, 2016×2240
recommended eye targets and 120 Hz runtime prediction. No screenshot capture
occurs inside the timing intervals. The dining room records 2,864 head poses
and 3,006 native movement calls; the museum records 2,853 and 3,010.

| Scene | Stereo submissions/s | GPU p99 | Submission-interval p99 | Client-interval p99 |
| --- | ---: | ---: | ---: | ---: |
| Dining room | 121.03 | 5.92 ms | 10.63 ms | 7.61 ms |
| Museum | 121.10 | 4.48 ms | 10.55 ms | 6.22 ms |

GPU/client/API steady-state analysis excludes one second at each interval edge
and drops the observer's first historical compositor batch. The complete
thirty-second API intervals have maxima of 13.86/15.57 ms, with no gap above
16.67 ms. Outside traced XR calls, steady-state p99 is 6.93/5.70 ms.
GPU headroom does not eliminate presentation-tail risk: submission intervals
still exceed the 8.33 ms 120 Hz budget. The null driver cannot establish actual
headset scanout, reprojection or delivered FPS. Investigate pacing rather than
reduce image quality solely on the basis of these results.

Native Quit, supervised exit zero, no supervisor errors, unchanged flat
files/preferences, player uninstall and graceful runtime shutdown all pass.
Global runtime configuration is unchanged. Renderer/player hashes remain
`78efafe767ceec56abc776412a56ba9ff04cd41b5877930b512d7426c6b80b0b` /
`931166110496a0f5545e9c82422da0a9fab8403fe48c0bc527ae80b075d96ef9`.
Evidence remains in ignored
`build/vr/steamvr-native-20261011-mirror-frame-wait-queue-moving-actors-120hz-v181-20261013/`.

**v182, 95.31 seconds**, qualifies the connected native puzzle route with
continuously moving raw head tracking on that same current renderer/player
pair. Enter SIDNEY through the native computer action, confirm Virgo corners,
move/resize/rotate the hexagram, complete Libra through the original handler,
return through the native chapter sequence to inventory/stereo and cancel/
confirm Quit using actual SteamVR virtual-controller actions. The head-motion
record confirms **6,284 poses over 66.53 seconds**, with no reported errors.
Unlike the preceding v178 repeat, this invocation enables the actual
`GK3HD_VR_SIDNEY_HEAD_MOVEMENT` workbench switch; moving-head evidence is not
inferred from merely enabling tracked devices.

Native completion/locked flags are observed without puzzle model/flag writes.
Earlier story prerequisites come from a staged save, so this is not a natural
whole-game playthrough. The run is capture-free and does not establish fresh
visual or physical-headset acceptance. Supervised exit zero, no supervisor
errors, unchanged flat files/preferences, uninstall and graceful runtime
shutdown with unchanged global configuration all pass. Evidence remains in
ignored
`build/vr/steamvr-native-20261011-mirror-frame-wait-queue-moving-puzzles-v182-20261013/`.

### Preserve loading ownership across nested native callbacks

The bridge previously joined/stopped its loading helper before every panel
operation. Nested scene-owner/UserScene loading notifications therefore stopped
the helper, waited for a new main-thread blank frame and started another helper.
An empty Close finalizer also stopped coverage before a real frame needed it.
The renderer now leaves an active helper owning submission for repeated Loading
and empty Close operations. Actual world/panel rendering and explicit Blank
still join before touching the runtime, and device destruction still joins.
This changes frame ownership, not original-engine scene construction or content.

The test-only GPU runtime exposes an atomic count of waits made by its original
session-owning thread. A behavioral transport test repeats four nested Loading /
Close pairs and verifies no additional main-thread waits. Ordinary frame/pixel
counters remain observed only after a join. Against the preceding qualified
renderer the new test fails with `nested loading or empty UI finalization
interrupted the loading frame owner`; the rebuilt candidate passes. No new
diagnostic export is part of the production renderer/runtime interface.

All six native groups, both GPU color formats, critical-copy/compile-policy
qualification and the existing flat-rendering checks pass. Independent build
inspection accepts the current source inventory. Focused loading/build/launch/
runtime-watch tests pass **185 tests in 1.65 seconds**, and full lint passes.

- Recipe: ignored `build/vr/loading-ownership-candidate-20261013/`.
- Renderer: `5c39d7d8a231d9ffee9694f59605263c0f9dedb96deec8f6f3baad0f172cb20f`.
- Player remains `931166110496a0f5545e9c82422da0a9fab8403fe48c0bc527ae80b075d96ef9`.

**v183, 65.85 seconds**, passes the full connected public-command controller
save/exact restore, native SIDNEY/search/Exit, saved-story reload, map highlights/
station travel, introduction Skip, inventory/navigation and Quit flow. Native
travel still takes 0.371 seconds, with **30 empty frames out of 38 successful
frames**. The incoming/outgoing boundary gaps are **35.80/43.27 ms**, versus
the earlier same-player sample's 35.16/40.36 ms. There is **no demonstrated
boundary-latency improvement**. The regression test proves ownership continuity
across duplicate callbacks; it does not prove that those callbacks caused the
remaining measured gaps. Keep the gaps open and profile their actual native
work rather than claiming this change solves transition comfort.

**v184** abruptly stops the strictly owned private SteamVR server during natural
scene loading. The new pair submits **four successful empty frames in 20.53 ms**
while native render counters remain unchanged; no artificial loading hold is
used. The public supervisor stops its owned child with actionable runtime-restart
and unsaved-progress guidance. This is intentional runtime loss, not normal Quit
or physical headset disconnection. Both runs preserve flat files/preferences and
global runtime configuration. v183 uninstalls and closes the runtime gracefully.

Evidence remains in ignored folders ending
`loading-ownership-connected-v183-20261014` and
`loading-ownership-runtime-loss-v184-20261014`. An opt-in bounded suspension
profile now targets controller-selected travel rather than diagnostic console
loads. Such a profile is attribution evidence only, and the timing summarizer
explicitly refuses to treat it as a performance acceptance run.

**v185, 64.52 seconds**, completes a fresh connected session after the intentional
runtime crash, using that same renderer/player pair. Its opt-in travel observer
takes 25 bounded samples of the owned game thread, each resumed in a `finally`
block. The observed controller travel gaps correlate with native resource
retirement on departure
(bitmap destructor path `0x54e200 → 0x54e230 → 0x54e2d0`, reached through
`0x520ad8`), and initial native drawing/system waits on arrival. The latter's
samples include original-engine drawing chains and opaque DLL waits; they do
not by themselves identify a particular driver function or justify removing
synchronization. Stack-word candidates also contain non-address data, so use
verified call chains and disassembly rather than interpreting every candidate
as a caller.

This narrows the next investigation: check whether loading coverage can start
ahead of this resource-retirement path, and attribute first-frame draw/wait
cost before changing it. Duplicate Loading callbacks are no longer the sole
hypothesis. Suspension profiling perturbs timing and this run is not a new
frame-time/FPS acceptance sample. The profiling result is kept separate from
the untouched v183 timing baseline. Native Quit, unchanged flat files/preferences,
uninstall and graceful shutdown with unchanged global runtime state all pass.
Reusable workbench defaults now select the newly qualified loading-ownership
recipe; an explicit recipe argument remains available for future candidates.
Evidence remains in ignored
`build/vr/steamvr-native-20261011-mirror-loading-ownership-travel-profile-v185-20261014/`.

### Cover resource retirement after map ownership has already disappeared

**v186** adds verified loading counters and an actual loaded-module inventory to
the bounded transition profile. Resource release executes while completed
loading calls remain at 12; only afterward do they advance to 13/14. Arrival
samples subsequently show the private world-frame pending flag becoming set.
Module attribution distinguishes the modified renderer from Windows' native
`ddraw.dll`; raw DLL addresses alone did not establish which one was waiting.
The sampled departure really precedes the existing scene-constructor coverage.

The new `vr.scene_resource_retire` hook preserves the original five-byte native
register-save sequence at `0x00520ADE`, with its prefix/continuation independently
verified. It accepts only the live location manager reached through the original
engine/services chain, never a foreign manager. The initial candidate also
requires a live recognized scene. **v188, 64.68 seconds**, passes connected
gameplay on that candidate but retains 34.71/43.99 ms departure/return gaps.
This is not a successful latency fix.

**v187** fails earlier at the first save-keyboard Caps target. The workbench
reports a predicted keyboard-ray mismatch and stops its owned game through the
supervisor; this is not evidence of a spontaneous native game crash. Flat files
and global runtime settings remain unchanged and cleanup succeeds. The initial
candidate's final null-manager guard was added while this earlier run was active,
so its older player hash is not promoted as the current qualification pair. Later
successful samples do not establish that mismatch's cause or repair it.

**v189** directly reveals the missing guard case: during map travel, both the
room and scene-owner globals are already zero while the verified location
manager remains live. Its resource sweep is therefore rejected by the initial
scene-required guard. The corrected hook accepts that fully scene-less state,
but still rejects a partially published owner, unknown live scene types, null
or foreign managers, absent services and dormant VR. It never reads an incoming
uninitialized object. Native tests execute the original saved-register sequence,
preserve all registers/flags and manager data, and reject modified prefix,
entry, continuation and emitted payload across all supported profiles.
Focused loading/full-compiler tests pass **238 tests in 7.97 seconds**; lint passes.

**v190, 64.78 seconds**, qualifies the corrected player through public install/
verify/launch, controller save/exact restore, native SIDNEY/search/Exit,
saved-story reload, map highlights/travel, introduction Skip, inventory/navigation
and native Quit. Timing uses the same renderer, eye/mirror dimensions and
controller-selected station route, with neither captures nor thread suspension
inside its travel interval.

| Boundary | Earlier v183 | Corrected v190 |
| --- | ---: | ---: |
| Last map frame → first empty loading frame | 35.80 ms | 7.66 ms |
| Last empty loading frame → returned world | 43.27 ms | 38.37 ms |

The 0.350-second travel interval contains 39 successful frames, 31 empty. This
supports earlier departure coverage on this sampled path, not a universal gain
or physical-headset comfort claim. The remaining arrival pause is still open;
do not infer that the modest return-gap difference is a controlled improvement.
Player: `3042b8f7e05703761a60dfface9a681107aaf53b6dd790c3deda39da3f4601d9`.
Renderer remains `5c39d7d8a231d9ffee9694f59605263c0f9dedb96deec8f6f3baad0f172cb20f`.
Normal exit zero, no supervisor errors, unchanged flat files/preferences,
uninstall and graceful runtime shutdown with global configuration unchanged pass.

Evidence remains under ignored folders ending
`loading-boundary-attribution-v186-20261014`,
`early-resource-loading-connected-v187-20261014`,
`early-resource-loading-connected-v188-20261014`,
`early-resource-guard-attribution-v189-20261014` and
`scene-less-resource-loading-connected-v190-20261014`. Profiled runs remain
attribution-only and cannot be substituted for the untouched timing sample.

The final resource-guard tree also passes the complete default regression suite:
**5,225 passed, 23 skipped, 402 deselected in 78.82 seconds**, with full
format/lint/typing/spelling checks passing. The routine under-60-second target
remains unfinished and is deferred behind first-session capabilities/comfort;
required behavior coverage has not been removed.

**v191, 96.94 seconds**, also passes native SIDNEY entry, Virgo recognition,
hexagram move/resize/rotation, Libra completion, chapter/inventory recovery
and controller Quit on the final scene-less-resource-loading player. The
capture-free actual SteamVR workbench publishes **6,353 moving head poses over
67.62 seconds**. Native story completion is observed without puzzle model/flag
writes; earlier prerequisites still come from a staged save. This verifies
connected gameplay on the corrected pair, not whole-game, fresh visual or
physical-headset acceptance. Exit zero, no supervisor errors, unchanged flat
files/preferences, uninstall and graceful runtime shutdown with unchanged
global configuration pass. Evidence is retained under ignored
`build/vr/steamvr-native-20261011-mirror-scene-less-resource-moving-puzzles-v191-20261014/`.

### Attribute the remaining return-frame wait without weakening fidelity

Diagnostic relinking of the current renderer produces a symbol map with
**byte-identical executable `.text`**, verified before using its addresses.
Loaded-module inventories distinguish the modern renderer, native Windows
DirectDraw and graphics-driver DLLs. **v192, 65.39 seconds**, completes the
connected controller flow with bounded thread sampling during travel. Its
returned-world interval contains native drawing, loading-worker joining and
`DxvkDevice::waitForResource`. Instruction-validated raw return candidates
also identify `DDrawSurface::DownloadSurfaceData → D3D9Surface::LockRect →
D3D9DeviceEx::WaitForResource`. Those raw candidates are not fully unwound
call chains, so they support the readback hypothesis without identifying every
active caller or attributing the entire gap to one function.

**v193, 64.60 seconds**, temporarily replaces the owned child's verified native
cursor-bounds routine only during controller-selected station travel, restoring
its original bytes before subsequent capture/gameplay/Quit. It uses no thread
sampling in the interval. Departure/return gaps are **7.99/28.64 ms**, compared
with v190's normal-cursor **7.66/38.37 ms**. This suggests cursor/save-under
work contributes to that first return frame. It is one reversible cost-isolation
sample, not a shipped optimization, controlled steady-state FPS gain or passing
cursor-visual test. The ordinary cursor and its input semantics remain intact
in production. The timing summarizer rejects this diagnostic as normal
visual/gameplay acceptance; earlier steady-state cursor suppression showed no
meaningful throughput gain and is not contradicted by a first-frame observation.

The private timing layer now records previous-frame logging cost separately:
the interval between recorded timestamps includes that previous row's formatting/
flush time. No game/renderer code is changed to collect it. **v194, 64.49 seconds**,
repeats normal connected gameplay with no cursor suppression or thread sampling.
The return gap is **42.778 ms**, of which previous logging consumes only
**0.0169 ms**; time outside measured XR calls and that logging is **42.290 ms**.
Thus the logger is not the cause of this sampled return pause. Observing a
logger stack in a suspension profile did not establish a significant cost.

All three runs preserve flat files/preferences, exit normally, uninstall and
shut down the owned runtime gracefully with global configuration unchanged.
The player/renderer pair remains `3042b8f7...` / `5c39d7d8...`; no production
code, ordinary installation, commit or release changed. Next isolate/remove
redundant cursor/background readback while preserving visible interaction,
native background/history consumers and necessary GPU synchronization. Do not
suppress the pointer, reduce eye resolution or manufacture a performance claim.

Evidence and symbol outputs remain ignored under
`build/vr/loading-ownership-symbols-20261014/` and case folders ending
`arrival-resource-wait-attribution-v192-20261014`,
`arrival-cursor-cost-isolation-v193-20261014` and
`arrival-logger-overhead-baseline-v194-20261014`.

### Cursor image versus cursor background/history cost

**v195, 64.54 seconds**, repeats the controller-selected station transition with
only the native CursorManager Draw routine temporarily disabled in the owned
child. Its original bytes are restored before subsequent gameplay/capture/Quit;
cursor selection and controller input remain native. It uses no thread sampling
and retains the new logger-overhead measurement. Departure/return gaps are
**7.71/43.16 ms**, versus normal v194's roughly 43 ms return pause. Suppressing
the visible draw alone therefore shows no meaningful improvement here, unlike
the earlier empty-bounds/save-under diagnostic's 28.64 ms return sample.

This further implicates background/history preparation rather than the cursor
image's drawing cost. It does not justify shipping either suppression. Native
cursor composition can use its private save-under surface as a destination;
discarding that data indiscriminately risks black backgrounds and broken modal
or retained-page behavior. Any optimization must prove a completed full VR
mirror/world redraw and preserve visible cursor feedback, modal histories,
clipping, glyph opacity and original flat behavior. Prior steady-state cursor
controls still do not demonstrate an FPS gain.

The complete connected flow still reaches native Quit, exits zero, preserves
flat files/preferences, uninstalls and shuts down the private runtime gracefully
with global configuration unchanged. The program/renderer pair remains
`3042b8f7...` / `5c39d7d8...`. This is diagnostic-only evidence, not visual
acceptance or a production change. Evidence remains in ignored
`build/vr/steamvr-native-20261011-mirror-arrival-cursor-draw-isolation-v195-20261014/`.

A read-only present-device inventory finds a Pimax streaming microphone audio
endpoint, but no clearly named HMD/controller in that filtered result. That
does not establish a live headset or prove none is connected. Physical scale,
controls and display delivery remain unqualified; no device/runtime settings
were changed for this inventory check.

### Ordinary frame waits release the graphics queue (13 October 2026)

The loading helper already uses scoped Vulkan-queue callbacks around queue-accessing
XR calls, but the ordinary renderer held its submission lock throughout
`xrWaitFrame` and subsequent CPU view/input sampling. The ordinary path now
retains its protected lifecycle event handling, releases the queue before waiting,
and uses the same balanced begin/failure-cleanup callbacks. Hidden/invalid-pose
frames end under the queue lock. Successful-frame state is still owned by the
sole renderer thread, after the loading helper has been joined.

This follows the [OpenXR Vulkan concurrency rules](https://registry.khronos.org/OpenXR/specs/1.1/man/html/XR_KHR_vulkan_enable-concurrency.html):
frame waiting and view/input sampling do not access the bound Vulkan queue,
while frame begin/end and image acquisition/release require external queue
synchronization. No image, pose, input mapping or simulation changes are intended.

Native tests explicitly observe an unlocked queue during wait/view sampling and
a protected queue during begin/end. Six cases cover ordinary, hidden and invalid
poses plus wait/begin/locate failures, with balanced callbacks and exactly the
required frame cleanup. Incomplete callback pairs fail before touching the queue.
All native groups, flat/OpenXR GPU tests and critical-copy qualification pass.
Independent prototype inspection accepts the current source inventory; focused
build/launch/runtime-watch regressions pass **38 tests in 0.69 seconds**, and
full lint/typing/format/spelling passes.

- Current recipe: ignored `build/vr/frame-wait-queue-candidate-v2-20261013/`.
- Renderer: `78efafe767ceec56abc776412a56ba9ff04cd41b5877930b512d7426c6b80b0b`.
- Player remains `931166110496a0f5545e9c82422da0a9fab8403fe48c0bc527ae80b075d96ef9`.
- The first output directory fails on a stale unified-diff hunk count. Correcting
  the count and using a fresh output directory produces the accepted build.
  The incomplete first output remains unqualified.

**v179, 95.71 seconds total**, measures sixty seconds of moving-controller/raw-head
exterior play with the same 2016×2240 eye targets and advertised 90 Hz prediction
period. It submits **120.45 frames/s**, with interval **p99 10.68 ms**, maximum
**18.75 ms**, outside-traced-XR **p99 8.73 ms**, 52 intervals above 11.11 ms and
one above 16.67 ms. The earlier v172 sample was 120.38/s and p99 10.68 ms, with
a smaller maximum. There is **no demonstrated FPS or tail-latency improvement**
in these virtual-runtime samples. Keep the outlier, and do not promote queue
availability into a hardware performance claim. The earlier sample also used
the preceding player, so this is not an identical-player controlled A/B result.

**v180, 65.26 seconds**, completes connected controller save/exact restore,
native SIDNEY, saved-story reload, map highlights/travel, introduction Skip,
inventory/navigation and normal Quit on the new pair. Both runs preserve flat
files/preferences, uninstall and shut down the owned runtime gracefully with
global configuration unchanged. Reusable workbench defaults now select this
qualified recipe, without accepting mismatched earlier renderer inventories.

Evidence is retained under ignored folders ending
`frame-wait-queue-moving-exterior-90hz-v179-20261013` and
`frame-wait-queue-connected-v180-20261013`. The queue change removes a verified
unnecessary scheduling restriction; solving the remaining performance/transition
tails and qualifying physical-headset behavior remain separate work. No ordinary
game installation, commit, release or physical-headset session changed.

### First-session priorities and current movie qualification (14 October 2026)

Work remains directed at one enjoyable seated session, not completion of every
possible screen variant. Stereo, controller navigation and interaction, floating
interfaces, keyboard entry, save/restore, SIDNEY, map travel and movies already
have connected implementation evidence. The remaining critical path is dependable
play, comfort during transitions and sustained moving performance, then physical
scale/controls/readability/pacing acceptance. Cursor micro-optimizations, optional
mouse modes and routine-test timing must not displace that path.

**v202, 48.75 seconds**, qualifies movie playback on the current player
`3042b8f7...` and renderer `5c39d7d8...`, rather than relying on the preceding
renderer's movie sample. Native `day2-2.bik` completes naturally with 1,479 XR
frames; `205PEND.BIK` is skipped through the virtual controller with 112 XR
frames. Both recover stereo. The test delivers 1,789 moving raw head poses over
18.80 seconds. Controller Quit cancellation/resumed stereo/confirmation exits
zero, with unchanged host cursor, flat files and display preferences. Installation
removal succeeds; owned SteamVR components shut down gracefully and global runtime
configuration is unchanged. No physical headset, movie audio/synchronization or
new compositor image-fidelity acceptance is implied. Evidence remains ignored
under `build/vr/steamvr-native-20261011-mirror-current-pair-moving-movies-v202-20261014/`.

A separate current-pair dormant/uninstall/flat-control workbench remains
**unqualified**. v197 passes dormant Play/inventory/Quit cancellation/confirmation
with every VR switch zero and removes every owned player file, but ordinary
post-uninstall launch uses the sandbox's protected Steam source and produces no
visible game window. Later title/input checks fail intermittently. v200 captures
native title controls already instantiated while the presentation still shows
startup artwork, so native control existence alone is not sufficient desktop
input readiness. A proposed visible-controls gate also times out on the Sierra
startup image in v203. The cause is not established, and these failures must not
be counted as fixed or as physical-controller regressions. v196 and v198–v203
use owned-child cleanup rather than normal Quit. Flat files/saves stay unchanged;
native flat preferences are snapshot/restored because dormant mode intentionally
retains ordinary registry writes. The v197 whole-directory comparison differs
only after ordinary launch creates a runtime log, so subsequent immutable-file
checks exclude generated `.log`/`.crash` files. No ordinary Steam installation is
modified. Bounded failing evidence remains in ignored `build/vr/dormant-current-flat-*`.

**v204, 101.88 seconds**, measures the current pair in two thirty-second moving
actor-heavy scenes without compositor screenshot capture. Eye targets remain
2016×2240 with a 1280×800 independent mirror. DIN and MS3 submit **121.43/120.87
stereo frames/s**. API submission-interval p99 is **10.51/10.54 ms**, with maxima
**14.40/16.69 ms**. The steady-state compositor analysis excludes one second at
each scene boundary and its first historical timing batch, matches the app PID,
and records GPU p99 **5.56/4.75 ms**. Median outside-OpenXR work is **4.37/3.46 ms**.
This is a new current-pair baseline, not evidence that a production optimization
improved performance. About 47% of API intervals exceed the advertised 8.33 ms
period, often narrowly; synthetic scanout counters cannot establish actual dropped
frames or delivered headset FPS. Keep the 16.69 ms museum outlier and the 120 Hz
acceptance gate open.

Controller native Quit exits zero; flat files/preferences remain unchanged,
uninstall succeeds and the owned runtime shuts down gracefully with no global
configuration change. Raw timings, PID-matched compositor observations and
summary remain ignored under
`build/vr/steamvr-native-20261011-mirror-current-pair-moving-actor-rooms-v204-20261014/`.

**v205, 28.92 seconds**, requalifies supervised runtime loss at a natural loading
boundary on the current pair. Independent API timing verifies three successful
empty XR frames over **20.18 ms**, with one wait/begin/end per frame, no image
acquire/release and unchanged native render counters. No private game-thread hold
is used. After deliberate termination of only the private test SteamVR server,
the public launcher stops its owned player and reports restart/unsaved-progress
guidance in **1.85 seconds**. This intentional failure is not native Quit or
graceful server exit. Remaining owned runtime components close without forced
cleanup, uninstall succeeds, and flat files/preferences/global runtime settings
are preserved.

One prior staging capture reports `could not resolve captured GK3 client bounds`;
it remains in the record. The independently verified later natural-loading
boundary and expected supervisor failure pass, but this is not a clean image
capture run or physical-headset disconnection/reconnection qualification. Evidence
remains ignored under
`build/vr/steamvr-native-20261011-mirror-current-pair-runtime-loss-loading-v205-20261014/`.

### Current-pair dormant/flat play and input ownership (14 October 2026)

**v211, 33.27 seconds**, closes the current-pair local dormant/removal/flat-play
milestone. The installed player `3042b8f7...` uses renderer `5c39d7d8...` with
XR disabled and all activation switches zero. Native Play, inventory, inventory
closure, Quit cancellation and Quit confirmation pass with exit zero. Uninstall
removes every owned VR file and preserves the original flat files and saves.
The recommended normal patch set compiled from the sandbox's protected Steam
source, paired with the current renderer in non-XR mode, then passes the same
flow and exits zero. Test-only flat executable/renderer changes are restored
exactly, and the final hashes/saves match the initial sandbox. Native flat
preferences are snapshot/restored because their normal registry writes remain
enabled. This does not qualify physical-headset behavior or arbitrary older
renderer versions. The ordinary Steam installation remains untouched.

The title/input failures had a demonstrated workbench component: v206–v208
observe Steam's process owning the foreground while `SetForegroundWindow`
returns false. Attaching the observer input queue does not grant focus, and the
test now aborts before sending keys/buttons to a foreign application. v209's
caption activation also aborts because another application occludes the target.
v210/v211 temporarily bring only the owned game window above it, validate the
caption hit's process identity, activate through that caption, and remove the
temporary topmost status. Native controls existing before a usable captured
title are no longer accepted as sufficient click readiness. This uses neither
Alt/Esc sent to Steam nor a machine-wide foreground-lock setting. These are
workbench changes, not production game or VR-input fixes. The observed Windows
behavior is consistent with Microsoft's documented
[foreground restrictions](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow).

v210 independently passes dormant play/removal but its normal control uses the
older sandbox renderer `7c052525...` and produces a black captured title. v211
passes with the current renderer. That difference is recorded, not an RCA or
claim that the older renderer is broken/fixed. Earlier failed captures/cleanup
remain unqualified; only v211 is a complete passing current-pair gate. Evidence
stays ignored under `build/vr/dormant-current-flat-v206-20261014/` through
`build/vr/dormant-current-flat-v211-20261014/`.

### Current first-room comfort and coherent keyboard aiming (14 October 2026)

**v212, 33.33 seconds**, qualifies native wall protection on the current pair
through actual SteamVR with raw virtual head tracking. In the first hotel room,
the sampled rear obstacle starts withdrawing world interaction between
**0.453125 and 0.46875 meters** of head displacement. At the sampled 0.76875-meter
crossing, both full compositor eye images contain **zero pixels above RGB 8**.
The authored camera remains unchanged and the tracked eyes remain unclamped;
this is a visual protection fade, not artificial head-motion blocking or
room-scale navigation collision. Holding Select while protected opens no native
menu, and retreat does not replay that held selection. Release re-arms normal
interaction. Both neutral and returned eyes were visually inspected, with the
scene and aiming beam recovered and no obvious sampled stale-world residue.
Physical fade comfort, thin/transparent surfaces and broader geometry still need
separate acceptance.

Native controller Quit exits zero; flat files/preferences and the host pointer
stay unchanged. Uninstall and graceful private-runtime shutdown pass without
global configuration changes. Raw eye BMPs, unchanged originals and smaller
inspection JPEGs remain ignored under
`build/vr/steamvr-native-20261011-mirror-current-pair-wall-comfort-v212-20261014/`.

The private keyboard-aiming workbench now samples a stable, completed parent
packet using repeated reads and the panel submission counter. It judges the
delivered ray against the **current** keyboard geometry, not the parent pose
captured before controller publication. Only an observed change in parent plane
or predicted aim orientation permits bounded physical re-aiming. A stable
incorrect ray remains an immediate failure; no native hit state, key callbacks
or puzzle state is manufactured. Every attempt records initial/final parent
packets and the delivered pixel ray. Ten fast behavior checks cover both hands,
center/edge targets, moving-plane recovery and stable-mismatch rejection in
0.69 seconds. This is ignored workbench code, not a production input change.

**v213, 66.43 seconds**, then repeats the connected public-command controller
save/exact restore, native SIDNEY entry/search/Exit, saved-story reload, map
highlights/travel, introduction Skip, inventory, navigation and Quit flow. All
**25 keyboard aims** pass without needing a geometry correction. The player and
renderer remain `3042b8f7...` / `5c39d7d8...`. Native Quit exits zero; the host
pointer, flat files/preferences and global runtime configuration remain unchanged;
uninstall and graceful owned-runtime shutdown pass. This does not establish the
cause of v187's earlier keyboard miss or physical-headset acceptance. Evidence
remains ignored under
`build/vr/steamvr-native-20261011-mirror-current-pair-keyboard-snapshot-connected-v213-20261014/`.

### Direct copy attribution rejects the current cursor-bypass hypothesis

**14 October 2026.** A private in-memory tracer separately measures two native
CursorPlatform background capture/restore callsites and two software text/effect
capture/restore callsites. It is installed before the owned child resumes, enabled
only during controller-selected station travel, and absent from disk artifacts
and production sources. Its entry wrappers tail into the original target so the
native return address remains unchanged. Its post-call wrappers replay exact
stolen instructions. That caller identity matters to GK3HD's blit classification;
an ordinary CALL-through timing wrapper would change behavior. Thirty-two
emitted-code checks compare native/traced arguments, stack cleanup, caller
identity, GPRs, flags and caller memory, including readable/unreadable geometry
and both enabled/dormant tracing. They pass in 0.50 seconds.

The workbench also now validates ownership of the foreground window before native
console staging, with caption-only activation of its owned window if necessary.
It retains the existing minimize/restore input refresh and records the focus
result. Map staging uses that bounded native console route and window-specific
capture. None of this changes production input or counts as controller gameplay;
staging remains outside the measured travel interval.

- **v214, 42.83 seconds:** fails before measurement while opening the map through
  the older staging path. Its exit code one is test-owned cleanup after an
  observation failure, not evidence of a spontaneous game crash.
- **v215, 28.60 seconds:** verified caption focus alone does not open the staging
  console after removing its input refresh. No copy-cost measurements are obtained.
- **v216, 38.13 seconds:** restoring that workbench input refresh permits the
  complete map/travel/Quit flow. Sixteen timed copy calls all complete, with
  coarse native millisecond readings of 0–1 ticks. No text/effect copy is observed
  at these two instrumented callsites during this span. This is attribution,
  not an unmodified performance benchmark.
- **v217, 38.11 seconds:** adds high-resolution QueryPerformanceCounter timing
  without changing clock resolution or GPU synchronization. All seventeen
  instrumented calls execute on the primary game thread. Nine cursor capture
  spans average **0.0554 ms**, maximum **0.4814 ms**; eight restore spans average
  **0.0091 ms**, maximum **0.0120 ms**. Spans include trace bookkeeping. The
  software text/effect callsites are again unobserved, not proven zero-cost.
  The return-to-world API gap is still **29.97 ms**.
- **v218, 37.95 seconds:** a matched control uses the same staging and timing
  layer but the unmodified player in memory. It passes map highlights, native
  controller travel and Quit. The return gap is **29.28 ms**, with **28.75 ms**
  outside traced XR calls and logger cost. Travel covers 39 successful XR frames,
  31 empty, in 0.342 seconds. This is a sampled control, not a production
  optimization or a controlled improvement over earlier differently staged runs.

The earlier empty-cursor-bounds isolation therefore does **not** justify removing
the timed copy paths. They are too cheap to explain the matched pause. Other
native resource work or readbacks remain possible, but raw stack return candidates
are not proof that the software-effect copies ran during the expensive interval.
Next attribute the broader native-world/resource-preparation span rather than
shipping a cursor/background bypass or treating experiment variability as a gain.
The ordinary travel summarizer now rejects copy-instrumented runs as benchmarks;
a separate reproducible copy summary keeps their attribution status explicit.

v214/v215 recover only their owned child/installation after the failed observation.
v216–v218 reach normal native Quit. All preserve flat files/preferences, remove
owned installation files and shut down the private runtime gracefully with global
configuration unchanged. The verified disk player/renderer remain `3042b8f7...` /
`5c39d7d8...`; v216/v217 have explicitly modified diagnostic memory and are not
unmodified-player qualification. No normal Steam installation, commit or release
changes. Evidence and reproducible diagnostic helpers remain ignored under
`build/vr/`, in case folders ending `native-copy-cost-attribution-v214-20261014`,
`native-copy-cost-attribution-focused-v215-20261014`,
`native-copy-cost-attribution-focus-reset-v216-20261014`,
`native-copy-precise-cost-v217-20261014` and
`native-copy-matched-unmodified-control-v218-20261014`.

### Scene-resource preparation before joining the stereo frame

**14 October 2026.** This addresses comfort-critical loading, not an optional
cursor optimization. The private tracer now measures page preparation, the
stereo bridge and each native eye draw, preserving direct/indirect caller return
identities. Fifty-six emitted-code tracer checks pass. Diagnostic timing is
kept separate from unmodified-in-memory qualification.

- **v219, 39.35 seconds:** the first bridge costs 26.74 ms, of which the first
  native eye costs 19.76 ms and the second 0.79 ms. Page preparation is about
  0.0001 ms. Later native eyes cost under 1 ms. The return submission gap is
  30.45 ms. This narrows the expensive scope without proving a particular GPU
  wait or shader compiler responsible.
- **v220:** one suspension sample reaches native image/texture preparation and
  surface unlocking inside the first-eye callback. The symbolized renderer
  text matches the qualified DLL. The eye-active probe precedes suspension,
  and the reconstructed stack is not an authoritative full unwind. This is
  supporting attribution, not a frame-time benchmark.
- **v221, 38.05 seconds:** experimental native draw-only preparation before
  joining the XR frame reduces the diagnostic maximum travel gap to 14.91 ms.
  It does not tick simulation or present another game frame. The existing
  loading worker retains responsibility for head-tracked empty frames.
- **v222, 78.53 seconds:** that first candidate stalls at Save entry. The test
  fails and cleans up its owned child. This is not successful connected-play
  qualification. A passing map-only timing result is insufficient to adopt it.
- Safety tests additionally expose projection nesting left behind when native
  preparation is interrupted. The revised candidate snapshots native projection
  globals and restores them on both ordinary return and escaping unwind, before
  either eye can inherit them. Resource retirement invalidates its owner even
  when the next scene reuses the allocation. The warm count is history, not an
  ownership substitute. **405 focused scene/loading/composition checks pass in
  10.92 seconds**, with lint, formatting and typing checks passing. These cover
  disabled/missing bridges, once-per-owner behavior, five native retirement
  boundaries and exception search/unwind state restoration.
- **v223, 68.10 seconds:** matched current-player control passes connected
  controller save/restore, SIDNEY, map travel, navigation and Quit. Its
  return-to-world submission gap is **28.78 ms**.
- **v224, 66.52 seconds:** the revised state-scoped candidate passes the same
  connected flow under synthetic tracking, without suspension or in-memory
  timing hooks. The return gap is **11.10 ms**. A later world-to-world gap still
  reaches 14.70 ms, so this does not qualify 120 Hz delivery. Total load duration
  is similar: the improvement is maintaining XR submissions during resource
  work, not making the assets themselves load three times faster.
- **v225, 44.91 seconds:** repeat map/controller-travel/Quit with compositor
  captures passes, with an **11.66 ms** return gap. Both settled station eyes
  and the map hover/tooltip are inspected. The first arrival left/right mirror
  files differ in fade brightness, whereas settled eyes match. These sequential
  captures are not a same-frame stereo pair and cannot qualify transient stereo
  brightness coherence. Keep that limitation explicit rather than treating them
  as proof of either an eye defect or a perfect transition.

- **v226, 53.50 seconds:** the same revised player completes natural movie
  playback, controller skipping, continuously moving raw head poses, stereo
  recovery and normal Quit. It preserves ordinary files/preferences, uninstalls
  and shuts down the private runtime gracefully. These checks support adopting
  resource preparation in the development VR compiler, not declaring the first
  release ready.

The revised preparation is now enabled in the development VR compiler. Its
verified player SHA is `830c5f5c7cd740062b043e9a1bfbc987824a2d9af1da6aac700df3668b4d690c`;
the renderer remains `5c39d7d8a231d9ffee9694f59605263c0f9dedb96deec8f6f3baad0f172cb20f`.
Both successful variants preserve flat files/preferences, uninstall cleanly and
shut down the private runtime gracefully. The normal Steam installation is not
modified. All raw experiments and helpers stay ignored under `build/vr/`.
No physical headset comfort or delivered performance acceptance is claimed.
The broader focused Python verification now passes **585 tests, 3 skipped, in
19.92 seconds**, with lint, formatting and typing checks passing.

**v227, 83.62 seconds**, then exercises the newly enabled public compiler without
the experimental environment override. It reproduces player `830c5f5c...` and
passes twenty seconds each of moving-head/controller navigation in actor-heavy
DIN and MS3, plus native Quit, uninstall and graceful runtime shutdown. Stereo
submission rates are **121.40/120.65 per second**. Interval p99 is
**10.56/10.68 ms**, maximum **13.41/15.92 ms**, consistent with the earlier pair's
short samples. This supports no observed steady-state regression in these
samples, not a guaranteed performance equivalence or physical 120 Hz delivery.
The next performance work is pacing/transition coherence, not lowering texture
quality or revisiting the already cheap cursor-copy paths.

### Same-transaction native fade verification and current-player puzzle coverage

**14 October 2026.** A private entry tracer verifies the actual renderer receives
the same fade for both eyes. It checks exact renderer text against the diagnostic
symbol relink, uniquely identifies the loaded renderer rather than the system
DirectDraw forwarding module, verifies the live prologue, and rewrites only the
owned player's memory under a bounded primary-thread suspension. It refuses to
rewrite an instruction beneath the current IP. The trampoline preserves the
native thiscall arguments/return identity, stack, GPRs and flags, records float
bits without FP/SSE operations, and replays the exact prologue. **36 emitted-code
contract checks pass in 0.43 seconds**, including both eyes, black/fractional/full
gain, saturation and differing native flags. The hook is removed before normal
gameplay resumes. This is ignored workbench code, not a shipped tracing path.

- **v228/v229:** fail before hook installation, first because map-file matching
  also matched non-entry text, then because the process legitimately has both
  system and private DirectDraw modules. Both recover their owned installation
  and runtime. They are failed diagnostic setup, not passing transitions or
  spontaneous game crashes.
- **v230, 38.67 seconds:** actual SteamVR controller map hover/travel/normal Quit
  passes. All **26 complete stereo transactions** have bit-identical left/right
  gains and the same native frame/device/pending ownership. Twenty-four pairs
  have fractional gain, progressing monotonically from opaque black to fully
  visible. No partial boundary rows, capacity overflow or foreign-thread writes
  occur. The original entry bytes are restored. Coupled with the existing real
  Vulkan GPU fade tests, this supports native stereo fade coherence. It does not
  prove compositor scanout synchronization or physical comfort, and the timing
  summarizer rejects this instrumented run as a benchmark.
- **v231, 94.40 seconds:** the current public compiler/player completes the native
  SIDNEY Virgo/Libra puzzle and chapter/inventory/Quit recovery flow with moving
  raw head poses and tracked synthetic controllers. This updates the earlier
  player variant's puzzle evidence without forcing completion callbacks or
  manufacturing puzzle state.

Both successful runs use player `830c5f5c...` and renderer `5c39d7d8...`, preserve
ordinary game files/preferences, uninstall and shut down the private runtime
gracefully. The normal Steam installation, commits and releases are untouched.
Raw traces and qualification artifacts remain ignored under `build/vr/`.

**v232, 109.74 seconds:** the same current public compiler/player passes twenty
seconds each of moving-head/controller navigation in CS2:212p, BEC:312p and
TE4:309p, followed by native Quit and clean removal/runtime shutdown. This adds
mid/late-game rendering and transition coverage rather than repeating menu
variants. Steady-state analysis excludes one second at each interval edge and
matches the compositor's application PID. Results:

| Scene | Stereo submissions/sec | GPU p99 | Submission interval p99 | Maximum interval |
| --- | ---: | ---: | ---: | ---: |
| CS2 | 121.50 | 6.39 ms | 10.49 ms | 12.94 ms |
| BEC | 121.95 | 3.72 ms | 10.60 ms | 12.72 ms |
| TE4 | 121.19 | 4.81 ms | 10.50 ms | 15.62 ms |

Five sampled early/mid/late moving scenes now have current-player evidence.
This is not an exhaustive story playthrough. The null-driver compositor still
does not prove physical scanout or delivered headset FPS. Its presentation/drop
counters must not be interpreted as a supported headset's measured loss rate.
The GPU generally has headroom, but submission tails and real-headset delivery
remain separate performance gates. Image quality has not been reduced.

### Predicted-display correlation and explicit rendering-failure supervision

**14 October 2026.** The private timing layer can opt into
[`XR_KHR_win32_convert_performance_counter_time`](https://registry.khronos.org/OpenXR/specs/1.1/man/html/xrConvertTimeToWin32PerformanceCounterKHR.html)
to convert the runtime's predicted display time to the same Windows performance
counter used for CPU timing. It requests the extension only for this diagnostic
instance and only if supported, preserves existing extension names, avoids
duplicates and records unavailable/failed conversions rather than fabricated
lead time. Eleven native clock-policy/conversion checks pass. The production
renderer and player bytes are unchanged by the probe.

**v233, 81.78 seconds**, passes moving DIN/CS2 samples and ordinary Quit/removal.
After excluding one second at each interval edge, all 2,202 dining-room CPU
submissions return before predicted display time, with median/minimum lead
**6.85/0.77 ms**. The château has **2 late returns out of 2,187**, median lead
**6.48 ms**. One was already about 1.76 ms late on estimated `xrEndFrame` entry;
the other crossed predicted time during that call. The estimate adds the measured
single end-call duration to return lead. This does not establish GPU readiness,
compositor scheduling deadlines or physical presentation, and must not turn the
null driver's drop counters into a claimed headset loss rate. About 47% of uneven
submission intervals exceeding the nominal period did **not** mean 47% late CPU
submissions. Preserve this distinction when choosing performance changes.

Review also exposes a real supervision gap: an explicit failed scene/interface
adapter can disable itself and fall back to ordinary drawing while the launcher
only watches runtime/session log errors. The renderer's logger buffers its file
stream, so adding more log markers alone is insufficient. The launcher now:

- Recognizes the existing explicit error-level world, panel, frame and native
  interface failure diagnostics, without treating info/warnings as terminal.
- Reads the independently verified native world/interface activation and result
  slots. A disabled adapter plus a failing HRESULT establishes failure without
  depending on a flushed log. An active adapter, successful/hidden result or
  ordinary native loading does not. Process-exit races remain safely handled.
- Stops only its owned child and gives relaunch, unsaved-progress and diagnostic
  log guidance. No new frame-stall timeout, renderer binary change or runtime
  process termination is introduced.

**v234, 30.01 seconds:** the first real fault experiment confirms the log-only
check does not stop the player within its five-second observation bound. The
test then cleans up its owned player; this is a failed supervision qualification.
No fault message was manufactured. The injected private draw callback returns
E_FAIL through the real scene bridge.

**v235, 27.67 seconds:** direct native-status supervision catches the same fault
after 391 successful stereo frames, stops the owned player in **0.152 seconds**
and reports world rendering disabled with `0x80004005` plus relaunch/unsaved-progress
guidance. The real renderer log is still buffered. The private runtime remains
alive until normal workbench shutdown. Flat files/preferences and global runtime
configuration remain unchanged; removal and graceful runtime shutdown pass.
This is expected fault recovery, not native Quit qualification.

All **246 VR Python tests pass, 3 skipped, in 13.92 seconds**, including error-level
diagnostics, disabled world/interface/completion failures, nonfatal hidden or
in-progress states, and existing runtime/process ownership guards. Lint and typing
checks pass. Raw probes and diagnostic binaries remain ignored under `build/vr/`.

**v236, 65.55 seconds:** the current public launcher, with direct rendering-status
supervision enabled and without fault injection, passes the connected controller
save/exact restore → native SIDNEY → saved-story reload → map travel → inventory/
navigation → Quit cancellation/confirmation flow. No false rendering failure is
reported during ordinary loading, modal ownership or native Quit. The player and
renderer hashes remain `830c5f5c...` / `5c39d7d8...`; only launcher supervision
changes. Flat files/preferences are unchanged, owned installation removal passes,
and runtime shutdown is graceful with no forced components. This verifies the
new delivery safeguard alongside the first-session capabilities, not physical
headset acceptance or a release claim.

### Current controller inspection/exit recovery

**v237, 38.73 seconds, 14 October 2026:** the current player/renderer and new
failure-status supervisor pass native museum-panel inspection and binocular
entry/exit. The workbench uses the native console only to stage each interface;
all exit actions use tracked synthetic controllers. Closeup uses native Back.
Binoculars do not bind Escape in the original game, so the controller selects
their actual Exit button instead of forcing layer removal or changing story
semantics. Both routes recover stereo. The host mouse remains unchanged during
controller interaction, and ordinary game files/preferences are preserved.
Native Quit cancellation/confirmation, removal and graceful runtime shutdown
pass. Captured closeup/binocular panels and both returned stereo eyes are
inspected. This is local controller/presentation evidence, not physical headset
readability or a complete binocular puzzle qualification. Evidence remains
ignored under `build/vr/` with the same `830c5f5c...` / `5c39d7d8...` pair.

**v238, 31.62 seconds:** a stronger navigation-recovery check fails because the
workbench sends forward movement to the right stick. This contradicts the
implemented controls: left stick translates, right stick snap-turns. No
production movement defect is established, and the owned test is cleaned up.

**v239, 36.95 seconds:** using the actual left-stick mapping passes both interfaces,
native exit-action completion, fresh controller navigation after return, stereo
recovery and native Quit. No fixed action-delay sleeps or forced script/UI state
are introduced; checks advance when the native state becomes ready. Flat files/
preferences, removal and graceful runtime shutdown pass. This strengthens
v237's viewing/exit evidence without changing the renderer or player.

### Teardown-safe status monitoring and two-session restart

**v240, 29.15 seconds, 14 October 2026:** the first restart attempt reaches normal
controller Quit, but the supervisor's new render-status sampler hits an unreadable
memory snapshot before the process signals exit. Raising that read error aborts
the launcher; the workbench's borrowed process view then observes closed handles
and its original cleanup is interrupted. This is not a successful Quit/restart
qualification. The isolated player is explicitly uninstalled afterward. Retained
preference/flat-file snapshots are verified unchanged; recovery reports no saved
preference values needing restoration and retains unknown newer registry values.

The production sampler now treats an unreadable snapshot as unknown rather than
a terminal renderer diagnosis. Confirmed disabled adapters with a failing result
still stop the owned player. Runtime/server supervision, error-log checks and
startup requirements remain in effect. No new timeout or assumption that a slow
frame is failure is added. A regression verifies that unreadable status while
the process remains unsignaled does not manufacture a rendering failure.

**v241, 63.29 seconds:** two successive current-player sessions reuse the same
private SteamVR runtime. Each passes the public build/install/verify/launch flow,
raw-runtime head transforms, tracking loss/recovery, upright recentering, native
controller Quit cancellation/confirmation and clean removal. Sessions take
**31.62/31.67 seconds**; both exit zero with no supervisor error, preserve ordinary
files/preferences and reproduce player `830c5f5c...`. The outer runtime shuts down
gracefully with no forced components. This verifies a runtime-persistent restart,
not reuse of a still-installed player, physical controllers or real-headset
reconnection. Those distinctions remain explicit.

All **247 VR Python tests pass, 3 skipped, in 13.75 seconds**, with focused lint and
typing checks passing. The normal Steam installation, commits and releases remain
unchanged. Raw restart/inspection/recovery evidence stays ignored in `build/vr/`.

### Larger runtime-recommended eye targets

**14 October 2026.** The first-release audit identifies a useful coverage gap:
the public renderer consumes each runtime's recommended eye dimensions, but
recent actual-runtime samples mostly used 2016×2240. The ignored pacing helper
now accepts an explicit diagnostic eye size and an optional single capture label.
The shipped renderer/player policy remains unchanged: no desktop-size cap or
legacy-resolution compatibility path is substituted for the headset's target.

- **v242:** requested 3840×4320 exceeds the existing private workbench's 4096
  dimension bound and is rejected before runtime/game startup. This is a
  diagnostic-fixture limit, not a measured renderer or headset incompatibility.
- **v243, 55.19 seconds:** a moving-head/controller actor-heavy DIN sample uses
  **4096×4096 per eye**, with the desktop/interface canvas still **1280×800**.
  It sustains **122.40 stereo submissions/sec** for twenty seconds. GPU p99 is
  **6.23 ms**, maximum **9.10 ms**; compositor client-interval p99 is **7.28 ms**.
  Submission interval p99/maximum is **10.75/14.54 ms**. One of 2,200 steady-state
  CPU submissions returns after predicted display time, by **0.31 ms**. This
  does not establish a physical 120 Hz delivery or GPU/compositor deadline rate.
- **v244, 46.32 seconds:** a separate stable-head 4096-square run captures the
  DIN world before its ten-second pacing interval. Both compositor eyes are
  inspected: full geometry, actors, textures and aiming beam fill the view,
  without an undersized/clipped world image masquerading as good performance.
  Runtime mirror files are 5368×5368, distinct from the verified 4096-square
  engine eyes. Sequential mirrors still do not prove same-frame scanout.

Both successful cases pass controller Quit, clean removal and graceful runtime
shutdown, preserve flat files/preferences and retain player `830c5f5c...` /
renderer `5c39d7d8...`. The larger workload is not an Index, Crystal or Beyond
qualification and does not reduce their rendering quality. Raw captures and
reproducible helpers remain ignored under `build/vr/`. No normal Steam game,
commit or release changes.

## 14 October: first registered physical-runtime session checks

These are bounded, unworn hardware-path diagnostics, not a headset playthrough.
The current renderer/player remain `5c39d7d8...` / `830c5f5c...`, unchanged.
Private cases and captures remain under the ignored `build/vr/` workbench.

- **v245:** the registered Pimax driver cannot create its vendor session while
  the installed vendor server is absent. Starting the already-installed vendor
  server permits discovery in **v246**, initially recommending 4312×5100 per
  eye. No firmware, display mode, system OpenXR selection or driver replacement
  is performed. The first discovery cleanup requires a subsequent owned-runtime
  close after Steam launches an additional monitor; later cases close gracefully.
- **v247:** refuses to start over that still-running test runtime. It does not
  kill or silently reuse it. After the owned session is closed, **v248** creates
  a real RTX 4090 Vulkan session/swapchains and submits one frame, but SteamVR
  launches Room Setup and replaces its scene. This is a private calibration
  omission, not a graphics failure. **v249** reuses a read-only copy of the
  existing room calibration and completes all 180 requested frames.
- **v250:** the actual game reaches 129 stereo frames, but the diagnostic's
  fixed startup deadline expires before its required three-second world sample.
  Its consequent forced test cancellation is not a spontaneous game failure.
  **v251** gives physical startup a bounded forty-second allowance and completes
  the full test in **62.49 seconds**, including public install/verify/launch,
  Play, real stereo, a twelve-second performance sample, compositor captures,
  minimized/resumed presentation, native Quit-No/Yes and uninstall. Flat files,
  native preferences, global SteamVR settings and original calibration are
  preserved; SteamVR closes gracefully with no forced components.
- Runtime recommendations can change during startup's automatic GPU calibration.
  The actual game eye target in v251 is **5028×5948**, independent of its
  **1280×800** mirror/interface canvas. The sampled game submits **59.91 stereo
  frames/sec**. Matching compositor data has GPU p99 **6.31 ms**, maximum
  **8.09 ms**, and zero counted dropped/reprojected frames during that interval.
  The OpenXR predicted period is approximately **16.67 ms**, not the physical
  display's 8.33 ms. This does not establish 120 Hz delivered game frames or
  explain the runtime's half-rate policy.
- **v252:** an independent clear-only Vulkan session completes 1,200 frames
  at **118.54 submissions/sec**. Its compositor mirror has the same large gray
  region as the game. **v253** disables `panelMask` only in private settings;
  that does not remove the gray region, so it is not adopted as a fix.
- **v254:** a read-only physical pose/mesh observation reports connected HMD,
  invalid pose, tracking result **201 (Running_OutOfRange)** and activity **0**.
  The standard hidden-area mesh covers **3.49%**, with an inverse mesh of
  **96.51%**. It is not a malformed GK3HD world or a huge hidden-area mesh.
- **v255:** setting `forceFadeOnBadTracking=false` only for an unworn private
  clear-only control removes the uniform gray region. The runtime background
  also becomes visible, so this is not a fidelity acceptance image. The causal
  control identifies SteamVR's bad-tracking fade, not a new game/menu defect.
  The ordinary safeguard stays enabled, and this diagnostic setting is not
  written globally or distributed. All later probes preserve global settings
  and close gracefully.

The next first-session priorities are valid physical tracking and measured
actual-game pacing, then a short comfort/aiming/readability tryout. No requirement
to exhaustively replay every interface or puzzle is added. Physical-controller
acceptance, worn-headset fidelity/comfort and release readiness remain open.
The vendor server and vendor Home process started for these checks are stopped
afterward; pre-existing platform services are left alone. No test game or SteamVR
session is left running. The ordinary game installation remains untouched.

## 14 October: matched physical-runtime pacing controls

The registered physical-display workbench now waits for compositor readiness
before timing probes and records their actual configured eye sizes. Before that
boundary, a probe could initialize at 4312×5100 while startup's automatic GPU
calibration subsequently recommended 5028×5948. Mirror dimensions alone do not
prove the application's eye target. Private supersample controls did not freeze
that startup change, so they are not a claimed fix or a player default.

| Control | Observed result | Conclusion |
| --- | --- | --- |
| v256–v258, early projection/interface probes | About 119 submissions/sec, but early configuration differs from the game | Not yet a fully matched workload |
| v259, compositor-ready projection at 5028×5948 | 118.59 submissions/sec across 1,200 frames | Physical path has no universal 60/sec ceiling |
| v260, same target plus a transparent 1280×800 quad | 118.32 submissions/sec across 1,200 frames | The floating layer alone does not reproduce the defect |
| v261, same probe plus four milliseconds of diagnostic CPU work | 84.40 submissions/sec average, 4.87 ms average frame-begin wait | Runtime scheduling is workload-sensitive; this is not a game performance measurement |
| v262, ordinary game, forty-second sample | 60.02 stereo submissions/sec; predicted period remains about 16.67 ms throughout | Not just a short startup recovery delay |
| v263, native Escape skips startup movies efficiently | First stereo at 6.63 seconds, 60.08 submissions/sec, full case 42.55 seconds | A faster repeatable setup, not a pacing fix |
| v264, bounded native-call trace | Thirty stereo transactions; median eye draw 1.27 ms, page preparation 0.0001 ms, cursor capture/restore 0.0004/0.0022 ms | Native copies/page seeding are not significant costs in this sample |
| v265, diagnostic blank-only loading instead of its background helper | 60.00 submissions/sec | Do not remove the working loading protection to address pacing |
| v266, private explicit throttle/prediction settings set to zero | 59.99 submissions/sec | These settings are not a demonstrated fix |
| v267, physical display with a synthetic tracked head pose | Tracked view flags 15, unobscured readable Quit interface, 60.00 submissions/sec | Tracking fade and pacing are separate issues |

The native trace records all 392 entries without overflow, with complete return
records. Its median stereo bridge span is 14.23 ms, much of which is the OpenXR
wait. Instrumentation preserves the native caller contract in **56 executable
checks**. It is a diagnostic, not shipping performance acceptance.

The workbench's synthetic-head control uses SteamVR's private TrackingOverrides
configuration with the real Pimax display driver. Both diagnostic controller
poses are invalid, and no physical tracking/controller acceptance is claimed.
No tracking fade is disabled for that control. The captured native Quit interface
is inspected, but does not establish worn-headset text comfort or visual scale.

All game cases reach native Quit and clean uninstall, preserve ordinary game
files/preferences and global SteamVR settings/calibration, and close the owned
runtime gracefully. The blank-only case uses a deliberately different private
player (`b3b5a15c...`), with loading continuity explicitly unqualified. It is not
adopted. Ordinary cases retain renderer `5c39d7d8...` and player `830c5f5c...`.
No production renderer/player, normal Steam game, commit or release is changed.

Next investigate the application's frame timing/deadline budget. Do not repeat
these eliminated hypotheses, reduce resolution, bypass tracking safeguards or
change faithful color conversion to manufacture a passing result. In particular,
the existing UNORM conversion followed by byte-preserving sRGB copy is deliberate;
replacing it with a direct sRGB blit would change color encoding, not merely
remove a redundant copy.

## 14 October: early-frame candidate rejected, desktop WSI eliminated

No fixed 60/sec rate limit is found in the isolated player's configuration.
A guarded candidate begins the shared OpenXR transaction before the native
update rather than waiting at its later draw hook. It retains scene-resource
warm-up: preparation is allowed only when the current UserScene's verified
`+0x50` draw receiver matches the warmed receiver. The frame scheduler caches
this sample, so later world/UI consumers neither begin again nor resample input.

The preliminary native test correctly rejects an incomplete export-dispatch
change before any game test. The corrected candidate renderer passes all six
native groups and the real-GPU transport/color/alpha/brightness checks. Its DLL
is `62cb1072...`. The native hook uses the actual three-argument panel ABI;
emitted-code tests verify clean stack, native update/device-health preservation,
missing/foreign warm ownership and failure withdrawal. These are candidate
checks, not evidence of a performance benefit.

- **v268:** physical discovery fails while the newly started vendor runtime is
  still connecting. No game is launched. The owned runtime closes and a fresh
  case follows once the vendor process has initialized.
- **v269/v270:** the first owner guard compares the enclosing UserScene with
  the warmed draw receiver. The latter run records 714 boundary entries but
  zero preparation calls; the guard safely skips them. Test cancellation at the
  explicit activation assertion is not a spontaneous game crash or a passing
  timing result.
- **v271:** the corrected association reaches **179 preparation calls** with
  success before the timed sample. The real 5028×5948-eye run still measures
  **60.00 stereo submissions/sec**, median predicted period **16.67 ms**, frame
  wait **12.16 ms** and CPU submission lead **2.20 ms**. Native Quit/removal,
  flat files/preferences, global runtime settings/calibration and graceful
  shutdown pass. There is no demonstrated benefit, so the new operation,
  compiler option and its production tests are removed. Source/tests and the
  validated candidate remain privately archived under `build/vr/`; explicit
  replay uses the archived renderer recipe and compiler, not a shipping option.
- **v272:** the restored ordinary pair is tested before, during and after
  reversible suppression of only its owned desktop `PresentImage` entry.
  Actual stereo submissions are **60.00 / 60.00 / 60.00 per second**. The
  original entry is restored before native Quit, and the **68.22-second** case
  closes/uninstalls gracefully with ordinary files/preferences and global
  runtime settings/calibration preserved. Desktop output during suppression
  is deliberately unqualified; it is not a mode being shipped.

The established renderer/player `5c39d7d8...` / `830c5f5c...` is restored and
the cached renderer again passes current recipe verification. The post-rollback
software run has **347 passing tests, three skipped**, comprising the ordinary
VR/presentation checks plus 59 explicit private candidate checks. Lint and strict
typing pass for the touched production Python files. The rejected candidate
adds no maintained runtime mode, API operation or dependency.

Next focus on the measured CPU/GPU scheduling budget and the runtime's frame
timing, not more early-wait or desktop-mirror variants. The
[Khronos frame-submission guide](https://github.com/KhronosGroup/OpenXR-Guide/blob/main/chapters/frame_submission.md)
provides the relevant frame-lifecycle constraints. Valve's
[Vulkan timing guidance](https://github.com/ValveSoftware/openvr/wiki/Vulkan)
explains the OpenVR explicit-timing path, but it is not itself permission to
override an OpenXR runtime's ownership of that path. No such workaround is
adopted without applicable evidence. Physical tracking/comfort and high-refresh
game delivery remain unqualified, and the normal Steam installation is untouched.

## 14 October: next-frame wait control and first-session priorities

A private clear-only probe tests overlapping the next `xrWaitFrame` with the
current frame's rendering work. Begin/end, pose sampling and graphics submission
remain on the main thread. Executable checks cover non-overlapping waits,
prediction association, repeated frame cycles, balanced teardown and session-loss
errors. The helper creates a worker per frame and is deliberately not a production
implementation.

Both physical-display cases use SteamVR/OpenXR, the RTX 4090, recommended
5028×5948 eye targets, a transparent interface quad, four milliseconds of
synthetic CPU work per frame and 1,200 frames:

| Private control | Submissions/sec | Mean frame-begin wait |
| --- | --- | --- |
| v273, next wait overlapped | 68.58 | 8.64 ms |
| v274, ordinary wait | 66.14 | 9.38 ms |

These sequential independent sessions do not establish a reliable improvement.
Neither reaches the headset budget, and neither is an actual-game or physical
tracking/comfort qualification. They also differ from the earlier independent
four-millisecond probe's 84.40/sec result, so that older result must not be used
as a matched baseline. Both cases finish, shut down their owned runtime gracefully
and preserve global configuration. No production player/renderer change is made.
Evidence remains under `build/vr/steamvr-physical-discovery-20261014-physical-pipeline-control-v273/`
and `build/vr/steamvr-physical-discovery-20261014-physical-pipeline-matched-baseline-v274/`.

The checklist's next milestones are now outcome-focused: smooth real-headset
pacing, valid tracking/interaction, one connected seated session and release
qualification. Existing local gameplay coverage is retained. Do not restart it,
add exhaustive variants or promote speculative renderer micro-optimizations just
to accumulate checked items. Physical tracking and comfortable headset play are
still open, and the ordinary Steam installation remains untouched.

## 14 October: frame-stage timings and controlled runtime sizing

The private independent probe now records CPU frame stages and Vulkan timestamps
without writing files during the measured loop. GPU timestamps are read only
after the previous submission's fence has completed. Each 1,200-frame run has
400 frames without added CPU work, 400 with four milliseconds of synthetic CPU
work, then 400 without it again. Summaries omit the first 50 frames of each phase;
cycle rates below are derived from measured stage durations, not physical display
delivery. All eye targets in these probe runs are 5028×5948.

| Control | First no-work phase | Four-millisecond phase | Final no-work phase |
| --- | --- | --- | --- |
| v275, transparent interface panel | 120.18 cycles/sec | 105.70 cycles/sec | 119.76 cycles/sec |
| v277, opaque interface panel | 120.09 cycles/sec | 60.04 cycles/sec | 120.16 cycles/sec |

In v277's half-rate phase, application GPU clearing averages **0.065 ms**, image
acquisition **0.089 ms**, previous-fence handling **0.005 ms**, and frame begin
**11.55 ms**. When the added CPU work stops, the same session returns near
120 cycles/sec. Both visible and transparent panels therefore support the full
rate without that workload. Different sessions do not prove that panel opacity
caused their different workload responses. The important result is that an
independent application reproduces near-60/sec scheduling with negligible GPU
work: GK3 geometry, its texture copies and its engine are not required for that
symptom. This narrows the next investigation to workload-sensitive runtime frame
scheduling; it does not prove that all of the game's remaining performance cost
has the same cause.

The wait also moves between frame end and frame begin during these sessions.
For example, v275's initial no-work phase spends about 7.92 ms in frame end,
whereas its final no-work phase spends about 7.32 ms in frame begin. Treating
only `xrWaitFrame` duration as the whole runtime delay would be misleading.

Separately, v276 sets manual 100% sizing through OpenVR's settings API **after
private runtime initialization**, checks the read-back values and leaves the
public launcher unchanged. Pre-start configuration alone had been overwritten
during initialization. The actual game now receives **4312×5100** recommended
eye targets instead of the auto-enlarged 5028×5948. It still measures **59.91
stereo submissions/sec** over twelve seconds. The process-matched compositor
reports application GPU mean/p99 **4.60/6.98 ms** and client interval mean/p99
**4.38/7.02 ms**. Extra automatic supersampling is not the demonstrated cause
of the half-rate behavior, and reducing it is not adopted as a player fix.

The game case completes Play, Quit cancellation/confirmation and uninstall in
42.44 seconds, with unchanged flat files/preferences, no supervisor failure,
graceful owned-runtime shutdown and unchanged global configuration. Independent
probes also finish and shut down gracefully. Physical tracking remains invalid;
none of these samples qualifies headset comfort, bindings or scanout delivery.
No production renderer/player, normal Steam game, commit or release is changed.

Evidence: `build/vr/steamvr-physical-discovery-20261014-physical-budget-phases-v275/`,
`build/vr/steamvr-native-20261011-mirror-physical-manual-runtime-resolution-v276/`
and `build/vr/steamvr-physical-discovery-20261014-physical-opaque-panel-phases-v277/`.
The replay helpers remain private under `build/vr/`. Do not repeat automatic
supersampling reduction or assume a transparent-panel-only probe represents
every loaded-runtime scheduling condition.

## 14 October: installed native Pimax runtime isolation

Read-only inspection finds Pimax Play's already-installed x86 OpenXR runtime.
Its instance/system discovery and required Vulkan extension pass without SteamVR.
The diagnostic selects its manifest only through the child environment. No
runtime installation or system-default registration change is requested.
The abandoned unofficial PimaxXR project is not installed or used; its
[maintainer now directs users to Pimax Play's implementation](https://github.com/mbucchia/Pimax-OpenXR).

The same independent opaque-panel/CPU-work probe runs on the vendor runtime
at its recommended 4312×5102 eye size:

| Private probe | No CPU work | Four milliseconds CPU work | No CPU work again |
| --- | --- | --- | --- |
| v278, ordinary frame loop | 120.00 cycles/sec | 60.00 cycles/sec | 120.00 cycles/sec |
| v279, next-frame wait overlapped | 120.02 cycles/sec | 119.62 cycles/sec | 120.02 cycles/sec |

The workload phase's application GPU clearing averages about 0.046 ms in both
variants. Thus the independent half-rate symptom is not unique to SteamVR.
Overlapping waits changes that probe's behavior on the native vendor runtime,
but this is not evidence that it improves the game. The existing diagnostic
ordering/prediction/teardown/session-loss checks pass before v279. Both independent
cases finish successfully and close their sessions. Their per-frame asynchronous
worker remains diagnostic-only, not a production scheduling implementation.

To test relevance, the private timing layer can enable the same resolver wrapper
only when explicitly requested. It calls the runtime's next resolver rather than
recursing into the loader. Worker waits call the raw runtime, so they do not race
the layer's consumer-frame timing counters. The workbench skips OpenVR captures
and observers on this native path, avoiding an accidental SteamVR startup.
That also means these game cases do not provide compositor-eye visual acceptance.

| Actual game, unchanged renderer/player | Twelve-second stereo sample | Quit |
| --- | --- | --- |
| v281, diagnostic overlap enabled | 107.24 submissions/sec | Fails with process exit `0xC0000409` |
| v282, ordinary frame loop | 105.50 submissions/sec | Fails with the same process exit |

Both use renderer `5c39d7d8...`, player `830c5f5c...`, recommended 4312×5102
world eyes and the separate 1280×800 desktop canvas. Both reach Play and stereo,
but neither is a passing end-to-end session. The same Quit failure in the baseline
means it must not be attributed solely to prefetch. Neither a reliable performance
gain nor a safe native-runtime replacement has been established. Do not switch
defaults or add a maintained player mode from these results. A setup-only v280
attempt failed before launching because the repository test-support import path
was missing; v281 corrects the child path instead of treating that as a game defect.

The failed game cases remove their owned player files and preserve flat files
and preferences; no game or SteamVR process remains afterward. Physical tracking,
headset comfort and delivered frames remain unqualified. Global Pimax preference
preservation was not independently snapshotted for these direct-runtime cases,
so it is not claimed. No production source, normal Steam game, commit or release
is changed. Evidence stays in `build/vr/pimax-native-budget-v278/`,
`build/vr/pimax-native-overlap-v279/`, the v280–v282 private logs and
`build/vr/steamvr-native-20261011-mirror-pimax-native-game-{overlap-v281,baseline-v282}/`.

## 14 October: actual SteamVR overlap, vendor smoothing and software preflight

**v283** runs the unchanged player/renderer on the original SteamVR target with
diagnostic overlapping waits and the same fixed 100% sizing as v276. Recommended
eyes remain 4312×5100. The twelve-second stereo sample is **60.00 submissions/sec**,
versus v276's ordinary **59.91/sec**. Play, Quit cancellation/confirmation, clean
uninstall and graceful owned-runtime shutdown pass in 42.30 seconds. Flat files,
preferences and global SteamVR configuration are preserved. This rules out a
useful game-level benefit from the tested overlap, not merely from the independent
probe. It remains private; do not add a maintained player mode for it.

The maintainer's standalone [Pimax configuration CLI](https://github.com/mbucchia/Pimax-OpenXR/wiki/pimax_cli)
reads the installed vendor settings: Smart Smoothing is enabled, compulsive
division is disabled, and Lighthouse tracking is selected. The downloaded tool
is isolated under `build/vr/pimax-settings-v284/`, SHA-256
`584d57ee8018d49986de4e69bc3b888b8e435a52f104ba0e46a4d8bea69041c3`.
These settings do not prove that working tracking hardware/base stations are
currently available, or that the smoothing setting caused the performance issue.

**v285** tests that hypothesis reversibly. It saves the observed smoothing value
1, sets it to 0 with read-back verification, runs the private SteamVR game case,
then restores and verifies 1 in `finally`. Its original-value recovery record
remains on disk before the mutation. The twelve-second sample still measures
**59.92 stereo submissions/sec**. Native Quit/uninstall, flat preservation and
graceful runtime shutdown pass in 42.35 seconds; the recovery record confirms the
vendor setting was restored. Disabling Smart Smoothing is not adopted as a fix.
No headset refresh rate, Windows monitor mode or firmware is changed.

Software inventory identifies installed **Pimax Play 1.41.1.152**. The vendor's
[current official download](https://www.new.pimax.com/support/downloads) is
**2.0.4.329**, with tracking/controller, frame-rate and visual fixes in its release
notes. Those notes are not proof that it fixes GK3's defect. The current signed
installer and its signed runtime sub-installer are downloaded under
`build/vr/pimax-update-preflight-v286/`; the outer SHA-256 is
`957da32e9b6ab6d402ecbea597f0d6bbd7b2e82acd8f042edd077b18209b6dfe`.
Both signatures validate to Pimax's vendor certificate.

This process has no administrator token. No installer/elevation prompt is launched,
and no installed driver or runtime registration is replaced. A user-level Inno
archive unpacker is installed to inspect the signed payload without executing
its setup. The package contains a newer 682,496-byte x86 OpenXR library versus
the installed 560,480-byte library, plus a newer PVR client and app server.
Selecting only the extracted new runtime DLL/manifest with the **old installed
middleware** fails system discovery with `XR_ERROR_FORM_FACTOR_UNAVAILABLE` (-35).
That mixed stack is not a valid new-version qualification or a reason to weaken
the launcher. Do not swap only the runtime DLL into the installed software.
Firmware updates and a Windows reboot are not performed.

The first-release implementation priorities remain unchanged. The two new game
controls eliminate proposed workarounds rather than creating player options.
The current vendor software stack is now an identified workbench constraint;
qualifying a coherent newer stack requires the appropriate installation/elevation
or an independently working isolated middleware setup. Physical tracking and
wearer acceptance remain open. The ordinary Steam game is untouched and no
test game/SteamVR session remains running. Detailed evidence stays in the v283
and v285 case folders and private v284/v286 preflight artifacts.

### Coherent vendor update and actual-game pacing (14 October, v287–v289)

The isolated newer middleware/client/runtime probe (v287) sustains 119.68
cycles/sec during its settled four-millisecond CPU-work phase, compared with
60/sec on the old middleware. This motivated a coherent full vendor update,
not a player-side timing workaround. The official signed Pimax Play 2.0.4.329
installer completes all five components with zero failures and reports no
Windows restart required. Runtime user data and registry settings were backed
up first. No firmware update or monitor-mode change was requested.

The initial v288 game probe cannot find the headset: the installed vendor
service is stopped and the server was launched without its runtime working
directory. Starting PiServiceLauncher and the installed server in its runtime
directory restores native instance/system discovery at 4312×5102.

The v289 actual-SteamVR game probe, with the same production player and renderer
as the old-stack controls, uses 4312×5100 per eye at private manual scale 100%.
Its twelve-second steady sample submits 119.412 stereo frames/sec, versus the
matched old-stack sample's 59.91. Application GPU p99 is 7.55 ms and compositor
client-interval p99 is 7.64 ms. No overlapping-wait mode, disabled tracking fade,
early-preparation hook or desktop-presentation workaround is enabled.
Native Quit cancellation, stereo recovery and confirmed Quit succeed; the
public supervisor reports no errors and the isolated player is uninstalled.
The complete case takes 43.90 seconds. Runtime shutdown is graceful without
forced components, global SteamVR configuration is unchanged, and flat game
files/preferences remain unchanged. Evidence is under ignored
`build/vr/steamvr-native-20261011-mirror-physical-updated-vendor-v289/`.

This proves an actual-game submission improvement, not physical headset
delivery or comfort. The unworn headset still reports out-of-range tracking
(201); gray safety fade remains enabled. Longer moving-scene acceptance and
real tracking remain open. Keep SteamVR as the first-release runtime.

### Gabriel-sized observer: initial dimensional evidence (14 October)

The current 40 game units per meter remains provisional. Reading native MOD
mesh transforms and only triangle-referenced vertices gives Gabriel a bind-pose
visible height of 75.94 units and Grace 68.29 units, corresponding to 1.899 m
and 1.707 m at the current scale. CHARACTERS.TXT independently sets Gabriel's
WalkerHeight to 76.0. These plausible proportions support the current scale,
but do not establish an exact historical metric convention or actual animated
in-game height. Unrendered actor axes/reference vertices must be excluded:
including them incorrectly inflates Gabriel's bounds to 131.12 units.
The parser's mesh transforms/layout were checked against the primary
[G-Engine model reader](https://github.com/kromenak/gengine/blob/master/Source/Engine/Rendering/Model.cpp).
Reproducible evidence is in ignored `build/vr/world_scale_evidence.py` and
`world-scale-evidence.json`; no original assets are modified.

The default R25 authored camera is at Y=61.70, while other room cameras range
from Y=56.25 to 68.70. Thus anchoring tracked eyes directly to authored cameras
does not provide a consistent Gabriel-height observer. A separate floor-based
observer anchor still needs implementation and verification against actual
standing head/eye landmarks, scripted-camera ownership, wall protection and
seated recentering. Gabriel remains the native protagonist, not a replaced body.

### Designated floor and eye-height evidence (14 October, v290–v294)

Native serialization anchors identify UserScene's SceneData pointer at +0x54,
SceneData's floor-name string at +4, and that string's buffer at +4. The room's
actual floor name is therefore available without a fixed per-room exception
list. The renderer's geometry query accepts this name as a filter; ordinary
furniture/actors are not floor substitutes. `VRFloorCompiler` implements a
read-only finite-segment adapter with exact source anchors, verified room
types, missing-resource rejection and no original call-site mutation.
Its 48 behavior tests pass, as do 234 combined floor/scene/geometry tests;
lint and strict type checks pass. It is not yet connected to observer placement.

The v292/v293/v294 private SteamVR sessions invoke the **package adapter**,
not a diagnostic duplicate, on the native render thread. They find `r25_floor`
at Y=0 under the ordinary camera at (278.31,61.72,49.89). The segment extends
downward at fixed X/Z. Native Quit cancellation/confirmation, removal, global
configuration preservation and unchanged flat game files pass. The earlier
v290 harness duration was below its supported minimum, and v291 timed out in
the optional Quit compositor capture; both cleaned up. Those failed harness
cases are not used as session acceptance.

The instrumented samples run near 17 stereo submissions/sec, substantially
below v289. Restricting the supervisor to one successful remote-memory sample
does not recover pacing; the first timed native floor query takes less than
one millisecond at the diagnostic clock's resolution. This is an unresolved
experiment regression, not proof that the query is free or that the vendor
update regressed. A matched no-op callback control is next. Do not enable a
per-frame floor query in the player before identifying this difference.

Further asset analysis uses the original FACES.TXT eye offsets, EYE_GREENX's
100×104 atlas/4×4 grid, GAB_FACE's 256×256 dimensions and triangle UV interpolation.
MOD V coordinates are negative and wrap into the native texture domain;
treating them as positive incorrectly yields no eye intersections. Both eye
centres are near model Y=69.95. CHARACTERS.TXT identifies the shoe reference
points and 0.75-unit shoe thickness; these place the bind-pose floor at Y=0.467,
giving an approximate **69.48-unit eye height** (1.737 m at 40 units/m).
This gives a data-derived target for the independent observer, rather than
an arbitrary 1.7/1.8 m setting. Animated model transforms and headset comfort
still need verification; this does not qualify complete world calibration.

### Floor control and independent runtime slowdown (14 October, v295–v298)

The floor diagnostic's no-op callback (v295) also measures 17.00 stereo
submissions/sec. Adding the same timing layer/clock extension as the fast
v289 baseline (v296) leaves it at 17.00. Thus neither floor arithmetic nor
the trace configuration explains the difference. More importantly, v297
repeats the **unchanged public-command baseline**, with the exact original
player hash `830c5f5c7cd740062b043e9a1bfbc987824a2d9af1da6aac700df3668b4d690c`,
and measures 17.17/sec. No floor adapter or diagnostic callback is present in
that player. Native Quit and graceful shutdown/removal succeed in these cases,
with global configuration and flat game files preserved.

The v298 independent Vulkan clear/panel probe uses the installed Pimax OpenXR
runtime directly, without GK3 or SteamVR. All 360 frames complete in 21.06
seconds at 17.09/sec, with 55.66 ms average frame wait. This reproduces the
slowdown outside the game, unlike the earlier fresh-stack 119/sec evidence.
Read-only vendor configuration shows `dbg_force_framerate_divide_by=1` and
`dbg_asw_enable=1`; no new vendor setting is written. Runtime/backend state
and repeatability, including the unworn/out-of-range headset, are the next
performance investigation. Do not claim the vendor update permanently solved
pacing, and do not remove faithful renderer features or floor functionality
to address a slowdown that the independent runtime reproduces.

### Gabriel-height observer implementation (14 October, v299–v302)

`VRFloorCompiler` now provides a second, ownership-guarded floor entry. It
matches the native camera manager, lock, controller-stack and user-controller
guards already used by VR navigation. Locked, stacked, scripted, unknown or
missing camera owners return no observer placement without querying geometry.
The ordinary floor entry remains independently usable. Scene compilation links
the observer entry into the expanded 256-byte x86 SceneV1 boundary, and complete
program verification includes the floor adapter and its dependencies.

The renderer uses a separate render/aim camera snapshot at **floor Y + 69.5
game units**, derived from the original Gabriel eye/shoe landmarks. It retains
horizontal placement and heading, makes the ordinary observer upright, preserves
axis scales and applies the runtime's actual eye separation and tracked offsets.
Controller world rays use the same adjusted anchor. The authored camera and
protagonist are not repositioned. Authored cameras remain intact when the adapter
declines placement, including scripts/locks and unavailable floor coverage.
Wall protection still casts from the trusted authored interior towards both
tracked eyes, so the height adjustment does not bypass the existing safeguard.

Native coordinator tests cover 20/40/80 units per meter, unequal authored axis
scales, pitched camera headings, both eyes, controller ray origin, crouch/stand,
seated recenter, floor elevation changes, unchanged native camera state, unavailable
floor fallback and rejection of off-segment hits without partial rendering.
Ownership emulation covers both native user-controller types and missing/locked/
stacked/scripted owners. The Python VR/floor/scene/geometry/navigation set passes
546 tests with three platform skips; all six native XR suites and the fresh
renderer build's additional transport/renderer checks pass. Lint/type checks pass.
The verified candidate is in ignored `build/vr/observer-anchor-v299-20261014/`,
DLL SHA-256 `d197d6e210152c1a324f7ac817959b73b1649fbed5267bafd490d261bda02038`.

The v300 actual-SteamVR null-display game session uses the public build/install/
verify/launch/removal path. Coherent read-only native snapshots confirm the eye's
Y=69.5 versus authored Y=61.7157, both initially and after the steady interval.
Both compositor eyes show the original Gabriel still present and are inspected.
The twelve-second sample submits 125.66 stereo frames/sec at the runtime's
1280×1280 eye recommendation; this is synthetic-display performance, not Pimax
delivery. Quit cancellation/confirmation, graceful runtime shutdown, removal,
unchanged global configuration and unchanged flat game files pass in 57.86 seconds.

The v302 actual-SteamVR virtual-controller session additionally passes world
Select, a native verb/camera action, Back pause/resume, stick movement, unchanged
host mouse and normal Quit/removal in 40.48 seconds. Inspect undo is not requested
by that case and is not newly qualified. v301 omitted the required virtual-device
mapping, failed in the workbench before controller actions, and cleaned up;
it is not a player defect or acceptance evidence. The current implementation still
requires broader elevation/floor-footprint coverage, animated-scale corroboration
and physical-headset comfort/tracking/pacing. The normal game is untouched.

### Persistent vendor state and recovery (14 October, v303–v306)

After verifying that no game/compositor/probe session is active, the workbench
restarts only its exact owned installed pi_server process (path and creation
time checked), leaving the device service, firmware, monitor settings and global
runtime selection unchanged. Native discovery briefly returns unavailable during
startup, then succeeds through the same live new server. No process is restarted
merely because an observation timed out.

The independent installed-Pimax OpenXR phased probe now completes 720 frames in
6.027 seconds at **119.47/sec**, versus the earlier same installed stack's 17.09.
A second native session without another restart reaches 119.49/sec. The v305
public-command game session uses the current Gabriel-height player/renderer
through actual SteamVR with its registered physical driver, at 4312×5100 per eye.
It reaches **119.494 stereo submissions/sec** over twelve seconds, with GPU p99
6.80 ms and compositor client-interval p99 6.60 ms. Read-only snapshots confirm
eye Y=69.5 and authored Y=61.7157 initially and after the interval. Native Quit
cancellation/confirmation, supervisor checks, uninstall, global configuration
preservation and graceful runtime shutdown pass in 42.38 seconds. An independent
native session after that complete SteamVR lifecycle still reaches 119.50/sec.

This is evidence of persistent/recoverable vendor runtime state rather than
insufficient GPU performance or a floor-query regression. It does not establish
which previous event caused the bad state, nor prove that it can never recur.
Normal balanced sessions remain fast in these four samples. The workbench's
new server identity is recorded in its tool output; no automatic server restart
is added to GK3HD. The physical headset remains unworn/out of range, and actual
delivered frames, valid physical tracking and comfort acceptance remain open.

### Independent multi-room floor validation (14 October, v307–v310)

The ignored observer-room workbench independently reads original SIF/SCN/BSP
resources, finds polygons belonging to the declared floor object, triangulates
their fans in X/Z and interpolates floor Y under the authored camera. It does
not derive the reference floor from the observer's own output. Conditional SCN
variants must produce equivalent floor heights at the tested point, or the
reference refuses to guess. SCNs without a BSP declaration use the documented
basename convention, corroborated by the primary
[G-Engine scene reader](https://github.com/kromenak/gengine/blob/master/Source/GK3/Scene/SceneAsset.cpp).

The connected v310 public-command actual-SteamVR session passes all four
neutral-head positions:

| Room | Original floor Y | Observed eye Y | Height above floor |
| --- | ---: | ---: | ---: |
| R25 | 0.000000 | 69.500000 | 69.500000 |
| LBY | 0.087891 | 69.587891 | 69.500000 |
| RC1 | -0.203956 | 69.296043 | 69.500000 |
| MS3 | 37.927322 | 107.427322 | 69.500000 |

Both exterior and museum compositor eyes are inspected: stereo geometry is
present, Gabriel remains visible, and the raised museum floor does not cause
a fixed-world-height viewpoint. Native Quit cancellation/confirmation, graceful
runtime shutdown, uninstall and unchanged global configuration/flat game files
pass in 44.40 seconds. Evidence is in ignored
`build/vr/steamvr-native-20261011-mirror-observer-rooms-v310/`.
The tiny transient HUD captions in the rapid console-staged captures still name
the previous location; this route does not qualify HUD retirement/update timing
or natural travel. Keep those acceptance gates separate from the floor proof.

Earlier workbench failures are explicit: v307 rejects an unregistered flow before
game launch; v308's reference initially rejects RC1's two BSP variants; v309's
reference incorrectly requires an explicit BSP declaration in MS3's SCN. These
are test-reader/setup failures, not evidence of player floor errors. Both RC1
variants agree on floor height at the sampled point, and MS3 uses its own named
BSP. The corrected reference is used in the complete passing v310 route.
The outer private harness now propagates child failure/timeout status after
cleanup, so shell success alone cannot masquerade as a passing game case.

### Cooperative launcher cancellation (v311–v315)

The launcher previously called `TerminateProcess` immediately whenever a live
child left its context, including Ctrl+C and supervision failures. That prevents
normal native renderer/OpenXR teardown. This is an independent cleanup defect,
not an established cause of the earlier SteamVR error dialogs or Pimax pacing
state.

Inspection of the normalized original executable shows native Quit at
`0x0053E090` posts `WM_QUIT` with exit code zero. Its main message pump checks
that message at `0x0053356A` and returns the exit request at `0x0053360D`.
The launcher now retains its owned primary-thread handle, checks that both the
game and that thread remain active, then posts the same quit message to that
thread. It allows three seconds for normal exit before falling back to the
existing owned-process termination. Failed activation never posts to a suspended
thread. Missing queues, request failures and unresponsive games cannot leave
an abandoned child running. Explicit `kill`/`terminate` remain force-stop
operations. No runtime process, global setting or normal game file is changed.

Actual public-command results with the verified observer renderer:

- v311, stereo hotel room: game exit zero in **0.257 seconds**, no forced stop.
  The initial workbench labels the expected CLI status 130 as an assertion;
  that harness classification is corrected for subsequent runs.
- v312, native Quit confirmation open: cancellation status **130**, game exit
  zero in **0.221 seconds**, no forced stop. The full case takes 34.53 seconds.
- v314, physical Pimax/SteamVR, **4312×5100 per eye**: cancellation status 130,
  game exit zero in **0.318 seconds**, no forced stop. The full case takes
  32.42 seconds. The headset remains unworn, not comfort/tracking accepted.

All three cases verify unchanged flat files and mirror preferences, removal of
the isolated installation, unchanged global runtime configuration and graceful
owned SteamVR shutdown. A separate independent Pimax probe before v314 (v313)
already measures **17.09/sec**, with **55.67 ms** average frame wait. Therefore
successful cooperative cancellation is not evidence that persistent vendor
pacing is resolved, and no automatic vendor restart or speculative workaround
is shipped. The same independent probe after cancellation (v315) again measures
**17.09/sec**, with **55.60 ms** average frame wait. The slow state predates
this physical game session and is unchanged afterward; its trigger remains
unproven. Final process inspection finds no remaining game, SteamVR or timing
probe process.

The final portable VR suite passes **253 tests with three skips in 17.05
seconds**, including clean cancellation, unavailable/failed message queues,
hung-player fallback, an already-ended primary thread, failed activation,
normal exit and preservation of the primary exception. Changed files pass
Ruff formatting/lint and strict type checking. No renderer rebuild is needed
for this launcher-only change.

### State-aware Pimax pacing controls (v316–v322)

A private timing resolver forwards real OpenXR calls without changing their
arguments/results and records session state, should-render, predicted period
and view flags. It is linked only into the ignored independent workbench,
not the renderer or game. A read-only PVR SDK probe reports HMD present, not
mounted, service ready, no display loss and no tracked head flags. Its
non-rendering client is not itself visible, so that field is not substituted
for the rendering application's OpenXR visibility.

- v317, existing slow server state: **17.04 submissions/sec**, 54.97 ms average
  frame wait, visible state 4, should-render true, 8.333305 ms predicted period,
  view flags 3 (valid orientation/position, neither actively tracked).
- After verifying no game/SteamVR/probe remains, restart only the previously
  owned server, checking its exact executable and creation time. The replacement
  server is owned by this workbench too. v318 starts before discovery is ready
  and exits with `XR_ERROR_FORM_FACTOR_UNAVAILABLE`; it renders nothing.
- v319, once discovery is ready: **39,534 submissions in 329.99 seconds**, or
  **119.80/sec**, with a constant 4 ms CPU workload. Every thirty-second interval
  retains a median predicted-time step near 8.334 ms. It remains in the same
  visible/untracked state for the entire test. No synthetic pose, frame-prefetch
  control, tracking fade bypass or global graphics setting change is used.
- v322, after a gap between rendering sessions: **17.05/sec**, 52.33 ms average
  frame wait, with the same state/renderability/nominal period/view flags.

This rejects untracked/unfocused OpenXR state alone as the explanation for low
submission throughput and demonstrates a longer healthy continuous session.
It does not distinguish idle behavior from a session-teardown problem, nor
qualify delivered physical-headset frames. Pimax documents a five-minute
stationary sleep behavior for
[Crystal Light](https://support.pimax.com/en/support/solutions/articles/60001506972-troubleshooting-screen-off-issue).
That model-specific guidance motivated the bounded long run; it is not proof
that Crystal's idle behavior causes this defect. The SDK/reference source is
[PimaxXR's native PVR dependency](https://github.com/mbucchia/Pimax-OpenXR), used
for read-only investigation only. The player still targets SteamVR, not that
abandoned runtime. No automatic vendor restart or speculative setting is shipped.

### Upright viewing when the floor is unknown (v320–v324)

An original SIF/SCN/BSP audit covers all 54 room/custom free-camera views in the
curated visual catalog. Fifty-three have designated floor triangles within the
observer query segment. TE3's `LONG_ALTAR` view does not; its authored pitch is
19 degrees. Returning an unchanged camera for this miss also retained that
downward pitch, rotating physical up/down with the authored camera. A missing
floor reference must not be confused with a scripted owner.

The observer callback now distinguishes three outcomes without enlarging the
bridge: 0 preserves an authored/locked/scripted camera, 1 supplies a validated
floor hit, and 2 keeps a user camera's native position but makes its viewing
basis upright. The direct floor query retains its independent hit/miss/unavailable
contract. No scenery surface is guessed as ground, no camera/actor/simulation
field is changed, and hit validation and wall protection remain in force.

Fresh verified renderer SHA-256:
`8a2528bb77a1a0e2f43044533d24d9383f88408208393126dc4caa62901e1555`.

The subsequent full default Windows regression (v338) passes **5,429 tests,
23 skipped, 402 slow cases deselected, in 90.54 seconds**. Repository-wide
formatting, lint, strict type checking and spelling also pass. This is portable
and Windows API regression evidence, not live-headset acceptance. The requested
sub-60-second routine-test target remains unmet and is not marked complete.

### Stair movement and escaping a wall fade (v339–v354)

The original hotel camera already follows stair elevations through its native
movement/commit methods. No new gravity, walker-boundary change or character
teleport is needed. A sampled height discrepancy was instead a workbench bug:
its snapshot reader could pair a newly copied authored camera with the previous
eye while the renderer waited for a frame. Requiring the complete producer to
be idle, not just its eye/projection hooks, removes that mismatch. Static earlier
height samples are not affected by this moving-camera measurement error.

The corrected check exposes a real navigation trap. In HAL, descending the
first stair flight stops at approximately X=-102.88. Both controller poses and
runtime focus remain valid, the native camera is unlocked with one user
controller, and stereo keeps rendering, but the wall fade withdraws every world
ray. Navigation was incorrectly contingent on a selectable ray. Neutral input
and a fresh reverse-stick command cannot retreat; v345 stays at that position
with 354 movement calls. Its compositor image is partially visible, not fully
black. Even the beginning of the safety fade could therefore trap the player.

The renderer now retains completed focused controller metadata during a wall
fade while still withdrawing all object rays. Authored-cut fades, hidden/failed
frames and lost tracking/focus retain their existing withdrawal behavior.
The native bridge freezes an explicit navigation-only owner, never copies an
old ray, and rejects that owner for both direct and event-dispatch picking.
The input router cancels selection/hover, rechecks native room/overlay ownership,
and permits the original camera navigation. Camera locks/collision remain native;
menus and puzzle overlays still take priority. Visibility recovery requires a
fresh trigger release before selecting again. No extra user setting or command,
and no external ABI size change, is introduced.

The source-matching renderer is built at
`build/vr/wall-retreat-v348-20261016/`, SHA256
`66258b64471867179e84ae21a9ef13f996e9c368facafc01db99e70f8603269a`.
All **six native CTest groups pass in 1.78 seconds**, followed by the actual
renderer transport/GPU/artifact checks. Focused Python regression passes
**854 tests, three skipped, in 21.57 seconds**. Behavior tests cover either hand,
held-selection cancellation/rearming, menu/overlay priority, lost tracking/focus,
failed frames, and rejection of stale-ray picking.

v352 passes the same native descent and return through the original failure
region: **1,113 movement calls**, 70.03 units of floor elevation (about 1.779 m),
maximum original-floor eye-height error **0.000938 units**, and return within
0.04 units of the start. It observes the completed navigation-only owner and
both compositor eyes are inspected. Native Quit/cancellation, unchanged flat
files/preferences, uninstall and graceful global-preserving runtime shutdown
pass in **44.68 seconds**. v353 then passes controller startup, native save/restore,
SIDNEY search, driving-map travel, resumed gameplay and controller Quit/cancel
in **63.33 seconds**, with clean removal and unchanged flat/global state.
These are actual SteamVR sessions using virtual controllers, not physical
headset tracking, delivered frame pacing or stair-comfort acceptance.

Earlier v339 rejects an unknown workbench flow before gameplay; v340 forgets
to restore controller dispatch after console staging; v341 reaches a different
native obstruction instead of a staircase. v342 times out before entering the
new flow. Its owned child/install/preferences are recovered; the immediate
runtime-stop check fails, and a subsequent process inventory confirms the
runtime has exited. None is counted as successful gameplay qualification.
v343/v344 expose the snapshot mismatch and the navigation trap respectively.
v351 completes descent/return, but its diagnostic reads a retired producer
mailbox instead of the frozen completed owner, so its stronger observation
assertion fails. v352 corrects that observation without weakening the requirement
to exercise the wall-fade case. All private evidence remains under `build/vr/`.

The post-fix full default Windows regression (v355) passes **5,458 tests,
23 skipped, 402 slow cases deselected, in 84.61 seconds**. Repository-wide
formatting, lint, strict types and spelling pass. The default test-time target
remains open; these results do not establish physical-headset acceptance.

### Redirected Windows installation output (v356)

Preparing the private player through the ordinary public command, without
`python -X utf8`, exposes a CLI output bug. The default Rich braille spinner
cannot be encoded in a redirected Windows cp1252 stream. The installation can
finish successfully and then report an encoding error when progress closes;
independent verification confirms its files are consistent.

VR installation now uses the same ASCII line spinner as the other package
commands and routes progress through the shared CLI console. A regression test
uses a real cp1252 text stream and checks both progress and the successful
installation report, including preservation of the real error on failure.
All **12 VR CLI tests pass**, as do focused formatting, lint and strict type
checks. The actual plain `uv run gk3hd vr install` command
then succeeds and the private installation independently verifies without any
UTF-8 environment override. This changes no native renderer bytes or VR behavior.

The complete Python VR group subsequently passes **259 tests, three skipped,
in 14.54 seconds** (v358), with repository-wide formatting, lint, strict types
and spelling passing. The private player is left installed and verified for
later physical acceptance, with every launch switch dormant on disk. No game
or VR session is left running. The normal game's files are not changed.

### Fresh physical-runtime readiness observation (v357)

A new independent native OpenXR graphics session through SteamVR and the Pimax
driver confirms the current tracking condition, rather than inferring it from
an idle vendor-status query. All 180 frames report view flags **3**, valid
last-known orientation/position but neither component tracked. After its initial
READY state, the session reports FOCUSED for 179 frames and shouldRender=true
throughout. Runtime focus alone therefore does not establish usable tracking.
The separate vendor status reports present/service-ready, not mounted, with
no head-tracking flags. No tracking result or wear sensor is overridden.

At **5028×5948 per eye** on the RTX 4090, the clear-only probe submits **16.21
frames/sec** over 11.10 seconds. Its Vulkan GPU work measures **0.0618 ms median,
0.0716 ms maximum**. Direct `xrWaitFrame`/`xrEndFrame` means are **18.30/38.97 ms**;
the nominal prediction period remains 8.3333 ms. Those blocking runtime calls,
not GK3 scenery or texture drawing, dominate this particular sample. This does
not distinguish standby behavior from a runtime/driver defect or establish
performance while worn. Earlier fresh-service fast samples remain relevant
controls, not evidence that the recurring slow state is fixed.

The probe exits normally, SteamVR stops gracefully and global configuration is
unchanged, in 11.82 seconds overall. It neither launches nor removes the prepared
private GK3 player. A real tracked-headset check remains necessary before
accepting scale, controls, readability, comfort or sustained delivered pacing.
All six native test groups and the renderer transport checks pass. The Python
VR/floor/scene/geometry/navigation set passes **588 tests, three skipped, in
17.22 seconds**, with Ruff and strict type checks passing on changed Python.

The actual SteamVR v324 public-command route verifies both normal R25 height
(69.5 over original floor Y=0) and the TE3 miss. TE3's authored Y=75.32557 and
pitch=0.33161 radians remain unchanged; the completed eye retains that Y but
has zero pitch. Both compositor eyes are inspected: the temple is upright
and consistently stereo, with no obvious new geometry defect. Native Quit
cancellation/resumption, confirmed exit, uninstall and graceful runtime shutdown
pass in **40.72 seconds**. Flat files/preferences and global configuration are
unchanged. This virtual-headset check is not physical comfort acceptance.

The earlier v323 check incorrectly equated the requested camera target Y=75
with the native camera position. GK3 places its camera one unit behind that
target, yielding the observed Y=75.32557. The private assertion is corrected to
compare the eye with the actual authored camera, rather than weakening the
height-preservation requirement. v323's failed assertion and cleanup remain
recorded; it is not a passing native-Quit qualification.

### Runtime wait and current-game pacing (v325–v327)

Per-call timing in the slow independent Pimax session places **53.62 ms**
average inside `xrWaitFrame` (median 53.77 ms). Begin-frame, eye location and
end-frame average **0.108/0.036/0.494 ms**. Earlier `wait_ms_per_frame` summaries
time the complete Runtime::beginFrame wrapper; this trace removes that ambiguity.
Read-only WOW64 sampling places 43/48 samples in RPC waits. The native SDK
function table identifies the dominant client chain as `pvr_waitToBeginFrame`,
through PiOpenXR and the installed PVR client into the Pimax service. The other
RPC chain is end-frame submission. The server already has High priority. No
driver/scheduler setting or client frame-wait bypass is introduced.

After restarting only the identity-verified owned vendor server, v327 exercises
the current upright-fallback renderer through actual SteamVR at **4312×5100 per
eye**. Twelve-second capture-free intervals reach **118.91 stereo submissions/sec
in R25** and **117.83/sec in RC1**, with the desktop mirror minimized. GPU
median/p99 is **3.98/7.08 ms indoors** and **5.97/9.87 ms outdoors**; client
interval median/p99 is **3.48/7.13 ms** and **5.49/9.72 ms**. The outdoor tail
still exceeds the 8.33 ms budget at 120 Hz. An unworn timing sample is not
delivered-frame or moving-head acceptance. Scene changes, native Quit/cancel,
uninstall, graceful runtime shutdown and unchanged flat/global state pass in
**57.80 seconds**. This does not resolve the between-session vendor wait.

### Documented inch-based world scale (v328–v334)

Original `FACES.TXT` explicitly documents model eye separation, head radius and
head-center offsets in inches. Its 2.5-unit eye separation is therefore 63.5 mm.
That is stronger unit evidence than assuming an average person's height.
Original visible model bounds of 75.94 units for Gabriel and 68.29 for Grace
become about **1.929 m and 1.735 m**. Gabriel's WalkerHeight=76 is 1.930 m;
the measured 54.52-unit armoire-door model is about 1.385 m. These are original
art dimensions, not claims about canonical character heights or standard doors.

The CLI/service default now shares `1 / 0.0254` units per meter, replacing the
provisional 40. Installed state stores 39.37007874015748; the native float stores
39.370079040527344. Movement, rays and tracked eye separation use that same
scale. Runtime IPD is preserved, not forced to the face-art metadata's 2.5 units.
The 69.5-unit resting observer eye height is about **1.7653 m**. Explicit overrides
remain supported; physical size/comfort acceptance is still open.

The focused suite passes **589 tests, three skipped, in 17.92 seconds**, with
formatting/lint/strict types passing. New behavior coverage checks documented
inches retain their metric length in installed metadata and native bytes, then
independently verifies/removes the player. No renderer rebuild is needed.

Public-command v330 passes controller Select → WINDOW Inspect → Back pause/resume
→ stick movement → opposite snap turns → native Quit/cancel/confirm in **38.01
seconds**. Both inspected-view compositor eyes are reviewed. v334 repeats without
gameplay screenshots in **36.97 seconds**. Host cursor, flat files/preferences
and global configuration are preserved, with clean removal and graceful runtime
shutdown.

The failed v328/v329 fixture picked an arbitrary desktop-pixel target but always
expected WINDOW's Inspect camera. It now derives the known window-frame target
from original BSP bounds and uses the upright observer basis. v331–v333 expose
a second fixture error: camera ownership can return before the first completed
VR world-input frame after the glide. Back during that handoff does not promise
to pause an unobstructed room. v334 waits for native camera/menu/action readiness
and a fresh completed world ray, then publishes neutral controls before testing
Back. No fixed delay, weakened expected outcome or game-input workaround is used.
All failed cases and cleanup remain recorded, not counted as qualifications.

### Startup deadline, display isolation and relaunch (v335–v337)

The actual 30-second startup deadline is exercised without changing its timer.
A private fault disables frame producers before resuming the isolated child;
the real renderer creates its OpenXR session, but submits no world/panel frames.
v335 exits normally after 30.18 seconds. That case did not check display
preferences before the workbench restored them, so it did not establish full
preference isolation.

The stronger v336 assertion exposes a real coupling: display-write suppression
used the renderer-owned scene flag. Once disabled, the native mirror arguments
persist Screen Width/Height=1280×800 and Full Screen=0. A rendering failure can
also retire that flag. The workbench restores the preferences, but this is not
acceptable protection for an ordinary launch. v336 fails before its healthy
relaunch; it is not counted as successful recovery.

The mirror compiler now owns a separate dormant launch flag. The verified
launcher activates it before resuming native code, and render failure cannot
retire it. Only the original game's five display DWORD writes are suppressed;
other settings and native write errors remain unchanged. No global registry
backup/restore or renderer DLL change is introduced. Emitted-code tests exercise
the complete player's display writer after scene/panel rendering is disabled,
for every supported executable profile.

v337 repeats the fault with all eight render/input switches disabled and the
launch guard active. The native room opens; zero frames are submitted; the
supervisor reports the actual deadline and log location at **30.22 seconds**;
the child exits normally without force. All five display preferences are
unchanged **before any harness restoration**. The same installed player then
launches again into stereo in the same SteamVR setup, without a workbench
runtime restart. This is a new child/OpenXR session, not session resurrection.
Normal Quit/cancellation, unchanged flat files/preferences, clean uninstall and
graceful global-preserving runtime shutdown pass in **69.02 seconds** overall.
Physical headset disconnection/reconnection remains unqualified.

The current focused Python suite passes **645 tests, three skipped, in 16.96
seconds**. The renderer remains the source-matching v321 artifact with SHA256
`8a2528bb77a1a0e2f43044533d24d9383f88408208393126dc4caa62901e1555`.

### Bounded developer test time (16 October, v359–v365)

The earlier serial routine suite's 84.61 seconds exceeded the requested
60-second Windows budget. A per-file profiler under ignored `build/vr/` first
measures 5,460 passing tests in 79.55 seconds. Reuse immutable canonical source
and compiled fixture bytes while returning fresh mutable PE images to each
test; custom profiles still build their own images. Add a behavior test proving
that image mutation does not leak and same-ID custom profiles are respected.
This brings the serial suite to 5,461 passing tests in 72.51 seconds, still
above the target.

The existing developer test task now uses pytest-xdist with automatic worker
selection capped at four and scope grouping for fixture reuse. It is a
development-only dependency in the existing single group. Two workers pass
in 45.71 seconds; four pass in 27.05 seconds. The final bounded task repeats
with **5,461 passed, 23 skipped in 27.48 seconds** (v365). The same task with
`--slow` passes **5,863 tests, 23 skipped in 86.46 seconds** (v364), below the
180-second full-suite budget. Logs are `build/vr/parallel-fast-v365.log` and
`build/vr/parallel-slow-v364.log`. These runs use `uv run --no-sync poe test`
with the corresponding slow option, preserving the already installed extras.

No cases are pruned and no texture corpus is upscaled. Plain pytest remains
serial, and `poe test -n0` permits serial debugging. Live-game visual comparisons
remain opt-in and serial, with their existing parallel-execution rejection.
CI already calls the developer task and needs no extra workflow step. No game,
headset session or renderer build is started for this work; the prepared private
VR installation is preserved. Local measurements do not guarantee identical
timing on other hardware or prove physical headset readiness.

### Independent Pimax standby controls (16 October, v367–v368)

The live vendor server still has the same verified process identity as the
earlier slow sample. No GK3, SteamVR server or compositor is running during
these controls. Use the installed native Pimax OpenXR runtime, not the game or
a replacement runtime, with the same independent Vulkan probe, 180 rendered
frames, opaque interface layer and four milliseconds of simulated CPU work.
Its eye target is **4312×5102 per eye**. This is not the larger SteamVR target
from v357, and rates from those workloads must not be treated as a matched
renderer comparison.

v367 measures **17.05 submissions/sec** initially. Temporarily change the
vendor's existing `standby_timeout_min` from 3 to 0 with readback. The unchanged
probe reaches **116.71/sec**, without a process restart. Restore the original
value of 3 and repeat: **117.35/sec**. All three cases have 180 valid-but-untracked
poses (view flags 3), plus one initial frame with no view flags. Mean frame wait
falls from about **52.29 ms to 3.92 ms**. Neither tracking nor focus is forged,
and no game/native renderer code is changed. The original preference is verified
restored. Evidence: `build/vr/vendor-standby-control-v367.json` and its raw state
CSVs.

This shows that the slow vendor state can clear without restarting the server.
It does **not** yet establish that standby is the triggering cause: changing a
setting may wake or reconfigure the driver for another reason. v368 therefore
compares one-minute and zero-minute settings around actual **75-second idle
intervals**. Rates remain **116.75 → 117.34/sec** and **117.98 → 117.99/sec**,
respectively. The short idle experiment does not reproduce the slowdown. The
same server remains alive and the original three-minute preference is restored
again. Evidence: `build/vr/vendor-idle-control-v368.json` and raw state CSVs.

Read-only vendor status still reports headset present/service-ready, unmounted,
not visible and zero head-tracking flags. No firmware, display mode, SteamVR
global setting or normal-game file is altered. This is an unworn workbench
control, not a player fix, sustained game performance or physical acceptance.
Do not add automatic vendor preference changes or restarts to the launcher.

For interpretation, the [Khronos view-state reference](https://registry.khronos.org/OpenXR/specs/1.1/man/html/XrViewStateFlagBits.html)
explicitly distinguishes valid last-known/inferred poses from actively tracked
ones. Pimax's [tracking-mode guidance](https://support.pimax.com/en/support/solutions/articles/60001644608-pimax-headset-tracking-mode-is-abnormal)
also identifies Reclined Mode as a possible cause of reduced tracking, but that
is a research lead, not evidence that this machine has that mode enabled. No
undocumented setting is changed on that assumption.

v369 waits **200.05 seconds** after restoring the original three-minute timeout,
without game or XR frame activity. The independent probe returns to **17.05/sec**.
Writing the unchanged value of 3 does not wake it: the next session remains
**17.05/sec**. This strengthens the idle/standby explanation and rules out a
generic same-value configuration write as the earlier recovery mechanism.
It does not yet explain why the one-minute control did not reproduce it, or
prove behavior while the headset is worn. Both vendor-status snapshots retain
visible=0, mounted=0 and head_flags=0; the same server process remains alive and
the three-minute preference is unchanged. Raw evidence is
`build/vr/vendor-idle-recheck-v369.json` and its two frame-state CSVs.

### Current player with the reversible idle control (v370–v372)

Keep the already verified private installation instead of recompiling and
removing it around each graphics test. The ignored workbench now explicitly
supports reuse, verifies all seven owned-file hashes before/after and retains
that installation in failure cleanup too. The ordinary installation workflow
is not changed.

v370 does not reach gameplay: it renders more than 4,500 title/interface frames,
but the graphics-only startup observer searches an unrelated desktop capture
and never finds Play. Its failed-case cleanup also removes the prepared player
despite the new inner reuse mode. v371 therefore fails preflight without
launching GK3. Neither case qualifies gameplay or performance. The private
player is restored from the same verified v348 artifact, and the failure-cleanup
path now respects explicit reuse. For physical graphics timing, capture the
actual game client, use the four live native title-button rectangles and fail
within seven seconds if no verified target exists. No guessed click, longer
startup deadline, tracking override or native player behavior is introduced.

v372 temporarily sets the vendor standby timeout to zero, then launches the
current installed player through actual SteamVR and the registered physical
Pimax driver. One verified Play click reaches R25/110a. Its twelve-second
capture-free interval averages **119.41 stereo submissions/sec**. Native
Quit → cancel → resumed stereo → Quit confirmation exits normally. The whole
game qualification takes **38.12 seconds**. All owned player files, private flat
files and display preferences remain unchanged; SteamVR stops gracefully and
its global configuration hashes are unchanged. The same vendor server remains
alive and the original three-minute standby preference is verified restored.
An independent public `vr verify` passes afterward. No game or SteamVR session
is left running.

The process-matched compositor trace contains **1,561 unique frame records**:
GPU median/p99 **4.40/7.19 ms**, client interval median/p99 **3.53/7.02 ms**,
with no reported dropped or mis-presented frames in that sample. These are
compositor statistics, not proof of delivered frames or worn-headset pacing.
Both inspected compositor-eye previews are still obscured by SteamVR's gray
tracking-loss safeguard. The physical device reports valid=0, tracking result
201 and activity=0; no tracking or wear-sensor result is overridden.
The compositor mirror is 5012×5928 per eye; this is **not** a measured OpenXR
swapchain size. Do not infer the game's eye extent from either that mirror or
the separate discovery-only probe.

Evidence is under `build/vr/steamvr-native-20261011-mirror-physical-standby-game-v372/`
(`world.json`, `world-run.json`, process-matched timing CSV and both raw/preview
compositor eyes), with vendor preference restoration in
`build/vr/physical-standby-game-v372.json`. The renderer remains SHA256
`66258b64471867179e84ae21a9ef13f996e9c368facafc01db99e70f8603269a`.
This closes the current-build graphics-path check with a reversible idle-state
control. It does not qualify physical controllers, tracking, readability,
comfort, continuous refresh-rate-budget delivery or a shipped vendor workaround.

### Player-facing tracking feedback (16 October, v374–v386)

The actual physical-runtime tests show why submitted frames alone are not a
useful tracking diagnosis: a valid last-known head pose can continue rendering,
while the input guard correctly rejects all VR controller actions. The public
launcher now explains sustained tracking loss and recovery instead of leaving
those controls apparently unresponsive. This changes neither safety gating nor
the definition of fatal renderer/session failure.

The native runtime reports tracked, untracked or unknown observations to an
optional diagnostic sink. Partial orientation/position tracking remains
untracked. Hidden or failed frames, session focus/state withdrawal and teardown
clear stale observations; those unknown states do not themselves diagnose a
headset failure. Repeated unchanged observations do not write output. A failed
sink cannot interrupt legal rendering or bypass input guards.

The renderer writes these rare transitions to the launch-owned
`tracking-status.txt`, closing/flushing each record independently of its buffered
renderer log. Its path is set only in the sanitized child environment. The
launcher reads at most 64 bytes per observation, ignores partial/unknown records
and waits for one second of stable state before reporting a change. Rich owns
the user-facing text. There are no new dependencies, user flags, global runtime
changes or engine bridge ABI changes.

Native lifecycle tests exercise full/partial tracking, recovery, unchanged-state
suppression, hidden/stopped sessions, recreation and a throwing diagnostic sink,
alongside the existing release-to-rearm checks. The final six native test groups
pass in **1.70 seconds**. Python tests cover complete/partial/long records,
unknown observations, debounce, startup jitter, normal session continuation and
CLI wording. The complete Python VR group passes **275 tests, three skipped in
19.35 seconds**. Repository formatting, lint, strict types and spelling pass.
The full fast suite passes **5,477 tests, 23 skipped in 30.13 seconds**, while the
native build also runs; no live game runs during that test suite.

The preliminary v376/v381 builds are not installed. v384 is built from the final
source, passes the native, ordinary GPU and actual-GPU XR transport checks and
is independently inspected before replacing only the prepared private player.
The previous v348 build is retained. The current renderer SHA256 is
`a9fc7d9310779932312cac11245f3b4f2510f7f0d8d922780a92a36d29c11611`.

v385 launches this installed player through the **public CLI** and actual
SteamVR/Pimax. It emits exactly one real "Headset tracking unavailable" warning,
states that VR controller input is paused, and continues into R25 with **119.74
stereo submissions/sec** over twelve seconds. Native Quit/cancel/confirmation,
unchanged private player and flat files/preferences, graceful runtime shutdown
and unchanged global configuration pass in **38.54 seconds**. The reversible
vendor idle control is again restored to its original value. Raw native records
contain untracked → unknown → untracked, with no false tracking-recovery message.
Evidence is under
`build/vr/steamvr-native-20261011-mirror-physical-standby-game-v385/`, with preference
restoration in `build/vr/physical-standby-game-v385.json` and build/test logs under
ignored `build/vr/`. No tracking result is forged and no game/runtime is left
running. Physical recovery, aiming, readability, comfort and headset delivery
still require their separate acceptance checks.

### Physical wake control and actual-runtime tracking recovery (v388–v390)

The independent vendor status still reports present/service-ready, unmounted,
not visible and zero head-tracking flags. Pimax's
[screen-off guidance](https://support.pimax.com/en/support/solutions/articles/60001506972-troubleshooting-screen-off-issue)
describes stationary-headset sleep and physical movement as a wake condition for
Crystal Light. That is relevant background, not proof of the cause on this
connected Crystal or permission to synthesize its wear/tracking state.

v388 performs one bounded display-idle control without starting SteamVR or GK3:
temporarily change the existing vendor `enable_screen_saver` setting from 1 to
0, verify readback and collect 22 real status samples over about five seconds.
Every sample retains zero tracking flags; neither visible nor mounted becomes
true. Restore the original setting and verify it independently. The same vendor
server remains alive. This control does not restore real tracking and is not
adopted by the player. No tracking/wear sensor result, firmware, calibration,
rendering safeguard or undocumented device mode is changed. Raw evidence is
`build/vr/vendor-display-wake-v388.json`.

Separately qualify the new feedback and release-to-rearm behavior through actual
SteamVR using the **isolated diagnostic head/controller driver**, not the
physical Pimax. v389 receives the correct tracked → untracked → tracked public
messages but fails its fresh Inventory assertion: the generic screen-staging
harness had left the native VR input adapter disabled. It therefore does not
qualify controller loss/recovery. The new flow now explicitly returns input
ownership, as the existing controller flows do, and observes the real adapter
flag. Correct its Back test to right Index B, not stick-click/recenter. Neither
change is made to production input handling or its acceptance assertions.

v390 passes in **28.06 seconds**. Public CLI feedback reports tracked →
untracked → tracked exactly once each. The raw SteamVR head probe confirms
invalid then valid hardware-fixture poses. During loss, original presentation
continues, the world ray is unavailable and Inventory cannot open. Recovery does
not replay the held Inventory action; after neutral input, a fresh press opens
the native inventory and right B returns it to the world. The final adapter flag
is **1**, so these are real native controller behavior assertions, not merely
tests of an inactive adapter. Native host-driven Quit/cancel/confirmation exits
normally, the supervisor has no errors, the prepared private installation and
flat files/preferences remain unchanged, global SteamVR configuration hashes
are unchanged and runtime shutdown is graceful without forced components.
This qualifies the actual runtime/player/CLI recovery path with diagnostic
devices, not physical controller bindings or worn-headset recovery.

Evidence is under
`build/vr/steamvr-native-20261011-mirror-tracking-feedback-recovery-v390/`
(`tracking-feedback.json`, `world.json` and `world-run.json`). The current
verified renderer remains v384; no production source or renderer binary is
changed for these checks. No game/runtime session is left running.

The current full developer regression command, `uv run --no-sync poe test --slow`,
passes **5,879 tests, 23 skipped in 84.15 seconds** (v391). Together with the
current fast result of 5,477 tests in 30.13 seconds and the six native test
groups, this revalidates the Windows test-time budgets after the tracking
feedback implementation. Formatting, lint, strict types and spelling also pass
(v392). No game or full texture-upscale batch runs as part of this suite. The
private player independently verifies afterward; vendor screen saver=1 and
standby timeout=3 are read back, with no game or SteamVR session left running.

### Readiness and remaining-blocker audit (16 October, v393)

Completion is not established. Recheck the six first-release categories against
the actual source and current artifacts rather than converting local test
milestones into a headset-ready claim:

- Rendering/comfort: original-engine stereo, runtime eye geometry, independent
  Gabriel-height viewing, safety fades and native scripted-camera/conversation
  cinema ownership exist and have local evidence. Unobscured physical stereo,
  scale, readability and comfort are still unverified.
- Controls/gameplay: the connected native save/restore/SIDNEY/map/movie routes
  are recorded, and v390 qualifies actual SteamVR diagnostic-device tracking
  loss/recovery with native input enabled. This does not establish physical
  bindings, aiming, subjective usability or a representative headset playthrough.
- Performance: v385 measures the current player at 119.74 stereo submissions/sec
  under a reversible vendor idle control. Independent idle controls identify a
  repeatable slow state. Neither proves delivered headset frames or sustained
  performance while worn; loading/transition tails also remain open.
- Delivery: the current private installation independently verifies, including
  all **nine dormant launch switches**. Native Quit/cancellation, isolated
  removal, error handling and preservation checks are recorded. Headset
  reconnection, full supported-flow automation and release qualification remain
  unchecked. Nothing is published or committed for this audit.

A fresh vendor API query still reports present/service-ready, visible=0,
mounted=0 and head_flags=0. The Windows present-device inventory finds Pimax
endpoints but no alternative headset endpoint; that alone is not a definitive
device-discovery API, so it is not used to claim other headsets are broken or
unsupported. Earlier actual OpenXR and compositor evidence corroborates missing
physical tracking on the connected device. The bounded display-wake control did
not restore it, and its original setting is verified restored. There is no
running game/runtime process to wait on.

This same physical-tracking condition has persisted across the independent
idle controls, native feedback implementation, actual-runtime recovery check
and this audit. Those stages made concrete progress; repeating them now would
not close the first-session gates. No new demonstrated software defect justifies
a speculative patch, tracking override, firmware change or more renderer
swapping. The next critical-path evidence requires the physical headset to wake
and track, and tracked controllers for interaction, followed by the short
acceptance procedure above. Waking/moving the device and checking SteamVR does
not itself require wearing it; subjective comfort acceptance eventually does.

The goal is unfinished and blocked at this external validation boundary, not
marked complete. The verified private v384 player is retained, normal game
files are untouched, and no game/SteamVR session is left running. Work can resume
from this installed build after genuine tracking becomes available, without
repeating the prior setup or altering global calibration.
