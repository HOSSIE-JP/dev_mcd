"""Reject stale direct-CLI inputs using hashes produced by the MD editor.

The three golden digests below were generated with the existing editor's
plugins/shared/md-vn/scene-schema.js hashDocument and Node's localeCompare,
using novel-service.js converter version 5 input documents. They are fixed
fixtures rather than hashes calculated with the Python implementation under
test. No image decoder or Node installation is required to run these tests.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from editor_freshness import recheck_editor_freshness, validate_editor_freshness

SCENE = 'assets/pce-vn-scenes.json'
CATALOG = 'assets/pce-assets.json'
PROFILE = 'data/md-novel/target-profile.json'
BINDINGS = 'data/md-novel/asset-bindings.json'
TRANSACTION = 'data/md-novel/transaction.json'
CORE = (SCENE, CATALOG, PROFILE, BINDINGS)
SCENE_HASH = '314172fedbc90dfb3cb104f5bd5716997513028ca827ef50b0adc4b6302620c3'
SINGLE_HASH = 'f03bee08aa99def8874e9c98772169e14fa07a6632fe31ac463de7c8f17b2655'
GROUP_HASH = '496bd5f33e4cc2dc18af9fe8263bf02a21dea4d5eb35aabfa59d8462f02cd8a8'
ORIGINALS = {
    'assets/originals/bg.png': b'source background\n',
    'assets/originals/alpha.png': b'source actor one\n',
    'assets/originals/Beta.png': b'source actor two\n',
}
CONVERTED = {
    'res/novel/backgrounds/bg.png': b'converted background\n',
    'res/novel/sprites/alpha.png': b'converted actor one\n',
    'res/novel/sprites/Beta.png': b'converted actor two\n',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


class EditorFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='mcd-editor-freshness-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'project'
        self.root.mkdir()
        for relative, data in {**ORIGINALS, **CONVERTED}.items():
            self.write_bytes(relative, data)
        self.write_json(SCENE, {
            'version': 2, 'startScene': 'start', 'scenes': [{
                'id': 'start', 'commands': [
                    {'type': 'background', 'assetId': 'bg'},
                    {'type': 'sprite', 'assetId': 'alpha', 'slot': 0},
                    {'type': 'sprite', 'assetId': 'Beta', 'slot': 1},
                    {'type': 'message', 'text': '同じノベルを MD とメガCDへ。'},
                ],
            }],
        })
        self.write_json(CATALOG, {'version': 2, 'assets': [
            # The binding's originalSource must take priority over this path.
            {'id': 'bg', 'type': 'image', 'source': 'assets/unused.png'},
            {'id': 'alpha', 'type': 'sprite', 'source': 'assets/originals/alpha.png'},
            {'id': 'Beta', 'type': 'sprite', 'source': 'assets/originals/Beta.png'},
        ]})
        self.write_json(PROFILE, {
            'schemaVersion': 1, 'id': 'md-ntsc', 'coordinateMode': 'pce-legacy-256',
        })
        assets = {}
        for asset_id, runtime, converted, original, resize in (
                ('bg', 'IMAGE', 'novel/backgrounds/bg.png', 'assets/originals/bg.png',
                 {'width': 320, 'height': 224, 'anchor': 'center'}),
                ('alpha', 'SPRITE', 'novel/sprites/alpha.png', None,
                 {'width': 64, 'height': 128, 'anchor': 'bottom'}),
                ('Beta', 'SPRITE', 'novel/sprites/Beta.png', 'assets/originals/Beta.png', None)):
            binding = {
                'assetId': asset_id, 'runtimeType': runtime, 'sourcePath': converted,
                'contentHash': digest(CONVERTED['res/' + converted]),
                'palette': 'PAL1' if runtime == 'IMAGE' else 'PAL2',
                'paletteGroup': None if runtime == 'IMAGE' else 'cast',
                'conversion': {
                    'converterVersion': 5,
                    'paletteProfile': 'general' if runtime == 'IMAGE' else 'shadow-safe-pal012',
                    'reserveTransparent': runtime == 'SPRITE',
                    'inputHash': SINGLE_HASH if runtime == 'IMAGE' else GROUP_HASH,
                },
            }
            if original is not None:
                binding['originalSource'] = original
            if resize is not None:
                binding['conversion']['resize'] = resize
            assets[asset_id] = binding
        self.write_json(BINDINGS, {
            'schemaVersion': 1, 'sourceSceneRevision': SCENE_HASH, 'assets': assets,
            'paletteGroups': {'cast': {
                'id': 'cast', 'members': ['Beta', 'alpha'], 'profile': 'shadow-safe-pal012',
                'reserveTransparent': True, 'inputHash': GROUP_HASH,
            }},
        })
        self.commit()

    def write_bytes(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_json(self, relative, document, bom=False):
        data = json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
        self.write_bytes(relative, (b'\xef\xbb\xbf' if bom else b'') + data)

    def read_json(self, relative):
        return json.loads((self.root / relative).read_text(encoding='utf-8-sig'))

    def commit(self):
        """Re-sign raw transaction files, deliberately keeping conversion hashes."""
        paths = (*CORE, *CONVERTED, *ORIGINALS)
        self.write_json(TRANSACTION, {
            'schemaVersion': 1, 'sourceSceneRevision': SCENE_HASH,
            'documents': {path: digest((self.root / path).read_bytes()) for path in paths},
        })

    def reject(self):
        with self.assertRaises(ValueError):
            validate_editor_freshness(self.root)

    def test_valid_editor_hashes_and_snapshot_cover_originals(self):
        snapshot = validate_editor_freshness(self.root)
        for relative in (*CORE, *CONVERTED, *ORIGINALS, TRANSACTION):
            self.assertIn(relative, snapshot)
            self.assertEqual(snapshot[relative], digest((self.root / relative).read_bytes()))
        self.assertIsNone(recheck_editor_freshness(self.root, snapshot))

    def test_missing_transaction_is_rejected(self):
        (self.root / TRANSACTION).unlink()
        self.reject()

    def test_originals_are_snapshotted_even_when_not_transaction_documents(self):
        transaction = self.read_json(TRANSACTION)
        for relative in ORIGINALS:
            del transaction['documents'][relative]
        self.write_json(TRANSACTION, transaction)
        snapshot = validate_editor_freshness(self.root)
        for relative, data in ORIGINALS.items():
            self.assertEqual(snapshot[relative], digest(data))
        self.write_bytes('assets/originals/alpha.png', b'changed untracked source\n')
        with self.assertRaises(ValueError):
            recheck_editor_freshness(self.root, snapshot)

    def test_transaction_schema_and_document_map_are_required(self):
        for replacement in ({}, {'schemaVersion': 2, 'documents': {}},
                            {'schemaVersion': 1, 'documents': []}):
            with self.subTest(transaction=replacement):
                self.write_json(TRANSACTION, replacement)
                self.reject()

    def test_every_core_and_converted_document_must_be_in_manifest(self):
        for relative in (*CORE, *CONVERTED):
            with self.subTest(relative=relative):
                self.commit()
                transaction = self.read_json(TRANSACTION)
                del transaction['documents'][relative]
                self.write_json(TRANSACTION, transaction)
                self.reject()

    def test_manifest_detects_changed_or_missing_file(self):
        for relative in (PROFILE, 'res/novel/sprites/alpha.png'):
            with self.subTest(relative=relative, change='bytes'):
                original = (self.root / relative).read_bytes()
                self.write_bytes(relative, original + b' ')
                self.reject()
                self.write_bytes(relative, original)
            with self.subTest(relative=relative, change='missing'):
                (self.root / relative).unlink()
                self.reject()
                self.write_bytes(relative, original)

    def test_binding_content_hash_must_match_committed_conversion(self):
        bindings = self.read_json(BINDINGS)
        bindings['assets']['bg']['contentHash'] = '0' * 64
        self.write_json(BINDINGS, bindings)
        self.commit()
        self.reject()

    def test_updated_transaction_cannot_hide_changed_original(self):
        self.write_bytes('assets/originals/bg.png', b'changed original after conversion\n')
        self.commit()
        self.reject()

    def test_changed_palette_group_member_invalidates_whole_group(self):
        self.write_bytes('assets/originals/Beta.png', b'changed one shared palette source\n')
        self.commit()
        self.reject()

    def test_palette_group_hash_and_every_member_hash_are_required(self):
        for key in ('group', 'member'):
            with self.subTest(key=key):
                bindings = self.read_json(BINDINGS)
                target = (bindings['paletteGroups']['cast'] if key == 'group'
                          else bindings['assets']['alpha']['conversion'])
                target['inputHash'] = '0' * 64
                self.write_json(BINDINGS, bindings)
                self.commit()
                self.reject()
                target['inputHash'] = GROUP_HASH
                self.write_json(BINDINGS, bindings)

    def test_conversion_resize_and_version_are_part_of_freshness(self):
        for change in ('resize', 'converterVersion'):
            with self.subTest(change=change):
                bindings = self.read_json(BINDINGS)
                original = dict(bindings['assets']['bg']['conversion'])
                conversion = bindings['assets']['bg']['conversion']
                if change == 'resize':
                    conversion['resize'] = {'width': 256, 'height': 224, 'anchor': 'center'}
                else:
                    conversion['converterVersion'] = 4
                self.write_json(BINDINGS, bindings)
                self.commit()
                self.reject()
                bindings['assets']['bg']['conversion'] = original
                self.write_json(BINDINGS, bindings)

    def test_scene_revision_must_match_actual_scene_and_transaction(self):
        scene = self.read_json(SCENE)
        scene['scenes'][0]['commands'][-1]['text'] += ' 編集'
        self.write_json(SCENE, scene)
        self.commit()
        self.reject()

    def test_transaction_and_bindings_revision_must_agree(self):
        transaction = self.read_json(TRANSACTION)
        transaction['sourceSceneRevision'] = 'f' * 64
        self.write_json(TRANSACTION, transaction)
        self.reject()

    def test_recheck_detects_original_and_transaction_changed_together(self):
        snapshot = validate_editor_freshness(self.root)
        self.write_bytes('assets/originals/bg.png', b'changed during native compile\n')
        self.commit()
        with self.assertRaises(ValueError):
            recheck_editor_freshness(self.root, snapshot)

    def test_recheck_rejects_missing_original_or_transaction(self):
        snapshot = validate_editor_freshness(self.root)
        for relative in ('assets/originals/alpha.png', TRANSACTION):
            with self.subTest(relative=relative):
                data = (self.root / relative).read_bytes()
                (self.root / relative).unlink()
                with self.assertRaises(ValueError):
                    recheck_editor_freshness(self.root, snapshot)
                self.write_bytes(relative, data)

    def test_utf8_bom_documents_are_accepted_and_hashed_as_stored(self):
        for relative in CORE:
            self.write_json(relative, self.read_json(relative), bom=True)
        self.commit()
        self.write_json(TRANSACTION, self.read_json(TRANSACTION), bom=True)
        snapshot = validate_editor_freshness(self.root)
        self.assertEqual(snapshot[SCENE], digest((self.root / SCENE).read_bytes()))
        self.assertIsNone(recheck_editor_freshness(self.root, snapshot))

    def test_windows_binding_separators_match_editor_path_normalization(self):
        bindings = self.read_json(BINDINGS)
        for binding in bindings['assets'].values():
            binding['sourcePath'] = binding['sourcePath'].replace('/', '\\')
            if binding.get('originalSource'):
                binding['originalSource'] = binding['originalSource'].replace('/', '\\')
        self.write_json(BINDINGS, bindings)
        self.commit()
        snapshot = validate_editor_freshness(self.root)
        for relative in (*CONVERTED, *ORIGINALS):
            self.assertIn(relative, snapshot)
        self.assertIsNone(recheck_editor_freshness(self.root, snapshot))

    def test_original_path_escape_is_rejected_even_with_matching_bytes(self):
        outside = self.root.parent / 'outside.png'
        outside.write_bytes(ORIGINALS['assets/originals/bg.png'])
        bindings = self.read_json(BINDINGS)
        bindings['assets']['bg']['originalSource'] = '../outside.png'
        self.write_json(BINDINGS, bindings)
        self.commit()
        self.reject()

    def test_symlink_escape_is_rejected_even_with_matching_bytes(self):
        for relative in ('assets/originals/bg.png', 'res/novel/backgrounds/bg.png', TRANSACTION):
            with self.subTest(relative=relative):
                path = self.root / relative
                data = path.read_bytes()
                outside = self.root.parent / 'outside-file'
                outside.write_bytes(data)
                path.unlink()
                try:
                    path.symlink_to(outside)
                except OSError as error:
                    self.write_bytes(relative, data)
                    self.skipTest('Symlinks unavailable: ' + str(error))
                try:
                    self.reject()
                finally:
                    path.unlink()
                    self.write_bytes(relative, data)


if __name__ == '__main__':
    unittest.main()
