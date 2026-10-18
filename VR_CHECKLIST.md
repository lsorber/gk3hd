# First enjoyable VR release

Updated: 16 October 2026. Status: **development prototype, physical tryout fixes in progress**.

## First Crystal tryout: user feedback

The first worn-headset test now confirms genuine tracking and a useful stereo
experience. World scale felt correct, snap turning worked well and smooth
movement worked. These are user observations, not full-story/release acceptance.
They supersede the earlier untracked-hardware blocker recorded below.

- [x] Plausible world scale confirmed by the wearer. Preserve this calibration.
- [x] Discrete turning confirmed usable by the wearer.
- [x] Missing game sound traced to native master volume zero and restored to 100.
- [ ] Confirm sound in the headset, including dialogue/music and non-movie effects.
- [ ] Fix inventory item selection and verify real item actions, not just opening/closing.
- [ ] Keep an explicit, accurately aligned cursor visible on menus and interfaces.
- [ ] Position action menus near the pointing direction and reduce oversized controls.
- [ ] Raise full-stick observer movement to walking pace while retaining fine control.
- [ ] Add distinct observer teleport aiming, preview, release/cancel and safe destinations.
- [ ] Modestly enlarge the isolated room-status HUD without altering other text/fades.
- [ ] Prevent false corridor-lamp blackouts while preserving physical wall-lean safety.
- [ ] Verify and install the complete revised private player, preserving normal GK3.

The remaining historical evidence describes the pre-tryout validation boundary.

Current validation boundary: the connected physical headset remains untracked.
Independent pacing controls, public tracking feedback/recovery and current
regressions are recorded below. A fresh audit verifies the installed private
player and all nine dormant launch switches; no game or SteamVR session remains
running. The next useful evidence requires an awake headset and controllers
with genuine tracking. No further synthetic variant can close headset comfort,
readability or delivered-pacing acceptance. Broader story/transition checks and
release qualification also remain open; this is not a completed-release claim.

Target: Windows + SteamVR, seated head-tracked viewing of the original game,
with controller interaction and comfortable floating interfaces. Gabriel and
Grace retain their original gameplay. Proton and additional runtimes are later
validation targets, not prerequisites for the first release.

VR targets the headset runtime's recommended per-eye rendering size, including
its distortion/supersampling requirements. Supporting legacy desktop resolutions
in VR is not a release requirement. Desktop sizes may still be diagnostic cases.
The default desktop mirror and native interface source canvas are separately
1280×800 windowed. They do not set or cap the stereo world's eye resolution.
Interface source resolution and physical-headset text quality remain separate
quality checks.
The native-resolution path also passes a 4096×4096-per-eye private-runtime test,
with its full world view inspected in both compositor mirrors and the separate
desktop canvas still 1280×800. This is a larger workload, not a specific headset
qualification.

Checked means implemented and verified in local automated or private-game tests.
Most tracking/controller tests use synthetic devices. Registered physical-headset
discovery and Vulkan session creation now pass too, without a wearer.
A checked implementation milestone does **not** mean its real-headset acceptance
gate is complete.
The detailed design and evidence are in [VR.md](VR.md).

Working priority: **one enjoyable seated session first**. Close demonstrated
start, interaction, transition and exit blockers before adding optional modes
or polishing isolated screens. The state-scoped resource-preparation player passes
connected save/restore → SIDNEY → map/travel → navigation → Quit in 63.33 seconds
with the current wall-retreat and rendering-failure safeguards enabled.
It also completes moving-head movie playback/skipping, stereo recovery and normal
Quit in 53.50 seconds. Software
evidence is not physical-headset acceptance.

The critical path is now **valid physical tracking and measured headset pacing**,
then one short headset tryout for comfort, aiming and readability.
Core stereo, navigation, controller interaction, floating interfaces, text
entry, saves, SIDNEY, map travel and movies already have local implementation
evidence. Do not restart those features or exhaustively enumerate their variants.
The connected local routes and representative moving-load tests are already
covered. Repeat them only after a relevant change or to investigate a demonstrated
first-session blocker, rather than adding more variants as prerequisites.
Isolated cursor optimizations, alternate mouse controls, routine-test timing
and broader headset support are follow-ups unless they reveal a first-session
blocker. Keep release acceptance separate from implementation completion.

This checklist tracks release readiness, not a percentage complete. Update it
when a milestone gains test evidence or a regression invalidates an earlier
check. Keep unfinished implementation work separate from headset acceptance.

## First-release acceptance at a glance

Local integration coverage is substantial, but does not substitute for headset
acceptance. This overview separates those two stages:

Latest physical-runtime observation (v357): a fresh independent clear-only
OpenXR session through SteamVR uses the RTX 4090 at 5028×5948 per eye. All 180
frames retain valid-but-untracked poses, even though 179 report FOCUSED. It
submits 16.21 frames/sec; GPU work is 0.0618 ms median/0.0716 ms maximum while
the blocking OpenXR frame calls dominate. Normal exit, graceful runtime shutdown
and unchanged global configuration pass. This does not establish worn-headset
behavior or distinguish standby from a runtime/driver defect. The current
private player is installed, independently verified and dormant for later
physical acceptance; it is not left running or installed over the normal game.

Latest hardware checkpoint (v303–v306): restarting only the verified,
workbench-owned Pimax server restores independent native OpenXR rendering to
119.47/sec. A second independent session reaches 119.49/sec, the new
Gabriel-height player reaches **119.49 stereo submissions/sec at 4312×5100 per
eye through actual SteamVR**, and a subsequent independent session reaches
119.50/sec. GPU/client-interval p99 in the game is **6.80/6.60 ms**. Native Quit,
uninstall and graceful runtime shutdown pass with unchanged flat files and
global configuration. Observer Y=69.5 and restored authored Y=61.72 are verified
both initially and after twelve seconds. Tracking remains out of range (201).
This identifies recoverable persistent vendor state, not its triggering cause
or a player-side fix. No automatic vendor restart is shipped and physical
delivery/tracking/comfort remain unqualified.

Latest idle-state controls (v367–v369): the independent installed-Pimax runtime
changes from **17.05 to 116.71 submissions/sec** when its three-minute standby
timeout is temporarily set to zero, without restarting the server. Restoring
the original preference initially retains 117.35/sec; after **200 seconds of
idle**, it returns to 17.05/sec. Reapplying the unchanged preference does not
wake it. A shorter one-minute-setting control does not reproduce the slowdown,
so the complete vendor mechanism remains unproven. Original settings are
verified restored; tracking remains unavailable. These are independent runtime
controls at 4312×5102 per eye, not game performance or worn-headset acceptance.
No automatic vendor-setting change or restart is added to the player.

The current wall-retreat renderer/player also passes actual SteamVR R25
graphics timing under that reversible zero-timeout control (v372): **119.41
stereo submissions/sec** over twelve seconds, GPU p99 **7.19 ms**, native
Quit/cancel/confirm and graceful runtime shutdown in **38.12 seconds** overall.
Private player/flat files, display preferences and global configuration are
preserved; the original vendor preference is restored. Both compositor eyes
remain gray under the tracking-loss safeguard. This is not worn-headset or
physical-controller acceptance, and no vendor workaround is shipped.

Latest repeatability controls (v317–v322): the independent installed Pimax
runtime sustains **119.80 submissions/sec over 330 seconds** with a constant
4 ms CPU workload, while unfocused and untracked. A later session after a gap
returns to **17.05/sec** with the same visible/renderable state, nominal 120 Hz
period and valid-but-untracked views. Those OpenXR states alone do not explain
the slowdown. Idle handling versus session teardown remains unresolved; no
automatic vendor restart or tracking bypass is shipped.

Earlier update/repeatability checkpoints:

Pimax Play **2.0.4.329** is installed as a
coherent vendor stack. Its device service was stopped after installation;
starting it and the installed server restores discovery. The unchanged current
player/renderer completes Play → stereo → Quit/cancel → Quit → uninstall through
actual SteamVR at **4312×5100 per eye**, submitting **119.41 stereo frames/sec**
over twelve seconds. GPU/client-interval p99 is **7.55/7.64 ms**. Quit, runtime
shutdown and uninstall pass, with unchanged global SteamVR configuration and
flat game files/preferences. No firmware update or reboot was performed.
This improves the demonstrated old-stack half-rate symptom in that sample,
but is **not repeatably resolved**: v297 repeats the unchanged public player
and measures 17.17/sec. Independent installed-Pimax OpenXR rendering (v298)
also measures 17.09/sec with 55.66 ms average frame wait, outside GK3 and
SteamVR. Forced frame division reads 1 (disabled); no new setting is applied.
Resolve this vendor/workbench state before claiming sustained pacing.
Tracking is still out of range (201); delivered frames and comfort remain open.

Earlier hardware controls below used the old vendor stack and are superseded
for current pacing by v289. They explain why no speculative renderer workaround
was adopted:

The connected Pimax Crystal is discovered after
starting its installed vendor runtime. A real RTX 4090 Vulkan session and the
isolated game's Play → stereo → Quit/cancel → Quit → uninstall pass. The game
uses the actual runtime recommendation, 5028×5948 per eye in this sample, not
the 1280×800 desktop canvas. Global SteamVR settings/calibration and flat game
files/preferences are preserved. This is an **unworn graphics/session check**,
not physical-controller or comfort acceptance.

The physical driver reports invalid tracking. SteamVR's bad-tracking fade
obscures the compositor view in both the game and an independent clear-only
probe. Disabling that fade only in a private control removes the gray region;
it is not a GK3HD default or a fix to ship. Keep that safeguard intact.
The game's twelve-second sample submits about **59.91 stereo frames/sec**,
with GPU p99 **6.31 ms**, despite a 120 Hz headset and a clear-only probe near
119 submissions/sec. Do not present the earlier synthetic 121/sec results as
headset delivery proof. Physical tracking and actual-game pacing remain open.
Follow-up controls use the same 5028×5948 eye target. Projection-only and
projection-plus-transparent-interface probes both sustain about 119 submissions/sec.
The actual game remains near 60/sec over forty seconds, with fast movie skipping,
without the loading-frame helper in a diagnostic build, and with a valid synthetic
pose on the physical display. That pose removes the tracking fade but does not
fix pacing. Cursor copies/page preparation are negligible in the native trace.
Keep the normal safeguards and faithful color conversion intact; the remaining
performance work is frame timing, not speculative removal of those features.
An early-frame preparation candidate also reached its intended native boundary
and passed graphics/caller-contract checks, but still ran at 60/sec with the
same submission margin. It was rejected and removed from production code.
A reversible desktop-presentation control likewise measured 60/sec before,
during and after isolation. Do not repeat either approach as a likely fix.
An independent next-frame-wait control measures 68.58 versus 66.14 submissions/sec
without it, with the same eye size and synthetic CPU workload. Neither reaches
the headset budget or demonstrates a game improvement. It remains a private
diagnostic, not a new player mode or a release prerequisite.
A same-session independent control now reproduces near-60/sec pacing with four
milliseconds of CPU work and only 0.065 ms of application GPU work, returning
near 120/sec when the added work stops. Fixing private runtime sizing at 100%
also leaves the actual game near 60/sec. Investigate workload-sensitive runtime
scheduling next; do not treat automatic supersampling reduction as a fix or
remove faithful graphics features on that assumption. Detailed controls remain
in `VR.md`.
The already-installed native Pimax OpenXR runtime also reproduces the independent
CPU-work-triggered half-rate symptom. Diagnostic overlapping waits restore that
probe's rate, but actual-game samples with/without overlap are similar, about
107/105 submissions/sec, and both fail during Quit. Neither overlap nor switching
runtime is a qualified player fix. Keep the passing SteamVR session path while
investigating its pacing; do not turn runtime coverage into extra release scope.
The actual SteamVR overlap control also remains at 60/sec and is rejected.
Temporarily disabling vendor Smart Smoothing likewise leaves the game near
60/sec; its original setting is verified restored. Installed Pimax Play is
1.41.1.152 in these earlier controls, before the full 2.0.4.329 update. A standalone newer
DLL does not discover the headset against the old middleware. Do not weaken validation or ship a
mixed vendor stack. Driver/firmware installation and physical tracking remain
separate from the already-tested player features.

