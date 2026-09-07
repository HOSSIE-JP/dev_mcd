"""Validate the committed sample against the source story, not generated C."""
import hashlib,json,struct,unittest,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'examples/ishinoura_ep01/data'
class NovelDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads((DATA/'manifest.json').read_text('utf-8'))
        cls.source=json.loads((DATA/'scenario.json').read_text('utf-8'))
        cls.pack=(DATA/'novel.pak').read_bytes()
    def test_source_story_is_complete(self):
        emitted=[c for s in self.source['scenes'] for c in s['commands'] if c['type'] not in ('comment','label') and not c.get('skip')]
        self.assertEqual(len(emitted),self.manifest['commands'])
        self.assertEqual([s['id'] for s in self.source['scenes']],[s['id'] for s in self.manifest['scenes']])
        voices={c['voiceAssetId'] for c in emitted if c.get('voiceAssetId')}
        self.assertEqual(voices,{r['id'] for r in self.manifest['assets'] if r['kind']=='adpcm'})
        ids={s['id'] for s in self.source['scenes']}
        for c in emitted:
            if c['type']=='jump':self.assertIn(c['sceneId'],ids)
            for option in c.get('choices',[]):self.assertIn(option['targetSceneId'],ids)
        self.assertEqual(sum(c['type']=='choice' for c in emitted),2)
    def test_pack_extents_and_voice_capacity(self):
        self.assertEqual(hashlib.sha256(self.pack).hexdigest(),self.manifest['pack_sha256'])
        self.assertEqual(len(self.pack)%2048,0)
        previous=131072
        for asset in self.manifest['assets']:
            offset,size=asset['offset'],asset['bytes'];self.assertEqual(offset%2048,0)
            self.assertGreaterEqual(offset,previous);self.assertLessEqual(offset+size,len(self.pack))
            data=self.pack[offset:offset+size]
            self.assertEqual(hashlib.sha256(data).hexdigest(),asset['sha256'])
            previous=offset+((size+2047)//2048)*2048
            if asset['kind'] in ('adpcm','psg-song','psg-sfx'):
                magic,version,rate,count,predictor,index,reserved=struct.unpack_from('>4sHHIhBB',data)
                self.assertEqual((magic,version,reserved),(b'MIMA',1,0));self.assertLessEqual(index,88)
                self.assertEqual(size,16+(count+1)//2);self.assertIn(rate,(8000,11025,16000))
                self.assertLessEqual((size+2047)//2048*2048,253952 if asset['kind']=='psg-song' else 131072)
    def test_compiled_structure_and_pages(self):
        h=struct.unpack_from('>4s10H6I',self.pack);self.assertEqual(h[:2],(b'MNVN',1))
        scenes,commands,resources=h[2],h[3],h[8];so,co,ro,size,fontbytes=h[11:16]
        self.assertEqual((scenes,commands),(18,self.manifest['commands']));self.assertLess(size,98304);self.assertLessEqual(fontbytes,32768)
        messages=0
        for i in range(commands):
            c=struct.unpack_from('>BBHhhHhHHIIII',self.pack,co+i*32)
            if c[0]!=4:continue
            messages+=1;speaker,pages,color,voice,mouth=struct.unpack_from('>I4H',self.pack,c[9])
            self.assertLess(speaker,size);self.assertGreater(pages,0)
            for page in range(pages):
                pos=struct.unpack_from('>I',self.pack,c[9]+12+page*4)[0];row=col=0
                while True:
                    self.assertLess(pos,size);glyph=struct.unpack_from('>H',self.pack,pos)[0];pos+=2
                    if glyph==65535:break
                    if glyph==65534:row+=1;col=0
                    else:self.assertLess(glyph,self.manifest['glyphs']);col+=1
                    self.assertLess(row,4);self.assertLessEqual(col,19)
        self.assertEqual(messages,275)
    def test_cdda_data_matches_manifest(self):
        for track in self.manifest['tracks']:
            raw=zlib.decompress((DATA/'cdda'/track['file']).read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(),track['sha256']);self.assertEqual(len(raw),track['samples']*4)
            self.assertEqual(len(raw)%2352,0);self.assertGreaterEqual(track['samples'],44100*4)
if __name__=='__main__':unittest.main()
