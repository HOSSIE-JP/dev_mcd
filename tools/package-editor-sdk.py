#!/usr/bin/env python3
"""Package editor SDK sources and video converters without game assets."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOP={'Makefile','mcd.cmd','toolchain.lock.json','LICENSE','THIRD_PARTY_NOTICES.md','.gitignore','.gitattributes','README.md'}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'dist/editor-sdk-release');args=ap.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    tracked=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z']).decode().split('\0')
    files=[n for n in tracked if n and (n in TOP or n.startswith(('src/','include/','tools/')) or n=='examples/ishinoura_ep01/main.c')]
    required=['LICENSE','Makefile','tools/video_preview.py','tools/build_editor_novel.py','tools/setup.ps1','tools/setup-editor.sh','examples/ishinoura_ep01/main.c']
    if any(n not in files for n in required):raise RuntimeError('Incomplete SDK source package')
    for name in files:
        if (ROOT/name).is_symlink():raise RuntimeError('SDK symlinks are not distributable')
        if any(part in ['.local','.deps','bios','BIOS','data'] for part in Path(name).parts):raise RuntimeError('Forbidden SDK input: '+name)
    archive=out/'dev-mcd-editor-sdk.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):z.write(ROOT/name,name)
    revision=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    result={'schema':1,'sdkRevision':revision,'archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'toolchainTag':'mcd-toolchain-gcc14.2.0-binutils2.44-v1','files':sorted(files)}
    (out/'dev-mcd-editor-sdk-release.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'revision':revision,'files':len(files),'archiveBytes':archive.stat().st_size}))
if __name__=='__main__':main()