| Category | Local milestone | Still required |
| --- | --- | --- |
| Rendering | Stereo, floating UI, movie screens and real physical-runtime game/session startup exercised | Valid physical tracking, headset fidelity/readability and transition acceptance |
| Comfort | Recenter, wall protection, snap turning and loading-frame coverage implemented | Physical scale/comfort and remaining transition pauses |
| Controls | Controller aiming, menus, keyboard entry and input-loss safeguards exercised | Physical bindings, aiming and feedback |
| Gameplay | Connected saves/SIDNEY/map session, movies and moving-head native Virgo/Libra progression pass on current player | Representative story and headset playthrough |
| Performance | Fresh vendor state: independent probes and new physical-runtime player reach ~119.5/sec across four sessions; persistent ~17/sec state clears on owned-server restart | Identify stale-state trigger and qualify sustained headset delivery/frame-time margins |
| Delivery | Isolated build/install/verify/launch/uninstall and supervised runtime loss exercised | Remaining actual-headset failure/reconnection paths and release qualification |

These stay unchecked until the complete experience passes, even when individual
implementation milestones below are checked.

- [ ] **Rendering:** stable stereo, faithful colors and readable interfaces, without flicker or stale frames.
- [ ] **Comfort:** convincing scale, safe head movement, comfortable navigation and scripted transitions.
- [ ] **Controls:** dependable controller aiming, menus and keyboard entry, without pointer offsets or conflicting input.
- [ ] **Gameplay:** representative puzzles, movies, inventory, SIDNEY, map, save/restore and quit work end to end.
- [ ] **Performance:** sustained frame times meet the supported headset's refresh-rate budget in representative scenes.
- [ ] **Delivery:** straightforward installation and launch, useful failure messages, clean uninstall and unaffected flat play.

Hardware-path milestones:

- [x] Discover the connected Pimax Crystal through its registered driver and create a real RTX 4090 Vulkan session at the runtime-selected eye size.
- [x] Exercise the isolated VR game's Play/stereo, native Quit cancellation/confirmation and clean uninstall on that physical runtime, preserving flat play and global SteamVR settings/calibration.
- [x] Separate tracking-loss presentation from the pacing defect using a private synthetic pose on the physical display. Tracked OpenXR view flags and an unobscured native Quit interface pass, while the near-60/sec pacing persists. This is not valid physical tracking or worn-headset acceptance.
- [ ] Obtain valid physical tracking and inspect faithful, unobscured stereo output. The current unworn driver reports `Running_OutOfRange`; do not bypass SteamVR's tracking safeguard as a workaround.
- [x] Reproduce the independent vendor slow state after a measured idle interval and find a reversible recovery without restarting processes. The 200-second original-timeout control returns to 17.05/sec; a temporary zero-timeout control reaches 116.71/sec. The same-value-write control stays slow. Restore the original preference and retain raw frame-state evidence. This is diagnosis, not a shipped workaround or physical pacing qualification.
- [x] Check a bounded software display-wake control without spoofing tracking or wear sensors. Temporarily disabling the vendor display-idle setting does not restore real tracking across 22 samples; restore the original setting. Keep the physical-tracking gate open rather than treating device presence or renderable last-known poses as acceptance.
- [ ] Explain the recurring vendor-side slow state and qualify sustained physical-headset pacing. Fresh-state game and independent sessions reach about 119.5/sec, but the independent Pimax probe again measures 17.09/sec before the latest game test. The earlier 60/sec result used the old vendor stack.

## Next milestones

1. **Repeatable headset presentation.** Identify the recurring vendor slow-state
   trigger and sustain the demonstrated fresh-state 119.5/sec on the 120 Hz
   headset. Keep runtime-recommended eye resolution, faithful colors and the
   working loading protection. Compare independent runtime and actual-game
   samples; do not treat a one-off server restart as a shipped solution.
2. **Real tracking and interaction.** Qualify physical head/controller poses,
   aiming, bindings and readable floating interfaces. Investigate tracking
   readiness independently of pacing. Synthetic poses are useful controls,
   never a substitute for tracking or a reason to disable safety fades.
3. **One enjoyable seated session.** Start, look around, move, interact,
   use inventory/SIDNEY/map, save/restore and quit. Check comfort and transition
   continuity together. The core route already passes locally, so repeat it
   after relevant changes rather than adding exhaustive screen/puzzle variants.
4. **Release readiness.** Qualify straightforward install/launch/uninstall,
   failure handling and unaffected flat play on the accepted build. Then close
   the six first-release gates above against their actual evidence.

Performance and tracking are the current blockers, not missing optional gameplay
modes. Prefer bounded experiments with a specific hypothesis and stop pursuing
controls that do not demonstrate a useful benefit. Defer alternate runtimes,
mixed mouse/controller modes, automatic reconnection and cosmetic refinements
unless they are needed to fix a demonstrated first-session blocker.

Local implementation coverage includes stereo/navigation, controller interaction,
text entry, dialogue, movies, inventory, SIDNEY puzzles, map travel, saves and
exit/restart. The current connected route completes in about 65 seconds; detailed
timings, earlier variants and rejected experiments belong in `VR.md`, not in the
critical-path task list. Physical comfort and headset delivery remain unqualified.

### Scope of the first headset tryout

The first enjoyable experience is a coherent seated play session, not exhaustive
completion of every game puzzle or compatibility with every headset. Before
asking for a headset tryout, prioritize dependable start/restart, stereo head
tracking, safe navigation/camera transitions, controller interaction/text entry,
readable interfaces and a representative connected session without known blocking
regressions. Fix demonstrated failures in those routes first. Broader content
coverage, optional desktop-mouse controls and micro-optimizations are follow-ups
unless they expose a blocker in that experience.

A headset tryout then validates physical scale, aiming, comfort, readability and
delivered frame pacing, which the synthetic workbench cannot establish. It is
not a release claim or permission to check the six acceptance gates prematurely.
The current build still needs physical-runtime game qualification and that
acceptance before being called headset-ready. Do not invent additional interface
or exhaustive-content prerequisites without a specific missing capability or
demonstrated defect.

Current-pair movie verification now passes in **48.75 seconds**, including natural
completion, controller skipping, continuously moving head poses, stereo recovery
and normal Quit. A **101.88-second** capture-free performance session measures
thirty seconds each in the dining room and museum, with normal Quit, clean removal
and graceful runtime shutdown. Both preserve ordinary game files/preferences and
global runtime settings. These are substantial first-session checks, not new
feature implementations or evidence of physical-headset acceptance.

The current pair also passes supervised runtime loss during a natural loading
boundary in **28.92 seconds**: the loading helper submits three successful empty
XR frames over 20.18 ms without game rendering, then the launcher stops its owned
player and gives restart/unsaved-progress guidance. Physical disconnection and
reconnection remain separate gates. A staging capture error is retained in the
evidence rather than silently counted as a clean capture run.

Latest first-session checks: **33.27 seconds** for current-pair dormant play,
clean uninstall and a normal non-XR flat control, plus **33.33 seconds** for
raw-head wall crossing/retreat and held-selection safeguards in the first hotel
room. Both eye captures are fully black while protected and recover the scene
on retreat. A **66.43-second** connected save/SIDNEY/map/travel/Quit repeat passes
with 25 keyboard aims checked against coherent current panel geometry. This
improves the workbench's reliability, not a claim that every earlier intermittent
failure or physical-controller behavior has been resolved.

Latest blocking-defect correction: moving-head cinematic captures exposed
subtitle breakup/disappearance that static dialogue tests had missed. Separating
the subtitle and native-screen planes while preserving angular text size fixes
the sampled defect in both actual SteamVR compositor eyes. The same controller
conversation/Cancel/inventory/stereo/Quit flow passes. Physical readability and
broader transition qualification remain open.

Current qualification work: movies now fit their actual native content into a
fixed VR cinema area rather than retaining desktop padding. Unit and both-eye
fit checks pass. The new player now passes connected play and a complete movie
flow, including normal Quit and unchanged host cursor. A read-only mouse-device
observer distinguishes outside input from game-driven cursor changes during
qualification; neither passing run records such input. Earlier intermittent
failures and their unproven causes remain recorded, not retrospectively resolved.

Floating native menus now have a larger, stable physical scale, with the same
transform used for rendering and controller picking. Scores keep their ordinary
placement. Dialogue now has a separate enlarged, noninteractive subtitle plane,
with a stable bottom-center anchor independent of menu expansion and line length.
Native, real-GPU and both-eye actual SteamVR comparisons pass locally. The
original window Look voice-over appears enlarged and retires cleanly, followed
by controller navigation and normal Quit. Headset readability and comfort
remain acceptance gates, not consequences of increasing eye resolution.

Latest progress: native eye rendering now uses OpenXR's recommended dimensions,
independently of the desktop. Private color/depth targets, camera, clipping,
viewport and clears all match those dimensions. GPU tests verify one-pixel
detail without enlargement and unchanged desktop pixels after successful or
failed eye draws.

The real SteamVR virtual-headset workbench passes startup, title, room stereo,
visible desktop mirrors, minimize/restore and native Quit → No → resumed stereo
→ Quit → Yes. The game exits with code zero and SteamVR shuts down gracefully.
Successive compositor captures show the score's native one-second fade and no
visible residue after retirement in both eyes. This sampled result does not
yet resolve the earlier reported artifact across all modes and transitions.

Opening a toolbar had displaced the room-status child and incorrectly withdrawn
its VR source. The lookup now validates the bounded live child list and accepts
the unique status class regardless of order. Real SteamVR captures pass status
fade/retirement with the toolbar open on windowed and 4K desktop mirrors, using
the same headset-recommended eyes. The 4K capture starts before the native fade
and captures compositor eyes before the slower desktop screenshot. Source-pixel,
GPU-transport and submitted-layer checks distinguish rendering defects from
capture timing. Other rooms, modal transitions and physical-headset acceptance
remain open.

Additional actual SteamVR samples cover inventory inspection, binoculars,
fingerprint inspection and driving-map highlights. Native save-name entry now
verifies the actual typed buffer instead of accepting an empty-field capture.
One save → different room → restore → score retirement → native Quit run passes
in 54.41 seconds, including inspected left/right compositor eyes and unchanged
private flat files. Two other save/restore attempts exceed their workbench
deadlines, so repeatable real-runtime lifecycle qualification remains open.
Their owned processes are stopped and private files/registry restored. These
samples use host input, not physical controllers or a worn headset.

A stack-instrumented repeat identifies diagnostic-file flushes as repeated
workbench delays. Replaceable observations no longer request durable installer
flushes, and verified rollback content is reused without rewriting it. New
rollback content and crash journals remain durable. The corrected workbench
passes another native save/restore/score/Quit cycle in 52.69 seconds. This
explains a demonstrated timeout mechanism, not every possible lifecycle defect.

Opaque modal interfaces now use a 2.4 m-wide physical canvas at 1.6 m distance,
with unchanged aspect ratio and shared renderer/pointer geometry. World menus,
captions and score kept their separate original scales in that qualification.
The newer dedicated subtitle layer is tracked separately. Both real compositor
eyes show the enlarged save editor; inspection/binocular/fingerprint transitions
return to the original world-overlay scale. Headset readability remains open.

The fresh modal build passes native/flat/OpenXR GPU qualification. Native
regressions check both-hand edge picking through repeated 1.6↔2.4 m panel
changes on both diagnostic canvases. A final actual SteamVR save/restore/Quit
repeat passes in 53.00 seconds with the exact fresh renderer/player, including
inspected score retirement in both eyes, unchanged private files and graceful
runtime shutdown. All 4,311 default tests pass in 67.88 seconds; the timing gate
is still open. Rollback regressions repeat in 3.45 seconds without slow flushes.

Latest frame-timed room samples submit about 119 stereo frames/s windowed and
118 with a 4K desktop, using the same runtime-recommended 1568×1568 eye targets.
The earlier short 89 frames/s fullscreen sample is not representative of the
latest warmed room interval. Bounded `BltFast` synchronization improves expanded
4K menus from about 58 to 78 submissions/s. A subsequent cropped CPU-cache
change samples about 79–82 with the 4K mirror and 118 windowed; this is a modest
additional reduction, not a sustained-refresh acceptance result. Remaining
menu/desktop cost is still performance work. The separate 1920×1920 compositor mirror is not the
application's eye target. Submission rates are not physical-headset delivered
frame rates, and frame-time outliers remain part of the performance gate.

Earlier real-runtime tests used host input with controller ownership temporarily
disabled for Play and Quit. Actual SteamVR now passes virtual-controller movie
skipping and Play, both-tracked-hand menu/inventory shortcuts and either-hand
trigger selection without moving the host mouse. A subsequent 44.45-second
sample also selects native Quit, cancels to resume stereo and confirms clean
exit using virtual-controller actions, followed by graceful runtime shutdown.
Physical controllers, sustained pacing and headset comfort remain unqualified.
Flat-game files and global runtime settings remain unchanged. No headset testing
is requested yet.

