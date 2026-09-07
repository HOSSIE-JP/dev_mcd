#!/usr/bin/env python3
"""Fetch exact upstream commits, keeping dependencies outside version control."""
import argparse
import json
import subprocess as sp
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def fetch(name,entry):
    path=ROOT/'.deps'/name
    if not (path/'.git').exists():
        path.mkdir(parents=True,exist_ok=True)
        sp.run(['git','init',str(path)],check=True)
        sp.run(['git','-C',str(path),'remote','add','origin',entry['url']],check=True)
    def git(*args): return sp.check_output(['git','-C',str(path),*args],text=True).strip()
    if git('status','--porcelain','--untracked-files=no'): raise RuntimeError(f'{path}: tracked local edits; refusing to overwrite')
    current=sp.run(['git','-C',str(path),'rev-parse','HEAD'],capture_output=True,text=True)
    if current.returncode or current.stdout.strip()!=entry['commit']:
        sp.run(['git','-C',str(path),'fetch','--depth=1','origin',entry['commit']],check=True)
        sp.run(['git','-C',str(path),'checkout','--detach',entry['commit']],check=True)
    assert git('rev-parse','HEAD')==entry['commit']
    print(name,entry['commit'])
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--emulator',action='store_true'); args=ap.parse_args()
    entries=json.loads((ROOT/'toolchain.lock.json').read_text())
    for name in ['megadev']+(['genesis-plus-gx'] if args.emulator else []): fetch(name,entries[name])
if __name__=='__main__': main()
