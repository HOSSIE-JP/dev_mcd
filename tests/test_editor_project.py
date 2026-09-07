import hashlib
import json
import struct
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
try:
    from PIL import Image, ImageFont
    from editor_project import prepare_project, project_file
except ImportError:
    Image = None


@unittest.skipIf(Image is None, 'Install tools/requirements-novel.txt for editor conversion tests')
class EditorProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'project'
        self.stage = Path(self.temp.name) / 'stage'
        (self.root / 'assets').mkdir(parents=True)
        self.write('project.json', {'title': 'Same project'})
        self.write('assets/pce-assets.json', {'version': 2, 'assets': [
            {'id': 'bg', 'type': 'image', 'source': 'assets/bg.png'},
            {'id': 'hero', 'type': 'sprite', 'source': 'assets/hero.png', 'options': {'animations': [
                {'id': 'default', 'frameWidth': 32, 'frameHeight': 64, 'frameCount': 1, 'firstCell': 0}]}}
        ]})
        self.doc = {'version': 2, 'startScene': 'start', 'scenes': [{'id': 'start', 'commands': [
            {'type': 'background', 'assetId': 'bg'},
            {'type': 'sprite', 'slot': 3, 'assetId': 'hero', 'x': 80, 'y': 20, 'animationId': 'default'},
            {'type': 'message', 'text': 'hello'}]}]}
        self.write('assets/pce-vn-scenes.json', self.doc)
        Image.new('RGB', (256, 224), (30, 80, 100)).save(self.root / 'assets/bg.png')
        hero = Image.new('RGBA', (32, 64))
        hero.paste((255, 0, 0, 255), (0, 0, 8, 64))
        hero.save(self.root / 'assets/hero.png')

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, value):
        p = self.root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value), 'utf-8')

    def test_standard_small_sprite_and_fourth_slot_preserve_source(self):
        before = (self.root / 'assets/pce-vn-scenes.json').read_bytes()
        result = prepare_project(self.root, self.stage)
        self.assertEqual(before, (self.root / 'assets/pce-vn-scenes.json').read_bytes())
        self.assertEqual(result['title'], 'Same project')
        doc = json.loads((self.stage / 'assets/pce-vn-scenes.json').read_text())
        self.assertEqual(doc['scenes'][0]['commands'][1]['slot'], 3)
        catalog = json.loads((self.stage / 'assets/pce-assets.json').read_text())['assets']
        sprite = next(a for a in catalog if a['type'] == 'sprite')
        with Image.open(self.stage / sprite['source']) as image:
            self.assertEqual(image.size, (128, 256))
            self.assertEqual(image.getpixel((40, 0))[3], 0)
            self.assertEqual(image.getpixel((0, 128)), (255, 0, 0, 255))

    def test_project_path_and_symlink_escape_rejected(self):
        outside = self.root.parent / 'outside.png'
        outside.write_bytes(b'private')
        with self.assertRaises(ValueError):
            project_file(self.root, '../outside.png')
        try:
            (self.root / 'assets/escape.png').symlink_to(outside)
        except OSError:
            return
        with self.assertRaises(ValueError):
            project_file(self.root, 'assets/escape.png')

    def test_single_animation_without_explicit_cell_reuses_its_row(self):
        catalog = json.loads((self.root / 'assets/pce-assets.json').read_text())
        del catalog['assets'][1]['options']['animations'][0]['firstCell']
        self.write('assets/pce-assets.json', catalog)
        prepare_project(self.root, self.stage)
        assets = json.loads((self.stage / 'assets/pce-assets.json').read_text())['assets']
        sprite = next(a for a in assets if a['type'] == 'sprite')
        with Image.open(self.stage / sprite['source']) as image:
            self.assertEqual(image.crop((0, 0, 64, 128)).tobytes(),
                             image.crop((0, 128, 64, 256)).tobytes())

    def test_oversized_sprite_fails_instead_of_truncating(self):
        catalog = json.loads((self.root / 'assets/pce-assets.json').read_text())
        catalog['assets'][1]['options']['animations'][0]['frameWidth'] = 96
        self.write('assets/pce-assets.json', catalog)
        with self.assertRaisesRegex(ValueError, '64x128'):
            prepare_project(self.root, self.stage)

    def test_video_source_hash_is_required(self):
        raw = b'example source'
        (self.root / 'assets/video.mp4').write_bytes(raw)
        catalog = json.loads((self.root / 'assets/pce-assets.json').read_text())
        catalog['assets'].append({'id': 'movie', 'type': 'video', 'source': 'assets/video.mp4'})
        self.write('assets/pce-assets.json', catalog)
        self.doc['scenes'][0]['commands'].append({'type': 'video', 'assetId': 'movie', 'skippable': True})
        self.write('assets/pce-vn-scenes.json', self.doc)
        self.write('assets/md-novel/video-assets.json', {'schemaVersion': 1, 'assets': {'movie': {
            'assetId': 'movie', 'sourcePath': 'assets/video.mp4', 'sha256': '0' * 64, 'profile': 'medium12'}}})
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            prepare_project(self.root, self.stage)

    def test_skipped_missing_video_is_not_converted(self):
        self.doc['scenes'][0]['commands'].append({'type': 'video', 'assetId': 'missing', 'debugSkip': True})
        self.write('assets/pce-vn-scenes.json', self.doc)
        prepare_project(self.root, self.stage)
        catalog = json.loads((self.stage / 'assets/pce-assets.json').read_text())['assets']
        self.assertFalse(any(a['type'] == 'video' for a in catalog))

    def test_auto_palette_uses_binding_and_matches_explicit_variant(self):
        actor = self.doc['scenes'][0]['commands'][1]
        actor['palette'] = ''  # The editor's ordinary Auto select value.
        self.doc['scenes'][0]['commands'].extend([
            dict(actor, slot=0, palette='PAL3'), dict(actor, slot=1, palette='PAL2')])
        self.write('assets/pce-vn-scenes.json', self.doc)
        self.write('data/md-novel/asset-bindings.json', {'assets': {'hero': {
            'legacyPalette': 'PAL3', 'palette': 'PAL2'}}})
        prepare_project(self.root, self.stage)
        commands = json.loads((self.stage / 'assets/pce-vn-scenes.json').read_text())['scenes'][0]['commands']
        self.assertEqual(commands[1]['assetId'], commands[3]['assetId'])
        self.assertNotEqual(commands[1]['assetId'], commands[4]['assetId'])

    def test_choice_implicit_values_remain_zero_based_in_native_pack(self):
        from novel_convert import convert
        self.doc['scenes'][0]['commands'].append({'type': 'choice', 'variableName': 'route', 'choices': [
            {'label': 'first'}, {'label': 'second'}, {'label': 'low', 'value': -32768},
            {'label': 'high', 'value': 32767}]})
        self.write('assets/pce-vn-scenes.json', self.doc)
        prepare_project(self.root, self.stage)
        font = ImageFont.load_default(size=16)
        data = self.root.parent / 'compiled'
        with patch('novel_convert.ImageFont.truetype', return_value=font):
            convert(self.stage, Path('test-font'), data)
        packed = (data / 'novel.pak').read_bytes()
        header = struct.unpack_from('>4s10H6I', packed)
        command_offset = header[12]
        choice = struct.unpack_from('>BBHhhHhHHIIII', packed, command_offset + 3 * 32)
        self.assertEqual(choice[0], 10)
        self.assertEqual([struct.unpack_from('>Ihh', packed, choice[9] + index * 8)[2]
                          for index in range(4)], [0, 1, -32768, 32767])

    def test_first_nonzero_define_initializes_once_before_original_start(self):
        self.doc['scenes'][0]['commands'].insert(0, {'type': 'variable', 'variableName': 'score', 'operation': 'add', 'value': 1})
        self.doc['scenes'].append({'id': 'later', 'commands': [
            {'type': 'variable', 'variableName': 'score', 'operation': 'define', 'value': 7},
            {'type': 'variable', 'variableName': 'score', 'operation': 'define', 'value': 99},
            {'type': 'jump', 'sceneId': 'start'}]})
        self.write('assets/pce-vn-scenes.json', self.doc)
        source = (self.root / 'assets/pce-vn-scenes.json').read_bytes()
        prepare_project(self.root, self.stage)
        staged = json.loads((self.stage / 'assets/pce-vn-scenes.json').read_text())
        bootstrap, original, later = staged['scenes']
        self.assertEqual(staged['startScene'], bootstrap['id'])
        self.assertEqual(bootstrap['commands'], [
            {'type': 'variable', 'variableName': 'score', 'operation': 'set', 'value': 7},
            {'type': 'jump', 'sceneId': 'start'}])
        self.assertEqual(original['commands'][0]['operation'], 'add')
        self.assertEqual([c['value'] for c in later['commands'][:2]], [7, 99])
        self.assertTrue(all(c['operation'] == 'define' for c in later['commands'][:2]))
        self.assertEqual(later['commands'][-1]['sceneId'], original['id'])
        self.assertEqual(source, (self.root / 'assets/pce-vn-scenes.json').read_bytes())

    def test_skipped_and_later_duplicate_defines_do_not_change_zero_initial_state(self):
        self.doc['scenes'][0]['commands'].extend([
            {'type': 'variable', 'variableName': 'score', 'operation': 'define', 'value': 12, 'debugSkip': True},
            {'type': 'variable', 'variableName': 'score', 'operation': 'define', 'value': 0},
            {'type': 'variable', 'variableName': 'score', 'operation': 'define', 'value': 9}])
        self.write('assets/pce-vn-scenes.json', self.doc)
        prepare_project(self.root, self.stage)
        staged = json.loads((self.stage / 'assets/pce-vn-scenes.json').read_text())
        self.assertEqual(staged['startScene'], 'start')
        self.assertEqual(len(staged['scenes']), 1)

    def test_reserved_variable_effects_are_rejected_instead_of_becoming_ordinary_variables(self):
        cases = [
            {'type': 'variable', 'name': 'AUTO_ENABLE', 'operation': 'define', 'value': 0},
            {'type': 'if', 'variable': 'MSG_SPEED', 'value': 1},
            {'type': 'choice', 'variableName': 'AUTO_ENABLE', 'choices': [{'label': 'yes'}]},
            {'type': 'switch', 'variableName': 'MSG_SPEED', 'cases': []}]
        for command in cases:
            with self.subTest(command=command):
                self.doc['scenes'][0]['commands'] = [command]
                self.write('assets/pce-vn-scenes.json', self.doc)
                with self.assertRaisesRegex(ValueError, 'reserved variable commands'):
                    prepare_project(self.root, self.stage)
        self.doc['scenes'][0]['commands'] = [dict(c, skip=True) for c in cases]
        self.write('assets/pce-vn-scenes.json', self.doc)
        prepare_project(self.root, self.stage)


if __name__ == '__main__':
    unittest.main()