Latest production launcher qualification keeps the native desktop mirror at
1280×800 without altering the flat game's five display preferences, checked
before cleanup. The same actual SteamVR session uses 1568×1568 eye targets.
Short room and advanced-menu intervals measure about 120 and 118 stereo
submissions/s. A matched 4K mirror sample measured about 79 with advanced menus
open. This supports the cheaper mirror default, not sustained headset acceptance.
Both compositor eyes show the restored native brightness slider. Native Quit
cancellation/resumption and confirmed exit pass, with unchanged private flat
files, owned VR installation removal and graceful SteamVR shutdown. The complete
default suite passes 4,364 tests in 60.64 seconds, just above the timing gate.

Native brightness interaction also passes with startup gamma 1 and 2. Both eyes
respond to signed relative slider drags and return near the original brightness,
within native slider quantization. The earlier failed return drag was an
absolute-pointer automation error: GK3 hides and recenters the host pointer
during capture. No extra game or renderer fix was needed. These two bounded
actual-SteamVR runs use host input, not physical controllers or headset displays.

Native hover-triggered status fading now passes through hotel room → lobby →
hotel exterior transitions in one 52.87-second actual-SteamVR run. Both eye
images show visible, fading and retired text. Lobby and exterior glyph-region
pixels match the later settled background; the room contains moving scenery,
so its small remaining pixel differences are not treated as text residue.
Native source ownership and overlay publication retire in all three scenes.
Quit cancellation/resumption and confirmed exit pass, followed by graceful
SteamVR shutdown with no forced components. The first exterior attempt ran
before native scripted-action input readiness; fixing only the test's readiness
check resolves that failure. Broader artifact and physical-headset acceptance
remain open.

An uncaptured three-scene pacing run measures about 112 submissions/s in the
room, 117 in the lobby and 88 outside the hotel, over 12/12/20-second intervals.
The exterior exposes a performance gap rather than passing the sustained
refresh-rate gate. A separate instrumented run places most elapsed time outside
OpenXR calls, with sampled stacks concentrated in native scenery drawing and
legacy renderer draw/state handling. It is not a physical-headset frame-rate
measurement, and no speculative rendering optimization has been applied.

A controlled follow-up repeats the unchanged renderer at about 119 indoor and
104 exterior submissions/s. A candidate that skipped equal transform writes
measures 101–102 exterior submissions/s on two runs, so it is rejected: the
earlier apparent improvement is not attributable to that change. The new native
GPU regression remains, verifying repeated writes, world/view changes and
projection changes through real target pixels. Fixed scenery regions in both
eyes match the unchanged renderer exactly. Sustained pacing remains open.

New 20-second actual-runtime intervals measure about 117 submissions/s in the
room and lobby, and 85 outside the hotel. Matching process-identified compositor
timings and OpenXR call timings are now recorded without screenshots inside the
intervals. A larger 3524×3524-per-eye exterior sample measures about 90/s, so
pixel count alone does not explain this bottleneck. Reversible center-draw
isolation repeats at 118–119/s, versus 99–105 in warmed restored intervals.
That diagnostic identified the extra center draw's cost. The integrated
prototype now replaces it with a GPU eye mirror, retaining native page
preparation, picking and save-preview reads. Both-hand controls, save/restore,
map, SIDNEY, movies and glides pass; 3524×3524-per-eye room/exterior intervals
now measure about 120/119 submissions/s. This is prototype qualification, not
a shipping optimization or physical-headset acceptance.
The null-headset drop counters also occur in a minimal 1,800-frame Vulkan clear
test and idle output. They are not physical-headset dropped-frame evidence.

The public-launcher graphics-menu regression is fixed and inspected in both
actual compositor eyes: the toolbar and expanded graphics menu float over the
stereo room, without a second flat room behind them. Capture activation now
follows rendering ownership, independently of controller input. Inventory and
return to stereo also pass. A focused regression run passes 525 tests with three
skips, and strict typing passes.

A longer counter-only sample maintains approximately 119 stereo submissions/s
over 12 seconds in the room and 118/s over six seconds with advanced graphics
expanded, at the same 1568×1568 eye target. There are no captures inside these
measurement intervals. This is still submission cadence, not measured GPU frame
time or headset-delivered performance. Native Quit and runtime shutdown pass.

SIDNEY's final-Quit rectangle warnings are fixed. A synchronous laptop redraw
was receiving the retained Quit dialog's transform before its own canvas fit.
The laptop now owns that redraw without withdrawing the dialog's input state.
An unmodified public-launcher run passes home, email, opened email and Quit
cancel/confirm, with no new error-log entries, unchanged flat files and graceful
SteamVR shutdown. The focused regression suite passes 1,731 tests with three
skips in 27.73 seconds. Physical-controller acceptance remains open.

## OpenXR and rendering

- [x] Native 32-bit OpenXR integration with runtime-selected Vulkan graphics.
- [x] Separate eye images, predicted poses/FOVs and coordinated frame submission.
- [x] Render engine eye targets at runtime-recommended dimensions, with private color/depth buffers, matching camera/clipping/clears and restored desktop state; verify one-pixel GPU detail and failed-draw isolation.
- [x] Verify real primitive rendering after repeated native transform setters and subsequent world, view and projection changes, supplementing clear-only transport fixtures.
- [x] GPU-only production eye/panel transport, without diagnostic CPU readbacks.
- [x] Tested session/device recreation, frame cancellation and partial startup cleanup.
- [x] Preserve encoded game colors and apply the accepted brightness ramp consistently to eyes and panels.
- [x] Reproducible, pinned prototype renderer build with native and actual-GPU tests.
- [x] Discover the actual SteamVR OpenXR runtime and its built-in virtual headset using isolated settings, restoring no global configuration because none is changed.
- [x] Create a real SteamVR Vulkan session and submit title panels and native hotel-room stereo using the verified renderer/player and virtual headset; no fake graphics/runtime calls.
- [x] Provide an isolated calibrated virtual-headset workbench that does not auto-launch Room Setup and interrupt the tested XR session.
- [x] Capture and visually inspect actual SteamVR compositor output for the title panel and both hotel-room eyes, waiting for compositor advancement after requesting the mirror textures.
- [ ] Qualify continuous real-runtime presentation, frame pacing and graphics fidelity beyond the sampled compositor images.
- [ ] Qualify real SteamVR presentation, lifecycle, focus changes and headset reconnection.
- [x] Make the score follow its native fade and disappear without residual pixels in tested actual SteamVR compositor output. Both-eye clean-before-hover comparisons in the bright exterior and dark cave restore the complete padded glyph region exactly; broader real-headset acceptance remains open.
- [x] Capture the current real-runtime score fade and retirement in both eyes, inspect the glyph area through disappearance, and verify native ownership/source retirement; extend this with five-scene and clean-baseline checks without claiming physical-headset acceptance.
- [x] Repeat native hover-triggered status fades across hotel-room, lobby and exterior scene transitions; inspect both compositor eyes and verify native retirement, Quit cancellation/resumption and graceful runtime shutdown.
- [x] Repeat visible/fading/retired/settled score captures with the integrated GPU eye mirror in R25, LBY, RC1, CS2 and BEC. Both-eye glyph regions retire to the same pixels as the later settled image; native ownership retires, controller Quit succeeds and flat files/runtime preferences remain unchanged.
- [x] Preserve live status ownership when a menu changes RoomLayer child order; verify bounded/ambiguous child-list rejection, capture-scope restoration, independent GPU fades and toolbar-open compositor retirement on both desktop mirrors.
- [x] Shut down the isolated SteamVR workbench gracefully: three real-runtime runs now request monitor closure and log orderly shutdown, without forced server termination. Player-native quit and physical-headset lifecycle remain separate gates.
- [x] Verify real SteamVR native Quit cancellation, resumed stereo and confirmed clean game exit through the public launcher, without forced player termination; host input is not physical-controller acceptance.

## World, camera and comfort

- [x] Render original room geometry and actors separately for each eye, without advancing simulation between eyes.
- [x] Support the verified native puzzle-scene subclasses, with shared stereo, wall-query and controller-picking eligibility; retain unknown-scene and scripted-camera guards.
- [x] Convert predicted head/eye transforms and asymmetric FOVs into the original engine's projection and culling.
- [x] Restore authored camera/render state after ordinary draws and tested native exception paths.
- [x] Seated recentering and consistent world/controller coordinate transforms.
- [x] Keep recentering gravity-aligned: reset seated position and horizontal heading without absorbing head pitch/roll, and retain the previous heading when looking vertically. Native startup/explicit/controller cases verify both eyes, asymmetric projection, shared controller origin and unchanged authored cameras. An actual SteamVR rolled-head comparison reduces the upright horizon error from 15° to 0°.
- [x] Exercise lean/right/up/forward and yaw/pitch/roll through a diagnostic tracker feeding actual SteamVR, not application-side pose replacement. Verify raw seated poses, native eye position/rotation and unchanged authored cameras; inspect both eyes after return and recenter. Physical scale and headset comfort remain separate acceptance gates.
- [x] Gentle stick camera translation and latched 30-degree snap turns, respecting native camera locks.
- [x] Recognize native scripted camera controllers, not only the input-lock flag, and block controller navigation until neutral input returns.
- [x] Detect abrupt authored camera translation/rotation and fade both eyes from opaque black over 200 ms of predicted display time, preserving head tracking and gating obscured world selection.
- [x] Verify native room-camera and room-to-room cuts, matching eye fades, world-input recovery and unchanged scripted-glide ownership in private-game tests.
- [x] Verify the current player's actual renderer receives identical per-eye fade gains in the same native stereo transaction during controller-selected map travel. Keep instrumented evidence separate from pacing and physical-compositor acceptance.
- [ ] Calibrate world scale and confirm one-to-one head movement, natural depth and a stable horizon in a headset.
- [x] Establish the native physical-unit conversion from original FACES.TXT documentation: model dimensions are inches. Default to 39.37007874 game units per meter, preserving runtime IPD rather than guessing it or fitting Gabriel to an assumed human height. Record original actor/scene-model dimensions and verify the installed native scale. Controller Select/Inspect, pause/resume, movement, snap-turn and Quit pass captured and capture-free public-command runs.
- [ ] Corroborate natural physical-headset world size and observer height against Gabriel and scene objects. Documented units and original model bounds do not substitute for worn-headset scale/comfort acceptance.
- [x] Implement a read-only designated-floor adapter with verified SceneData/string layout anchors, known-room guards and finite-input checks. Verify the package adapter against actual R25 floor geometry and run 48 behavior tests, including missing-floor rejection and unchanged cameras/segments; no observer-height adjustment is enabled yet.
- [x] Recover approximate Gabriel eye height from original face UV mapping and native shoe-reference metadata: 69.48 units above his bind-pose floor, about 1.74 m at the provisional scale. Exclude unrendered reference geometry from visible body dimensions. This is asset evidence, not animated/headset calibration.
- [x] Provide a separate Gabriel-height observer render/aim anchor from the designated floor, leaving the native camera and protagonist unchanged. Gate it to an unlocked user-owned camera; retain authored scripted/locked viewpoints. Verify fixed virtual height on seated recenter, runtime IPD, one-to-one crouch/stand, floor changes and level physical up/down across 20/40/80 units per meter in native tests. Actual R25 renders at Y=69.5 over its Y=0 floor, with authored Y=61.72 restored; inspect both compositor eyes and verify controller world Select/verb, pause/resume, stick movement and normal Quit. This is local implementation coverage, not whole-game or physical comfort acceptance.
- [ ] Qualify the observer anchor across additional rooms/elevations, authored views outside the floor footprint, native puzzles and scripted transitions; confirm natural height/world scale in a headset.
- [x] Compare native observer eye heights with independently parsed original named BSP floor triangles in R25, LBY, RC1 and MS3, including the raised museum floor. The connected route, both exterior/museum compositor eyes, normal Quit/removal and unchanged global/flat state pass. Rapid console staging is not natural-transition/HUD acceptance.
- [x] Separate missing ground from scripted ownership. A user-controlled free camera remains upright even without a designated-floor hit, retaining its native height rather than guessing a floor. Static original-geometry checks find references for 53 of 54 curated free-camera views; the pitched TE3 altar view exposes the fallback. A fresh verified renderer and actual SteamVR run confirm normal R25 height plus unchanged TE3 native height with upright eyes, inspect both temple eyes, then pass native Quit/cancel, removal and global/flat preservation in 40.72 seconds. Broader physical/natural-transition acceptance remains open.
- [x] Fade both eyes before the near plane reaches native BSP geometry and hide the world through walls, without clamping predicted head tracking or changing the authored camera.
- [x] Verify wall approach, crossing, retreat, matching opaque eyes and world-input recovery against actual hotel-room and lobby geometry in the private game.
- [x] Extend protection to raw head poses delivered through actual SteamVR in R25, LBY and BEC: both eyes hide the world at geometry crossing, stereo submission/tracking continue, authored cameras remain unchanged and tracked eyes are not clamped. Retreat restores viewing; the stronger lobby/puzzle probes verify held Select stays blocked until release. Inspect both-eye captures. This is synthetic hardware, not headset comfort acceptance.
- [x] Repeat wall-crossing and recovery checks across 18 sampled views, including outdoor scenes and native puzzle rooms, with unchanged authored cameras and saves.
- [x] Query the nearest native scenery or visible model triangle, keeping finite segments and authored camera state unchanged.
- [x] Verify hotel scenery and a model remain solid with object hit testing disabled, disappear from wall queries when hidden and return when shown.
- [x] Verify production wall queries follow the native wardrobe and dumbwaiter door animations: closed hits clear on opening and return on closing, without stale obstacles or changes to camera/selectability.
- [x] Verify a controlled thin model's color-keyed holes remain clear while opaque texels remain solid, using native UV-aware queries in the private game.
- [x] Verify neutral tracked viewing remains visible and world rays recover at all 16 authored hotel-room camera poses, including window, dumbwaiter and SIDNEY close-ups.
- [x] Regression-test a camera 25 cm from a surface across world scales: neutral visibility, binocular approach fade, safe crossing, retreat and live transparent-hole results.
- [x] Keep stick navigation available during a wall-safety fade without permitting object selection. Reproduce the native hotel-stair trap, then qualify descent/return through the same region with current SteamVR, a 70.03-unit elevation change and original-floor eye-height error below 0.001 units. Reject held-trigger replay, menus, lost focus/tracking, failed frames and authored-cut input. Inspect both compositor eyes; controller-operated connected saves/SIDNEY/map travel/Quit also pass. This is virtual-device testing, not physical comfort acceptance.
- [ ] Verify transparent holes and thin surfaces do not cause inappropriate wall fades.
- [ ] Qualify wall protection across broader scenes, thin/transparent surfaces, movable doors/actor geometry and authored cameras close to walls; verify comfort in a headset.
- [ ] Qualify cut-fade comfort in a headset and cover unsafe transitions beyond the tested cuts/glide.
- [ ] Verify navigation cannot bypass character triggers, puzzles or walker boundaries across representative scenes.

