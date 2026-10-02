"""Large-disc packet integrity and bounded cache regressions, without a BIOS."""
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from PIL import ImageFont
from novel_paged import convert_paged, SCRIPT_LIMIT
from novel_convert import convert_resources


class PagedNovelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'assets').mkdir()
        (self.root / 'assets/pce-assets.json').write_text('{"assets":[]}', 'utf-8')
        self.font = ImageFont.load_default(size=16)

    def tearDown(self):
        self.temp.cleanup()

    def convert(self, scenes):
        doc = {'startScene': scenes[0]['id'], 'scenes': scenes}
        (self.root / 'assets/pce-vn-scenes.json').write_text(json.dumps(doc), 'utf-8')
        with patch('novel_paged.ImageFont.truetype', return_value=self.font):
            return convert_paged(self.root, 'font.ttf', self.root / 'out')

    def test_300_scenes_global_glyphs_targets_and_variables_roundtrip(self):
        scenes = [{'id': str(i), 'nextSceneId': str((i+1)%300), 'commands': [
            {'type': 'message', 'text': ''.join(chr(0x4e00+i*5+j) for j in range(5))},
            {'type': 'variable', 'variableName': 'shared', 'value': i},
            {'type': 'choice', 'variableName': 'choice', 'choices': [
                {'label': 'Choose this complete long label', 'targetSceneId': '299'}]},
            {'type': 'jump', 'sceneId': '299'}]} for i in range(300)]
        m = self.convert(scenes)
        p = (self.root / 'out/novel.pak').read_bytes()
        self.assertGreater(m['glyphs'], 1024)
        self.assertLess(m['max_scene_glyphs'], 100)
        self.assertEqual(m['variables'], {'shared': 0, 'choice': 1})
        h = struct.unpack_from('>4s10H6I', p)
        self.assertEqual(h[:4], (b'MNVN', 2, 300, 0))
        self.assertEqual(h[16], len(p))
        for i, row in enumerate(m['scenes']):
            off, size = struct.unpack_from('>II', p, h[11]+i*8)
            self.assertEqual((off, size), (row['offset'], row['bytes']))
            self.assertEqual(off % 2048, 0)
            self.assertLessEqual((size+2047)//2048*2048, SCRIPT_LIMIT)
            packet = p[off:off+size]
            self.assertEqual(hashlib.sha256(packet).hexdigest(), row['sha256'])
            self.assertEqual(struct.unpack_from('>h', packet, 52)[0], (i+1)%300)
            self.assertEqual(struct.unpack_from('>h', packet, 56+3*32+10)[0], 299)
            data = struct.unpack_from('>I', packet, 56+2*32+16)[0]
            label, target, value = struct.unpack_from('>Ihh', packet, data)
            chars = []
            while struct.unpack_from('>H', packet, label)[0] != 65535:
                chars.append(row['glyphs'][struct.unpack_from('>H', packet, label)[0]])
                label += 2
            self.assertEqual(''.join(chars), 'Choose this complete long label')
            self.assertEqual(target, 299)
            font_off, font_size, kind, glyphs = struct.unpack_from('>IIHH', p, h[13]+i*16)
            self.assertEqual(font_off % 2048, 0)
            self.assertEqual((font_size, kind, glyphs), (len(row['glyphs'])*32, 0, len(row['glyphs'])))
            self.assertEqual(struct.unpack_from('>I', packet, 44)[0], i)
            cursor = row['glyphs'].index('▶')
            self.assertNotEqual(p[font_off+cursor*32:font_off+(cursor+1)*32], bytes(32))

    def test_single_scene_font_and_script_overflow_rejected(self):
        with self.assertRaisesRegex(ValueError, 'glyphs exceed'):
            self.convert([{'id': 's', 'commands': [{'type': 'message', 'text': ''.join(chr(0x4e00+i) for i in range(1025))}]}])
        with self.assertRaisesRegex(ValueError, 'script .* exceeds'):
            self.convert([{'id': 's', 'commands': [{'type': 'message', 'text': 'a'*76}]*700}])

    def test_global_scene_count_and_target_validation(self):
        with self.assertRaisesRegex(ValueError, '32768'):
            self.convert([{'id': str(i), 'commands': []} for i in range(32769)])
        with self.assertRaisesRegex(ValueError, 'Unknown next scene'):
            self.convert([{'id': 's', 'commands': [], 'nextSceneId': 'missing'}])

    def test_long_bgm_preserves_duration_and_corrupt_cache_is_rebuilt(self):
        assets = {'music': {'id': 'music', 'type': 'psg-song', 'options': {'bpm': 60, 'steps': 260}}}
        cache = self.root / 'cache'
        def run():
            payload, resources = bytearray(2048), []
            _, rows, _ = convert_resources(self.root, assets, {'music'}, set(), self.root/'audio', payload, resources,
                                           cache=cache, adaptive_bgm=True)
            return payload, rows[0]
        payload, row = run()
        self.assertEqual((row['sampleRate'], row['samples']), (4000, 65*4000))
        self.assertLessEqual((row['bytes']+2047)//2048*2048, 253952)
        cached = next(cache.glob('*.bin'))
        cached.write_bytes(b'corrupted cached output')
        payload2, row2 = run()
        self.assertEqual(payload, payload2)
        self.assertEqual(row, row2)


if __name__ == '__main__':
    unittest.main()
