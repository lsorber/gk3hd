# Native OpenXR component

Development prototype, not yet qualified for headset play. The isolated player
connects GK3's original world and interfaces to native OpenXR. See
[the implementation plan](../../../../VR.md) and
[release checklist](../../../../VR_CHECKLIST.md) for the current evidence and
unfinished acceptance gates. The integration notes below include earlier-stage
experiments, not a replacement for those current-status documents.

For development, use a private game copy rather than the installed flat game:

```shell
uv run gk3hd vr build --game-dir PATH_TO_PRIVATE_GAME
uv run gk3hd vr install --game-dir PATH_TO_PRIVATE_GAME
uv run gk3hd vr verify --game-dir PATH_TO_PRIVATE_GAME
uv run gk3hd vr launch --game-dir PATH_TO_PRIVATE_GAME
uv run gk3hd vr uninstall --game-dir PATH_TO_PRIVATE_GAME
```

Build runs renderer qualification and install independently verifies the private
renderer/player. Launch activates dormant VR hooks before the child starts,
selects a compatible 32-bit runtime without changing the global selection, and
supervises the child until exit. Windows and a suitable native build toolchain
are currently required. These commands are explicitly opt-in and are not part
of ordinary `gk3hd install` or package releases.

Stereo world resolution comes from the runtime's recommended per-eye dimensions,
including distortion/supersampling requirements. The separate 1280×800 windowed
desktop mirror and native interface source canvas do not cap those dimensions.
The isolated VR player protects flat display preferences from mirror writes and
retains the native brightness interface in windowed mode. Headset text quality,
comfort and sustained performance remain acceptance gates.

Build the complete opt-in renderer candidate from pinned sources:

```powershell
pwsh -NoProfile -File src/gk3hd/renderer/build.ps1 -OutputRoot build/vr/renderer -OpenXR
```

The output directory must be new. The recipe activates the pinned x86 toolchain,
downloads dependencies into that directory, runs native XR, ordinary GPU, and
XR GPU transport tests, and produces a `*-xr-prototype.dll` with notices and provenance.
It does not install or publish anything. The normal release commands deliberately
reject this prototype filename. Without `-OpenXR`, the usual renderer is built.

In this candidate, `GK3HD_XR_PROTOTYPE=1` enables XR bootstrap before Vulkan
initialization. A compatible runtime and headset are required, and startup
fails explicitly if they are unavailable. Without that process-local variable,
the candidate follows the flat renderer path. Do not set it persistently.
This is a development switch, not a player-facing VR launch command.

The C++ library owns the OpenXR instance, session, local tracking space,
two independent eye swapchains, and frame lifecycle. Vulkan instance/device
creation follows the runtime's `XR_KHR_vulkan_enable2` contract. The host retains
ownership of Vulkan objects and must submit image writes before releasing each
eye, with queue access externally synchronized. Drain GPU work before shutdown.
Destroy XR resources before
destroying the graphics device. No initialization is permitted from `DllMain`.

The Khronos loader is statically linked, so no separately installed SDK or
untrusted loader DLL from the working directory is required. Loader and Vulkan
header sources are pinned and downloaded only into the build directory.
Their upstream licenses must accompany any distributed binary. Nothing from
this development component is a newly published renderer artifact.

Build on Windows using CMake and the existing Visual Studio x86 toolchain:

```shell
cmake -S src/gk3hd/renderer/vr -B build/vr/native -A Win32
cmake --build build/vr/native --config Release --parallel
ctest --test-dir build/vr/native -C Release --output-on-failure
```

`build/vr/native/Release/gk3hd-xr-probe.exe` checks actual 32-bit runtime and
headset discovery. It does not test rendering, controller input, or comfort.
`gk3hd-xr-input-probe.exe` separately creates actions and suggests bindings on
the selected runtime. It does not start a session or test physical input.
The local SteamVR probe currently fails its first hand-path lookup without an
attached headset. Actual binding acceptance remains unverified.
A failed headset lookup is expected on a machine without a headset.
The mock lifecycle tests do not need SteamVR, a headset, Vulkan drivers, or game
files. They exercise two-eye submission, ordering guards, invalid poses,
hidden frames, runtime positive result codes, partial initialization, retries,
and cleanup. Passing them is not evidence of playable game integration.

The engine-camera adapter converts runtime FOVs into GK3's canonical clipping
space, including asymmetric frustum shear and conservative sphere-culling
bounds. Private experiments verify projection/outcodes against the original
engine routines and redraw both static room geometry and actors from frozen
eye poses. Readback captures are diagnostic only, not a production transport.
The Sarek integration patch routes Vulkan instance/device creation through the
runtime, selects its GPU, creates an XR session, and wraps its eye images without
owning their memory. Device recreation closes the session after draining GPU
work, while retaining the shared XR instance. The full candidate builds and
passes ordinary GPU renderer checks with XR disabled.

