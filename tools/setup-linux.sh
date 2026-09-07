#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v m68k-linux-gnu-gcc >/dev/null; then
  echo 'Install once on Debian/Ubuntu: sudo apt-get install git make python3 gcc gcc-m68k-linux-gnu binutils-m68k-linux-gnu'
  exit 1
fi
python3 tools/deps.py
make doctor all host-test
