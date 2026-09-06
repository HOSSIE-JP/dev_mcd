import hashlib
import os
import struct
import subprocess as sp
import sys
import unittest
import wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class MediaTests(unittest.TestCase):
    def test_decoder_on_host(self):
        out=ROOT/'build/ima_vectors.exe'
        out.parent.mkdir(exist_ok=True)
        sp.run([os.environ.get('HOST_CC','gcc'),'-std=c11','-Wall','-Wextra','-Werror','-Iinclude',
                'tests/ima_vectors.c','src/sub/ima.c','-o',str(out)],cwd=ROOT,check=True)
        sp.run([str(out)],check=True)
    def test_iso_extents_and_payloads(self):
        data=(ROOT/'dist/mcd_demo.iso').read_bytes()
        self.assertEqual(data[:16],b'SEGADISCSYSTEM  ')
        self.assertEqual(data[0x110:0x120],b'(C)2026 HOSSIE  ')
        self.assertEqual(data[16*2048:16*2048+7],b'\1CD001\1')
        pvd=data[16*2048:17*2048]
        self.assertEqual(struct.unpack('<I',pvd[80:84])[0]*2048,len(data))
        self.assertEqual(struct.unpack('<I',pvd[80:84])[0],struct.unpack('>I',pvd[84:88])[0])
        root_sector=struct.unpack('<I',pvd[158:162])[0]
        directory=data[root_sector*2048:(root_sector+1)*2048]
        offset=0; found=[]
        while directory[offset]:
            length=directory[offset]; record=directory[offset:offset+length]
            extent=struct.unpack('<I',record[2:6])[0]; size=struct.unpack('<I',record[10:14])[0]
            self.assertEqual(extent,struct.unpack('>I',record[6:10])[0])
            self.assertEqual(size,struct.unpack('>I',record[14:18])[0])
            name=record[33:33+record[32]]
            if name not in (b'\0',b'\1'):
                path=ROOT/'build/disc'/name.decode().split(';')[0]
                self.assertEqual(data[extent*2048:extent*2048+size],path.read_bytes())
                found.append(path.name)
            offset+=length
        self.assertEqual(sorted(found),['IMAGE.MIM','IPX.MMD','SOUND.IMA'])
    def test_adpcm_format_and_disc_audio(self):
        data=(ROOT/'build/disc/SOUND.IMA').read_bytes()
        self.assertEqual(data[:4],b'MIMA')
        version,rate,count,predictor,index,reserved=struct.unpack('>HHIhBB',data[4:16])
        self.assertEqual((version,rate,count,predictor,index,reserved),(1,22050,44100,0,0,0))
        self.assertEqual(len(data),16+(count+1)//2)
        with wave.open(str(ROOT/'dist/track02.wav'),'rb') as wav:
            self.assertEqual((wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes()),(2,2,44100,441000))
            self.assertEqual(wav.readframes(88200),b'\0'*(88200*4))
            self.assertNotEqual(wav.readframes(44100),b'\0'*(44100*4))
        cue=(ROOT/'dist/mcd_demo.cue').read_text()
        self.assertIn('TRACK 02 AUDIO',cue)
        self.assertIn('INDEX 01 00:02:00',cue)
    def test_reproducible_assets(self):
        paths=[ROOT/'build/disc/IMAGE.MIM',ROOT/'build/disc/SOUND.IMA',ROOT/'dist/track02.wav']
        before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        sp.run([sys.executable,'tools/assets.py'],cwd=ROOT,check=True,stdout=sp.DEVNULL)
        self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])
if __name__=='__main__': unittest.main()