`Gk3hdXrFrameV1` is a private, fixed-width frame bridge described in
`frame_bridge.h`. It returns predicted eye poses and accepts a separately rendered
D3D target for each eye. Transfers are GPU-only, preserve encoded game colors
through UNORM conversion plus a compatible sRGB copy, and submit writes before
image release. The host serializes queue access without a normal-path GPU-idle
wait. Runtime-owned eye images are never initialized by the application.
The unreleased bridge also returns the fixed-width input snapshot described in
`input_bridge.h`, sampled at the same predicted display time as the eyes.

`Actions` owns the OpenXR action set, profile suggestions, and session-bound
pointing spaces. Both hands have aim, select/back, menu, inventory, recenter,
and stick inputs. Core Simple, Touch, Index, Vive, and Microsoft motion profiles
have provisional suggested bindings. No system/dashboard button is bound.
Valid core binding suggestions must be accepted, even without that hardware.

The supervised launcher also supplies a child-only tracking-status path. The
native runtime reports changed tracked/untracked/unknown observations through
an optional diagnostic sink; the renderer closes each record promptly, without
depending on buffered renderer logs. Hidden/failed or stopped sessions withdraw
stale observations. The launcher debounces feedback and owns the displayed text.
Diagnostic failures cannot change legal presentation or input safety. This is
not a tracking substitute or evidence of physical headset readiness.
Back, Menu and Inventory work from either tracked hand while the pointing hand
remains stable. Trigger selection belongs only to that pointing hand. Shared
shortcuts preserve per-hand release arming and the native priority/cancellation
rules. This does not yet qualify convenient switching of the pointing hand.

Focus loss neutralizes input immediately. Lost or invalid tracking neutralizes
the affected hand. Button/action/profile/session recovery requires releasing
held buttons, and stick recovery requires returning to neutral. Input errors
cancel the frame and discard stale snapshots. The action set survives graphics
device recreation; action spaces close before the session and the set before
the instance. Native tests verify these contracts without a headset.

The build also runs `gk3hd-xr-transport-tests` against a separate test-only runtime.
Synthetic tracking is not a headset, but images and transfers use the actual
Vulkan GPU. The fixture checks 16-bit/32-bit sources and RGBA/BGRA eye targets,
separate eye pixels, mid-tone colors, orientation,
image reuse, cancellation, controller snapshots and tracking recovery,
invalid ordering, and device recreation. Its CPU
readback exists only in the test runtime. Neither that runtime nor the test
executable is installed or registered persistently.

`Gk3hdXrSceneV1` coordinates a frozen authored camera and two predicted views.
The profile-checked `VRSceneCompiler` scopes the original engine's camera and
CPU projection state, clears each eye's color/depth, and redraws geometry and
actors without advancing simulation between eyes. It restores authored state
and preserves the ordinary center draw for desktop history and picking.
Failed clears cancel the eye transaction. Hidden frames do not draw eyes.
Focused controller recentering resets the seated tracking origin through this
coordinator. The private input adapter described below routes other actions
through native game interaction in the opt-in development player.

The scene request also supplies a profile-checked native BSP segment query.
Wall protection casts from the authored interior to each predicted eye, extended
by the current near distance plus 10 cm. Both eyes share the lower visibility,
fading to opaque black before a surface reaches the near plane. Tracked poses
continue unchanged, and obscured world input is withheld. The private request
is 252 bytes on x86; patch and renderer must be built together. Unit tests and
private hotel-room/lobby approach, crossing and retreat tests pass. Movable
actor geometry, broader scenes and physical-headset comfort remain unqualified.

The compiler has passed isolated live-game tests in the hotel room, lobby, and
outdoor village at 1024x768 and 1280x800, plus more than 2,500 stereo pairs across
scene transitions in one process. All tracking in those tests is synthetic,
and the GPU fixture uses 256x256 eye images. These results are not headset
presentation, a VR performance benchmark, or full-game coverage.

The opt-in development commands compose this compiler into the private player,
not the normal flat patch plan. Broader render-state qualification, calibrated
world-scale acceptance and actual headset tests remain incomplete. The native
interaction, panel and accepted-brightness integration described below are
development components, not a public playable release.

