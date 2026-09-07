#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.deps/toolchain/bin:/ucrt64/bin:$PATH"
export CROSS=m68k-elf-
case "${1:-build}" in
  build) make all ;;
  novel) make novel ;;
  clean) make clean ;;
  doctor) make doctor ;;
  test) make host-test ;;
  shell) exec bash --noprofile --norc -i ;;
  *) echo 'Usage: mcd.cmd [build|novel|clean|doctor|test|shell]' >&2; exit 2 ;;
esac