## Controller interaction

- [x] Both-hand controller rays use original object picking and noun/verb actions.
- [x] Qualify actual SteamVR Index-profile Inventory and Back actions using isolated virtual devices, including tracked-hand fallback and stereo return; this does not qualify physical controllers.
- [x] Qualify actual SteamVR trigger selection on the visible native inventory Exit button with either tracked hand, matching delivered ray coordinates to the displayed panel and returning to stereo without host mouse movement.
- [x] Accept Menu, Inventory and Back shortcuts from either tracked hand without switching the pointing hand or borrowing the other hand's trigger; verify focus/tracking rejection and no repeated shortcut edges in native tests, plus actual SteamVR left-hand shortcuts with both devices tracked.
- [x] Skip the opening movie and select Play using actual SteamVR virtual-controller actions with controller ownership enabled, verifying the delivered ray against the native button and reaching stereo without host mouse input.
- [x] Use actual SteamVR virtual-controller Menu and trigger actions to select native Quit, cancel back to stereo, reopen Quit and confirm clean exit through the public supervisor, without host mouse/keyboard events or forced termination.
- [x] Offer explicit left/right pointing preference at launch, setting world and panel ownership before resume without modifying the player on disk; verify all settings before activation and reject incomplete writes.
- [x] Qualify left-handed Play, SIDNEY keyboard/search, native Exit and Quit through actual SteamVR virtual controllers; verify tracking fallback, foreign-trigger rejection, held-trigger handoff rejection and release-to-rearm recovery.
- [x] Repeat the tracking-loss, held-trigger handoff and preferred-hand recovery sequence with both left and right launch preferences through actual SteamVR, followed by clean native Quit and graceful runtime shutdown.
- [x] Preserve native tooltip timing by delivering controller pointer movement only when its pixel point, hand or layer changes; keep Select edges and world noun picking responsive, and invalidate the movement cache after cancellation.
- [x] Qualify controller-driven Cuiza and Rennes-les-Bains highlights/tooltips, native station travel, stereo recovery and Quit through actual SteamVR with both pointing preferences, without moving the host cursor; physical controllers and broader map coverage remain open.
- [ ] Qualify remaining required text-entry routes through actual SteamVR, then verify the complete controls on physical hardware.
- [x] Depth-tested aiming beam and target marker agree with the native world hit.
- [x] Connect the packaged stereo scene to its verified native hit-query callback; execute tests through the installed callback and reject occupied or changed links. Inspect both SteamVR compositor eyes and exercise native object Select/Look with virtual controllers.
- [x] Select opens the original action menu and invokes native actions, then returns control to the world.
- [x] Qualify native scenery Select → Inspect → Back pause/resume and returned stick movement through actual SteamVR controller actions. The window Inspect uses an authored room camera. Verify 30-degree snap turning, held-input rejection and neutral rearming after the comfort transition.
- [x] Qualify native Inspect → Undo through actual SteamVR controller selection with either preferred hand. Restore the authored camera position and orientation exactly, retire the menu, then verify pause/resume, stick movement, snap turning and normal Quit. This is distinct from Back pause/resume and does not establish physical-headset comfort.
- [x] Inventory, Menu, Back and recenter actions, with cancellation and release-to-rearm safeguards.
- [x] Back pauses/resumes an unobstructed room, cancels native interfaces and follows the game's configured movie-skip binding.
- [x] Back follows the configured native action-skip key while a visible/enabled original ActionSkipper owns the room, then resumes ordinary pause behavior. Respect open-menu priority, missing/unassigned bindings, native skip guards and release-to-rearm. Emitted-code tests cover all supported profiles; actual SteamVR controller Look → Skip → Pause/Resume → movement/snap turn → Quit cancellation/confirmation passes in 38.18 seconds. Inspect both returned compositor eyes. Renderer remains unchanged; this is a virtual-controller sample, not physical acceptance.
- [x] Qualify controller action skipping across the courtyard-to-barn transition and barn introduction, recovered inventory/stereo, then canceled/reopened/confirmed native Quit. The captured public-command flow passes in 67.27 seconds and the capture-free repeat in 70.36 seconds. The latter recovers from one native action-start menu interruption using normal Back and a fresh menu attempt, without forced state or callbacks. Both exit zero, uninstall and shut down SteamVR gracefully. Inspect both returned eyes from the captured pass. A separate captured repeat hangs during observation/shutdown, so broader runtime repeatability and physical-headset acceptance remain open.
- [x] Panel pixels and controller hitboxes share coordinates, including edges, clipped controls and transparent gaps.
- [x] Controller input does not move the host mouse; focus/tracking loss cannot retain an active selection.
- [x] Retire all interaction on valid-but-untracked head poses, while continuing legal last-known-view presentation. Native tests cover either/both lost tracking components, held buttons/stick rejection on recovery and fresh release/neutral rearming. Actual SteamVR loss/recovery verifies that held Inventory is not replayed, fresh Inventory works and controller Exit remains aligned after moving the viewer; both eye images are inspected.
- [x] Preserve native physical-keyboard typing/editing alongside controller pointing, without treating incomplete renderer output as focus loss. Retire stroke permissions and native modifiers on completed runtime focus loss, reject held autorepeat after recovery and require a fresh press. Emitted-code tests cover native releases, fast queued characters, extended scan codes, dormant flat behavior and reentrant producer output. Actual SteamVR modal-keyboard focus loss/recovery, mixed physical/controller SIDNEY search and normal Quit pass in 48.92 seconds with both eyes inspected. Win32 keyboard events and controllers are scripted; this is not physical-headset acceptance or a passing dashboard sample.
- [ ] Verify physical controller bindings, handedness, aiming and comfort on the first supported SteamVR setup.
- [ ] Confirm usable pointer feedback and exactly one visible interface cursor in the headset.
- [ ] Establish and test practical alternate mouse/keyboard input without conflicting ownership. Native keyboard text entry is now qualified alongside controller pointing; independent desktop-mouse/world control remains unfinished.

## Interfaces, text and saving