`Gk3hdXrPanelV1` now presents an explicitly selected 2D canvas in its own opaque
OpenXR quad swapchain. `panel_bridge.h` defines its sized request, physical pose
and extent, logical pointer coordinates, and focused input snapshot. The target
pixel dimensions must match the requested canvas. Panels preserve aspect ratio,
anchor upright in local space when opened, stay fixed while the head moves, and
support explicit/controller recentering. Close makes the next opening establish
a fresh anchor; it does not submit a new XR frame by itself.

The same geometry is used for composition and controller intersection. Rays
outside the panel or behind its invisible back do not hit, and tracking/focus
loss neutralizes input. Native panel tests cover both hands across the canvas,
movement, reopening, recentering, invalid placement, and aspect ratio.

GPU tests exercise 128x128 and 320x240 canvases without CPU source readback,
including canvas mismatch recovery, encoded mid-tones, resize/reopen, exact
submitted pose/size correspondence, both-hand edge picking, world/panel/world
transitions, and device recreation. Both RGBA/BGRA XR targets and 16-/32-bit
game targets pass. The producer context must finish deferred full-screen clears
before the separate XR transfer context reads its image. The bridge does so
without a normal-path device-idle wait or a source readback.

The private `VRPanelCompiler` chains after the existing engine final-page
presenter, preserving its cursor and interface composition. The legacy bridge
uploads that target's dirty DirectDraw pixels before the quad reads them.
Actual map, SIDNEY-home, and right-click-menu pages have been captured in the
isolated game at 1280x800 and compared to desktop pixels. A GPU regression also
checks that a newer CPU-authored page replaces the previous 3D image before
Flip, for both target formats and 16-/32-bit game sources.

The scene and completed-page hooks now share `FrameScheduler`: a deferred world
draw keeps its XR frame open until the panel presenter finishes it. World and
panel use one predicted tracking/action snapshot and one submission. Close
finishes a pending world without opening another frame. Hidden updates remain
sampled until completion; raw diagnostic calls cannot steal a coordinated frame.
Invalid UI and duplicate world draws cancel instead of publishing partial work.
Submission failure clears ownership before reporting the error, preventing a
second end. Standalone scene and panel gates remain usable for diagnostics.

GPU regressions inspect runtime counters, independently captured eye/panel
pixels, and input changed between the two hooks. They require exactly one
begin/sync and a two-layer submission, with neither eye overwritten by UI work.
An isolated original-game test switched through combined, world-only, panel-only,
combined again, and dormant modes without restarting or moving the host cursor.

This is not yet complete automatic interface integration. The panel still
captures the opaque finished game page rather than isolated transparent UI.
Complete world interaction, screen detection, and media/transition ownership
remain outstanding. Actual headset composition, readable text, input, comfort,
and full-game behavior remain unverified. Test-runtime image captures and
synthetic tracking are development-only, never a player fallback.

The private `VRInputCompiler` now routes panel Select and Menu into native GK3
mouse methods, reusing its existing per-interface coordinate inverses. Virtual
client-point queries keep cursor painting and hit testing consistent; mode-owned
warps never move the desktop mouse. Held selection cancels outside controls on
focus/tracking loss, pointer exit, hand/layer changes and mode closure, with a
release latch on recovery. Cancellation callbacks retain the virtual point even
while disabling the mode. Dormant hooks preserve normal host input.

Portable emulation tests verify those behaviors and event/caller ABI. A separate
test-runtime shared-memory channel can drive synthetic controller actions in
the private game process, with committed packet sampling/acknowledgment. It is
not part of the player renderer. Live tests opened SIDNEY email and returned
home, canceled six held-press cases without activating the button, highlighted
three driving-map locations and closed the native context menu. The desktop
cursor remained unchanged. These are actual game interactions with synthetic
tracking, not headset/controller acceptance tests or complete world interaction.

Controller Inventory and Back now pulse native I and Escape without needing to
point at the panel. Menu opens the native right-click toolbar at the pointed
canvas position or the center when not pointing. Shortcuts run once per press,
cancel held Select before changing layers, and require release after focus,
tracking, hand, or layer ownership changes. Native synchronous redraws preserve
desktop composition without resampling XR or starting another stereo frame.

The Windows message table identifies right-button callbacks at EngineLoop
vtable offsets 0x68/0x6c, not 0x50/0x54. The latter are middle-button callbacks.
Their corrected profiles also retain the native four-argument right-click and
two-argument middle-click dispatcher contracts. All host mouse buttons are
suppressed while this explicit VR input mode owns the pointer.

Back deliberately preserves the driving map, which does not handle Escape.
Opening it unloads the room. Force-popping its UI layer exposes an empty room
instead of traveling and is not a valid cancellation route. A private live
controller test leaves the map intact on Back, selects Cuiza station through
the native destination button, and verifies the rendered destination. The
same Inventory/Menu/Back sequence passes with stereo enabled. No desktop
cursor moves. The opt-in development player links these hooks; physical input
acceptance remains unfinished.

