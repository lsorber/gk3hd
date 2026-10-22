param([Parameter(Mandatory)][string]$Output, [Parameter(Mandatory)][string]$Include)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/../../renderer/toolchain.ps1"
$pin = Get-Content "$PSScriptRoot/../../renderer/upstream.json" -Raw | ConvertFrom-Json
Initialize-Gk3hdToolchain $pin
Push-Location $Output
try {
    & cl /nologo /std:c++17 /EHsc /O2 /MT /DUNICODE /D_UNICODE /LD "/I$Include" "$PSScriptRoot/player.cpp" /link /OUT:gk3hd-videos.dll ole32.lib strmiids.lib
    if ($LASTEXITCODE) { throw 'Movie player compilation failed' }
} finally { Pop-Location }
