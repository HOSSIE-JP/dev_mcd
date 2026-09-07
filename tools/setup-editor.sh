#!/usr/bin/env bash
# Editor-owned installation: no sudo, no global Python modifications.
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in git make gcc g++ python3 curl tar xz bison flex ffmpeg ffprobe; do
  command -v "$tool" >/dev/null || { echo "Missing host prerequisite: $tool. Install it with your OS package manager, then retry Setup." >&2; exit 1; }
done
printf '#include <gmp.h>\n#include <mpfr.h>\n#include <mpc.h>\nint main(void){return 0;}\n' | gcc -x c - -fsyntax-only || {
  echo 'Install host GMP/MPFR/MPC development headers, then retry Setup.' >&2; exit 1;
}
python3 -m venv .deps/python
.deps/python/bin/python3 -m pip install -r tools/requirements-novel.txt
.deps/python/bin/python3 tools/deps.py
bash tools/build-toolchain.sh
PATH="$PWD/.deps/python/bin:$PWD/.deps/toolchain/bin:$PATH" make CROSS=m68k-elf- libs build/libmcd_novel.a doctor