`WorldInputV1` now exports both controller ray segments and the input snapshot
from the same predicted frame as the stereo eyes. It uses the same authored
camera basis, recentered tracking origin and physical scale, independently of
desktop coordinates and eye FOV. Hidden/failing scenes, unfocused input and
invalid hand tracking clear ray validity rather than retaining the last pose.

The private `VRWorldCompiler` provides a render-thread entry with the native
Room3D picking signature. During that call only, scenery/actor intersection and
closest-hit comparisons consume a frozen controller segment and origin. Native
screen-rectangle filters are bypassed for the room and actor candidate list,
while selectable/resource checks and hidden-room rejection remain. Ordinary
mouse callers retain their original camera rays and rectangle filtering.
An x86 registration handler retires and disables this scope on native exception
unwind, without swallowing the exception or changing inner-handler recovery.

A private live gate compared both hands against same-update native screen picks
on Gabriel and static room geometry. Sixteen equivalent rays agreed within
0.001 game units. Two translated controller origins still hit the intended
static surface, and two rays beyond the desktop viewport hit geometry where
ordinary screen picking rejects the point. Tracking/focus loss rejects picks.
These use actual Vulkan and original-engine callbacks with synthetic poses,
not physical controllers. Portable tests separately exercise candidate filtering,
native caller/stack preservation and exception-unwind behavior.

`VRInputCompiler` can now explicitly link that picker. It freezes the completed
frame's controller ray before native event dispatch disables another stereo
submission during synchronous redraws. Room Select uses original noun/action
logic with a centered menu anchor, independently of the pointed object's screen
projection. Visible action menus and the right-click toolbar take panel priority
even though they remain children of the same room layer. Mode/hand changes and
focus/tracking loss retire held selection outside controls and require release.
Failed world/completion state cannot fall back to clicking a desktop object.

GK3's hover refresh normally depends on a changed mouse pixel. The world route
calls its original noun/tooltip producer for the current tracked ray without
inventing a camera-drag delta. The ordinary update and desktop picker remain
unchanged outside the scoped input transaction. Portable tests exercise native
dispatch, frozen rays, menu priority, failures, cancellation and handoff.

Live private tests with each hand pointed at the curtains, opened their native
action menu and selected Look, producing the original close-up camera. Both
hands also canceled held selection on tracking/focus loss without accidentally
opening a menu on recovery. A linked-world regression still opens/closes
Inventory and the toolbar, preserves the driving map on Back and travels to
Cuiza station through its native destination action. Host cursor position stayed
unchanged, temporary settings were restored and private processes closed.

The optional private `VRNavigationCompiler` links to completed world input.
Left stick moves the authored camera through GK3's original float translation
and collision commit at a maximum 0.8 metres/second, with a radial dead zone
and capped monotonic elapsed time. Right stick applies one 30-degree yaw step
per deflection and requires a full neutral return to repeat. Keyboard ramps,
physical mouse control and character movement are not used as substitutes.
The native camera input lock, panel ownership, failed frames and focus/tracking
loss stop navigation. Each hand independently requires neutral on recovery.

A private live check verifies native yaw deltas, forward movement, right strafe,
held-turn latching, neutral stopping, native camera locking, tracking/focus
recovery and Inventory ownership. It recorded 133 stereo pairs, twelve movement
callbacks and two snap turns. The desktop cursor stayed unchanged and the private
game closed. All controller input was synthetic, not headset acceptance.

The current scene bridge additionally queries the predicted controller segment
through the native world picker before drawing either eye. A depth-tested ring
marks that same hit in both eyes, with scoped drawing-state restoration. A thin
cyan beam leads from the controller to the hit. An eligible world miss shows a
1.5-metre beam without inventing an action target. Ownership rejection differs
from a miss: lost tracking/focus and visible native menus suppress the beam too.
The target
and action snapshot become valid only after successful frame transport. Actual
GPU checks cover depth occlusion, eye disparity, 16-bit/32-bit sources and
RGBA/BGRA runtime targets. A private curtains pick agrees with its native
reference within 0.000077 game units; the captured eyes were inspected. No real
headset or controller was used. Beam geometry clips against all six native eye
frustum planes, keeps its per-endpoint depth, and restores blending as well as
the other renderer state. Native math checks cover near-plane crossings,
offscreen/behind-eye segments, physical scale and invalid hits. Actual GPU checks
verify binocular projection, partial depth occlusion, miss feedback and removal
on tracking/ownership loss. The finalized private candidate passes the complete
renderer recipe, including both RGBA and BGRA paths. A private controller pose
25 cm to the side and 20 cm below/in front of the viewer produced inspected
stereo beam captures, with a native reference hit error below 0.000047 game units.

