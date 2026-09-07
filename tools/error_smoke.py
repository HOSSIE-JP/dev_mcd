#!/usr/bin/env python3
"""Corrupt copies of the generated disc; verify safe target-side failures."""
import argparse
import shutil
import struct
import subprocess as sp
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--bios',required=True,type=Path); a=ap.parse_args()
    original=(ROOT/'dist/mcd_demo.iso').read_bytes()
    directory=struct.unpack_from('<I',original,16*2048+158)[0]*2048
    records={}; p=directory
    while original[p]:
        name=original[p+33:p+33+original[p+32]]
        records[name]=p; p+=original[p]
    for case,error in [('missing-image',2),('oversized-image',8),('invalid-adpcm-index',4)]:
        dest=ROOT/'build/error-discs'/case; dest.mkdir(parents=True,exist_ok=True)
        data=bytearray(original)
        if case=='missing-image': data[records[b'IMAGE.MIM;1']+33]=ord('X')
        elif case=='oversized-image':
            p=records[b'IMAGE.MIM;1']; struct.pack_into('<I',data,p+10,0x40001); struct.pack_into('>I',data,p+14,0x40001)
        else:
            p=records[b'SOUND.IMA;1']; extent=struct.unpack_from('<I',data,p+2)[0]; data[extent*2048+14]=89
        (dest/'mcd_demo.iso').write_bytes(data)
        shutil.copyfile(ROOT/'dist/mcd_demo.cue',dest/'mcd_demo.cue')
        shutil.copyfile(ROOT/'dist/track02.wav',dest/'track02.wav')
        sp.run([sys.executable,str(ROOT/'tools/smoke.py'),'--bios',str(a.bios.resolve()),
                '--disc',str(dest/'mcd_demo.cue'),'--expect-error',str(error),
                '--output',str(ROOT/'build/error-validation'/case)],check=True)
if __name__=='__main__': main()
