#!/usr/bin/env bash
# Build a local freestanding C compiler; no administrator access or Docker.
set -euo pipefail
cd "$(dirname "$0")/.."
project_root="$PWD"
case "$project_root" in *' '* ) echo 'Use a path without spaces for GNU configure.' >&2; exit 1;; esac
prefix="$project_root/.deps/toolchain"
cache="$project_root/.deps/downloads"
sources="$project_root/.deps/sources"
work="$project_root/.deps/toolchain-build"
logs="$project_root/.deps/logs"
host_args=()
case "$(uname -s)" in
  MSYS*|MINGW*)
    export PATH="/ucrt64/bin:$PATH"
    export CC=gcc CXX=g++
    host_args=(--build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32)
    ;;
esac
mkdir -p "$prefix" "$cache" "$sources" "$work" "$logs"
if [ -f "$prefix/.complete-14.2.0-2.44" ]; then
  "$prefix/bin/m68k-elf-gcc" --version
  exit 0
fi
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
  cd "$work/binutils"
  if [ ! -f Makefile ]; then
    "$sources/binutils-2.44/configure" "${host_args[@]}" --target=m68k-elf --prefix="$prefix" \
      --disable-nls --disable-werror --disable-gdb --disable-gprofng --disable-sim
  fi
  make -j"$jobs"
  make install
) > "$logs/binutils.log" 2>&1 || { tail -60 "$logs/binutils.log" >&2; exit 1; }
echo 'Binutils installed; building GCC (first setup can take a while).'
(
  cd "$work/gcc"
  if [ ! -f Makefile ]; then
    "$sources/gcc-14.2.0/configure" "${host_args[@]}" --target=m68k-elf --prefix="$prefix" \
      --enable-languages=c --without-headers --with-newlib --disable-nls \
      --disable-multilib --disable-threads --disable-shared --disable-libssp \
      --disable-libquadmath --disable-libgomp --disable-libatomic --disable-libstdcxx \
      --disable-bootstrap --with-arch=m68k
  fi
  make -j"$jobs" all-gcc all-target-libgcc
  make install-gcc install-target-libgcc
) > "$logs/gcc.log" 2>&1 || { tail -60 "$logs/gcc.log" >&2; exit 1; }
"$prefix/bin/m68k-elf-gcc" --version
touch "$prefix/.complete-14.2.0-2.44"