The executable adapter protects the outer scene and each eye with x86 exception
registrations. Search is side-effect free; escaping unwind restores authored
camera/projection/nesting and room cache, invalidates world output and disables
VR scene ownership without calling game methods or swallowing the fault. A
normal callback that bypassed native scene end is also restored and rejected.
Nested native redraws cannot overwrite the saved scene or resubmit XR. Portable
tests execute these instructions, and a loader-mapped synthetic PE verifies
nine real Windows exception/recovery cases. This is CPU scope restoration,
not acceptance of arbitrary engine/COM/runtime failure recovery.

The input adapter separately retires linked VR ownership on unwind and defers
outside mouse release or native key-up to a healthy update. Missing engine
ownership or another release fault retains pending cleanup; held actions need
neutral input before recovery. Seven actual Windows synthetic cases cover this
path. All fixtures are local, with no game assets or protection-policy changes.

The private executable now optionally links a native ownership classifier into
both world drawing and final-page completion. Free rooms use stereo without an
opaque desktop quad; visible action menus/toolbars use combined presentation;
modal/unknown interfaces and native camera locks use the interface panel only.
The classifier reads the original layer/child graph and camera state, without
modifying native locks or requiring per-screen VR toggles. Modal presentation
retires old world rays/targets even when no room draw occurs. A world-only
completion exports the already sampled controller state, creates no panel hit,
and cannot begin another XR frame. Actual GPU tests enforce those invariants.

The private-game gate passes automatic room/Inventory/room-menu transitions,
SIDNEY home and the driving map, with focused input in each mode. Both-hand
world actions and native navigation also pass with classification enabled.
These checks use synthetic tracking, not a headset. Dialogue captions now have
an isolated transparent layer, but other room HUD and menus still use the opaque
completed page. The classification is an increment, not complete media handling.

The caption producer exposes an explicitly keyed system-memory surface and
current-frame replay proof. The renderer converts only those producer pixels
into a premultiplied overlay, preserving black glyph outlines and leaving the
rest of the canvas transparent. No desktop/eye readback or background subtraction
is used. It completes the same deferred world frame, retains world input and
does not manufacture a panel pointer hit. Removing captions returns to world-only
presentation; Inventory still uses its ordinary opaque panel.

Caption font positions and measured blit bounds now share the final physical
transform. Cursor/save-under transfers cannot enter that recorder. Initial
native wrapping receives inverse-scaled width, with native line origins moved
alongside the box anchor. All stacked captions share the framebuffer-bottom
scaling anchor, keeping their original spacing proportional to glyph size.
Private-game tests verify long dialogue and three-caption stacks at reference,
Deck and 4K resolutions, including clearing and Inventory transitions. The final
4K stack has three distinct opaque glyph bands, not overlapping text. Portable
instruction tests also check native register/stack effects, caller-point/source
immutability, dense font scope restoration and excluded cursor transfers.

XR eyes, opaque panels and binary-keyed captions now use the accepted native
DirectDraw brightness ramp through the same swapchain blitter as desktop
presentation. Complete eye/opaque-panel images with identity ramps retain the
existing GPU-copy path. Cropped overlays use the exact-size drawing path even
with a neutral ramp, to preserve their canvas origin and clear their surroundings.
Non-identity ramps apply the correction once in UNORM before the compatible sRGB copy, without
CPU readback or a normal-path GPU-idle wait. Transparent pixels remain zero RGB
and zero alpha, including ramps that raise the black point. Opaque black glyph
outlines are corrected as actual black, not mistaken for transparent holes.
The shader's premultiplied flag uses DXVK's pipeline-constant range rather than
its resource-bound constants, and is reset after each draw.

Actual GPU regressions cover both eye targets, native-resolution opaque panels,
every caption pixel's coverage, mid-tone correction and exact image restoration
after returning to neutral. They pass for RGB565/32-bit game targets and both
RGBA/BGRA runtime formats, including device recreation. This validates submitted
pixels, not headset display calibration or non-binary HUD transparency.

The private `Overlay` operation can now compose up to 16 explicitly isolated
RGB565 system-memory surfaces into one transparent canvas. Each source supplies
its local crop, physical destination and an optional producer-owned colour key.
Opaque black remains visible; keyed holes retain earlier parts. Screen-edge
clipping does not rescale or shift source pixels. Completed game pages, render
targets and video-memory sources are rejected, and all source locks are released
before the GPU upload. A failed later part cancels the deferred frame without
submitting partially composed UI. GPU tests cover local origins, overlap,
clipping, resizing, both runtime colour formats and failure recovery.

