#!/usr/bin/env python3
"""Build allowlisted Windows toolchain and matching-source release assets."""
import argparse, hashlib, json, os, re, shutil, subprocess, urllib.request, zipfile, tarfile, io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SYSTEM={'kernel32.dll','advapi32.dll','user32.dll','shell32.dll','ole32.dll','oleaut32.dll','ws2_32.dll','ntdll.dll','msvcrt.dll','ucrtbase.dll','bcrypt.dll','secur32.dll','version.dll','shlwapi.dll'}
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def fields(p):
    parts=p.read_text(encoding='utf8').split('%')
    return {parts[i]:parts[i+1].strip().splitlines() for i in range(1,len(parts)-1,2)}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'dist/release');ap.add_argument('--source-cache',type=Path,default=ROOT/'.deps/release-sources');args=ap.parse_args()
    prefix=ROOT/'.deps/toolchain'; msys=ROOT/'.deps/msys64'; native=msys/'ucrt64'
    stamp=prefix/'.complete-14.2.0-2.44-m68000-v4'
    if not stamp.is_file(): raise RuntimeError('A completed pinned toolchain build is required')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    stage=out/'stage';stage.mkdir(exist_ok=False)
    binary=stage/'binary';target=binary/'.deps/toolchain'
    shutil.copytree(prefix,target,dirs_exist_ok=True)
    # Only compiler installation files, never the parent .deps or game assets.
    for p in target.rglob('*'):
        if p.is_symlink():raise RuntimeError('Symlink in compiler installation: '+str(p))
    objdump=native/'bin/objdump.exe'
    pending=list(target.rglob('*.exe'))+list(target.rglob('*.dll'));seen=set();dlls={}
    while pending:
        p=pending.pop(); key=p.name.lower()
        if key in seen:continue
        seen.add(key)
        text=subprocess.check_output([str(objdump),'-p',str(p)],text=True,encoding='utf8')
        for name in re.findall(r'DLL Name:\s*(\S+)',text):
            if name.lower() in SYSTEM or name.lower().startswith(('api-ms-win-','ext-ms-win-')):continue
            source=native/'bin'/name
            if not source.is_file():raise RuntimeError('Unresolved DLL: '+name)
            dest=target/'bin'/name
            if not dest.exists():shutil.copy2(source,dest);pending.append(dest)
            dlls[name]=source
    packages={}
    for d in (msys/'var/lib/pacman/local').iterdir():
        if not (d/'desc').is_file() or not (d/'files').is_file():continue
        meta=fields(d/'desc');files=fields(d/'files').get('FILES',[])
        if any('ucrt64/bin/'+name in files for name in dlls) or meta.get('NAME',[''])[0] in ['mingw-w64-ucrt-x86_64-gcc','mingw-w64-ucrt-x86_64-gcc-libs','mingw-w64-ucrt-x86_64-crt','mingw-w64-ucrt-x86_64-headers']:
            packages[d.name]=(meta,files)
    for name in dlls:
        if not any('ucrt64/bin/'+name in files for _,files in packages.values()):raise RuntimeError('Unowned DLL: '+name)
    source_root=stage/'source';source_root.mkdir(exist_ok=True)
    license_root=binary/'licenses';license_root.mkdir(exist_ok=True)
    inputs=[]
    for name,sha in [('gcc-14.2.0.tar.xz','a7b39bc69cbf9e25826c5a60ab26477001f7c08d85cec04bc0e29cabed6f3cc9'),('binutils-2.44.tar.xz','ce2017e059d63e67ddb9240e9d4ec49c2893605035cd60e92ad53177f4377237')]:
        p=ROOT/'.deps/downloads'/name
        if digest(p)!=sha:raise RuntimeError('Source checksum mismatch: '+name)
        shutil.copy2(p,source_root/name);inputs.append({'file':name,'sha256':sha})
    for pkg,(meta,files) in packages.items():
        base=meta['BASE'][0];version=meta['VERSION'][0];name=f'{base}-{version}.src.tar.zst'
        url='https://repo.msys2.org/mingw/sources/'+name
        dest=source_root/name
        print('Corresponding source:',name,flush=True)
        cache=args.source_cache/name;cache.parent.mkdir(parents=True,exist_ok=True)
        if not cache.exists():
            partial=cache.with_suffix(cache.suffix+'.part');urllib.request.urlretrieve(url,partial);partial.replace(cache)
        shutil.copy2(cache,dest)
        entries=subprocess.check_output([str(msys/'usr/bin/tar.exe'),'--force-local','-tf',str(dest)],text=True,env={**os.environ,'PATH':str(msys/'usr/bin')+os.pathsep+os.environ.get('PATH','')})
        if not any(e.endswith(('.tar.gz','.tar.xz','.tar.bz2','.tar.zst','.tgz','.zip')) or '/objects/pack/' in e and e.endswith('.pack') for e in entries.splitlines()):
            raise RuntimeError('Source package lacks upstream source archive; release blocked: '+name)
        inputs.append({'file':name,'sha256':digest(dest),'url':url,'package':pkg,'licenses':meta.get('LICENSE',[])})
        for file in files:
            if '/share/licenses/' in file and (msys/file).is_file():
                dest=license_root/pkg/Path(file).name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(msys/file,dest)
        if not (license_root/pkg).exists() and base=='mingw-w64-gcc': shutil.copytree(native/'share/licenses/gcc-libs',license_root/pkg)
        if not (license_root/pkg).exists():
            tarenv={**os.environ,'PATH':str(msys/'usr/bin')+os.pathsep+os.environ.get('PATH','')}
            for entry in entries.splitlines():
                if entry.endswith(('.tar.gz','.tar.xz','.tar.bz2','.tgz')):
                    blob=subprocess.check_output([str(msys/'usr/bin/tar.exe'),'--force-local','-xOf',str(source_root/name),entry],env=tarenv)
                    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:*') as nested:
                        for member in nested.getmembers():
                            if member.isfile() and Path(member.name).name.upper().startswith(('COPYING','LICENSE','COPYRIGHT')) and member.size<1024*1024:
                                dest=license_root/pkg/(hashlib.sha256(member.name.encode()).hexdigest()[:8]+'-'+Path(member.name).name);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(nested.extractfile(member).read())
            if not (license_root/pkg).exists():raise RuntimeError('Missing package license files: '+pkg)
    for component in ['gcc-14.2.0','binutils-2.44']:
        for p in (ROOT/'.deps/sources'/component).glob('COPYING*'):shutil.copy2(p,license_root/(component+'-'+p.name))
    for name in ['LICENSE','tools/build-toolchain.sh','tools/setup-msys2.sh','tools/setup.ps1','tools/package-release.py','tools/verify-toolchain-release.py','docs/RELEASE-LICENSING.md','docs/TOOLCHAIN-RELEASE.md']:
        dest=source_root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dest)
    metadata={'schema':1,'platform':'win32-x64','target':'m68k-elf','gcc':'14.2.0','binutils':'2.44','abi':'m68000-int32','sources':inputs,'dlls':sorted(dlls)}
    for dest in [binary,source_root]:(dest/'toolchain-manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (binary/'SOURCE-OFFER.txt').write_text('The matching source archive is distributed alongside this binary in the same Release. Retain both assets together. Source includes upstream archives, package sources and build scripts. Licenses are in licenses/. No BIOS, emulator or game content is included.\n')
    for name,folder in [('dev-mcd-toolchain-win32-x64.zip',binary),('dev-mcd-toolchain-sources.zip',source_root)]:
        with zipfile.ZipFile(out/name,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(folder.rglob('*')):
                if p.is_file():z.write(p,p.relative_to(folder).as_posix())
    manifest={'schema':1,'platform':'win32-x64','abi':'m68000-int32','binary':'dev-mcd-toolchain-win32-x64.zip','source':'dev-mcd-toolchain-sources.zip','sha256':digest(out/'dev-mcd-toolchain-win32-x64.zip'),'sourceSha256':digest(out/'dev-mcd-toolchain-sources.zip')}
    (out/'dev-mcd-toolchain-release.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest),flush=True)
if __name__=='__main__':main()
