#!/usr/bin/env python3
"""Deterministic ISO9660 level-1 root-only writer + mixed-mode CUE.

The first 16 sectors hold Megadev's IP/SP boot block. No external mkisofs.
"""
import struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SECTOR=2048
def both16(x): return struct.pack('<H',x)+struct.pack('>H',x)
def both32(x): return struct.pack('<I',x)+struct.pack('>I',x)
def record(name,extent,size,directory=False):
    n=33+len(name)+(len(name)%2==0)
    return bytes([n,0])+both32(extent)+both32(size)+bytes([126,9,6,0,0,0,0,int(directory)*2,0,0])+both16(1)+bytes([len(name)])+name+b'\0'*(n-33-len(name))
def build():
    boot=(ROOT/'build/boot.bin').read_bytes()
    assert len(boot)<=16*SECTOR
    assert boot.startswith(b'SEGADISCSYSTEM')
    paths=sorted((ROOT/'build/disc').iterdir())
    assert all(p.is_file() and p.name==p.name.upper() for p in paths)
    # sector 16 PVD, 17 terminator, 18 L path table, 19 M path table, 20 root
    entries=[record(b'\0',20,SECTOR,True),record(b'\1',20,SECTOR,True)]
    extent=21; files=[]
    for p in paths:
        name=(p.name+';1').encode('ascii')
        data=p.read_bytes()
        assert len(p.stem)<=8 and len(p.suffix)<=4 and data
        entries.append(record(name,extent,len(data)))
        files.append((extent,data)); extent+=(len(data)+2047)//2048
    root=b''.join(entries)
    assert len(root)<=SECTOR, 'One root directory sector supported'
    sectors=max(450,extent+150)
    image=bytearray(sectors*SECTOR)
    image[:len(boot)]=boot
    pvd=bytearray(SECTOR)
    pvd[:8]=b'\x01CD001\x01\x00'
    pvd[8:40]=b'MEGA_CD'.ljust(32,b' ')
    pvd[40:72]=b'MCD_BRIDGE'.ljust(32,b' ')
    pvd[80:88]=both32(sectors)
    pvd[120:124]=both16(1); pvd[124:128]=both16(1); pvd[128:132]=both16(SECTOR)
    pvd[132:140]=both32(10)
    struct.pack_into('<I',pvd,140,18); struct.pack_into('>I',pvd,148,19)
    pvd[156:190]=record(b'\0',20,SECTOR,True)
    pvd[190:813]=b' '*623
    for pos in (813,830,847,864): pvd[pos:pos+17]=b'2026090600000000\x00'
    pvd[881]=1
    image[16*SECTOR:17*SECTOR]=pvd
    image[17*SECTOR:17*SECTOR+7]=b'\xFFCD001\x01'
    image[18*SECTOR:18*SECTOR+10]=struct.pack('<BBIHBB',1,0,20,1,0,0)
    image[19*SECTOR:19*SECTOR+10]=struct.pack('>BBIHBB',1,0,20,1,0,0)
    image[20*SECTOR:20*SECTOR+len(root)]=root
    for sector,data in files: image[sector*SECTOR:sector*SECTOR+len(data)]=data
    (ROOT/'dist/mcd_demo.iso').write_bytes(image)
    (ROOT/'dist/mcd_demo.cue').write_text('FILE "mcd_demo.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\nFILE "track02.wav" WAVE\n  TRACK 02 AUDIO\n    INDEX 00 00:00:00\n    INDEX 01 00:02:00\n')
    print(f'Disc: {sectors} data sectors, {len(paths)} files, track 02 stereo CD-DA')
if __name__=='__main__': build()
