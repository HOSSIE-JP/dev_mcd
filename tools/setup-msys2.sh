#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
case "$(uname -s)" in MSYS*) ;; *) echo 'Run this inside the project MSYS2 MSYS shell.' >&2; exit 1;; esac
pacman -S --needed --noconfirm make git python curl tar xz gzip bzip2 diffutils \
  patch bison flex texinfo mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-gmp \
  mingw-w64-ucrt-x86_64-mpfr mingw-w64-ucrt-x86_64-mpc \
  mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-numpy \
  mingw-w64-ucrt-x86_64-python-pillow mingw-w64-ucrt-x86_64-ffmpeg
export PATH="/ucrt64/bin:$PATH"
mkdir -p .deps/logs
pacman -Q > .deps/logs/msys2-packages.txt
python3 tools/deps.py
if [ "${1:-}" = --prepare-only ]; then exit 0; fi
echo 'Building the M68000 cross-compiler; detailed output is in .deps/logs.'
bash tools/build-toolchain.sh
PATH="$PWD/.deps/toolchain/bin:$PATH" make CROSS=m68k-elf- doctor all host-test
