#!/bin/sh
# Private clean-source player-driver candidate. No device or ordinary build changes.
set -eu
if [ "$#" -ne 4 ]; then
    echo 'Usage: build-player.sh MESA_ARCHIVE CROSS_FILE ARM64_SYSROOT NEW_OUTPUT' >&2
    exit 2
fi
archive=$(realpath "$1")
cross_file=$(realpath "$2")
sysroot=$(realpath "$3")
output=$(realpath -m "$4")
recipe=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for program in git tar zstd python3 meson ninja aarch64-linux-gnu-gcc aarch64-linux-gnu-readelf aarch64-linux-gnu-strip; do
    command -v "$program" >/dev/null
done
expected=b9436b3e1a8be76fbd4823dc884f90596ab7c6ac5e1867a305e66ffccfb31a92
test -f "$archive" && test -f "$cross_file" && test -d "$sysroot"
test ! -e "$output"
actual=$(sha256sum "$archive" | cut -d ' ' -f1)
test "$actual" = "$expected"
mkdir -p "$output/patches" "$output/package/usr/lib" "$output/package/licenses"
tar -xJf "$archive" -C "$output"
source_dir="$output/mesa-26.2.6"
# A source archive may live below the GK3HD checkout. Git would otherwise
# inherit that checkout and silently skip patches outside its current prefix.
apply_mesa_patch() {
    env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_CONFIG_PARAMETERS \
        GIT_CEILING_DIRECTORIES="$output" GIT_CONFIG_COUNT=1 \
        GIT_CONFIG_KEY_0=core.autocrlf GIT_CONFIG_VALUE_0=false \
        git -C "$source_dir" apply "$@"
}
for patch in winlator-native-import.patch vertex-storage-loads.patch kgsl-waits.patch queue-failure.patch compressed-x11.patch; do
    sed 's/\r$//' "$recipe/$patch" > "$output/patches/$patch"
    apply_mesa_patch --check "$output/patches/$patch"
    apply_mesa_patch "$output/patches/$patch"
    apply_mesa_patch --reverse --check "$output/patches/$patch"
done
grep -Fq MESA_GK3HD_COMPRESSED_X11 "$source_dir/src/vulkan/wsi/wsi_common_x11.c"
sh "$recipe/build.sh" "$source_dir" "$cross_file" "$output/build" kgsl,msm
# Meson removes the build-tree library search path when installing the driver.
meson install -C "$output/build" --destdir "$output/install"
driver="$output/install/usr/lib/libvulkan_freedreno.so"
LC_ALL=C aarch64-linux-gnu-readelf -h -d -V -n "$driver" > "$output/driver-elf.txt"
if grep -Eq '\((RPATH|RUNPATH)\)' "$output/driver-elf.txt"; then
    echo 'The installed driver still has an embedded library search path' >&2
    exit 1
fi
cp "$driver" "$output/package/usr/lib/libvulkan_freedreno.so"
aarch64-linux-gnu-strip --strip-unneeded "$output/package/usr/lib/libvulkan_freedreno.so"
if grep -aFq -e "$sysroot/usr/lib/aarch64-linux-gnu" -e "$output" "$output/package/usr/lib/libvulkan_freedreno.so"; then
    echo 'The stripped driver still contains a build-machine path' >&2
    exit 1
fi
cp "$source_dir/docs/license.rst" "$output/package/licenses/Mesa-license.rst"
mkdir "$output/package/licenses/Mesa"
cp -R "$source_dir"/licenses/. "$output/package/licenses/Mesa/"
for item in libxcb-xfixes.so.0:libxcb-xfixes0 libxcb-shape.so.0:libxcb-shape0 libxshmfence.so.1:libxshmfence1; do
    library=${item%:*}
    package=${item#*:}
    cp -L "$sysroot/usr/lib/aarch64-linux-gnu/$library" "$output/package/usr/lib/$library"
    cp "$sysroot/usr/share/doc/$package/copyright" "$output/package/licenses/$package-copyright.txt"
    aarch64-linux-gnu-readelf -h -d -V "$output/package/usr/lib/$library" > "$output/$library-elf.txt"
done
python3 - "$archive" "$cross_file" "$recipe" "$output" <<'PY'
import hashlib
import json
import pathlib
import subprocess
import sys

archive, cross, recipe, output = map(pathlib.Path, sys.argv[1:])
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
files = {p.relative_to(output / 'package').as_posix(): digest(p)
         for p in sorted((output / 'package').rglob('*'))
         if p.is_file() and p != output / 'package/driver-build.json'}
driver = output / 'package/usr/lib/libvulkan_freedreno.so'
data = driver.read_bytes()
assert data[:5] == b'\x7fELF\x02' and int.from_bytes(data[18:20], 'little') == 183
assert 1024**2 < len(data) < 32 * 1024**2
for marker in (b'GK3HD_GPU_PHASE_', b'GK3HD_WSI_PHASE_', b'GK3HD_TU_SHADER_CAPTURE_'):
    assert marker not in data, marker
record = dict(schema=1, kind='standalone-private-source-driver', mesa='26.2.6',
              archive_sha256=digest(archive), cross_file_sha256=digest(cross),
              patches={p.name: digest(p) for p in sorted((output / 'patches').glob('*.patch'))},
              recipe={p.name: digest(p) for p in (recipe / 'build.sh', recipe / 'build-player.sh')},
              compiler=subprocess.check_output(['aarch64-linux-gnu-gcc', '--version'], text=True).splitlines()[0],
              meson=subprocess.check_output(['meson', '--version'], text=True).strip(),
              ninja=subprocess.check_output(['ninja', '--version'], text=True).strip(),
              minimum_transport='four-row-padded-stereo', files=files,
              scope='Private candidate. No default adoption, performance or native headset acceptance.')
(output / 'package/driver-build.json').write_text(json.dumps(record, indent=2) + '\n')
PY
tar --zstd -cf "$output/gk3hd-turnip-candidate.tar.zst" -C "$output/package" .
sha256sum "$output/gk3hd-turnip-candidate.tar.zst"
