#!/bin/sh
# Private source-driver qualification, not a normal package build.
set -eu
if [ "$#" -ne 4 ]; then
    echo 'Usage: build.sh MESA_SOURCE CROSS_FILE OUTPUT_DIRECTORY kgsl|kgsl,msm' >&2
    exit 2
fi
source_dir=$(realpath "$1")
cross_file=$(realpath "$2")
output_dir=$3
kmds=$4
case "$kmds" in kgsl|kgsl,msm) ;; *) echo 'Unsupported qualification KMD selection' >&2; exit 2 ;; esac
test -f "$source_dir/meson.build"
test -f "$cross_file"
# No fetch, system package changes, source edits, cleanup or device installation.
meson setup "$output_dir" "$source_dir" --cross-file "$cross_file" \
    --wrap-mode=nofallback \
    --prefix=/usr --libdir=lib \
    -Dbuildtype=release -Db_ndebug=true \
    -Dplatforms=x11 -Dvulkan-drivers=freedreno -Dfreedreno-kmds="$kmds" \
    -Dgallium-drivers= -Dglx=disabled -Degl=disabled -Dgbm=disabled \
    -Dopengl=false -Dgles1=disabled -Dgles2=disabled -Dllvm=disabled \
    -Dvideo-codecs= -Dbuild-tests=false -Dtools= \
    -Dzstd=disabled -Dexpat=enabled -Dzlib=enabled -Dshader-cache=enabled \
    -Dspirv-tools=disabled -Ddisplay-info=disabled -Dlibunwind=disabled \
    -Dlmsensors=disabled -Dvalgrind=disabled -Dperfetto=false \
    -Dxlib-lease=disabled
ninja -C "$output_dir" -j8 src/freedreno/vulkan/libvulkan_freedreno.so