Game captions and tooltips remain display-only: they retain the completed
world's input and cannot create a panel pointer hit. The renderer also accepts
explicit interactive parts, with per-pixel coverage built from the same source
crop, placement, clipping and colour key as the displayed image. Opaque black
controls are hittable; keyed holes are not. An opaque display-only part can
occlude an underlying control without becoming interactive itself. Each frame
builds its own mask, so withdrawing a menu cannot retain old hits. Ordinary
opaque modal panels keep their existing rectangular pointing behavior. This
is a renderer foundation; the verified native producers described below decide
which original interfaces can use it. Scaled tooltips now compose native
glyphs directly into an independent RGB565 system-memory cache, using a private
destination wrapper rather than borrowing the live page's surface or mutex.
The completed cache is copied only toward the flat page. Private-game comparisons
at 1280x800 and 4K match the previous tooltip pixels exactly, including changing
hover labels, replay and dismissal. The versioned cache ABI now publishes only
successful current-frame transfers. The paired VR presenter enables isolation
before native UI composition, including reference-height output, and releases
that ownership when disabled or unavailable. Flat reference-height rendering
keeps its original owner by default.

World-owned frames can submit captions and tooltips through the shared overlay
batch, with independent crops, positions, colour keys and publication counters.
Private actual-GPU controls pass tooltip-only at 1024x768 and 1280x800 and
caption-plus-tooltip at 1280x800; tooltip pixels match the same native desktop
crop exactly. Hover changes replace the source, dismissal removes it, and
neither source creates a panel pointer hit. Those early controls explicitly
overrode only panel ownership while a room menu was visible. They qualified
the label producers and transport separately from the later interactive menu
integration. Ordinary modal ownership continues to use its opaque page panel.

Native coverage tests exercise both hands at reference, Deck and 4K canvas
sizes, near all edges and the center, including key holes, source pitch/crops,
overlap, clipping, focus/tracking loss and withdrawal. Actual GPU transport
tests verify interactive versus display-only ownership without resampling the
completed world's input or duplicating XR frames. The full recipe passes flat
surface/helper tests and XR tests for both RGBA/BGRA runtime formats. Native
private-game caption/tooltip regressions still match the desktop crop exactly
at 1024x768 and 1280x800. Synthetic isolated control surfaces qualify the
renderer picking path, not original ActionMenu/toolbar capture or real-headset
interaction. A private native destination scope now qualifies ActionMenu icons
and the basic/expanded room toolbar without copying room pixels. It temporarily
binds an independently owned CPU destination during a complete native traversal,
then restores the original bitmap resource and return state. Reference, Deck
and 4K canvas controls match the normal menu pixels within one colour level;
native geometry predicts their fully opaque footprints exactly. Deck/4K toolbar
controls near all four screen corners also match. Optional package helpers now
reuse/clear bounded independent CPU surfaces and release changed, hidden or
destroyed owners. Child Blt/BltFast results are collected through a temporary
per-object Surface1 table, without changing the renderer's shared COM table.
Sources become ready only after successful child transfers and carry the native
successful-Flip generation. Before consumption, a validator rejects stale,
hidden/foreign roots and changed owners/extents. An exact-root destructor chains
the existing runtime wrapper. The private flat-game gate verifies reuse, close
withdrawal, restored bitmap/COM bindings and pixel fidelity at reference, Deck
and 4K sizes.
An optional x86 SEH termination handler restores the temporary destination and
COM table during unwind, without swallowing an exception or modifying a
resumable first-pass dispatch. Its exact stack registration prevents duplicate
or delayed cleanup. Native Windows controls pass normal return, resumed and
noncontinuable software exceptions, access violation and C++ throw, alongside
the private game's normal menu pixel/reuse/closure checks.

The current qualified path performs that complete widget traversal only once.
After restoring bindings and qualifying child results/footprints, it copies
the opaque body and optional popup to the ordinary desktop destination, at the
same clipped coordinates. Room-visible gaps are never copied. Failed allocation,
child transfer, footprint or mirroring retains ordinary native drawing with its
original destination/damage and withholds isolated publication. Native return
registers/flags and exception cleanup remain intact. The duplicate traversal is
retained only as a diagnostic primitive for controlled comparisons, not the
compiler's successful playback path.

`VRMenuCompiler` now verifies the complete original Runtime2D producer payloads
and menu bindings before installing dormant capture hooks. It rejects unsupported
exception metadata instead of disabling SafeSEH or other protection. Its query
validates cache lifetime and native page generation, then appends visible menus
in the original child order. Source crops, displayed placement and controller
coverage use the same clipped physical coordinates. Opaque black menu content
remains visible and hittable. Disabling XR withdraws cache ownership without
waiting for a hidden root to draw again.

