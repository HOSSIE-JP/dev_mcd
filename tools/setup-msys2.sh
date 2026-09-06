#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
case "$(uname -s)" in MSYS*) ;; *) echo 'Run this inside the project MSYS2 MSYS shell.' >&2; exit 1;; esac
pacman -S --needed --noconfirm make git python curl tar xz gzip bzip2 diffutils \
  patch bison flex texinfo mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-gmp \
  mingw-w64-ucrt-x86_64-mpfr mingw-w64-ucrt-x86_64-mpc
export PATH="/ucrt64/bin:$PATH"
mkdir -p .deps/logs
pacman -Q > .deps/logs/msys2-packages.txt
python3 tools/deps.py
bash tools/build-toolchain.sh
PATH="$PWD/.deps/toolchain/bin:$PATH" make CROSS=m68k-elf- doctor all host-test
