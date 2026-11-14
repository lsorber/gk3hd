#Requires -Version 7.0
<# Development-only component build. No installation, game data or vendor SDK payload. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OutputRoot,
    [Parameter(Mandatory)][string]$RendererBuild,
    [Parameter(Mandatory)][string]$AndroidSdk,
    [Parameter(Mandatory)][string]$Python,
    [string]$WslDistribution,
    [switch]$Release,
    [ValidateRange(1, 8)][int]$Jobs = 4
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
function Get-SourceInventory([string]$Root) {
    $inventory = [ordered]@{}
    foreach ($file in (Get-ChildItem -LiteralPath $Root -File -Recurse | Sort-Object FullName)) {
        if ($file.Extension -notin @('.java','.c','.cpp','.h','.patch','.json','.ps1','.sh','.py','.vert','.frag') -and
            $file.Name -ne 'CMakeLists.txt') { continue }
        $relative = [IO.Path]::GetRelativePath($Root, $file.FullName).Replace('\','/')
        $bytes = [Text.Encoding]::UTF8.GetBytes([IO.File]::ReadAllText($file.FullName).Replace("`r`n","`n"))
        $inventory[$relative] = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    }
    return $inventory
}
function Get-PinnedSource($Pin, [string]$Destination, [string[]]$Patches) {
    Invoke-Checked git @('init','--quiet',$Destination)
    Invoke-Checked git @('-C',$Destination,'remote','add','origin',$Pin.repository)
    Invoke-Checked git @('-C',$Destination,'fetch','--depth','1','origin',$Pin.commit)
    Invoke-Checked git @('-C',$Destination,'-c','core.autocrlf=false','checkout','--detach','FETCH_HEAD')
    $actual = (& git -C $Destination rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $Pin.commit) { throw 'Fetched source commit does not match the pin' }
    foreach ($patch in $Patches) {
        $normalized = Join-Path $output ([IO.Path]::GetFileName($patch))
        [IO.File]::WriteAllText($normalized,[IO.File]::ReadAllText($patch).Replace("`r`n","`n"),[Text.UTF8Encoding]::new($false))
        Invoke-Checked git @('-C',$Destination,'apply','--check',$normalized)
        Invoke-Checked git @('-C',$Destination,'apply',$normalized)
    }
}
$sourceRoot = $PSScriptRoot
$pin = Get-Content -LiteralPath (Join-Path $sourceRoot 'upstream.json') -Raw | ConvertFrom-Json
$rendererPin = Get-Content -LiteralPath (Join-Path $sourceRoot '../../renderer/upstream.json') -Raw | ConvertFrom-Json
$sdk = (Resolve-Path -LiteralPath $AndroidSdk).Path
$renderer = (Resolve-Path -LiteralPath $RendererBuild).Path
$headers = Join-Path $renderer 'source/include/vulkan/include'
$glslc = Join-Path $sdk "ndk/$($pin.ndk)/shader-tools/windows-x86_64/glslc.exe"
foreach ($required in @($headers,$glslc,(Join-Path $sdk 'platforms/android-35/android.jar'))) {
    if (!(Test-Path -LiteralPath $required)) { throw "Missing component-build input: $required" }
}
foreach ($command in @('git','cmake','ctest','java','javac','wsl','tar')) {
    if (!(Get-Command $command -ErrorAction SilentlyContinue)) { throw "Missing $command on PATH" }
}
& $Python -c "import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)"
if ($LASTEXITCODE) { throw 'Standalone component builds require Python 3.14 or newer' }
if ($env:CL -or $env:_CL_ -or $env:LINK -or $env:_LINK_) {
    throw 'Clear custom compiler/linker arguments before building standalone components'
}
. (Join-Path $sourceRoot '../../renderer/toolchain.ps1')
Initialize-Gk3hdToolchain $rendererPin
$output = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $output) { throw 'Output already exists; choose a fresh component-build directory' }
$before = Get-SourceInventory $sourceRoot | ConvertTo-Json -Depth 8
New-Item -ItemType Directory -Path $output | Out-Null
$stage = Join-Path $output 'adapters'
foreach ($entry in ((Get-SourceInventory $sourceRoot).Keys)) {
    $target = Join-Path $stage $entry
    New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($target)) | Out-Null
    if ([IO.Path]::GetExtension($entry) -eq '.sh') {
        [IO.File]::WriteAllText($target,[IO.File]::ReadAllText((Join-Path $sourceRoot $entry)).Replace("`r`n","`n"),[Text.UTF8Encoding]::new($false))
    } else { Copy-Item -LiteralPath (Join-Path $sourceRoot $entry) -Destination $target }
}
$wxr = Join-Path $output 'wxr-source'
$winlator = Join-Path $output 'winlator-source'
Get-PinnedSource $pin.wxr $wxr @(
    (Join-Path $stage 'openxr-wxr.patch')
    (Join-Path $stage 'openxr-wxr-direct.patch')
)
Get-PinnedSource $pin.winlator $winlator (Join-Path $stage 'winlator.patch')
$driverOptions = @()
if ($WslDistribution) { $driverOptions += @('-d',$WslDistribution) }
$linuxWineRecipe = (& wsl @driverOptions --exec wslpath -u (Join-Path $stage 'wine/build.py')).Trim()
$linuxWineOutput = (& wsl @driverOptions --exec wslpath -u (Join-Path $output 'wine-server-build')).Trim()
if ($LASTEXITCODE -or !$linuxWineRecipe.StartsWith('/') -or !$linuxWineOutput.StartsWith('/')) {
    throw 'Cannot locate the source Wine server build in WSL'
}
Invoke-Checked wsl ($driverOptions + @('--exec','python3',$linuxWineRecipe,$linuxWineOutput,"$Jobs"))
Invoke-Checked $Python @((Join-Path $stage 'wine_assets.py'),
    (Join-Path $output 'wine-server-build/package'),(Join-Path $winlator 'app'))
