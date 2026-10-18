#Requires -Version 7.0
<#
.SYNOPSIS
Build and test the modified x86 D7VK candidate without installing or publishing it.
.DESCRIPTION
Run from PowerShell with uv and Git available; the installed x86 C++ toolchain is activated automatically.
The output directory must not exist. All downloaded source and binaries stay there.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [ValidateRange(1, 64)][int]$Jobs = 12,
    # Development-only candidate, deliberately not accepted by the release CLI.
    [switch]$OpenXR
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

function Assert-Hash([string]$Path, [string]$Expected) {
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Expected) {
        throw "SHA-256 mismatch: $Path"
    }
}

function Get-SourceHash([string]$Path) {
    $bytes = [Text.Encoding]::UTF8.GetBytes([IO.File]::ReadAllText($Path).Replace("`r`n", "`n"))
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

$pin = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'upstream.json') -Raw | ConvertFrom-Json
$patch = Join-Path $PSScriptRoot 'renderer.patch'
$patchHash = (Get-FileHash -LiteralPath $patch).Hash
$pinHash = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'upstream.json')).Hash
foreach ($command in @('uvx', 'git')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing $command; install it and make it available on PATH."
    }
}
if ($OpenXR) {
    foreach ($command in @('cmake', 'ctest')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            throw "Missing $command; install CMake for the optional OpenXR build."
        }
    }
}
if ($env:CL -or $env:_CL_ -or $env:LINK -or $env:_LINK_) {
    throw 'Clear custom CL, _CL_, LINK and _LINK_ arguments before building the pinned recipe.'
}
. (Join-Path $PSScriptRoot 'toolchain.ps1')
Initialize-Gk3hdToolchain $pin
$output = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $output) { throw "Output already exists; choose a fresh -OutputRoot: $output" }
New-Item -ItemType Directory -Path $output | Out-Null
$source = Join-Path $output 'source'
$build = Join-Path $output 'build'
$sourcePatch = Join-Path $output 'renderer.patch'
$xrInputs = [ordered]@{}
$xrStage = $null
$candidateVersion = $pin.version
# Git may check out the recipe with CRLF; git apply needs an LF-only diff.
[IO.File]::WriteAllText($sourcePatch, [IO.File]::ReadAllText($patch).Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
$shaderArchive = Join-Path $output 'glslang.zip'
$shaderRoot = Join-Path $output 'glslang'
$oldPath = $env:PATH
$oldConfig = $env:DXVK_CONFIG_FILE
$oldInlineConfig = $env:DXVK_CONFIG
$oldLogPath = $env:D7VK_LOG_PATH
$oldDxvkLogPath = $env:DXVK_LOG_PATH
$oldCl = $env:CL
$oldXrPrototype = $env:GK3HD_XR_PROTOTYPE
$oldXrRuntime = $env:XR_RUNTIME_JSON
$oldXrBgra = $env:GK3HD_XR_TEST_BGRA
$oldXrEyeSize = $env:GK3HD_XR_TEST_EYE_SIZE
$oldXrSkipReadback = $env:GK3HD_XR_TEST_SKIP_PIXEL_READBACK
try {
    # Flat checks must not inherit a development VR launch setting.
    $env:GK3HD_XR_PROTOTYPE = $null
    # Qualification owns its compile policy, including inline overrides.
    $env:DXVK_CONFIG = $null
    # Preserve assertions while making their __FILE__ paths independent of
    # the builder. This compiler version requires both options together.
    $env:CL = '/experimental:deterministic /pathmap:"' + $output + '=gk3hd-build"'
    Invoke-Checked git @('-c', 'core.autocrlf=false', 'clone', '--depth', '1', '--branch', $pin.tag,
        '--recurse-submodules', '--shallow-submodules', $pin.repository, $source)
    $head = Invoke-Checked git @('-C', $source, 'rev-parse', 'HEAD')
    if ($head -ne $pin.commit) { throw 'Upstream tag no longer matches the pinned commit.' }
    $submodules = @(Invoke-Checked git @('-C', $source, 'submodule', 'status', '--recursive'))
    if ($submodules | Where-Object { $_ -notmatch '^ [0-9a-f]{40} ' }) {
        throw 'An upstream submodule does not match its recorded commit.'
    }
    Invoke-Checked git @('-C', $source, 'apply', '--check', $sourcePatch)
    Invoke-Checked git @('-C', $source, 'apply', $sourcePatch)
    if ($OpenXR) {
        $xrRecipe = Join-Path $PSScriptRoot 'vr'
        $xrSource = Join-Path $output 'xr-source'
        $xrBuild = Join-Path $output 'xr-build'
        $xrStage = Join-Path $source 'src/gk3hd_xr'
        New-Item -ItemType Directory -Path $xrSource | Out-Null
        foreach ($input in (Get-ChildItem -LiteralPath $xrRecipe -File | Sort-Object Name)) {
            if ($input.Extension -in @('.cpp', '.h', '.patch') -or $input.Name -eq 'CMakeLists.txt') {
                $xrInputs[$input.Name] = Get-SourceHash $input.FullName
                Copy-Item -LiteralPath $input.FullName -Destination (Join-Path $xrSource $input.Name)
            }
        }
        $xrPatch = Join-Path $xrSource 'sarek.patch'
        [IO.File]::WriteAllText($xrPatch, [IO.File]::ReadAllText($xrPatch).Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
        Invoke-Checked git @('-C', $source, 'apply', '--check', $xrPatch)
        Invoke-Checked git @('-C', $source, 'apply', $xrPatch)
        Invoke-Checked cmake @('-S', $xrSource, '-B', $xrBuild, '-G', 'Visual Studio 17 2022',
            '-A', 'Win32', '-T', "version=$($env:VCToolsVersion.TrimEnd('\'))",
            "-DCMAKE_SYSTEM_VERSION=$($pin.windows_sdk)",
            "-DFETCHCONTENT_SOURCE_DIR_VULKAN_HEADERS=$(Join-Path $source 'include/vulkan')")
        & cmake --build $xrBuild --config Release --parallel "$Jobs"
        if ($LASTEXITCODE -ne 0) {
            # A failed parallel MSBuild worker can leave otherwise valid units
            # unfinished. One serial retry still requires a successful compile
            # and the same independent tests before any artifact is accepted.
            Write-Host 'Parallel native build failed; retrying once serially.'
            Invoke-Checked cmake @('--build', $xrBuild, '--config', 'Release', '--parallel', '1')
        }
        Invoke-Checked ctest @('--test-dir', $xrBuild, '-C', 'Release', '--output-on-failure')
        Invoke-Checked cmake @('--install', $xrBuild, '--config', 'Release', '--component', 'Renderer', '--prefix', $xrStage)
        $candidateVersion += '-xr-prototype'
    }
    Invoke-WebRequest -Uri $pin.glslang_url -OutFile $shaderArchive
    Assert-Hash $shaderArchive $pin.glslang_archive_sha256
    Expand-Archive -LiteralPath $shaderArchive -DestinationPath $shaderRoot
    Assert-Hash (Join-Path $shaderRoot 'bin/glslang.exe') $pin.glslang_exe_sha256
    $env:PATH = (Join-Path $shaderRoot 'bin') + [IO.Path]::PathSeparator + $env:PATH
    $meson = @('--from', "meson==$($pin.meson)", '--with', "ninja==$($pin.ninja)", 'meson')
    $xrOptions = if ($OpenXR) { @('-Dgk3hd_openxr=true') } else { @() }
    Invoke-Checked uvx ($meson + @('setup', $build, $source, '--buildtype=release', '--wrap-mode=nodownload',
        '-Denable_ddraw=true', '-Denable_d3d9=true', '-Denable_dxgi=false', '-Denable_d3d8=false',
        '-Denable_d3d10=false', '-Denable_d3d11=false', '-Dbuild_id=false',
        "-Dgk3hd_version=v$candidateVersion") + $xrOptions)
    $machines = Get-Content -LiteralPath (Join-Path $build 'meson-info/intro-machines.json') -Raw | ConvertFrom-Json
    $compilers = Get-Content -LiteralPath (Join-Path $build 'meson-info/intro-compilers.json') -Raw | ConvertFrom-Json
    if ($machines.host.cpu_family -ne 'x86' -or $machines.host.system -ne 'windows' -or
        $compilers.host.cpp.id -ne 'msvc' -or $compilers.host.cpp.version -ne $pin.msvc -or
        $compilers.host.c.id -ne 'msvc' -or $compilers.host.c.version -ne $pin.msvc) {
        throw "The compiler must be x86 MSVC $($pin.msvc); see upstream.json."
    }
    Invoke-Checked uvx ($meson + @('compile', '-C', $build, '-j', "$Jobs", 'ddraw'))
    $dll = Join-Path $build 'src/ddraw/ddraw.dll'
    $bytes = [IO.File]::ReadAllBytes($dll)
    $pe = [BitConverter]::ToInt32($bytes, 0x3c)
    if ([BitConverter]::ToUInt32($bytes, $pe) -ne 0x4550 -or
        [BitConverter]::ToUInt16($bytes, $pe + 4) -ne 0x14c -or
        [BitConverter]::ToUInt16($bytes, $pe + 24) -ne 0x10b -or
        -not ([BitConverter]::ToUInt16($bytes, $pe + 22) -band 0x2000)) {
        throw 'The renderer is not an x86 PE32 DLL.'
    }
    $debugRva = [BitConverter]::ToUInt32($bytes, $pe + 24 + 96 + 6 * 8)
    $debugSize = [BitConverter]::ToUInt32($bytes, $pe + 24 + 96 + 6 * 8 + 4)
    if ($debugSize) {
        # MSVC may emit POGO layout data even without debug symbols. Reject
        # CodeView/PDB records, not that harmless optimization metadata.
        if ($debugSize % 28) { throw 'Malformed PE debug directory.' }
        $sectionCount = [BitConverter]::ToUInt16($bytes, $pe + 6)
        $sections = $pe + 24 + [BitConverter]::ToUInt16($bytes, $pe + 20)
        $debugOffset = $null
        for ($i = 0; $i -lt $sectionCount; $i++) {
            $section = $sections + 40 * $i
            $rva = [BitConverter]::ToUInt32($bytes, $section + 12)
            $rawSize = [BitConverter]::ToUInt32($bytes, $section + 16)
            if ($debugRva -ge $rva -and $debugRva + $debugSize -le $rva + $rawSize) {
                $debugOffset = [BitConverter]::ToUInt32($bytes, $section + 20) + $debugRva - $rva
            }
        }
        if ($null -eq $debugOffset -or $debugOffset + $debugSize -gt $bytes.Length) {
            throw 'PE debug directory is outside file-backed sections.'
        }
        for ($offset = 0; $offset -lt $debugSize; $offset += 28) {
            if ([BitConverter]::ToUInt32($bytes, $debugOffset + $offset + 12) -eq 2) {
                throw 'The release DLL unexpectedly contains CodeView/PDB records.'
            }
        }
    }
    foreach ($encoding in @([Text.Encoding]::ASCII, [Text.Encoding]::Unicode)) {
        $text = $encoding.GetString($bytes)
        if ($text -match '(?i)[a-z]:[\\/](?:users|home)[\\/]') {
            throw 'The DLL contains a machine-specific home-directory path.'
        }
        foreach ($root in @($output, $PSScriptRoot)) {
            foreach ($spelling in @($root, $root.Replace('\', '/'))) {
                if ($text.Contains($spelling, [StringComparison]::OrdinalIgnoreCase)) {
                    throw 'The DLL contains an absolute build or tool directory.'
                }
            }
        }
    }
    $test = Join-Path $output 'surface-tests.exe'
    Invoke-Checked cl @('/nologo', '/std:c++17', '/EHsc', '/O2',
        (Join-Path $PSScriptRoot 'tests/check_surface_aliases.cpp'),
        "/Fe:$test", "/Fo:$(Join-Path $output 'surface-tests.obj')", # codespell:ignore fo
        '/link', 'dxguid.lib', 'user32.lib', 'gdi32.lib')
    $env:DXVK_CONFIG_FILE = Join-Path $PSScriptRoot 'tests/dxvk.conf'
    $env:D7VK_LOG_PATH = $output
    $env:DXVK_LOG_PATH = $output
    Invoke-Checked $test @($dll)
    foreach ($unit in @('region_tests', 'check_lock_regions', 'check_baseline_damage', 'check_native_copy', 'check_stretch', 'check_area_blend', 'check_area_blt', 'check_present_retention', 'check_readback', 'check_wine_log_abi', 'check_descriptor_pool')) {
        $unitExe = Join-Path $output "$unit.exe"
        Invoke-Checked cl @('/nologo', '/std:c++17', '/EHsc', '/O2',
            (Join-Path $PSScriptRoot "tests/$unit.cpp"), "/I$(Join-Path $source 'src/ddraw')",
            "/I$(Join-Path $source 'include/vulkan/include')",
            "/I$(Join-Path $source 'include/spirv/include')",
            "/Fe:$unitExe", "/Fo:$(Join-Path $output "$unit.obj")", # codespell:ignore fo
            '/link', 'ddraw.lib', 'dxguid.lib', 'user32.lib', 'gdi32.lib')
        if ($unit -in @('check_area_blend', 'check_area_blt', 'check_present_retention', 'check_readback')) { Invoke-Checked $unitExe @($dll) }
        else { Invoke-Checked $unitExe @() }
    }
    if ($OpenXR) {
        # Select the test runtime for this process only. It uses real GPU images
        # and synthetic tracking, never a headset or a persistent registration.
        $env:XR_RUNTIME_JSON = Join-Path $xrBuild 'Release/gpu-runtime.json'
        $env:GK3HD_XR_PROTOTYPE = '1'
        $env:GK3HD_XR_TEST_BGRA = $null
        # Fidelity qualification must not inherit a profiling-only workload.
        $env:GK3HD_XR_TEST_EYE_SIZE = $null
        $env:GK3HD_XR_TEST_SKIP_PIXEL_READBACK = $null
        Invoke-Checked (Join-Path $output 'check_readback.exe') @($dll)
        $xrLog = Get-Content -LiteralPath (Join-Path $output 'check_readback_ddraw.log') -Raw
        if ([regex]::Matches($xrLog, 'GK3HD: Native OpenXR renderer bootstrap enabled').Count -ne 1 -or
            [regex]::Matches($xrLog, 'GK3HD: OpenXR session and separate eye images created').Count -ne 2) {
            throw 'The GPU fixture must exercise one shared XR instance and two device/session lifecycles.'
        }
        Invoke-Checked (Join-Path $xrBuild 'Release/gk3hd-xr-transport-tests.exe') @(
            $dll, (Join-Path $xrBuild 'Release/gk3hd-xr-gpu-runtime.dll'))
        $env:GK3HD_XR_TEST_BGRA = '1'
        Invoke-Checked (Join-Path $xrBuild 'Release/gk3hd-xr-transport-tests.exe') @(
            $dll, (Join-Path $xrBuild 'Release/gk3hd-xr-gpu-runtime.dll'))
        # Critical presentation copies cannot skip or reuse a gamma/alpha
        # variant during compilation. Test first use, not warmed-up retries,
        # under both async policies while ordinary game shaders keep theirs.
        foreach ($method in @('dyasync', 'async')) {
            $env:DXVK_CONFIG = "dxvk.shaderCompilationMethod = $method"
            foreach ($layout in @('', '1')) {
                $env:GK3HD_XR_TEST_BGRA = if ($layout) { $layout } else { $null }
                Invoke-Checked (Join-Path $xrBuild 'Release/gk3hd-xr-transport-tests.exe') @(
                    $dll, (Join-Path $xrBuild 'Release/gk3hd-xr-gpu-runtime.dll'), '--critical-copy')
            }
        }
        $env:DXVK_CONFIG = $oldInlineConfig
        $env:GK3HD_XR_TEST_BGRA = $null
        $env:GK3HD_XR_PROTOTYPE = $null
    }

    # Package only after the freshly compiled native tests pass. No game files.
    Assert-Hash $patch $patchHash
    Assert-Hash (Join-Path $PSScriptRoot 'upstream.json') $pinHash
    foreach ($input in $xrInputs.Keys) {
        if ((Get-SourceHash (Join-Path $PSScriptRoot "vr/$input")) -ne $xrInputs[$input]) {
            throw "OpenXR source changed during compilation: $input"
        }
    }
    $name = "dxvk-sarek-$candidateVersion"
    $releaseDll = Join-Path $output "$name.dll"
    $notices = Join-Path $output "$name.txt"
    Copy-Item -LiteralPath $dll -Destination $releaseDll
    $licenses = @($pin.licenses.PSObject.Properties | Sort-Object Name)
    if (-not $licenses.Count) { throw 'The recipe must declare its third-party notices.' }
    $noticeText = "Modified DXVK-Sarek (D7VK-derived) for GK3HD. Source and modifications: https://github.com/lsorber/gk3hd/tree/main/src/gk3hd/renderer`n"
    # Preserve notices for code carried from our previous D7VK base, too.
    $noticeText += "`n" + (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'LICENSE') -Raw)
    foreach ($license in $licenses) {
        $noticeText += "`n=== $($license.Name) ===`n"
        $noticeText += Get-Content -LiteralPath (Join-Path $source $license.Value) -Raw
    }
    if ($OpenXR) {
        foreach ($license in (Get-ChildItem -LiteralPath (Join-Path $xrStage 'notices') -File | Sort-Object Name)) {
            $noticeText += "`n=== $($license.Name) ===`n"
            $noticeText += Get-Content -LiteralPath $license.FullName -Raw
        }
    }
    Set-Content -LiteralPath $notices -Value $noticeText -Encoding utf8NoBOM
    [ordered]@{
        version = $candidateVersion
        upstream_commit = $pin.commit
        submodules = $submodules
        msvc = $pin.msvc
        windows_sdk = $pin.windows_sdk
        meson = $pin.meson
        ninja = $pin.ninja
        source_path_mapping = 'gk3hd-build'
        patch_sha256 = (Get-FileHash -LiteralPath $sourcePatch).Hash.ToLowerInvariant()
        dll_sha256 = (Get-FileHash -LiteralPath $dll).Hash.ToLowerInvariant()
        notices_sha256 = (Get-FileHash -LiteralPath $notices).Hash.ToLowerInvariant()
        surface_tests = 'passed'
        helper_tests = 'passed'
        openxr_prototype = [bool]$OpenXR
        openxr_inputs = $xrInputs
        openxr_native_tests = if ($OpenXR) { 'passed' } else { 'not enabled' }
        openxr_gpu_tests = if ($OpenXR) { 'passed' } else { 'not enabled' }
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output "$name.json") -Encoding utf8NoBOM
    Get-FileHash -LiteralPath $releaseDll
    Write-Host "Candidate only; not installed or published: $releaseDll"
} finally {
    $env:PATH = $oldPath
    $env:DXVK_CONFIG_FILE = $oldConfig
    $env:DXVK_CONFIG = $oldInlineConfig
    $env:D7VK_LOG_PATH = $oldLogPath
    $env:DXVK_LOG_PATH = $oldDxvkLogPath
    $env:CL = $oldCl
    $env:GK3HD_XR_PROTOTYPE = $oldXrPrototype
    $env:XR_RUNTIME_JSON = $oldXrRuntime
    $env:GK3HD_XR_TEST_BGRA = $oldXrBgra
    $env:GK3HD_XR_TEST_EYE_SIZE = $oldXrEyeSize
    $env:GK3HD_XR_TEST_SKIP_PIXEL_READBACK = $oldXrSkipReadback
}