- [x] Stable, aspect-correct floating panels with shared drawing/picking geometry and recentering.
- [x] Automatic stereo-room versus modal-interface ownership in representative native-game tests.
- [x] Qualify current-player closeup and binocular inspection using controller exits, recovered stereo and fresh controller navigation, without moving the host mouse or forcing layers. Native console use is limited to staging those interfaces. Captured panels and returned eyes are inspected; physical readability remains open.
- [x] Isolated action menus, room toolbar and resolution dropdown over the stereo world.
- [x] Activate native menu capture through the public launcher, verify graphics/advanced menus over actual SteamVR stereo without a flat-background quad, and withdraw capture when either render owner is disabled.
- [x] Isolated dialogue captions and tooltips, with faithful colors, wrapping and stacking.
- [x] Qualify the original hotel-window Look voice-over through actual SteamVR controller selection, subtitle appearance and retirement in both compositor eyes, returned navigation and clean Quit. Broader dialogue coverage and physical-headset readability remain open.
- [x] Transport producer-supplied partial-opacity fades, preserving keyed transparency, opaque black and brightness adjustments.
- [x] Verify every eye pixel remains unchanged through HUD opacity steps and retirement, with the retired HUD quad absent from the submitted layer list, on the actual GPU in both runtime color formats.
- [x] Capture unblended score/status glyphs in a private-game test, restoring native widget fields on return and exception unwind.
- [x] Native SIDNEY, driving-map and inventory controller interaction in representative tests.
- [x] Inspect actual SteamVR driving-map highlights and SIDNEY home/email/content panels, with modal ownership, Quit cancellation and confirmed exit; these samples use host input, not physical controllers.
- [x] Fix SIDNEY's competing laptop/dialog transforms during final Quit, verify single fitting in 18 emitted-code cases, and repeat actual-runtime shutdown without diagnostic hooks or new error-log entries.
- [x] Automatically isolate transient RoomLayer time/score/status text, preserving native glyph and backing fades.
- [x] Withdraw that HUD on native destruction, hidden/modal state or disabling, clearing owned pointers and releasing its source.
- [ ] Qualify other HUD variants and room/modal transitions beyond the transient status sample.
- [x] Route save-name characters and editing keys through the native editor, rejecting stale screen/controller ownership and focus loss without host input events.
- [x] Render and inspect a readable controller-keyboard layout; test all printable characters, editing keys, both-hand ray picking and release-to-rearm ownership guards.
- [x] Test an independent keyboard swapchain and editor/keyboard/stereo-world composition in one OpenXR frame, including cancellation and failed-acquisition cleanup.
- [x] Verify the renderer's keyboard labels, colors, opacity, controller typing, Select isolation and retirement on the actual GPU, in both RGBA and BGRA runtime images.
- [x] Qualify the complete renderer-to-native-save-editor keyboard flow in a running game, including editing, screen changes and tracking loss.
- [x] Type and edit a save name through actual SteamVR virtual-controller rays, inspect the displayed keyboard in both eyes, reject held-key repeats, retire the keyboard on cancellation and finish native Quit without host mouse/keyboard events.
- [x] Qualify ordinary native text editors through the game's ordered character dispatch, without assuming SaveGame-specific layout or focus fields.
- [x] Type a SIDNEY search using the controller keyboard, invoke the native search and return Home, retiring text ownership without host input.
- [x] Repeat SIDNEY search through actual SteamVR virtual-controller actions: verify every typed character and held-key rejection, inspect compositor results, retire the keyboard at Home, select native Exit and complete controller Quit cancellation/confirmation with graceful runtime shutdown. Console scene staging is separate from controller interaction.
- [x] Add explicit controller-keyboard Enter through a revalidated native editor, separate from printable/editing input. Test at-most-once delivery, stale epochs, modifiers, retired recipients and nested redraws. Complete SIDNEY's Arcadia missing-word prompt with actual `SUM` typing and native Return, verify the updated translation in both compositor eyes and keyboard retirement, then exit normally. This uses a staged scanner fixture, not full story acquisition.
- [x] Support SIDNEY's native multiline notes editor without replacing its editing semantics. Type notes, exercise Home/End and native Return/newline, reject held repeats, leave/reopen and verify both lines persist through actual SteamVR controller actions. Fix its separately drawn caret using the existing SIDNEY affine; inspect alignment in the desktop and both compositor eyes, then complete normal Quit and graceful runtime shutdown. Physical-headset text quality and further editor routes remain open.
- [x] Repeat native SIDNEY entry, multiline notes/keyboard typing and Home/End/Return, retained notes, editor retirement/Exit and Quit while raw head tracking continuously moves. Exact `note`/newline/`ok` contents and held-key rejection pass, with both compositor eyes inspected on the subtitle-depth-corrected build. Physical controller/headset acceptance remains open.
- [x] Save a controller-typed name to a native slot, change the camera, restore the exact saved state and resume inventory/world interaction in the private game.
- [x] Repeat controller-typed save, native slot writing, a runtime-controller 30-degree camera turn, selection of that slot in Restore and exact camera recovery under actual SteamVR; inspect both-eye interfaces and complete controller-operated Quit with graceful runtime shutdown.
- [x] Verify actual native save-name entry in visual automation using the live empty-row bounds and exact editor contents; reject hidden, invalid or unreadable rows/editors instead of recording a false-positive capture.
- [x] Sample real SteamVR native save/restore from a different room, inspect restored score retirement in both eyes and complete native Quit with unchanged private files; one passing host-input run does not establish repeatable or physical-controller acceptance.
- [x] Repeatedly open and cancel Quit, including 30 forced input-publication race cycles and 20 cycles after save/restore; verify Back, No and clean Yes exit.
- [x] Prevent native page-repair redraws from starting a second stereo frame before the first completes, with regression and running-game tests.
- [x] Pause/resume using only controller Back, keep XR submission responsive while paused and require release after focus loss before resuming.
- [x] Verify synthetic focus loss inside native save-file writing and restore-browser file loading, blocking held Menu replay on recovery and preserving valid saves.
- [x] Verify focus loss while mapping the selected save during final restoration, including restore from another room, exact camera recovery and resumed controller interaction.
- [x] Cancel a held Quit Yes selection on focus loss, block activation on focus recovery and require a fresh press/release for clean exit.
- [ ] Repeat file-I/O, restore and Quit lifecycle checks with a real runtime and physical controllers.
- [ ] Qualify remaining required text-entry screens, including custom editor routes and interface-heavy puzzles.
- [x] Requalify native SIDNEY entry, Virgo corner selection/confirmation, hexagram move/resize/rotation, Libra completion/chapter return, inventory/stereo and normal Quit on the current cinema-sizing player while raw head tracking continuously moves. The capture-free 95.49-second actual-SteamVR run publishes 6,260 head poses, preserves the host cursor and flat files/preferences, then uninstalls and shuts down gracefully. Story prerequisites are staged; this is not a whole-game or physical-headset acceptance claim.
- [x] Repeat native SIDNEY entry, Virgo/Libra recognition, shape editing, chapter return, inventory/stereo recovery and normal controller Quit on the newer early-scene-owner-loading player. The 94.96-second actual-SteamVR sequence confirms native completion/locked flags without puzzle model/flag writes, preserves flat files/preferences and uninstalls with graceful runtime shutdown. Prerequisites come from a staged save. Tracking/controllers are virtual; this repeat does not establish moving-head or physical-device acceptance.
- [x] Qualify that connected puzzle flow with continuously moving raw head tracking on the current frame-wait-queue renderer/player pair. Native SIDNEY entry, Virgo/Libra completion, shape editing, chapter/inventory recovery and normal controller Quit pass in 95.31 seconds with 6,284 head poses over 66.53 seconds. Flat files/preferences and global runtime settings are unchanged, with clean uninstall and graceful shutdown. Story prerequisites remain staged; this capture-free virtual-device run establishes neither fresh visual nor physical-headset acceptance.
- [x] Repeat that moving-head puzzle/chapter/inventory/Quit sequence on the corrected scene-less-resource-loading player and loading-ownership renderer. The 96.94-second run records 6,353 head poses over 67.62 seconds, native completion without puzzle-model/flag writes, restored controls and clean exit/uninstall with flat/global state preserved. Prerequisites remain staged; physical devices and fresh visual acceptance are not implied.
- [x] Qualify the sampled native Make ID portrait/category selectors and file-list closure through actual SteamVR controllers, keeping the VR keyboard absent on read-only controls. Inspect both eyes and finish normal Quit with the freshly requalified renderer.
- [x] Exercise controller-operated N.Y. Times ID printing during its native Day 2, 2pm timeblock; observe the 000 → 002 score award, inspect both compositor eyes, return to gameplay and cancel/confirm native Quit. The current-player/current-renderer run passes in 64.82 seconds with clean uninstall and graceful SteamVR shutdown. Chapter/character setup uses console commands; this is not a natural story playthrough.
- [x] Independently verify the newly printed ID through the original engine's ownership layout: status 0 before printing, status 3/Gabriel-owned afterward. Open native inventory through the controller, inspect the visible N.Y. Times card and return to stereo. The public-command flow passes in 55.82 seconds with clean native Quit, uninstall and graceful runtime shutdown.
- [x] Select the château door, Knock and the reporter-card conversation topic through actual SteamVR virtual-controller input. The original story awards five points and advances into the barn, without forced inventory, actor positions, action callbacks or completion flags. Post-introduction recovery is qualified separately below.
- [x] Complete the printed-ID story interaction through native introduction completion, recovered controls, return to inventory/stereo and controller-operated Quit cancellation/confirmation. The public-command sample passes in 203.53 seconds, including native story content, unchanged flat files/preferences, clean uninstall and graceful SteamVR shutdown. Inspect both inventory compositor eyes. Console loads the previously genuinely printed-ID save and stages the courtyard/camera; this is not a natural full-story playthrough. Earlier short deadlines omitted scripted animation waits. Broader repeatability and the intermittent second-Quit-target miss remain separate investigations.
- [ ] Enter save names and other required text without removing the headset, using a dependable panel keyboard.
- [ ] Complete headset save, restore, pause and quit flows, including focus and modal transitions.
- [ ] Verify readable fonts, comfortable panel/subtitle placement and correct hover/highlight feedback in a headset.
- [x] Enlarge floating native menus with shared drawing/picking geometry, stable submenu expansion and independent caption/HUD placement; verify both-hand GPU picking, transparent gaps, auxiliary-layer retirement and both actual SteamVR compositor eyes.
- [x] Enlarge opaque modal interfaces without changing world-menu/caption/HUD scale; verify emitted bridge size through modal-to-world transitions and inspect actual SteamVR save-editor eyes, typed text and clean native Quit.
- [x] Separate enlarged dialogue from menus and ordinary HUD text, retaining native source pixels, current-frame ownership and noninteractive picking; test simultaneous GPU layers and retirement/reappearance without changing headset eye resolution or flat play.
- [x] Inspect enlarged original dialogue in both actual SteamVR compositor eyes and requalify controls, caption retirement and native Quit with the new renderer/player; the private run passes in 44.06 seconds without changing the recommended 1568×1568 eye targets or independent 1280×800 mirror.
- [ ] Cover inventory inspection, SIDNEY screens, the map and interface-heavy puzzles beyond the current samples.
- [x] Extend actual SteamVR controller coverage from SIDNEY Search to email reading, analysis/translation file browsers and parchment opening. Verify no spurious editor/keyboard ownership on those pages, return to the room and native Quit cancellation/exit, with both-eye captures and unchanged flat files.
- [x] Run SIDNEY's native parchment recognition and French anomaly extraction with controller rays, selecting popup buttons from their live native bounds. Respect the native narration/action lock before dismissing its result; return to ordinary gameplay and Quit normally. This is one analysis sequence, not complete SIDNEY puzzle/editor coverage.
- [x] Complete SIDNEY's native anagram from a private copy of a real pre-puzzle story save using actual SteamVR virtual controllers: recognize its Arcadia file, wait for discovery, select and erase a word, scroll and select the correct words, and inspect the confirmed solution in both eyes. Exit/Home, return to stereo and native Quit cancellation/confirmation pass without changing puzzle flags or host-pointer position. Full-story prerequisite acquisition and physical-headset acceptance remain open.
- [x] Open SIDNEY's map-analysis file through actual SteamVR controllers, pan the magnified pane with a held overview ray and stop panning on release. In a later real-story fixture, select Enter Points, place a native point in the magnified pane and clear it without disturbing locked geometry. Inspect both compositor eyes, return to stereo and complete controller Quit with unchanged flat files/preferences and graceful runtime shutdown. Shape manipulation, full puzzle solutions and physical-headset acceptance remain open.
- [x] Correct SIDNEY's second native motion pass to use its current authored canvas rather than screen coordinates. Execute owner/retained/null and hover/held regressions, compile all supported profiles and qualify native controller square placement, selection, movement and deselection in actual SteamVR. Preserve dimensions, return Home/room and complete native Quit with clean cleanup. Other shape types are qualified separately below; full puzzle sequences remain open.
- [x] Keep SIDNEY drag positions and movement deltas in one coordinate domain. Derive logical deltas from both mapped physical endpoints, leaving original pointer/delta data and other owners untouched. Execute signed-rounding, null and zero-delta transport checks, then resize and rotate a native square through actual SteamVR controllers. Verify stable center/size as appropriate, no changes after release, both compositor eyes, deselection, room recovery and clean native Quit/runtime shutdown. Full puzzle solutions and physical-controller feel remain open.
- [x] Complete the native Aquarius map-analysis step and qualify circle editing with actual SteamVR controller rays. Stage only its two inventory prerequisites through the native console, then pan to verified live positions, place the two points, analyze and dismiss the confirmed result after narration. Add a circle, dismiss its native instruction, select/move/resize/release/deselect it, inspect both compositor eyes, return to the room and Quit normally with unchanged flat files/preferences and graceful SteamVR shutdown. Full-story item acquisition and physical-headset acceptance remain open.
- [x] Complete native Virgo in its original chapter, confirm the game's flag and score changes, then qualify hexagram selection/movement/resizing/rotation/release/deselection through actual SteamVR controller rays. Read puzzle state without changing it, inspect both compositor eyes, return Home/room and Quit normally with unchanged flat files/preferences and graceful runtime shutdown. Full zodiac coverage and physical-headset controls remain open.
- [x] Solve native Libra using controller-only center/radius/angle alignment, with the original executable's acceptance criteria. Verify the locked blue hexagram, score 565, native completion/locked flags and withdrawn selection without model or flag writes. This is puzzle recognition, not post-puzzle recovery qualification.
- [x] Qualify the sampled Libra chapter transition through native computer entry, puzzle completion, Inventory/Back and normal Quit. A returned room camera precedes narration/action completion and is not sufficient readiness evidence. The bounded check waits for real Inventory acceptance after the original sequence advances to the hotel hall in `310a`. Actual SteamVR virtual-controller evidence passes; full-story and physical-headset acceptance remain open.
- [x] Correct the clipped toolbar opened by right-click inside SIDNEY. Restrict isolated room-menu capture and publication to the current readable room, retaining SIDNEY's native fitted composition. Verify opening, ray hover and Back closure at center, the original failure position and near the edge, inspect both compositor eyes, then requalify square movement and native Quit with unchanged flat files/preferences and graceful SteamVR shutdown. Expanded toolbar features and physical-headset acceptance remain separate gates.
- [x] Reveal a native fingerprint through actual SteamVR virtual-controller brush selection, powder selection and held-trigger strokes. Native opacity increases; released brush motion adds no powder. This is a partial interaction check, not a completed puzzle or physical-controller acceptance.
- [x] Qualify fingerprint-interface controller Exit/Back, tape/paper collection and return to interactive stereo without forced layer removal. Back dismisses the native temporary script/dialogue child before closing its parent; separate uninstrumented collection and visible-Exit runs pass. Physical-controller and broader puzzle acceptance remain open.
- [x] Select a native CS2 laser head through actual SteamVR controller rays, invoke both turn directions through its ordinary verb menu, verify only that head changes and then returns to its original setting, and recover interactive stereo/native Quit. This is a sampled control check, not a completed laser puzzle.
- [x] Give completed, validated interactive-overlay hits priority over world selection, including non-menu puzzle controls. Preserve failed-world rejection and cancel/rearm held triggers and navigation on ownership changes; verify all supported binary profiles and the package-generated coordinate-device power button in actual SteamVR.
- [x] Integrate the coordinate device as an independent interactive source over stereo. Validate its live owner, native reverse draw order, current-frame cache and exact native corner rounding across all supported executable profiles. Actual SteamVR verifies power-button interaction, toolbar coexistence, close/reopen, scene-replacement withdrawal and native Quit. Source/desktop comparison covers 78,315 pixels with at most one RGB-level difference; a short uncaptured sample reaches 119.17 stereo submissions/s. Physical-headset acceptance and full-story acquisition/use are not implied.