$wineServerTests = Join-Path $output 'wine-server-tests'
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$wineServerTests,
    (Join-Path $stage 'WineRegistryServer.java'),(Join-Path $stage 'tests/WineRegistryServerTests.java'))
Invoke-Checked java @('-cp',$wineServerTests,'org.gk3hd.standalone.WineRegistryServerTests')
$linuxDriverRecipe = (& wsl @driverOptions --exec wslpath -u (Join-Path $stage 'turnip/build.py')).Trim()
$linuxDriverOutput = (& wsl @driverOptions --exec wslpath -u (Join-Path $output 'turnip-build')).Trim()
if ($LASTEXITCODE -or !$linuxDriverRecipe.StartsWith('/') -or !$linuxDriverOutput.StartsWith('/')) {
    throw 'Cannot locate the private source-driver build in WSL'
}
Invoke-Checked wsl ($driverOptions + @('--exec','python3',$linuxDriverRecipe,$linuxDriverOutput))
Invoke-Checked $Python @((Join-Path $stage 'turnip_assets.py'),
    (Join-Path $output 'turnip-build/driver/package'),(Join-Path $winlator 'app'))
# Check the actual bundled Wine input; do not keep a second runtime DLL in source.
$wineFixture = Join-Path $output 'wine-map-fixture'
New-Item -ItemType Directory -Path $wineFixture | Out-Null
Invoke-Checked tar @('-xf',(Join-Path $winlator 'app/src/main/assets/rootfs.tzst'),
    '-C',$wineFixture,'./opt/wine/lib/wine/i386-windows/wined3d.dll')
$wineTests = Join-Path $output 'wine-map-tests'
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$wineTests,
    (Join-Path $stage 'WineMapCompletion.java'),(Join-Path $stage 'tests/WineMapCompletionTests.java'))
Invoke-Checked java @('-cp',$wineTests,'org.gk3hd.standalone.WineMapCompletionTests',
    (Join-Path $wineFixture 'opt/wine/lib/wine/i386-windows/wined3d.dll'),
    (Join-Path $wineFixture 'qualified-wined3d.dll'))
New-Item -ItemType Directory -Force -Path (Join-Path $winlator 'app/src/main/assets/gk3hd') | Out-Null
Copy-Item -LiteralPath (Join-Path $stage 'wine-map-completion.patch') `
    -Destination (Join-Path $winlator 'app/src/main/assets/gk3hd/wine-map-completion.patch')
& (Join-Path $stage 'openxr/build-android.ps1') -AndroidSdk $sdk -Output (Join-Path $output 'native-openxr') `
    -App (Join-Path $winlator 'app') -Jobs $Jobs
