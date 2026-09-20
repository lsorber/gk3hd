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
    [ValidateRange(1, 64)][int]$Jobs = 12
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

$pin = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'upstream.json') -Raw | ConvertFrom-Json
$patch = Join-Path $PSScriptRoot 'renderer.patch'
$patchHash = (Get-FileHash -LiteralPath $patch).Hash
$pinHash = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'upstream.json')).Hash
foreach ($command in @('uvx', 'git')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing $command; install it and make it available on PATH."
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
$shaderArchive = Join-Path $output 'glslang.zip'
$shaderRoot = Join-Path $output 'glslang'
$oldPath = $env:PATH
$oldConfig = $env:DXVK_CONFIG_FILE
$oldLogPath = $env:D7VK_LOG_PATH
$oldCl = $env:CL
try {
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
    Invoke-Checked git @('-C', $source, 'apply', '--check', $patch)
    Invoke-Checked git @('-C', $source, 'apply', $patch)
    Invoke-WebRequest -Uri $pin.glslang_url -OutFile $shaderArchive
    Assert-Hash $shaderArchive $pin.glslang_archive_sha256
    Expand-Archive -LiteralPath $shaderArchive -DestinationPath $shaderRoot
    Assert-Hash (Join-Path $shaderRoot 'bin/glslang.exe') $pin.glslang_exe_sha256
    $env:PATH = (Join-Path $shaderRoot 'bin') + [IO.Path]::PathSeparator + $env:PATH
    $meson = @('--from', "meson==$($pin.meson)", '--with', "ninja==$($pin.ninja)", 'meson')
    Invoke-Checked uvx ($meson + @('setup', $build, $source, '--buildtype=release', '--wrap-mode=nodownload',
        '-Denable_ddraw=true', '-Denable_d3d9=true', '-Denable_dxgi=false', '-Denable_d3d8=false',
        '-Denable_d3d10=false', '-Denable_d3d11=false', '-Dbuild_id=false',
        "-Dgk3hd_version=v$($pin.version)"))
    $buildEnv = Get-Content -LiteralPath (Join-Path $build 'buildenv.h') -Raw
    if (-not $buildEnv.Contains('DXVK_TARGET "x86"') -or
        -not $buildEnv.Contains("DXVK_COMPILER_VERSION `"$($pin.msvc)`"")) {
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
    Invoke-Checked $test @($dll)
    foreach ($unit in @('region_tests', 'check_lock_regions', 'check_baseline_damage', 'check_native_copy', 'check_stretch', 'check_area_blend', 'check_area_blt')) {
        $unitExe = Join-Path $output "$unit.exe"
        Invoke-Checked cl @('/nologo', '/std:c++17', '/EHsc', '/O2',
            (Join-Path $PSScriptRoot "tests/$unit.cpp"), "/I$(Join-Path $source 'src/ddraw')",
            "/Fe:$unitExe", "/Fo:$(Join-Path $output "$unit.obj")", # codespell:ignore fo
            '/link', 'ddraw.lib', 'dxguid.lib', 'user32.lib', 'gdi32.lib')
        if ($unit -in @('check_area_blend', 'check_area_blt')) { Invoke-Checked $unitExe @($dll) }
        else { Invoke-Checked $unitExe @() }
    }

    # Package only after the freshly compiled native tests pass. No game files.
    Assert-Hash $patch $patchHash
    Assert-Hash (Join-Path $PSScriptRoot 'upstream.json') $pinHash
    $name = "d7vk-$($pin.version)"
    $releaseDll = Join-Path $output "$name.dll"
    $notices = Join-Path $output "$name.txt"
    Copy-Item -LiteralPath $dll -Destination $releaseDll
    $licenses = @{
        'D7VK.txt' = 'LICENSE'
        'dxbc-spirv.txt' = 'subprojects/dxbc-spirv/LICENSE'
        'libdisplay-info.txt' = 'subprojects/libdisplay-info/LICENSE'
        'SPIRV-Headers.txt' = 'include/spirv/LICENSE'
        'dxbc-SPIRV-Headers.txt' = 'subprojects/dxbc-spirv/submodules/spirv_headers/LICENSE'
        'Vulkan-Headers.txt' = 'include/vulkan/LICENSE.md'
        'Vulkan-MIT.txt' = 'include/vulkan/LICENSES/MIT.txt'
        'Vulkan-Apache-2.0.txt' = 'include/vulkan/LICENSES/Apache-2.0.txt'
        'OpenVR.txt' = 'include/openvr/LICENSE'
    }
    $noticeText = "Modified D7VK for GK3HD. Source and modifications: https://github.com/lsorber/gk3hd/tree/main/src/gk3hd/renderer`n"
    foreach ($license in ($licenses.GetEnumerator() | Sort-Object Key)) {
        $noticeText += "`n=== $($license.Key) ===`n"
        $noticeText += Get-Content -LiteralPath (Join-Path $source $license.Value) -Raw
    }
    Set-Content -LiteralPath $notices -Value $noticeText -Encoding utf8NoBOM
    [ordered]@{
        version = $pin.version
        upstream_commit = $pin.commit
        submodules = $submodules
        msvc = $pin.msvc
        windows_sdk = $pin.windows_sdk
        meson = $pin.meson
        ninja = $pin.ninja
        source_path_mapping = 'gk3hd-build'
        patch_sha256 = (Get-FileHash -LiteralPath $patch).Hash.ToLowerInvariant()
        dll_sha256 = (Get-FileHash -LiteralPath $dll).Hash.ToLowerInvariant()
        notices_sha256 = (Get-FileHash -LiteralPath $notices).Hash.ToLowerInvariant()
        surface_tests = 'passed'
        helper_tests = 'passed'
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output "$name.json") -Encoding utf8NoBOM
    Get-FileHash -LiteralPath $releaseDll
    Write-Host "Candidate only; not installed or published: $releaseDll"
} finally {
    $env:PATH = $oldPath
    $env:DXVK_CONFIG_FILE = $oldConfig
    $env:D7VK_LOG_PATH = $oldLogPath
    $env:CL = $oldCl
}