## Movies, scripted scenes and transitions

- [x] Present an original Bink movie on the modal panel, stop stereo-world draws during playback and continue XR frame submission.
- [x] Skip a movie using controller Back through the native character handler, without host keyboard events or held-button replay after focus loss.
- [x] Return to interactive stereo after both controller skipping and natural movie completion in private-game tests.
- [x] Repeat native movie presentation with actual SteamVR: XR frames continue while world draws stop, both-eye movie images are inspected, natural completion and host-keyboard skipping return to stereo, and native Quit/runtime shutdown pass. This is not physical-controller or headset acceptance.
- [x] Requalify movies with the integrated GPU mirror and actual SteamVR virtual-controller Back: native completion and skipping recover stereo, held Back does not pause the returned room, host mouse remains unchanged and native Quit/runtime shutdown pass.
- [x] Repeat native movie completion and controller Back/held-input rejection while raw SteamVR head tracking moves, with the subtitle-depth-corrected renderer and the earlier qualified player. Both movie eyes, stereo recovery and normal Quit/cleanup pass. This does not qualify the newer cinema-sizing player's complete flow.
- [x] Implement and verify uniform VR cinema fitting from live, validated fullscreen software-movie rectangles, independent of desktop padding/aspect. Emitted-code tests preserve native object data and ordinary/custom/embedded/invalid fallback; both-eye images and native fit measurements show larger undistorted content. Decoder, audio, timing and desktop layout remain untouched.
- [x] Qualify current cinema sizing through a complete actual-SteamVR movie flow: moving raw head poses, natural completion, controller skipping, interactive stereo return and normal Quit. The 48.89-second run preserves host cursor, private flat files/preferences and global runtime state; both eyes are inspected. A separate connected save/SIDNEY/map/navigation/Quit session passes in 67.60 seconds. No outside mouse events occur in either run. Earlier intermittent failures remain documented and do not count as repaired merely because these samples pass.
- [x] Route an actual native camera glide to a stationary floating screen, stop immersive world draws, continue XR submission and recover stereo without replaying held turn input.
- [x] Repeat room and cinematic camera glides with actual SteamVR, observing the native stacked controller, moving camera, stationary published panel geometry, continuous XR frames and resumed stereo; native Quit and graceful runtime shutdown pass. This host-input sample is not headset-comfort acceptance.
- [x] Repeat two native camera glides while a raw-runtime tracker delivers smooth head movement. The current head-comfort baseline stops immersive world draws, keeps the screen geometry stationary and submits 16/15 XR frames in the sampled interior glide intervals, then recovers stereo and controller Quit. Physical comfort and other scripted sequences remain open.
- [x] Recognize native cinematic conversation ownership independently of camera-controller count and subtitle presence. With the original cinematics policy enabled, keep the screen stationary through native dialogue cuts, stop immersive draws and continue XR submission. Qualify actual SteamVR controller Talk/topic/Cancel/inventory/stereo/Quit with both eyes inspected, and preserve stereo when cinematics are disabled. Native forced-camera/input-lock safety remains in effect. This is sampled implementation evidence, not headset comfort or complete dialogue coverage.
- [x] Preserve enlarged independent VR subtitles during opaque cinematic conversations, with native glyph colors and a black contrast backing. The private XR copy removes the smaller baked glyphs without modifying the game page or picking. Native/GPU tests and an actual SteamVR Talk/topic/Cancel/inventory/stereo/Quit session pass, with both eyes inspected; subtitles retire correctly and ordinary world voice-over still works. Physical-headset readability and comfort remain separate acceptance gates.
- [x] Prevent moving-head cinematic subtitle breakup by separating the subtitle and native-screen planes while preserving apparent text size/placement. Native tests verify separation, angular footprint and a stable anchor after head movement. A fresh actual SteamVR conversation with 2,946 raw head poses passes Talk/topic/Cancel/inventory/stereo/Quit in 62.58 seconds, with clear text inspected in both eyes. This corrects the demonstrated coplanar-layer defect, not every runtime or physical-headset readability case.
- [ ] Qualify movie-screen comfort in a headset and route unsafe cinematic cameras to that screen by default.
- [ ] Qualify other scripted camera controllers and dialogue sequences, including cuts that do not stack a moving-camera controller.
- [ ] Broaden responsive tracking/frame-submission checks to loading, dialogue and scripted transitions beyond the tested pause/movie samples.
- [x] Clear outgoing VR layers before the active recognized scene's blocking destruction, and retire old world/panel hits and pending text input without changing native buffers, story logic, flat behavior or loading work. Native and GPU tests cover idle/pending/hidden/failure frame transactions. Four actual-SteamVR moving-head loads and a connected save/SIDNEY/map/Quit session pass on the freshly qualified renderer. A bounded inspection hold confirms the old game view is gone; SteamVR's waiting environment can still appear during longer stalls.
- [x] Maintain empty XR submissions during blocking scene retirement through an exclusive, renderer-owned loading helper. It does not tick/draw the game, acquire images or deliver native input. Queue-accessing XR calls share Vulkan synchronization with asset uploads, but frame waits leave that queue available; normal drawing joins the helper before taking XR ownership. Native/GPU tests cover ownership, restart, failure propagation and stereo recovery. A held actual-runtime load records 64 frames over 0.53 seconds with a maximum 9.96 ms gap, and both captured eyes stay black. Four natural loads and connected gameplay/Quit pass.
- [x] Start the loading helper during initial Play before constructing the first scene, without reading the incoming uninitialized object or changing native construction. Preserve dormant flat behavior, live-scene ownership, original registers/flags and SEH continuation across all supported profiles. Actual SteamVR confirms the initial loading call succeeds, followed by the connected controller save/restore/SIDNEY/map/travel/navigation/Quit session in 65.08 seconds. Ordinary game files/preferences remain unchanged and runtime shutdown is graceful.
- [x] Extend loading coverage to the earlier shared scene-owner construction/retirement boundaries, covering graphics/assets created before UserScene and exit/unregistration before its destructor. Keep guarded UserScene fallbacks, avoid reading uninitialized incoming objects and require the outgoing active recognized UserScene. Tests preserve both objects and every register/flag across all supported profiles. The current player completes connected controller save/restore/SIDNEY/map/travel/navigation/Quit in 67.33 seconds and moving-head movie playback/skipping/stereo return in 49.19 seconds. In one matched controller-travel sample, the pre-blank gap improves from 50.45 to 35.16 ms; the returned-world gap remains 40.36 ms. This is earlier coverage, not faster native loading or a universal frame-time guarantee.
- [x] Qualify abrupt private SteamVR-server death during an actual native scene load, without an inspection hold or game-state bypass. The current player submits six successful empty XR frames in a 20.64 ms observed interval while native rendering counters remain unchanged and stale panel/world input is retired. The public supervisor stops its owned player and gives restart/unsaved-progress guidance. Private files/preferences and global runtime configuration remain intact; a fresh moving-controller/head-tracked sixty-second exterior run and normal Quit pass after the crash. Physical device loss/reconnection is separate acceptance work.
- [ ] Reduce comfort-critical loading/transition gaps and qualify physical-headset behavior. Earlier natural-load samples had 45–83 ms gaps. The new state-scoped preparation reduces sampled return gaps from a matched 28.78 ms control to 11.10/11.66 ms, while later world frames still reach about 15 ms. This is not uninterrupted refresh-rate-budget presentation throughout every transition.
- [x] Preserve the loading helper across nested native loading notifications and empty UI finalizers until actual rendering needs ownership. A GPU regression fails on the preceding renderer and passes on the new build, including both color formats and device recreation. Connected controller gameplay, natural-loading runtime-loss supervision and subsequent restart pass. Controller travel boundary gaps remain 36–43 ms, so this is an ownership correction, not a measured latency improvement.
- [x] Start loading coverage before the verified location manager purges cached graphics, including driving-map travel after both scene globals have already been withdrawn. Require the live manager from native engine services, reject partial owners/unknown live scene types and preserve native register saves, flags and manager data. The current player passes the connected controller flow in 64.78 seconds; its sampled map departure gap is 7.66 ms versus the earlier 35.80 ms, while the return-to-world gap remains 38.37 ms. This is a matched-path observation, not a universal loading or headset-comfort guarantee.
- [ ] Complete the broader scene-loading qualification, distinguishing legitimate native camera locks from VR ownership or frame-submission failures.
- [x] Recover stereo after loading the CS2 laser scene and BEC coordinate-device scene, and verify binocular wall protection, retreat and resumed world rays in private-game tests.
- [ ] Verify movie audio/synchronization, scripted movie sequences, scene changes and physical-controller skipping in a headset.
- [ ] Avoid stale views, white flashes, duplicate frames and involuntary head rotation during transitions.

## Performance and visual quality

