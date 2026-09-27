# Modified D7VK candidate

This is an altered build of D7VK on the pinned
[DXVK-Sarek](https://github.com/pythonlover02/dxvk-sarek) backend, not an official
upstream release. It carries our D7VK surface, sampling and performance fixes
without the newer backend's Vulkan extension requirements that prevented
GE-Proton 8 from starting GK3. It also preserves the windowed backbuffer across
presentations, avoiding stale pixels during incremental interface redraws.
The build recipe produces a candidate for the next renderer release; it does not
replace the published DLL. Its GitHub DLL must be uploaded before users can
download it. The package includes the source patch and native
build checks; downloaded source, compilers and binaries stay in ignored build output.
The altered renderer source retains the zlib/libpng license and upstream
attributions. Release notices include both the pinned source's dependencies and
the D7VK code carried from the previous backend.

The candidate batches CPU/GPU surface transfers, preserves shared surface state
across DirectDraw interface versions, and retains the desktop refresh rate.
It requires `ddraw.cpuRenderTargetBacking = True`; this opt-in is disabled by
default. Eligible RGB565 stretches use consistent fixed-point pixel-center
sampling, including source color keys and SRCCOPY operations. This preserves
the original glyph footprint when stretching an exact 4x atlas replica.
Clipped/unsupported operations retain native DirectDraw fallback.
Color-key draws do not temporarily replace the application's shaders/render
state: the unnecessary GPU key-draw/cache path has been removed.
GK3 also needs the `speed_up_surface_checks` engine patch: fixing the renderer
alone does not remove the game's unnecessary full-screen readiness readbacks.
Selecting D7VK in the installer now journals `dxvk.conf` as well as the DLL.
It appends an executable-specific section for legacy presentation, its strict
guard, CPU render-target backing and uncapped D3D9 presentation. Unrelated
settings remain intact. Shader pipelines compile before their draw, rather than
temporarily substituting a pipeline with different blending or depth state.
Uninstall restores the exact original file and refuses
to overwrite later file edits. Later registry edits or deletions are retained
without blocking uninstall. Stock upstream D7VK does not contain these changes.

The renderer also exports `Gk3hdSurfaceHistoryDepth(IDirectDrawSurface*)`
(`DWORD`, Windows `stdcall`). It returns `1` only for a recognized, initialized,
non-lost surface with retained CPU backing, and `0` otherwise. The query does
not allocate backing, copy pixels, or change the swapchain. The fixed-interface
patch uses this capability to restore the cursor's immediately previous
background instead of an older rotating-page history. Missing exports and
unsupported surfaces retain the original game behavior; no renderer-name guess
or global override of the game's buffer count is used.

The D3D6 binding fix retains each bound Texture2's parent surface through a
private reference. Retaining only the texture wrapper allowed the parent to be
freed and its memory reused during scene transitions. This preserves texture
identity without changing application-visible reference counts; native tests
release application references, churn differently sized surfaces, and verify
the retained dimensions and pixels at every texture stage.

`Gk3hdAreaBlend565` is a separate, versioned `stdcall` entry point for reducing
dense inventory artwork. It averages RGB565 color and L8 opacity together over
each destination pixel's exact source footprint, preserving GK3's integer fade
weights and transparent source keys. The caller supplies a sized view of locked,
non-overlapping buffers and owns their allocation/lock lifetimes. The function
retains no pointers, allocates nothing, and leaves unsupported inputs untouched.
The game patch scopes this operation to dense inventory items; ordinary font
and pixel-art stretching continues to use exact point sampling.

`Gk3hdAreaBlt565` provides a separate, explicitly requested opaque area reduction
between wrapped Surface1 interfaces. A 48-byte x86 request contains its size,
destination/source interfaces, copied destination/source rectangles and an output
HRESULT. The return value is one only when handled; a declined request leaves
the HRESULT and pixels untouched. An error after a lock or write is reported as
handled, so callers must not retry using another sampler. The operation preserves
lock/unlock ownership, rejects clippers and aliases, and supports bounded RGB565
minification with exact footprint weights and nearest channel rounding. It does
not apply alpha, color keys, gamma conversion or a global filtering override.
The engine adapter selects only reviewed dense opaque action artwork. Unsupported
images and renderers without the capability retain the native draw path.

## Build

Use Windows with PowerShell 7, Visual Studio C++ Build Tools (MSVC 19.44.35222),
Windows SDK 10.0.26100.0, Git, uv, and a Vulkan-capable GPU/driver. The command
automatically locates and activates the pinned x86 toolchain; an ordinary
PowerShell terminal is sufficient. Then run:

```powershell
uv run gk3hd renderer build
```

The command clones the pinned upstream commit and submodules, verifies the
shader-compiler download, applies the patch, builds only the x86 DirectDraw DLL,
and compiles and runs the native tests, including pixel retention across actual
screen presentations (needed for GK3's incremental interface redraws).
Third-party notices are declared once in the pinned recipe and checked before
the release files can be accepted.
It stops on any failure and packages
nothing until the tests pass. It never launches GK3 or changes its executable,
active renderer or settings. Run `uv run gk3hd renderer install --local` to install the
successful build with its required settings.

Output defaults to a recipe-hashed directory under `<GAME>/gk3hd/renderer/`.
The game is detected automatically; `--game-dir PATH` selects another installation.
Matching, verified builds are reused; changed recipe inputs select a fresh directory.
Use `--output PATH` for an explicit fresh build directory. The build record still
lives in the selected game's renderer workspace, so `install --local` can find it
from any current directory.
The `latest.json` record identifies the last successful build for installation
and release commands. Interrupted/incomplete directories are never overwritten.
The outputs are `dxvk-sarek-VERSION.dll`, `dxvk-sarek-VERSION.txt` (third-party notices), and
`dxvk-sarek-VERSION.json` (build provenance), where `VERSION` includes the upstream
version and our modification revision (currently `1.13.0-gk3hd.1`).
Use `gk3hd package draft --renderer`;
the release tool verifies and uploads all three files separately. The reviewed
source patch stays in this repository at the release tag. Only the DLL is
downloaded by the installer and installed as `ddraw.dll`; there is no renderer ZIP
or separate D3D9 DLL. Fresh installs discover the most recently published stable
release containing a renderer DLL and verify GitHub's size and SHA-256 digest.
Recovery and uninstall use the exact recorded identity, never a new discovery.
Source/toolchain inputs are pinned; byte-identical builds across different
machines have **not** yet been demonstrated. Release binaries omit PDB records;
debug builds use a [filename-only PDB reference](https://learn.microsoft.com/en-us/cpp/build/reference/pdbaltpath-use-alternate-pdb-path).
The recipe maps compiled source paths to `gk3hd-build` without disabling
assertions, and rejects binaries containing the actual build directory.

## Acceptance gates

The synthetic native tests cover all five surface interfaces, partial locks,
clipping, color keys, GDI writes, device recreation, failed-transfer retries,
and 240 fractional keyed/unkeyed/ROP stretches. Exact atlas replicas must retain
the original footprint; clipped stretches must match native fallback. They use
generated pixels, not game assets. Five helper tests additionally check region
bookkeeping against a pixel model, lock tracking, exact full-resolution copies,
overlapping/padded storage, and rejected/failed stretch operations. A sixth
helper tests area reduction against an independent integer reference, including
fractional and one-axis scaling, opacity/fades, keys, tile origins, refusal
without writes, and exact channel rounding. It repeats the tests through the
actual DLL export to check the x86 calling convention and request layout.

A seventh helper checks opaque area reduction against an independent integer
reference, including fractional sizes, one-axis reduction, subrectangles, padding,
overlapping storage, malformed formats and failed locks/unlocks. Its actual-DLL
tests cover system/video memory, source subrectangles, clippers, wrong interfaces
and unknown pointers, as well as exact RGB565 output and unchanged surrounding pixels.

Private Windows tests reached approximately 120 completed game frames/s at
3840x2160 on an RTX 4090, including right-click menus, inventory and the driving
map's idle/hover states. Map captures match the earlier renderer baseline within one color level
apart from the shared blinking position marker's capture phase. This is
not a guarantee for every scene or hardware configuration, nor an independent
measurement of monitor scanout. A status-font edge discrepancy was traced to
native stretching: replaying 72 glyph draws with stable sampling now matches
the original-atlas reference byte for byte, while the game still reaches
approximately 120 frames/s. Broader scene coverage, loss/resize/failure behavior
and actual Steam Deck/Proton compatibility remain
release gates. Passing the native tests does not waive those gates.

A Windows 1280x800 native-mode check also reached approximately 120 frames/s;
all four driving-map captures matched the earlier renderer baseline within one RGB level. Capture
tools now use per-monitor DPI coordinates across display changes. This is a
resolution/layout check on Windows, not a Steam Deck hardware test. Sporadic
startup-window timeouts occurred with both tested renderers during these mode-change
experiments; a successful retry is not proof that startup is universally reliable.

## Local Proton verification

The current source candidate has also been exercised in an isolated Linux VM
with software Vulkan, including actual offline Steam launches with Proton 9,
Steam Input joystick-mouse and Mouse Region, and nested Gamescope. Tests cover
driving-map overlays and picking, edge menus, SIDNEY page transitions, Restore,
startup and software Bink playback. Independent pointer measurements include
scaled presentation and 125% Wine DPI. No growing edge offset was reproduced.
An emulated multi-interface USB Deck also exercises actual Steam Input
right-trackpad motion at native 1280x800 and with 1024x768 fitted into 1280x800.
Eight edge-menu hovers pass in each mode; the scaled control additionally checks
16 live cursor-draw positions against native input coordinates and reviews the
matching captions. The invisible host pointer is not used as the displayed
cursor oracle under Gamescope. Menu opening and dismissal use the lab mouse,
so these controls do not certify physical Deck clicks or Gaming Mode.
The laptop's own menu also passes ten native-resolution edge hovers with
matching captions; a real trackpad-selected Type action reaches the visibly
rendered SIDNEY home screen. One native-resolution activation also uses an
emulated USB Deck pad press and pressure, independently decoded from input
reports, instead of an injected mouse click. The same activation also passes
with 1024x768 fitted into 1280x800: native input and cursor-draw coordinates
agree, and SIDNEY is visibly rendered. A closer Steam gamepad-UI control exposed
a descriptor-pool exhaustion crash under software Vulkan: the renderer waited
for an allocation failure to retire pools, but Lavapipe kept accepting sets.
The recipe now enforces each pool's declared capacity and recycles it only
after GPU completion. A native regression test covers permissive drivers,
allocation failure and reset failure. Native-resolution Deck-input activation
then passes without the earlier mapping growth; a short displayed SIDNEY
stability control passes too. This does not establish universal reliability
or identify every previously unexplained exit.
The clean-built candidate passes local GE-Proton-8-32 and Experimental UI
controls as well. Experimental exposed a separate game-window issue: GK3
repeatedly reasserts an already-satisfied topmost position, which can briefly
hide Vulkan output in newer Wine. The game's `prevent_transition_flicker`
patch now skips that request only when the window is already foreground,
topmost and first in z-order. Real activation and ordering changes still use
the original Win32 call. An independent constant-image program reproduces the
issue without GK3; guarded
game tests verify the correction through Restore, the map and SIDNEY pages.

The fixed-interface game patch also requests RGB565 explicitly for the native
software-alpha scratch pool. Its callbacks write 16-bit pixels, while Wine can
otherwise create an implicit 32-bit desktop-format surface, corrupting faded
text after window recovery. This is a scoped game correction, not a global
display-depth, gamma, font-atlas or renderer filtering change. Stock and HD
Proton fade controls pass; native Windows checks preserve readable, neutral
text at 1280x800 and 4K.

The recipe also corrects the x86 calling convention of Wine's logging callback.
The upstream declaration can corrupt the caller's stack during logging, causing
otherwise valid configuration parsing to crash on Proton. A native build test
checks repeated callback calls preserve the stack; small Proton initialization
controls also exercise the actual callback with the installer configuration.

The tested dgVoodoo alternatives are not the default: one version reached the
Windows frame-rate target but failed Proton startup/text checks; another ran
under Proton 9 but lost 3D output under Experimental. Switching renderers would
therefore trade known failures rather than resolve the compatibility goal.
The D7VK candidate remains separate from the published renderer until release
review; local test results do not silently update users' downloaded DLLs.

Matched Windows 4K camera controls complete roughly 116 frames per second at
120 Hz. Earlier warmed controls reach about 119; these count successful game
frame flips, not physical scanout, and do not guarantee that rate in every
scene. Descriptor-pool reset measurements did not identify a meaningful CPU
bottleneck. Smaller readback batches can introduce more GPU synchronization,
so they were not adopted without a demonstrated benefit.

Keyboard yaw now ramps from its precise base speed to twice that speed over
500 ms of held input. A live 4K half-turn takes about 1.92 seconds rather than
3.54; a 100 ms tap remains roughly five degrees including native smoothing.
Pitch, walking, strafing and physical mouse movement retain their existing
behavior. Native execution tests cover direction changes, idle, timer wrap,
different update cadences and resolutions, including 1280x800. A separate
Windows 1280x800 startup capture timed out at the title screen; it is retained
as an inconclusive capture failure, not counted as a passing live turn test.

The final local edge-hover control additionally waits for the cursor's actual
pixels in the compositor capture. All ten hovers then show the matching button
caption. Waiting only for native draw callbacks or completed flips was not
sufficient with software Vulkan: earlier screenshots contained a coherent but
older cursor/caption pair. This capture lag is not evidence of the reported
physical Deck cursor-on-one-button/caption-for-another discrepancy.

This is correctness evidence, not Steam Deck certification or Linux GPU
performance evidence. Physical trackpad/Gaming Mode, AMD hardware, and every
displayed frame remain unverified; the reported Deck pointer offset remains
unresolved. These results do not describe the older published renderer DLL.

## Release

After gameplay review and committing reviewed work, attach the build through
the same release task as the textures:

```powershell
uv run gk3hd package draft --textures --renderer
```

The task checks the DLL against this recipe, verifies the reported test results
and hashes, and requires the separate notices and build record alongside it.
It pins the upcoming tag before committing release metadata, then uploads the
DLL, notices, build record, and texture parts to a GitHub draft. This does not require a public URL
to exist before preparing the lock. Omit `--renderer` to retain the published
renderer; omit `--textures` to retain the published texture pack. Each may use
a different older tag. Publishing the reviewed draft triggers a gate checking
both asset families before PyPI publication. It does not rerun native GPU tests.

The lock identifies the existing published renderer baseline, not the new build
candidate. The build command itself never commits, tags, uploads,
or publishes. Preserve upstream license notices and identify modified versions.