$vortek = Join-Path $output 'vortek-source'
Get-PinnedSource $pin.vortek $vortek (Join-Path $stage 'vortek.patch')
& (Join-Path $stage 'build-vortek-client.ps1') -Source $vortek -Headers $headers -Output (Join-Path $output 'vortek-build') `
    -App (Join-Path $winlator 'app') -Python $Python -Jobs $Jobs -WslDistribution $WslDistribution
$libraryBuild = Join-Path $output 'vulkan-import'
Invoke-Checked cmake @('-S',(Join-Path $wxr 'vulkan32'),'-B',$libraryBuild,'-A','Win32')
Invoke-Checked cmake @('--build',$libraryBuild,'--config','Release','--parallel',"$Jobs")
$runtimeBuild = Join-Path $output 'wxr-build'
Invoke-Checked cmake @('-S',$wxr,'-B',$runtimeBuild,'-A','Win32',
    "-DGK3HD_ANDROID_SOURCE=$stage",'-DGK3HD_COMPOSITOR_TESTS=ON',"-DGK3HD_VR_SOURCE=$(Join-Path $renderer 'xr-source')",
    '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded',"-DVulkan_INCLUDE_DIR=$headers",
    "-DVulkan_LIBRARY=$(Join-Path $libraryBuild 'Release/vulkan-1.lib')","-DGLSLC=$glslc")
Invoke-Checked cmake @('--build',$runtimeBuild,'--config','Release','--parallel',"$Jobs")
$helperBuild = Join-Path $output 'helper-build'
Invoke-Checked cmake @('-S',$stage,'-B',$helperBuild,'-A','Win32','-DGK3HD_WINE_TESTS=ON',
    "-DWXR_SOURCE=$wxr","-DVULKAN_INCLUDE=$headers")
Invoke-Checked cmake @('--build',$helperBuild,'--config','Release','--parallel',"$Jobs")
Invoke-Checked ctest @('--test-dir',$helperBuild,'-C','Release','--output-on-failure','--timeout','15')
$javaTests = Join-Path $output 'identity-tests'
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$javaTests,
    (Join-Path $stage 'StereoTransport.java'),(Join-Path $stage 'tests/StereoTransportTests.java'))
$transportVectors = Join-Path $javaTests 'stereo-transport.txt'
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.StereoTransportTests',$transportVectors)
Invoke-Checked (Join-Path $wxr 'oxrwxr/gk3hd-vulkan-quad-tests.exe') @('--transport-layout',$transportVectors)
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$javaTests,
    (Join-Path $stage 'FramePoses.java'),(Join-Path $stage 'ImageIdentity.java'),(Join-Path $stage 'FrameIdentity.java'),
    (Join-Path $stage 'tests/FrameIdentityTests.java'),(Join-Path $stage 'tests/ImageIdentityWireTests.java'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.FrameIdentityTests')
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.ImageIdentityWireTests',
    (Join-Path $helperBuild 'frame-metadata-vectors.bin'))
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-cp',(Join-Path $sdk 'platforms/android-35/android.jar'),'-d',$javaTests,
    (Join-Path $stage 'XrInput.java'),(Join-Path $stage 'StereoViews.java'),
    (Join-Path $stage 'MovieCanvas.java'),(Join-Path $stage 'tests/MovieCanvasTests.java'),
    (Join-Path $stage 'PimaxTracking.java'),(Join-Path $stage 'tests/PimaxOpticsTests.java'),
    (Join-Path $stage 'XrApiBridge.java'),(Join-Path $stage 'tests/RuntimeStartupTests.java'),(Join-Path $stage 'tests/StereoViewsTests.java'),
    (Join-Path $stage 'NativeOpenXr.java'),(Join-Path $stage 'FramePoses.java'),(Join-Path $stage 'tests/NativeFrameTests.java'),
    (Join-Path $stage 'OpenXrControllerSample.java'),(Join-Path $stage 'tests/ControllerViewsTests.java'),
    (Join-Path $stage 'XrRuntimeSelection.java'),(Join-Path $stage 'tests/RuntimeSelectionTests.java'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.RuntimeSelectionTests')
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.PimaxOpticsTests')
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.MovieCanvasTests')
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.RuntimeStartupTests')
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.NativeFrameTests')
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$javaTests,
    (Join-Path $stage 'GraphicsRetirement.java'),(Join-Path $stage 'tests/GraphicsRetirementTests.java'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.GraphicsRetirementTests')
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$javaTests,
    (Join-Path $stage 'NativeDrawProgress.java'),(Join-Path $stage 'tests/NativeDrawProgressTests.java'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.NativeDrawProgressTests')
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$javaTests,
    (Join-Path $stage 'FramePoses.java'),(Join-Path $stage 'TrackingWorker.java'),
    (Join-Path $stage 'tests/TrackingWorkerTests.java'),(Join-Path $stage 'tests/TrackingAdmissionTests.java'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.TrackingWorkerTests')
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.TrackingAdmissionTests')
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-cp',$javaTests,'-d',$javaTests,
    (Join-Path $stage 'NativeSessionReport.java'),(Join-Path $stage 'tests/NativeSessionReportTests.java'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.NativeSessionReportTests',
    (Join-Path $javaTests 'native-session-report'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.ControllerViewsTests',$javaTests)
$opticsPacket=Join-Path $javaTests 'stereo-views.bin'
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.StereoViewsTests',$opticsPacket)
Invoke-Checked (Join-Path $helperBuild 'Release/gk3hd-host-input-tests.exe') @($opticsPacket)
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-cp',$javaTests,'-d',$javaTests,
    (Join-Path $stage 'tests/InputLifetimeTests.java'))
$inputPackets=Join-Path $javaTests 'input-lifetime'
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.InputLifetimeTests',$inputPackets)
Invoke-Checked (Join-Path $helperBuild 'Release/gk3hd-input-lifetime-tests.exe') @($inputPackets)
Invoke-Checked (Join-Path $wxr 'oxrwxr/gk3hd-vulkan-quad-tests.exe') @('--input-lifetime',
    (Join-Path $wxr 'oxrwxr/openxr_wxr32.dll'),$inputPackets)
Invoke-Checked (Join-Path $wxr 'oxrwxr/gk3hd-vulkan-quad-tests.exe') @('--startup-pending',
    (Join-Path $wxr 'oxrwxr/openxr_wxr32.dll'),$inputPackets)
Invoke-Checked (Join-Path $wxr 'oxrwxr/gk3hd-vulkan-quad-tests.exe') @('--startup-port-conflict',
    (Join-Path $wxr 'oxrwxr/openxr_wxr32.dll'))
$wslOptions = @()
if ($WslDistribution) { $wslOptions += @('-d',$WslDistribution) }
$linuxStage = (& wsl @wslOptions --exec wslpath -u $stage).Trim()
if ($LASTEXITCODE -or !$linuxStage.StartsWith('/')) { throw 'Cannot locate mapped reader tests in WSL' }
Invoke-Checked wsl ($wslOptions + @('--exec','gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-pthread',
    '-I',"$linuxStage/native","$linuxStage/tests/FrameMetadataReaderTests.c",'-o',"$linuxStage/frame-metadata-reader-tests"))
Invoke-Checked wsl ($wslOptions + @('--exec',"$linuxStage/frame-metadata-reader-tests"))
$runtime = Join-Path $wxr 'oxrwxr/openxr_wxr32.dll'
Invoke-Checked (Join-Path $helperBuild 'Release/gk3hd-wxr-binding-tests.exe') @($runtime)
Invoke-Checked (Join-Path $wxr 'oxrwxr/gk3hd-vulkan-quad-tests.exe') @()
# Embed the exact producer identities in this consumer APK before compilation.
$launcher = Join-Path $helperBuild 'Release/gk3hd-wine-launcher.exe'
$pairing = Join-Path $winlator 'app/src/main/assets/gk3hd-components.sha256'
$pairingText = ((Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash.ToLowerInvariant()+"  openxr_wxr32.dll`n"+
    (Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash.ToLowerInvariant()+"  gk3hd-wine-launcher.exe`n")