- [x] Separate diagnostic pixel-readback overhead from actual prototype performance measurements.
- [x] Exercise runtime-recommended 4096×4096 eye targets without changing the 1280×800 desktop/interface canvas. A moving actor-heavy sample sustains about 122 stereo submissions/sec with GPU p99 6.23 ms; a separate captured pass verifies a full, unclipped world view in both eyes. Actual headset delivery remains open.
- [x] Compare completed CPU submissions with OpenXR predicted display time using the runtime's Windows clock-conversion extension, rather than treating every uneven submission interval as a missed frame. Keep GPU readiness and physical scanout as separate acceptance gates.
- [x] Leave the renderer/uploader's Vulkan queue available during ordinary OpenXR frame waits, not only during loading. Protect queue-accessing frame begin/end and exception cleanup, without changing view/input sampling or frame ownership. Native tests cover balanced callbacks, visible/hidden/invalid-pose frames and wait/begin/locate failures; native and flat/OpenXR GPU qualification passes. The new renderer passes a moving sixty-second exterior interval and the connected save/SIDNEY/map/Quit flow. Its measured FPS and p99 interval are effectively unchanged, with one longer outlier. This removes an unnecessary scheduling restriction, not a verified FPS improvement or a completed performance gate.
- [x] Keep native graphics updates coherent with the game's write-eliding state cache across eyes and frames. Restore only VR-owned target/depth/viewport/clipping bindings, rather than rolling back all GPU draw state behind that cache. A GPU cached-alpha regression reproduces the old defect and passes with the scoped fix. A same-renderer dormant flat control and both-eye native BEC comparison show the large black ground rectangle is removed; other graphics/content acceptance remains open.
- [x] Reuse CPU overlay buffers and upload only their occupied crop, preserving pixels and picking.
- [x] Batch overlay pixel conversion, with exact colors, transparency and hit coverage verified.
- [x] Draw qualified menus once for both desktop and VR, with ordinary-draw failure recovery.
- [x] Test transport with larger runtime eye images, not only the tiny fidelity fixture.
- [ ] Reduce remaining native menu/capture overhead, particularly expanded menus.
- [ ] Measure sustained CPU/GPU frame times and missed frames at the headset's selected refresh rate.
- [x] Requalify the current first-load player after the runtime crash with a fresh, capture-free sixty-second exterior interval under raw head tracking and actual virtual-controller movement. Record 120.38 stereo submissions/s, submission-interval p99 10.68 ms/max 13.98 ms, outside-traced-XR p99 8.62 ms and process-matched GPU p99 8.17 ms. The runtime reports a 90 Hz prediction period, not 120 Hz physical delivery. Forty-eight intervals exceed 11.11 ms; no measured interval exceeds 16.67 ms. Preserve those outliers and synthetic-runtime limitations. Normal Quit, unchanged flat preferences/files, uninstall and graceful global-preserving shutdown pass. This is a moving software baseline, not a completed headset performance gate.
- [x] Qualify the isolated SteamVR workbench at 120 Hz and rectangular headset-recommended eye dimensions, independently of the desktop mirror. OpenXR records an approximately 8.333 ms predicted period; native regression tests cover distinct per-eye recommendations, projection extents, invalid sizes and cleanup. Mean submission rates do not establish physical display delivery or a passed frame-time gate.
- [x] Recognize windowed render-target aliases before CPU downloads and remove duplicate VR-completion desktop presentation. All five surface aliases, CPU overlays, later reads and device recreation pass GPU checks; actual SteamVR exterior and SIDNEY selector/browser samples preserve both-eye rendering and clean native Quit. Median GPU time improves in the exterior sample, but frame-time tails and intermittent SteamVR shutdown remain open.
- [x] Stop repeatedly attempting invalid fullscreen page seeds for a windowed complete VR eye mirror, without fabricating native Flips or consuming pending fullscreen repair. Executed mode-switch/fallback checks and actual SteamVR save/scene-change/restore/score-retirement samples pass; the exterior profile no longer samples readback waits. Remaining frame-time tails, an intermittent save-test row-list observation and physical-headset acceptance stay open.
- [x] Establish a real-runtime GPU timing baseline independently of GK3: complete 180 binocular Vulkan clear frames, with runtime exit handled and explicit completion evidence.
- [x] Measure real-runtime room and expanded-menu submission intervals with runtime-sized eyes, separately from capture/profiling overhead, and verify matching renderer/player artifacts and clean runtime shutdown.
- [x] Record sustained room/lobby/exterior intervals with read-only, process-identified SteamVR compositor timings and matching OpenXR call durations; retain raw outliers and separate late loading history from steady-state statistics.
- [x] Exercise a larger runtime-recommended 3524×3524 eye target with the unchanged 1280×800 mirror, inspect both exterior compositor views and complete native controller Quit with matching artifacts.
- [x] Isolate the third center-view world draw reversibly in the owned private player, repeat restored/isolated intervals and restore code before native Quit; retain native mirror/history/picking replacement as unfinished implementation work.
- [x] Qualify an opt-in GPU eye-to-desktop mirror at independent aspect ratios, without CPU pixel readbacks; preserve native render state, preview reads, non-neutral gamma and failed-eye recovery.
- [x] Inspect both compositor eyes and the populated desktop while the private center draw is suppressed; measure approximately 118 versus 99 warmed stereo submissions/s in the exterior and restore normal code before native Quit.
- [x] Qualify actual SteamVR virtual-controller picking with either hand while the center draw is suppressed: native Inspect/Undo restores the camera exactly, pause/resume retains it, and movement/snap input returns correctly.
- [x] Integrate successful eye mirroring with the native page-preparation logic, before the eye copy; qualify hidden/failed/missing-bridge fallback and one-time per-generation handoff seeding without a third successful world draw.
- [x] Qualify the integrated path with both actual SteamVR virtual-controller hands and native save → scene change → restore → score retirement → Quit; inspect the populated preview and retired-score compositor images.
- [x] Requalify integrated-mirror map hover/highlights/travel, SIDNEY controller typing/search/exit, natural movie completion/controller skipping and native room/cinematic glides in actual SteamVR; retain stationary glide panels, resumed stereo and clean native Quit/runtime shutdown.
- [x] Measure the integrated path without diagnostic draw suppression: approximately 120 room and 118 exterior stereo submissions/s over separate 12-second intervals, with both exterior compositor views inspected and clean native Quit/runtime shutdown.
- [x] Replace the expensive center-view world draw in the prototype with a qualified GPU eye mirror, preserving tested page history, save previews, overlay ownership, picking and failure recovery; verify its benefit in native UI/movie/glide samples and runtime-recommended eye targets.
- [x] Repeat integrated room/exterior timing at 3524×3524 per eye over separate 20-second intervals: about 120/119 stereo submissions/s, process-matched compositor GPU timings, unchanged 1280×800 mirror and graceful native Quit/runtime shutdown. Exterior tail frames still exceed the 120 Hz budget; physical-headset acceptance remains open.
- [x] Bound `BltFast` source readback, destination readback and upload damage to validated transfer rectangles across all five DirectDraw surface interfaces; verify transparent cursor/save-under pixels, overflow rejection and actual SteamVR menu/quit behavior.
- [x] Avoid uploading an entire dirty CPU-authored cache for a cropped copy; retain accelerated clean/GPU-authored copies and verify cropped destination preservation across all five surface interfaces.
- [x] Launch with a smaller independent windowed mirror, leaving runtime-recommended stereo eye targets unchanged; verify matching artifacts, native menus and about 118 advanced-menu submissions/s in a short actual SteamVR sample.
- [x] Prevent active VR mirror settings from overwriting the flat game's display preferences; verify exact case-insensitive DWORD guards, native forwarding/error returns, dormant behavior and unchanged registry values before cleanup.
- [x] Keep the native brightness interface available with a windowed VR mirror, preserving capability checks and COM lifetime; inspect the restored slider in both actual compositor eyes.
- [x] Qualify native brightness-slider interaction in both actual compositor eyes with startup gamma 1 and 2, adjustment in both directions and return within native slider quantization; physical-controller and headset acceptance remain separate.
- [x] Submit windowed VR frames at the native completed-page boundary, outside its blit retry loop; preserve native registers, flags, fullscreen behavior and pending-world cancellation.
- [x] Present completed windowed modal panels on the desktop using a GPU render-target copy, without intermediate blit flashes or diagnostic CPU readbacks; visually verify the title mirror.
- [x] Reach the hotel room from the visible windowed title using host-mouse Play automation and verify both actual SteamVR eye images, with approximately 119 stereo submissions/s in the latest short sample.
- [x] Mirror completed windowed world/overlay frames as well as modal panels, using the restored desktop target; inspect the visible room and Quit dialog, with minimize/restore and unchanged flat files.
- [x] Pace only the visible desktop preview to approximately 30 Hz, without sleeping or reducing headset rendering, input, simulation or eye resolution. Native/GPU tests, actual SteamVR exterior timing, captured controller dialogue/inventory/Quit and native SIDNEY puzzle/chapter/inventory/Quit pass. Preserve ordinary presentation when XR prediction is absent. The sampled exterior has more frame headroom; sustained/physical-headset acceptance remains open.
- [x] Keep title and room VR frames advancing while minimized, bypassing the native inactive-window wait only for active VR and completing pending stereo before desktop presentation is skipped; preserve device-health checks and dormant flat behavior.
- [x] Verify minimize/restore with actual SteamVR: approximately 123 submissions/s minimized and 124 restored in short samples, with both minimized room eye images populated and visually checked.
- [ ] Qualify sustained minimized/background submission, runtime focus changes and physical-headset presentation beyond those short samples.
- [ ] Qualify windowed mode/focus transitions with actual SteamVR controllers; virtual-controller Play now passes without disabling controller ownership, but physical-controller acceptance remains open.
- [x] Account for the current null-driver compositor counters using idle output and a successful 1,800-frame real-GPU OpenXR clear baseline: presents and drops rise together with asynchronous flags even without GK3. Do not infer physical-headset delivered FPS or declare its missed-frame gate passed from these counters.
- [ ] Test demanding rooms, actors, effects, transparent UI and scene transitions, not only the hotel room.
- [x] Sample Castle Serres, the cave entrance and Temple 4 at runtime-recommended 4316×4316 eye targets over separate capture-free 20-second intervals; inspect both compositor eyes, retain submission/GPU timing tails and complete native Quit with unchanged flat files. Broader dynamic effects, longer sessions and physical-headset delivery remain open.
- [x] Sample exterior performance during actual runtime-controller camera movement and two snap turns with the matching build: 1,931 native movement calls, 120 stereo submissions/s, outside-OpenXR p99 8.17 ms and compositor client-interval p99 8.92 ms over a capture-free 20-second interval. This qualifies a moving-camera sample, not physical head movement or delivered headset frames.
- [x] Extend the current subtitle-depth-corrected build's capture-free exterior test to sixty seconds of simultaneous raw head movement and controller navigation: 5,718 head poses, 6,144 native movement calls, two snap turns and 119.93 stereo submissions/s. Outside-XR p99 is 8.11 ms, compositor client interval p99 9.08 ms and total GPU p99 7.90 ms. Submission-interval p99 is 10.50 ms, so sustained 120 Hz delivery remains unproven and the performance acceptance gate stays open.
- [x] Extend the current cinema-sizing player's moving-head/controller performance sample to the dining room, museum and village exterior, twenty seconds per scene. Native movement, snap turns and normal Quit pass; submissions average 121.15/121.70/120.50 per second. GPU p99 is 5.34/4.69/8.13 ms and compositor client-interval p99 is 6.74/6.29/9.16 ms. The exterior retains tighter margins; physical delivery and longer-session acceptance remain open. This run has compositor timings but no XR API trace, so it does not establish outside-XR or submission-interval tails.
- [x] Extend the current-build exterior sample to combined raw-runtime head motion and controller navigation: 1,913 head pose publications, 1,935 native movement calls, two turns and 119.7 stereo submissions/s over 20 seconds. Outside-OpenXR/compositor-client p99 is 8.47/9.20 ms; 120 Hz tails and physical display delivery remain open.
- [ ] Qualify longer moving gameplay, cold/warm variability and physical display delivery beyond those short exterior samples. Reject optimizations without a controlled benefit.
- [x] Preserve first-use presentation gamma, alpha and cropped fades under both asynchronous compile policies, without skipped copies or mismatched pipeline fallbacks.
- [x] Prevent black-border sampling at scaled OpenXR image edges, including during fades and accepted brightness adjustments; ordinary desktop sampling is unchanged.
- [ ] Qualify cold ordinary-world shaders and scene transitions under the shipping compile policy, including real-runtime timing and visual stability.
- [x] Recover stereo and actual runtime-controller inventory/Back after native chapter introductions and loading in CS2, BEC, TE4, RC1 and R25, using visible interactive gameplay rather than the first transient room layer; inspect compositor evidence and finish with normal controller Quit.
- [x] Remove native buttons' blocking 70 ms + 50 ms feedback waits only while VR is successfully presenting; preserve native callbacks, ordinary play, hidden/failed sessions and unrelated sleeps. Actual five-scene controller-return gaps fall from 134–143 ms to 20–31 ms, without extra simulation or frame submissions inside callbacks.
- [x] Prepare a new world's native resources before joining its stereo frame, keeping the loading helper's head-tracked blank frames active. Restore preparation globals on ordinary return/unwind, invalidate ownership on native retirement, and verify connected controller play, map travel and movies without changing flat files.
- [ ] Reduce remaining comfort-critical scene-loading pauses. State-scoped preparation reduces sampled return-to-world gaps from a matched 28.78 ms control to 11.10/11.66 ms. Later world frames still reach about 15 ms. Native page counters alone do not measure loading-helper frames; uninterrupted refresh-rate-budget presentation, same-frame transition fidelity and physical comfort remain unqualified.
- [ ] Check stereo consistency, clipping/culling, text sharpness, brightness and texture fidelity in a headset.

Latest short synthetic benchmark: approximately **120 fps with and without
isolated status text**, including native per-eye scenery and visible-model
probes. This uses a 4K game canvas, 2048×2048 runtime images per eye and no
diagnostic readbacks.
The latest matching actual-SteamVR build repeats **119.66 stereo submissions/s
in the room** over 12 seconds and **115.65/s with advanced graphics options
open** over 6 seconds, using recommended 1568×1568 eyes and a separate 1280×800
mirror. Both compositor eyes are populated, inventory/modal return and native
Quit cancellation/exit pass, and SteamVR closes gracefully. Earlier expanded
resolution-list measurements are not superseded by this advanced-menu sample.
These bounded submission counts do not establish sustained headset-delivered
performance. Exterior pacing and the release performance gate remain open.

## Installation, release and acceptance

