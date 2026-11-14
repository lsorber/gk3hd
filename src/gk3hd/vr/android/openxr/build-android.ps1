#Requires -Version 7.0
param(
    [Parameter(Mandatory)][string]$AndroidSdk,
    [Parameter(Mandatory)][string]$Output,
    [Parameter(Mandatory)][string]$App,
    [string]$LoaderAar,
    [ValidateRange(1,8)][int]$Jobs=4
)
$ErrorActionPreference='Stop'
function Checked([string]$Program,[string[]]$Arguments) {
    & $Program @Arguments
    if($LASTEXITCODE) {throw "$Program failed ($LASTEXITCODE)"}
}
$sdk=(Resolve-Path -LiteralPath $AndroidSdk).Path
$appRoot=(Resolve-Path -LiteralPath $App).Path
$out=[IO.Path]::GetFullPath($Output)
if(Test-Path -LiteralPath $out) {throw 'Preserve earlier native host output; choose a fresh directory'}
$upstream=Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot '../upstream.json')|ConvertFrom-Json
$pin=$upstream.openxr_android_loader
$toolchain=Join-Path $sdk "ndk/$($upstream.ndk)/build/cmake/android.toolchain.cmake"
$ninja=Join-Path $sdk 'cmake/3.22.1/bin/ninja.exe'
foreach($file in @($toolchain,$ninja)) {if(!(Test-Path -LiteralPath $file)){throw "Missing Android build input: $file"}}
New-Item -ItemType Directory -Path $out | Out-Null
$aar=Join-Path $out 'loader.aar'
if($LoaderAar) {Copy-Item -LiteralPath $LoaderAar -Destination $aar}
else {Invoke-WebRequest -Uri $pin.url -OutFile $aar}
if((Get-Item -LiteralPath $aar).Length -gt $pin.maximum_bytes -or
   (Get-FileHash -LiteralPath $aar).Hash.ToLowerInvariant() -ne $pin.sha256) {throw 'Android OpenXR loader does not match the pin'}
$native=Join-Path $appRoot 'src/main/jniLibs/arm64-v8a'
$headers=Join-Path $out 'headers'
$license=Join-Path $appRoot 'src/main/assets/gk3hd/OpenXR-Loader-LICENSE.txt'
New-Item -ItemType Directory -Force -Path $native,$headers,([IO.Path]::GetDirectoryName($license)) | Out-Null
$zip=[IO.Compression.ZipFile]::OpenRead($aar)
try {
    $items=@(@('jni/arm64-v8a/libopenxr_loader.so',"$native/libopenxr_loader.so"),@('META-INF/LICENSE',$license))
    foreach($name in @('openxr.h','openxr_platform.h','openxr_platform_defines.h')) {
        $items+=,@("prefab/modules/headers/include/openxr/$name","$headers/openxr/$name")
    }
    foreach($item in $items) {
        if(Test-Path -LiteralPath $item[1]) {throw "Preserve occupied OpenXR output: $($item[1])"}
        New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($item[1])) | Out-Null
        $entry=$zip.GetEntry($item[0]);if(!$entry -or $entry.Length -gt 8MB){throw 'Missing/oversized OpenXR loader entry'}
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$item[1])
    }
} finally {$zip.Dispose()}
$build=Join-Path $out 'build'
Checked cmake @('-S',$PSScriptRoot,'-B',$build,'-G','Ninja',"-DCMAKE_MAKE_PROGRAM=$ninja",
    "-DCMAKE_TOOLCHAIN_FILE=$toolchain",'-DANDROID_ABI=arm64-v8a','-DANDROID_PLATFORM=android-26','-DANDROID_STL=c++_static',
    "-DOPENXR_INCLUDE_DIR=$headers","-DOPENXR_LOADER_LIBRARY=$native/libopenxr_loader.so",'-DGK3HD_OPENXR_ANDROID=ON','-DCMAKE_BUILD_TYPE=Release')
Checked cmake @('--build',$build,'--parallel',"$Jobs")
$nativeHost=Join-Path $native 'libgk3hd_openxr.so'
if(Test-Path -LiteralPath $nativeHost){throw 'Preserve occupied native host library'}
Copy-Item -LiteralPath "$build/libgk3hd_openxr.so" -Destination $nativeHost
@{loader=$pin;host_sha256=(Get-FileHash -LiteralPath $nativeHost).Hash.ToLowerInvariant();
  loader_sha256=(Get-FileHash -LiteralPath "$native/libopenxr_loader.so").Hash.ToLowerInvariant();
  scope='Opt-in Android OpenXR JNI/GLES host; actual headset lifecycle and controllers remain unqualified'}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath "$out/build-receipt.json" -Encoding utf8
