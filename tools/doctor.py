#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess as sp
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--cross',default='m68k-linux-gnu-'); a=ap.parse_args()
    report={}
    for name in ('gcc','ld','objcopy'):
        tool=a.cross+name
        if not shutil.which(tool): raise SystemExit(f'Missing {tool}. Run tools/setup.ps1 on Windows or tools/setup-linux.sh on Linux.')
        report[name]=sp.check_output([tool,'--version'],text=True).splitlines()[0]
    lock=json.loads((ROOT/'toolchain.lock.json').read_text())
    for name in ('megadev',):
        got=sp.check_output(['git','-C',str(ROOT/'.deps'/name),'rev-parse','HEAD'],text=True).strip()
        assert got==lock[name]['commit'],f'{name} version mismatch'
        report[name]=got
    tracked=sp.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    for path in tracked:
        low=path.lower()
        if low.endswith(('.bin','.rom','.iso','.chd','.srm','.state')) or low.startswith(('.local/','bios/','.deps/')):
            raise SystemExit(f'Unexpected private/generated binary tracked: {path}')
    print(json.dumps(report,indent=2))
    (ROOT/'.deps/logs').mkdir(parents=True,exist_ok=True)
    (ROOT/'.deps/logs/doctor.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__': main()