- [x] Compose the seated VR features through one package-level compiler, without mutating the flat baseline; verify the complete output by independent deterministic rebuild.
- [x] Regression-test composition across all supported executable profiles, including altered hooks, mismatched calibration, missing dependencies and dormant activation defaults.
- [x] Qualify the package-generated program through private-game controller typing, save/restore, interaction recovery and clean quit; sample ordinary room/inventory keyboard input with VR disabled.
- [x] Verify prototype DLL identity, pinned renderer recipe, complete OpenXR source/test inventory, native/GPU qualification records and required notices; reject prototypes from the flat release gate even if renamed.
- [x] Build and reuse verified prototypes through a separate package-level build service and local record, preserving flat build records and the last successful prototype when compilation or verification fails.
- [x] Compile and independently verify an alternate player bound to its private renderer, with regression coverage across all supported executable profiles.
- [x] Demonstrate the alternate `GK3-VR.exe` beside the original game data, using its private renderer configuration, with ordinary room/inventory input and VR disabled; leave the flat executable, renderer and INI unchanged.
- [x] Qualify immersive controller interaction, save/restore and clean exit through the isolated player, not only the earlier shared-renderer prototype.
- [x] Verify fixed-scope file publication/removal, interrupted-operation recovery and preservation of flat or externally changed files; test corrupt/missing cache, running-game guards and Windows junction rejection.
- [x] Install, independently verify, update and remove the player through a package service in a fresh private target, with flat files unchanged and no VR-owned files left behind.
- [x] Test suspended-child activation: verify all eight dormant switches before writing, enable them before resuming, preserve executable bytes and clean up failed activation.
- [x] Validate the selected 32-bit runtime manifest and DLL, respecting explicit selection and the 32-bit registry view; use installed SteamVR as a child-only fallback without changing the system runtime.
- [x] Qualify controller-operated title Restore and the save/restore/interaction/Quit flow through the managed installation service, with VR active before startup and flat files preserved.
- [x] Skip the opening movie, select Play on a fresh title screen with Restore disabled and reach native hotel-room stereo through the public launcher using synthetic controllers, without host input.
- [x] Complete the fresh-game controller flow through native toolbar Options, Quit and Yes, waiting for the game's normal button enablement; verify clean exit, unchanged flat files and removal afterward.
- [x] Expose explicit development-only build/install/verify/launch/uninstall commands; test defaults, delegation, prototype warnings and actionable failures without affecting normal installation.
- [x] Run actual CLI installation, verification and removal against a supported private game copy, with flat files unchanged and all owned installation files removed.
- [x] Qualify the public supervisor with the unmodified installed player and verified renderer: controller-only movie skipping, title interaction, clean exit, disk verification and removal using the GPU test runtime.
- [x] Qualify a complete public-command flow with matching artifacts and actual SteamVR presentation: build reuse → default local install → verify → launch → controller title/room/SIDNEY printing/inventory/return/Quit → uninstall. The 55.82-second sample preserves flat files and preferences. This uses the verified cached renderer build and synthetic controllers, not a new cold compilation or physical-headset acceptance.
- [x] Qualify a connected public-command gameplay session with the matching player/renderer: controller-typed save → changed camera → exact restore → native SIDNEY entry/search/Exit → native saved-story reload → map highlights/travel → original introduction Skip → inventory/Back → movement/snap turn → Quit-No/Yes → uninstall. The capture-free actual-SteamVR sample passes in 67.80 seconds with unchanged flat files/preferences and graceful runtime shutdown. Console staging is explicit and physical controllers/headset comfort remain unqualified.
- [x] Unit-test the launch supervisor's no-frame timeout, runtime bootstrap errors, cancellation and clean-exit behavior, including ownership of the child process and child-only settings.
- [x] Give a cancelled running player up to three seconds for native Quit/renderer teardown before forced cleanup. Retain ownership of its primary thread; do not post to another game or wait on a suspended player. Actual public-command tests exit cleanly from a stereo room in 0.26 seconds, a native confirmation dialog in 0.22 seconds, and the physical Pimax/SteamVR path in 0.32 seconds. CLI cancellation returns 130, the game exits zero, no forced game/runtime stop is needed, and flat/global state is preserved. Suspended startup, missing queues, failed requests and hung games retain bounded owned-handle cleanup. This does not prove the earlier vendor slow-state trigger or physical reconnection behavior.
- [x] Quit and relaunch through two complete public-command cycles in the same actual SteamVR session. Both freshly installed players recover controller Play, raw head tracking, tracking-loss input guards, anchored Inventory/Exit, upright recenter and Quit-No/Yes; both uninstall with flat files/preferences preserved. The 75.02-second two-cycle workbench uses synthetic devices, not a physical reconnect or worn headset.
- [x] Exercise actual SteamVR startup without submitted frames, verifying bounded failure, owned-child termination, unchanged player bytes and clean removal; the private test uses a shortened six-second startup deadline.
- [x] Distinguish terminal OpenXR session/instance loss and runtime-requested exit from temporarily hidden/stopping states. Native lifecycle and supervisor tests verify actionable failure, owned-child cleanup and a terminal-log/zero-exit race. The freshly built renderer passes all six native test groups and GPU/flat qualification. Actual SteamVR user-requested shutdown after stereo closes the game and supervisor without forced runtime components; it uses native window closure, not the terminal-error branch. Hard physical disconnection and automatic reconnection remain unqualified.
- [x] Stop the owned game and report restart/unsaved-progress guidance if the selected SteamVR server abruptly dies while a native XR call is blocked. Bind a query/synchronize-only handle to the exact server executable/lifetime after frames begin; do not use a frame-stall timeout or terminate runtime processes. Unit tests and an actual public-command private-runtime crash test pass, with the game stopped in 0.21 seconds and flat/global state preserved. Physical headset disconnection and automatic reconnection remain unqualified.
- [x] Stop only the owned player when a render adapter explicitly disables itself with a failing result. Read verified world/interface status even if error logs are buffered; do not mistake hidden/in-progress frames or native loading for failure. A real failing eye-callback test verifies actionable relaunch/unsaved-progress guidance and a 0.15-second owned-player stop, with ordinary files preserved.
- [x] Recheck connected save/restore, SIDNEY, map travel, inventory/navigation and normal Quit with rendering-failure supervision enabled. The current pair passes in 65.55 seconds without false failure reports, with flat files/preferences unchanged, clean removal and graceful private-runtime shutdown.
- [x] Distinguish an unreadable render-status snapshot during natural teardown from a confirmed disabled/failed adapter. Two consecutive current-player sessions in one private runtime pass tracking loss/recovery, recenter, native Quit and clean removal in 63.29 seconds total, without false failure reports or forced runtime shutdown.
- [x] Qualify the real 30-second no-frame startup deadline and healthy relaunch in the same private SteamVR setup. Keep display-preference protection launch-owned, independent of render failure. v337 reaches the native room with zero submitted frames, exits normally at 30.22 seconds, preserves flat display preferences before harness cleanup, then relaunches stereo and passes Quit/cancellation without restarting SteamVR. Clean removal and graceful runtime shutdown pass. This is actual-runtime fault injection, not physical headset reconnection.
- [ ] Qualify remaining launcher failure/recovery against an actual headset, including physical reconnection.
- [ ] Clear runtime/headset diagnostics and safe handling of unavailable VR, without persistent development environment variables.
- [x] Explain sustained headset-tracking loss/recovery through the public CLI, independently of fatal rendering/session failure. Debounce startup changes, suppress repeats and unknown observations, retain all input safeguards and bound status reads. Native/Python behavior tests and an actual SteamVR/Pimax public launch pass: one unavailable warning, continued 119.74 stereo submissions/sec, native Quit/cancel/confirm and preserved private/global state. The updated private renderer/player is installed and verified; physical tracking/recovery remains unqualified.
- [x] Qualify the public feedback/rearm path end to end through actual SteamVR diagnostic head/controller devices: tracked → sustained loss → recovery, legal continued presentation, no usable lost-tracking world ray, no held-Inventory replay, fresh Inventory/Back and normal native Quit/cancel/confirm. The 28.06-second sample preserves the prepared installation, flat/global state and graceful runtime shutdown. Input is independently confirmed enabled; physical tracking/controller acceptance remains separate.
- [x] Qualify current-pair dormant play and clean removal. A 33.27-second private test passes Play/inventory/Quit cancellation/confirmation with all VR switches zero, removes every owned VR file without altering flat files/saves, then passes the same flow with the recommended flat executable and current renderer in non-XR mode. Both exit normally. Test-only flat controls are restored exactly afterward; native flat preferences are snapshot/restored, not claimed to be unwritten. Earlier foreground/readiness failures remain recorded and an older-renderer black capture is not claimed fixed.
- [x] Document the opt-in prototype's setup, supported target, controller controls, logs, known limitations and short first-physical-acceptance procedure in `VR.md`; keep the headset-ready/release claim explicitly withheld.
- [x] Keep installation progress compatible with redirected Windows output. Reproduce a completed installation reporting a cp1252 spinner error, use the existing ASCII line style and shared CLI console, regression-test a real encoded stream, then independently install/verify the private player through the plain public commands without a UTF-8 override.
- [ ] Automated regression coverage for the complete supported install/launch/gameplay flow.
- [x] Bring the default developer test command below 60 seconds and its full `--slow` run below 180 seconds on this Windows workbench without dropping behavior coverage. `uv run poe test` uses up to four workers with scope grouping: the current fast run passes 5,477 tests with 23 skipped in 30.13 seconds; the full slow run passes 5,879 tests with 23 skipped in 84.15 seconds. Cache immutable compiled fixture bytes, not shared mutable images. Plain pytest remains serial; live-game visual tests remain separate and serial. These are measured local timings, not hardware-independent guarantees.
- [ ] Representative early/middle/late-game playthrough checks, including puzzles, saves and scripted sequences.
- [ ] Real-headset acceptance on a first supported setup, then compatibility checks on the other available headsets where feasible.
- [ ] Prepare a versioned release with renderer provenance/notices only after the above release gates pass.

Earlier focused Python VR suite: **182 passed, 3 skipped** in 12.10 seconds,
including oversized calibration input.
This includes compiler/artifact/installer behavior, process control, runtime
selection, launch supervision and CLI tests. Skips are Windows symlink-creation
restrictions, not passing qualification. The managed private-game controller
flow, public title/Quit flow and public fresh-game flow also pass. None
establishes physical headset acceptance. Private-game evidence and artifacts stay
in the ignored `build/vr/` directory, not in the installed Steam game.
The latest full default regression run passed **4,364 tests**, with 23 skips and
402 slow-test deselections, in 66.42 seconds. Full formatting, lint, strict type
checks and spelling checks also pass. This is a passing behavior check, not
achievement of the under-60-second timing gate.
The duration profile finds expensive full-size texture fixtures as well as
repeated native composition. No tests were removed, marked slow or weakened to
make this run appear to meet the timing target.

Latest full default-suite repeat: **4,425 passed, 23 skipped, 402 slow-test
deselections in 78.46 seconds**, with live-game experiments stopped. The behavior
checks pass, but this repeat still does not meet the under-60-second timing gate.
Latest repeat: `build/vr/button-wait-fast-suite-20261011.log`.
Earlier duration profile: `build/vr/fast-suite-profile-final-20261011.log`.

Latest additional checks: **56 passed** in 2.40 seconds for title readiness,
launch supervision, process ownership and CLI behavior. Fresh title-screen
readiness is tested at 1024×768, 1280×800 and 4K without treating disabled
Restore as a selectable control. Full lint passes. Actual SteamVR discovery
now passes with the built-in virtual headset and isolated configuration in
1.12 seconds. Actual SteamVR title and room submission checks also pass, but
compositor presentation/pacing and physical-headset acceptance remain open.
Latest evidence:
`build/vr/public-launch-20261010/new-game.json` and
`build/vr/steamvr-null-20261011/{probe,game,world}.json`.

Latest windowed-boundary regression checks: **230 passed, 3 skipped** in
9.02 seconds; a repeat during renderer compilation took 20.28 seconds with
the same result. Full formatting, lint and type checks pass. The new bridge is
compiled only into the isolated VR player, stays dormant with VR disabled and
does not manufacture successful native Flip generations. Actual SteamVR title
submission passes in windowed mode, and fullscreen hotel-room stereo still
passes. Direct compositor evidence is in
`build/vr/steamvr-native-20261011/world-compositor-{left,right}.bmp` and
`build/vr/steamvr-visible-20261011/title-compositor-left.bmp`.

Latest modal-mirror renderer build passes all six native tests and the flat,
OpenXR and asynchronous-copy GPU qualification checks. The matching artifact
is in `build/vr/windowed-mirror-copy-qualified-20261011/`. Actual SteamVR title,
windowed hotel-room, minimize/restore and repeated 4K checks are recorded in
`build/vr/steamvr-visible-20261011-mirror/{game,world}.json` and
`build/vr/steamvr-native-20261011-mirror/world.json`. These runs verify private
installation removal and unchanged flat files/global runtime settings. Their
test-owned termination is not clean native Quit acceptance.

Latest background-pacing correction also passes a repeated native-4K room
sample: 348 stereo frames in 3.011 seconds, approximately 116 frames/s. The
renderer recipe is unchanged from the qualified modal-mirror build. Native-code
regression tests cover active/dormant producers, pending-frame cancellation,
inactive presentation, device-health failures and preserved registers/flags.

## Explicitly outside the first release

Room-scale walking, hand grabbing, character embodiment, gesture controls and a
standalone headset port. Proton/OpenXR and additional runtimes remain follow-up
compatibility work. None of these substitutes for finishing the seated release.
