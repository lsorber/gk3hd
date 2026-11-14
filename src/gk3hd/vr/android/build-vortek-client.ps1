#Requires -Version 7.0
<# Build private ARM64 graphics libraries and package with the matching Android server. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Headers,
    [Parameter(Mandatory)][string]$Output,
    [Parameter(Mandatory)][string]$App,
    [Parameter(Mandatory)][string]$Python,
    [ValidateRange(1,8)][int]$Jobs=4,
    [string]$WslDistribution
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$selector=if($WslDistribution){@('--distribution',$WslDistribution)}else{@()}
function Invoke-Linux([string[]]$Arguments) {
    & wsl @selector --exec @Arguments
    if($LASTEXITCODE){throw 'Native Vulkan client build/check failed; inspect the preceding compiler or test output'}
}
function Linux-Path([string]$Path) {
    return (Invoke-Linux @('wslpath','-u',[IO.Path]::GetFullPath($Path))).Trim()
}
if(Test-Path -LiteralPath $Output){throw 'Preserve the existing client build; choose a fresh output'}
$sourceRoot=Linux-Path $Source
$headerRoot=Linux-Path $Headers
$outputRoot=Linux-Path $Output
$testSource=Linux-Path (Join-Path $PSScriptRoot 'native/ClientWireTests.c')
$helperRoot=Linux-Path (Join-Path $PSScriptRoot 'native')
$compilerFlags="-I`"$headerRoot`" -I`"$helperRoot`" -idirafter /usr/include -Wl,-rpath=/data/data/com.winlator/files/rootfs/usr/lib"
Invoke-Linux @('cmake','-S',$sourceRoot,'-B',$outputRoot,'-DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc',
    '-DCMAKE_BUILD_TYPE=Release',"-DCMAKE_C_FLAGS=$compilerFlags",'-DCMAKE_C_FLAGS_RELEASE=-O2 -DNDEBUG')
Invoke-Linux @('cmake','--build',$outputRoot,'--parallel',"$Jobs")
Invoke-Linux @('cc','-O1','-w','-DVK_USE_PLATFORM_XLIB_KHR',"-I$sourceRoot/include","-I$headerRoot","-I$helperRoot",
    $testSource,"$sourceRoot/src/vk_object.c","$sourceRoot/src/arrays.c",'-o',"$outputRoot/client-wire-tests")
Invoke-Linux @("$outputRoot/client-wire-tests")
$waitTests=Linux-Path (Join-Path $PSScriptRoot 'native/PresentWaitsTests.c')
Invoke-Linux @('cc','-std=c11','-O2','-Wall','-Wextra','-Werror',"-I$headerRoot",
    $waitTests,'-o',"$outputRoot/present-wait-tests")
Invoke-Linux @("$outputRoot/present-wait-tests")
$formatTests=Linux-Path (Join-Path $PSScriptRoot 'native/HardwareBufferFormatTests.c')
Invoke-Linux @('cc','-std=c11','-O2','-Wall','-Wextra','-Werror',"-I$headerRoot",
    $formatTests,'-o',"$outputRoot/hardware-buffer-format-tests")
Invoke-Linux @("$outputRoot/hardware-buffer-format-tests")
$fenceTests=Linux-Path (Join-Path $PSScriptRoot 'native/FenceWaitTests.c')
Invoke-Linux @('cc','-std=c11','-O2','-Wall','-Wextra','-Werror',"-I$headerRoot",
    $fenceTests,'-o',"$outputRoot/fence-wait-tests")
Invoke-Linux @("$outputRoot/fence-wait-tests")
$packetTests=Linux-Path (Join-Path $PSScriptRoot 'native/PacketWriterTests.c')
Invoke-Linux @('cc','-std=gnu11','-O2','-Wall','-Wextra','-Wno-unused-parameter',
    "-I$sourceRoot/include","-I$helperRoot",$packetTests,"$sourceRoot/src/ring_buffer.c",
    '-pthread','-o',"$outputRoot/packet-writer-tests")
Invoke-Linux @("$outputRoot/packet-writer-tests")
$kgslHeaders=Linux-Path (Join-Path $App 'src/main/cpp/libadrenotools/src/hook')
$allocationSource=Linux-Path (Join-Path $PSScriptRoot 'native/KgslAllocation.c')
$allocationTests=Linux-Path (Join-Path $PSScriptRoot 'native/KgslAllocationTests.c')
Invoke-Linux @('cc','-std=c11','-O2','-Wall','-Wextra','-Werror',"-I$kgslHeaders",
    $allocationTests,'-ldl','-pthread','-o',"$outputRoot/kgsl-allocation-tests")
Invoke-Linux @("$outputRoot/kgsl-allocation-tests")
Invoke-Linux @('aarch64-linux-gnu-gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',
    "-I$kgslHeaders",$allocationSource,'-Wl,-z,relro,-z,now','-Wl,-soname,libgk3hd_kgsl.so',
    '-ldl','-pthread','-o',"$outputRoot/libgk3hd_kgsl.so")
& $Python (Join-Path $PSScriptRoot 'native_client.py') (Join-Path $Output 'libvulkan_vortek.so') $App (Join-Path $Output 'libgk3hd_kgsl.so')
if($LASTEXITCODE){throw 'Native Vulkan client packaging failed'}
