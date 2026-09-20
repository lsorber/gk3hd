# Initialize only this build process; never change the user's persistent environment.
function Get-Gk3hdCompilerVersion([string]$Path) {
    $version = (Get-Item -LiteralPath $Path).VersionInfo
    return "$($version.FileMajorPart).$($version.FileMinorPart).$($version.FileBuildPart)"
}

function Initialize-Gk3hdToolchain($Pin) {
    $compiler = Get-Command cl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($compiler -and $env:VSCMD_ARG_TGT_ARCH -eq 'x86' -and
        ([string]$env:WindowsSDKVersion).TrimEnd('\') -eq $Pin.windows_sdk -and
        (Get-Gk3hdCompilerVersion $compiler.Source) -eq $Pin.msvc -and
        (Get-Command rc.exe -CommandType Application -ErrorAction SilentlyContinue)) {
        return
    }

    $requirement = "Install Visual Studio C++ Build Tools with MSVC $($Pin.msvc) and Windows SDK $($Pin.windows_sdk)."
    $locator = Get-Command vswhere.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $vswhere = if ($locator) { $locator.Source } else {
        Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Microsoft Visual Studio/Installer/vswhere.exe'
    }
    if (-not (Test-Path -LiteralPath $vswhere)) { throw $requirement }
    $installations = & $vswhere -all -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -sort -format json
    if ($LASTEXITCODE -ne 0) { throw "Visual Studio discovery failed. $requirement" }
    $hostArch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { 'x86' }
    $hostFolder = if ($hostArch -eq 'amd64') { 'Hostx64' } else { 'Hostx86' }
    foreach ($installation in ($installations | ConvertFrom-Json)) {
        $root = $installation.installationPath
        $module = Join-Path $root 'Common7/Tools/Microsoft.VisualStudio.DevShell.dll'
        $toolsets = Join-Path $root 'VC/Tools/MSVC'
        if (-not (Test-Path -LiteralPath $module) -or -not (Test-Path -LiteralPath $toolsets)) { continue }
        foreach ($toolset in (Get-ChildItem -LiteralPath $toolsets -Directory | Sort-Object Name -Descending)) {
            $candidate = Join-Path $toolset.FullName "bin/$hostFolder/x86/cl.exe"
            if (-not (Test-Path -LiteralPath $candidate)) { continue }
            if ((Get-Gk3hdCompilerVersion $candidate) -ne $Pin.msvc) { continue }
            Write-Host "Activating x86 MSVC $($Pin.msvc) and Windows SDK $($Pin.windows_sdk)..."
            Import-Module $module
            Enter-VsDevShell -VsInstallPath $root -Arch x86 -HostArch $hostArch -SkipAutomaticLocation `
                -DevCmdArguments "-no_logo -vcvars_ver=$($toolset.Name) -winsdk=$($Pin.windows_sdk)" | Out-Null
            $active = Get-Command cl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($active -and $env:VSCMD_ARG_TGT_ARCH -eq 'x86' -and
                ([string]$env:WindowsSDKVersion).TrimEnd('\') -eq $Pin.windows_sdk -and
                (Get-Gk3hdCompilerVersion $active.Source) -eq $Pin.msvc -and
                (Get-Command rc.exe -CommandType Application -ErrorAction SilentlyContinue)) {
                return
            }
            throw "Could not activate the required x86 compiler and SDK. $requirement"
        }
    }
    throw "The pinned C++ toolchain was not found. $requirement"
}
