#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v m68k-linux-gnu-gcc >/dev/null; then
  echo 'Install once on Debian/Ubuntu: sudo apt-get install git make python3 gcc gcc-m68k-linux-gnu binutils-m68k-linux-gnu'
  exit 1
fi
if ! python3 -c 'import PIL, numpy' >/dev/null 2>&1; then
  echo 'Install Python conversion/test dependencies in a local virtual environment:'
  echo 'python3 -m venv .deps/python && .deps/python/bin/pip install -r tools/requirements-novel.txt'
  echo 'Then activate it with: source .deps/python/bin/activate'
  exit 1
fi
python3 tools/deps.py
make doctor all host-test