The private `VRPanelCompiler` can compose those interactive menu sources with
display-only captions and tooltips over the stereo room, using the normal native
ownership classifier. Missing, stale or incomplete sources roll back the entire
menu batch and retain the opaque-page fallback. Modal interfaces still use the
opaque panel. Resolution dropdowns now use two independently qualified crops
from the same native cache: toolbar body and deferred popup. Their shared
footprint leaves room-visible gaps transparent and unhittable. Changed popup
identity, visibility, geometry or pre-union bottom withdraws publication.

Actual-GPU private-game tests at reference, Deck and 4K canvas sizes match the
initial toolbar's desktop RGB exactly, and synthetic controller clicks open
settings, display, graphics and advanced graphics sections. All three sizes
also cover pointing at all four corners, controller Back closure, disable/reopen
and resolution-list pointing without claiming the gaps beside its lower rows. Both
simulated hands select a room object, hover its isolated ActionMenu and invoke
its native action without moving the host mouse. These gates qualify current
game/renderer integration, not physical-controller bindings, headset readability,
production VR performance or full-game acceptance.

This is not yet a complete playable VR mode. Movie/scripted-camera qualification,
isolated transparent HUD/UI, text entry, panel pointing UX, comfort
transitions and head-lean wall masking remain open, along with actual-headset
scale, readability, brightness, performance and complete-game coverage. Public
installation/launch and Proton OpenXR qualification remain incomplete too.
All controller poses/actions above are synthetic.

The GPU test runtime normally reads submitted eye/panel pixels back every frame
for fidelity checks. Its explicit development-only
`GK3HD_XR_TEST_SKIP_PIXEL_READBACK=1` mode retains submission/lifecycle validation
but refuses pixel queries and simultaneous file-capture requests. This allows
lower-bound transport timing without diagnostic readbacks. It is not a headset
compositor or an end-to-end VR benchmark. The player DLL has no such readbacks.
The legacy device now owns a reusable overlay buffer under its existing bridge
lock. Each batch clears the preceding clipped footprint, including picking
coverage, rather than reallocating/zeroing the entire canvas. Resizing validates
and allocates before replacement. Abandoned batches cannot leak pixels or hits
into later frames. The GPU upload now covers only the clipped union of explicit
producer rectangles. A grow-only texture capacity avoids reallocation when a
label or hover changes. Uninitialized capacity padding is neither uploaded nor
sampled. Exact-size GPU placement retains full-canvas geometry and input mapping,
and clears the remaining panel to transparent zero, including old menu pixels.
Entirely clipped batches submit an explicitly transparent pixel, not a blitter
rectangle whose empty extent would mean the complete image.

The test runtime accepts `GK3HD_XR_TEST_EYE_SIZE=1440x1600` (or another strictly
validated size between 64 and 4096 per axis), captured at instance creation.
An unset value retains the 256x256 fidelity fixture. These settings are not
player options. The build's fidelity checks clear both profiling overrides and
restore their invoking environment afterward.

At a 4K desktop canvas, reusable buffers raise isolated toolbar throughput from
about 62 to 90 fps and the expanded resolution list from 32 to 45 fps. Tests
with 1440x1600 and 2048x2048 runtime images per eye reach about 119–120 fps for
world-only stereo. The engine still draws both eyes into its 4K target, then
scales each to the runtime image. These short synthetic measurements exclude
diagnostic readbacks and headset-compositor costs, so they do not certify
headset performance. Native menu drawing and the duplicate capture traversal
remain bottlenecks and prerequisites for real-headset acceptance.

Cropped uploads subsequently raise the isolated toolbar to about 116 fps in a
short 4K-canvas / 2048x2048-eye experiment; the expanded list reaches only about
49 fps. Overlay composition/upload/submission falls to approximately 0.65 ms
for the toolbar and 2.95 ms for the list. The fresh recipe passes both runtime
image formats, moving/shrinking/clipped/empty overlays, exact colors/alpha and
gamma/reset tests. Private game dropdown pixels and pointing pass at reference,
Deck and 4K canvas sizes, as do both-hand native world/menu/action transactions.
Those synthetic results still do not qualify sustained headset frame timing.
See [the first-release checklist](../../../../VR_CHECKLIST.md) for remaining gates.

