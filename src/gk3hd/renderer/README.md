# Modified D7VK candidate

This is an altered build of [D7VK](https://github.com/WinterSnowfall/d7vk),
not an official upstream release. The upcoming gk3hd release pins this modified
build as its default on Windows and Linux. Its GitHub DLL must be uploaded
before that package is published. The package includes the source patch and native
build checks; downloaded source, compilers and binaries stay in ignored build output.
The altered renderer source retains D7VK's zlib/libpng license in `LICENSE`.

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
settings remain intact; uninstall restores the exact original file and refuses
to overwrite later user edits. Stock upstream D7VK does not contain these changes.

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
and compiles and runs the native tests. It stops on any failure and packages
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
The outputs are `d7vk-VERSION.dll`, `d7vk-VERSION.txt` (third-party notices), and
`d7vk-VERSION.json` (build provenance). Use `gk3hd package draft --renderer`;
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

The current lock targets the planned v1.0 asset; it is not evidence that the
asset has been published. The build command itself never commits, tags, uploads,
or publishes. Preserve upstream license notices and identify modified versions.
