#!/usr/bin/env bash
# Build a local freestanding C compiler; no administrator access or Docker.
set -euo pipefail
cd "$(dirname "$0")/.."
project_root="$PWD"
case "$project_root" in *' '* ) echo 'Use a path without spaces for GNU configure.' >&2; exit 1;; esac
prefix="$project_root/.deps/toolchain"
cache="$project_root/.deps/downloads"
sources="$project_root/.deps/sources"
work="$project_root/.deps/toolchain-build/m68000-v3"
logs="$project_root/.deps/logs"
# New host GCC releases default to C23/C++20. GCC 14's libcody configure
# requires C++11 specifically; newer modes also change its UTF-8 literals.
export CFLAGS='-O2 -std=gnu11'
export CXXFLAGS='-O2 -std=gnu++11'
export CFLAGS_FOR_BUILD="$CFLAGS" CXXFLAGS_FOR_BUILD="$CXXFLAGS"
host_args=()
case "$(uname -s)" in
  MSYS*|MINGW*)
    export PATH="/ucrt64/bin:$PATH"
    export CC=gcc CXX=g++
    host_args=(--build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32)
    ;;
esac
mkdir -p "$prefix" "$cache" "$sources" "$work" "$logs"
if [ -f "$prefix/.complete-14.2.0-2.44-m68000-v3" ]; then
  "$prefix/bin/m68k-elf-gcc" --version
  exit 0
fi
failed() {
  echo "Build failed. First errors and final output from $1:" >&2
  # A parallel configure may print successful checks after the actual error.
  grep -m 10 -B 2 -A 3 -E 'configure: error:|: error:|Error [0-9]' "$1" >&2 || true
  tail -40 "$1" >&2
  exit 1
}
fetch() {
  local archive="$1" url="$2" checksum="$3"
  if [ ! -f "$cache/$archive" ]; then
    curl --fail --location --retry 3 "$url" -o "$cache/$archive.part"
    mv "$cache/$archive.part" "$cache/$archive"
  fi
  printf '%s  %s\n' "$checksum" "$cache/$archive" | sha256sum -c -
}
fetch binutils-2.44.tar.xz https://ftp.gnu.org/gnu/binutils/binutils-2.44.tar.xz ce2017e059d63e67ddb9240e9d4ec49c2893605035cd60e92ad53177f4377237
fetch gcc-14.2.0.tar.xz https://ftp.gnu.org/gnu/gcc/gcc-14.2.0/gcc-14.2.0.tar.xz a7b39bc69cbf9e25826c5a60ab26477001f7c08d85cec04bc0e29cabed6f3cc9
for archive in binutils-2.44 gcc-14.2.0; do
  if [ ! -d "$sources/$archive" ]; then tar -xJf "$cache/$archive.tar.xz" -C "$sources"; fi
done
export PATH="$prefix/bin:$PATH"
jobs="${MCD_JOBS:-2}"
mkdir -p "$work/binutils" "$work/gcc"
(
  cd "$work/binutils" || exit 1
  if [ ! -f Makefile ]; then
    "$sources/binutils-2.44/configure" "${host_args[@]}" --target=m68k-elf --prefix="$prefix" \
      --disable-nls --disable-werror --disable-gdb --disable-gprofng --disable-sim || exit 1
  fi
  make -j"$jobs" || exit 1
  make install || exit 1
) > "$logs/binutils.log" 2>&1 || failed "$logs/binutils.log"
echo 'Binutils installed; building GCC (first setup can take a while).'
(
  cd "$work/gcc" || exit 1
  if [ ! -f Makefile ]; then
    "$sources/gcc-14.2.0/configure" "${host_args[@]}" --target=m68k-elf --prefix="$prefix" \
      --enable-languages=c --without-headers --with-newlib --disable-nls \
      --disable-multilib --disable-threads --disable-shared --disable-libssp \
      --disable-libquadmath --disable-libgomp --disable-libatomic --disable-libstdcxx \
      --disable-bootstrap --disable-lto --with-arch=m68k --with-cpu=m68000 || exit 1
  fi
  # Explicit exits are necessary: errexit is suppressed inside a subshell
  # whose status is tested by the outer log/error handler.
  make -j"$jobs" all-gcc || exit 1
  make -j"$jobs" all-target-libgcc || exit 1
  make install-gcc || exit 1
  make install-target-libgcc || exit 1
) > "$logs/gcc.log" 2>&1 || failed "$logs/gcc.log"
"$prefix/bin/m68k-elf-gcc" --version
touch "$prefix/.complete-14.2.0-2.44-m68000-v3"