[IO.File]::WriteAllText($pairing,$pairingText,[Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path (Split-Path -Parent $pairing) 'gk3hd-component-update'),'4',[Text.UTF8Encoding]::new($false))
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$javaTests,
    (Join-Path $stage 'ComponentPairing.java'),(Join-Path $stage 'tests/ComponentPairingTests.java'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.ComponentPairingTests',$pairing,$runtime,$launcher)
Invoke-Checked javac @('--release','8','-Xlint:all,-options','-Werror','-d',$javaTests,
    (Join-Path $stage 'RendererRecovery.java'),(Join-Path $stage 'tests/RendererRecoveryTests.java'))
Invoke-Checked java @('-cp',$javaTests,'org.gk3hd.standalone.RendererRecoveryTests')
$pruneArguments = @((Join-Path $stage 'prune_windows_payload.py'),
    (Join-Path $winlator 'app/src/main/assets'))
if ($Release) { $pruneArguments += '--release' }
Invoke-Checked $Python $pruneArguments
if ($Release) {
    Invoke-Checked $Python @('-c','from pathlib import Path; from gk3hd.vr.android.runtime_assets import omit_from_release; import sys; omit_from_release(Path(sys.argv[1]))',
        (Join-Path $winlator 'app/src/main/assets'))
    Invoke-Checked $Python @('-c','from pathlib import Path; from gk3hd.vr.android.notices import embed; import sys; embed(Path(sys.argv[1]))',
        $winlator)
}
# Never install/copy the Vulkan import stub DLL. Wine must load its real Vulkan implementation.
$apkTask = if ($Release) { ':app:assembleRelease' } else { ':app:compileReleaseJavaWithJavac' }
$previousSdk = $env:ANDROID_HOME
try {
    $env:ANDROID_HOME = $sdk
    Push-Location $winlator
    try {
        Invoke-Checked (Join-Path $winlator 'gradlew.bat') @('--no-daemon',"--max-workers=$Jobs",
            '--gradle-user-home',(Join-Path $output 'gradle-cache'),"-Pgk3hdAndroidSource=$stage",
            ':app:assembleDebug',$apkTask)
    } finally { Pop-Location }
} finally { $env:ANDROID_HOME = $previousSdk }
$androidClasses = Join-Path $winlator 'app/build/intermediates/javac/debug/compileDebugJavaWithJavac/classes'
$androidJar = Join-Path $sdk 'platforms/android-35/android.jar'
Invoke-Checked javac @('--release','8','-Xlint:-options','-cp',"$androidJar;$androidClasses",'-d',$javaTests,
    (Join-Path $stage 'tests/OwnedGuestShutdownTests.java'))
Invoke-Checked java @('-cp',"$javaTests;$androidJar;$androidClasses",'org.gk3hd.standalone.OwnedGuestShutdownTests')
Invoke-Checked javac @('--release','8','-Xlint:-options','-cp',"$androidJar;$androidClasses",'-d',$javaTests,
    (Join-Path $stage 'tests/SharedMemoryShutdownTests.java'))
Invoke-Checked java @('-cp',"$javaTests;$androidJar;$androidClasses",'org.gk3hd.standalone.SharedMemoryShutdownTests')
$after = Get-SourceInventory $sourceRoot | ConvertTo-Json -Depth 8
if ($before -ne $after) { throw 'Standalone build sources changed; do not use these components' }
$apkPath = if ($Release) { 'release/app-release-unsigned.apk' } else { 'debug/app-debug.apk' }
$outputs = [ordered]@{
    'openxr_wxr32.dll' = $runtime
    'gk3hd-wine-launcher.exe' = (Join-Path $helperBuild 'Release/gk3hd-wine-launcher.exe')
    'gk3hd-standalone.apk' = (Join-Path $winlator "app/build/outputs/apk/$apkPath")
}
$hashes = [ordered]@{}
foreach ($name in $outputs.Keys) {
    Copy-Item -LiteralPath $outputs[$name] -Destination (Join-Path $output $name)
    $hashes[$name] = (Get-FileHash -LiteralPath (Join-Path $output $name) -Algorithm SHA256).Hash.ToLowerInvariant()
}
Copy-Item -LiteralPath (Join-Path $wxr 'LICENSE') -Destination (Join-Path $output 'OpenXR-WXR-LICENSE.txt')
Copy-Item -LiteralPath (Join-Path $winlator 'LICENSE') -Destination (Join-Path $output 'Winlator-LICENSE.txt')
Copy-Item -LiteralPath (Join-Path $vortek 'LICENSE') -Destination (Join-Path $output 'Vortek-LICENSE.txt')
$receipt = [ordered]@{
    schema = 1; kind = 'standalone-development-components'; upstream = $pin
    inputs = ($before | ConvertFrom-Json); outputs = $hashes
    checks = @(Get-Content -LiteralPath (Join-Path $stage 'component-checks.json') -Raw | ConvertFrom-Json)
    qualification = 'Development build only; physical headset, sustained performance and complete source/license delivery remain unqualified'
}
[IO.File]::WriteAllText((Join-Path $output 'standalone-components.json'),($receipt | ConvertTo-Json -Depth 12)+"`n",[Text.UTF8Encoding]::new($false))
Write-Output "Standalone development components: $output"
