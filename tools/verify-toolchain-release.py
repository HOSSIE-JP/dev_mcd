#!/usr/bin/env python3
"""Verify relocation and minimal compiler execution with no MSYS PATH."""
import argparse,json,os,subprocess,tempfile,zipfile
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('archive',type=Path);args=ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='mcd relocated ') as temp:
        root=Path(temp)
        with zipfile.ZipFile(args.archive) as z:
            for name in z.namelist():
                target=(root/name).resolve()
                if not target.is_relative_to(root.resolve()):raise RuntimeError('Archive traversal')
            z.extractall(root)
        tool=root/'.deps/toolchain';bin=tool/'bin'
        env={k:v for k,v in os.environ.items() if k.upper() not in ['PATH','GCC_EXEC_PREFIX','COMPILER_PATH','LIBRARY_PATH','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH']}
        env['PATH']=str(bin)+os.pathsep+str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32')
        source=root/'smoke.c';source.write_text('volatile unsigned a=1234567,b=13; unsigned entry(void){ return a/b+a%b; }\n')
        elf=root/'smoke.elf';raw=root/'smoke.bin'
        for command in [[bin/'m68k-elf-gcc.exe','--version'],[bin/'m68k-elf-gcc.exe','-m68000','-ffreestanding','-nostdlib',source,'-Wl,-e,entry','-lgcc','-o',elf],[bin/'m68k-elf-objcopy.exe','-O','binary',elf,raw]]:
            subprocess.run([str(x) for x in command],env=env,cwd=root,check=True,timeout=60)
        if raw.stat().st_size<16:raise RuntimeError('Empty compiler output')
        print(json.dumps({'relocated':True,'systemOnlyPath':True,'compile':True,'linkLibgcc':True,'objcopy':True,'bytes':raw.stat().st_size}))
if __name__=='__main__':main()
