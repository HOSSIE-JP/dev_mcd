#!/usr/bin/env python3
"""Package the bridge sample without changing the media-demo disc outputs."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from disc import make_iso


def main():
    image = make_iso((ROOT / 'build/boot.bin').read_bytes(), {
        'IPX.MMD': (ROOT / 'build/bridge/IPX.MMD').read_bytes(),
        'IMAGE.MIM': (ROOT / 'build/disc/IMAGE.MIM').read_bytes(),
    })
    (ROOT / 'dist').mkdir(exist_ok=True)
    (ROOT / 'dist/bridge_demo.iso').write_bytes(image)
    (ROOT / 'dist/bridge_demo.cue').write_text(
        'FILE "bridge_demo.iso" BINARY\n  TRACK 01 MODE1/2048\n'
        '    INDEX 01 00:00:00\n', encoding='ascii')
    print(f'Bridge demo: {len(image) // 2048} sectors')


if __name__ == '__main__':
    main()
