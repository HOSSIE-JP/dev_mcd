#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.deps/toolchain/bin:/ucrt64/bin:$PATH"
export CROSS="${CROSS:-m68k-elf-}"
command="${1:-build}"
if (( $# )); then shift; fi
case "$command" in
  build) exec make all "$@" ;;
  novel) exec make novel "$@" ;;
  bridge) exec make bridge "$@" ;;
  video) exec make video "$@" ;;
  video-data) exec make video-data "$@" ;;
  libs) exec make libs "$@" ;;
  editor-novel) exec "${PYTHON:-python3}" tools/build_editor_novel.py "$@" ;;
  clean) exec make clean "$@" ;;
  doctor) exec make doctor "$@" ;;
  test) exec make host-test "$@" ;;
  shell) exec bash --noprofile --norc -i ;;
  help|--help|-h)
    echo 'Usage: mcd.cmd [build|novel|bridge|video|video-data|libs|clean|doctor|test|shell] [make options]'
    echo '       mcd.cmd editor-novel --project PATH --output PATH --font PATH [options]'
    echo 'Change the procedural video profile with: mcd.cmd video-data VIDEO_PROFILE=full6'
    echo 'Then build the prepared movie with: mcd.cmd video'
    ;;
  *) echo 'Unknown command. Run mcd.cmd help for available commands.' >&2; exit 2 ;;
esac
