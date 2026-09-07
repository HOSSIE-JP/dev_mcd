#!/usr/bin/env python3
"""Build the committed novel assets with Python's standard library only."""
import hashlib,json,shutil,struct,wave,zlib
from pathlib import Path
import disc
ROOT=Path(__file__).resolve().parents[1]
def build():
    sample=ROOT/'examples/ishinoura_ep01/data';out=ROOT/'dist/ishinoura_ep01';out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((sample/'manifest.json').read_text('utf-8'))
    pack=(sample/'novel.pak').read_bytes()
    if hashlib.sha256(pack).hexdigest()!=manifest['pack_sha256']:raise ValueError('Novel pack differs from manifest')
    files={'IPX.MMD':(ROOT/'build/novel/IPX.MMD').read_bytes(),'NOVEL.PAK':pack}
    image=disc.make_iso((ROOT/'build/boot.bin').read_bytes(),files)
    (out/'ishinoura_ep01.iso').write_bytes(image)
    cue=['FILE "ishinoura_ep01.iso" BINARY','  TRACK 01 MODE1/2048','    INDEX 01 00:00:00']
    for track in manifest['tracks']:
        data=zlib.decompress((sample/'cdda'/track['file']).read_bytes())
        if hashlib.sha256(data).hexdigest()!=track['sha256']:raise ValueError('CD-DA checksum mismatch')
        name=f"track{track['track']:02}.wav"
        with wave.open(str(out/name),'wb') as f:
            f.setparams((2,2,44100,0,'NONE','not compressed'));f.writeframes(b'\0'*(44100*4*2));f.writeframes(data)
        cue.extend([f'FILE "{name}" WAVE',f"  TRACK {track['track']:02} AUDIO",'    INDEX 00 00:00:00','    INDEX 01 00:02:00'])
    (out/'ishinoura_ep01.cue').write_text('\n'.join(cue)+'\n',encoding='ascii')
    print('Novel disc:',len(image),'bytes,',len(manifest['tracks']),'CD-DA tracks')
if __name__=='__main__':build()