Batched RGB565 conversion subsequently reduces expanded-menu overlay
composition/upload/submission from approximately 2.95 ms to 1.27 ms. The short
synthetic expanded-list sample rises only from about 49 to 51 fps: native menu
drawing and the separate capture traversal still dominate. Native tests compare
all 65,536 source colors against an independent arithmetic oracle and cover
keyed holes, overlapping hit coverage, unaligned rows, tails and guard pixels.
The new qualified recipe passes the complete native and actual-GPU build gates.
This optimization does not resolve the expanded-menu performance release gate.

Single native traversal subsequently raises the expanded list to about 74 fps
versus 51 in a paired duplicate-draw control, using the same renderer and
2048x2048 runtime eyes. Toolbar samples are about 110 versus 104 fps in that
pair; earlier samples varied. The remaining native traversal takes about
4.5 ms for the expanded list, plus approximately 0.8 ms for desktop mirroring.
Independent ordinary-draw controls match its menu pixels exactly at reference,
Deck and 4K resolutions. Native Windows exception and failed-copy controls also
pass. These are still short synthetic tests, not headset frame-time acceptance.

The current private overlay producer contract also carries a finite opacity
between zero and one for each source part. Parts are now 40 bytes, so this
prototype DLL must be paired with the matching current patch compiler. Existing
menu, caption and tooltip producers explicitly publish opacity one. Fractional
opacity uses source-over premultiplied colors, while exact source keys remain
holes and black remains content. Zero-opacity parts contribute neither pixels
nor picking coverage. Invalid opacity rejects the batch before mutation.
The existing gamma shader is tested with fractional alpha on the actual GPU,
including raised black levels and reset to neutral. This qualifies fade
transport, not isolated room HUD production: native score/status capture and
object retirement still need implementation.

The private patch-side HUD source primitive now brackets an exact synchronous
TextBox capture, temporarily selecting opaque glyph drawing without its backing.
It restores all authored font-option words and backing opacity on return or
actual x86 SEH unwind, retaining the original result and resumable exceptions.
The isolated cache supports an explicit RGB565 key with tested setup failure
withdrawal. A native-game experiment matches the opaque status glyphs exactly
and withdraws them after expiration. This experiment uses a private query
override, not the final automatic HUD producer, fade/backing composition or
complete lifetime hooks. Those release requirements remain open.

The subsequent private automatic HUD compiler uses separate native opaque glyph
and backing sources, then publishes each with its authored fade. Ordinary Draw
runs once and capture-only failure cannot redraw onto the desktop. Publication
requires the exact live RoomLayer child and current qualified native page.
Hidden/modal/disabled state and the verified native destructor withdraw ownership
and release the source. The GPU private-game gate verifies fractional glyph
alpha/color, while a separate native backing oracle preserves the actual fill
color exactly. Fifty-one compiler behavior tests cover routing, clipping,
rollback and lifetime. The actual Windows capture-only exception harness passes.

At a 4K canvas with 2048x2048 synthetic eyes and no diagnostic readbacks, short
paired samples reach about 120 fps without HUD and 117 fps with status text.
Other HUD variants, complete-game transitions and real-headset readability,
comfort and sustained frame timing still require qualification. This remains
a private prototype, not a public playable VR release. See `VR.md` and the
first-release checklist for current evidence and remaining acceptance gates.

The patch now also has a private native save-name text mailbox. It qualifies the
actual SaveGame editor and dispatches original character/editing callbacks on
the game thread, with epoch-based cancellation on ownership or tracking changes.
An actual private-game test verifies insertions, caret movement, deletion, focus
loss and dialog closure without saving or generating host input. This is the
backend for a controller keyboard, not yet a displayed keyboard or qualification
of other text fields. See the latest text-entry evidence in `VR.md`.

The renderer library now also provides a readable, CPU-authored keyboard image
and an ownership-guarded ray/key model. Its modes cover printable ASCII and the
native sink's six editing keys, without Enter/Escape or host input injection.
Native tests verify labels, both-hand edge picking, stale epochs, held-input
suppression and occupied-mailbox behavior. An independent keyboard swapchain
can compose with the editor and stereo world in one runtime frame; lifecycle
and failed-wait cleanup tests pass. The current renderer wires this independent
quad to the private native text mailbox through `Gk3hdXrTextV1`. Actual GPU tests
verify labels, colors, selection isolation, event retirement and both runtime
color layouts. A private-game test types and edits the original save-name field,
recovers from focus/tracking loss without held-key replay, and closes the editor
without saving or moving the host pointer. Ordinary native text editors are now
qualified through the game's ordered character dispatch, rather than SaveGame
layout assumptions. A private-game controller test types a SIDNEY query, runs
the native search and returns Home with keyboard ownership retired. Remaining
custom editors and real-headset save/restore acceptance remain open. See the
latest evidence in `VR.md`.
