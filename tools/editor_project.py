"""Prepare the canonical MD Novel project for the MCD compiler.

Only the temporary build tree is written. Source scenes, bindings and media stay
in the editor project. Unsupported runtime features fail before publication.
"""
import copy
import hashlib
import json
import math
import shutil
from pathlib import Path
from PIL import Image, ImageOps


def read_json(path, default=None):
    if not path.exists() and default is not None:
        return default
    return json.loads(path.read_text('utf-8-sig'))


def project_file(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Invalid project-relative asset path')
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Missing asset or path outside project: ' + relative)
    return path


def file_hash(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_integer(value, fallback=0):
    """Match MD compiler Number/Math.round/clamp for the signed-16 fields."""
    try:
        if isinstance(value, str):
            value = value.strip()
            if value.lower().startswith(('0x', '0o', '0b')):
                value = int(value, 0)
        number = float(0 if value is None or value == '' else value)
        if not math.isfinite(number):
            return fallback
        return max(-32768, min(32767, math.floor(number + 0.5)))
    except (TypeError, ValueError, OverflowError):
        return fallback


def portrait_palette(command, binding):
    for value in (command.get('palette'), binding.get('legacyPalette') or binding.get('palette')):
        palette = str(value or '').strip().upper()
        if palette in ('PAL0', 'PAL1', 'PAL2', 'PAL3'):
            return palette
    return 'PAL2'


def normalize_md_semantics(doc):
    """Lower canonical MD defaults without changing the standalone converter."""
    initial = {}
    for scene in doc['scenes']:
        for command in scene.get('commands', []):
            if any(command.get(key) for key in ('skip', 'skipped', 'debugSkip')):
                continue
            kind = command.get('type')
            if kind not in ('variable', 'if', 'switch', 'choice'):
                continue
            if kind == 'choice':
                name = command.get('variableName') or command.get('variable') or command.get('resultVariable') or ''
            else:
                name = command.get('variableName') or command.get('name') or command.get('variable') or ''
            if name in ('AUTO_ENABLE', 'MSG_SPEED'):
                raise ValueError('MCD does not support reserved variable commands for ' + name
                                 + '; use messageAdvanceMode/messageSpeedFrames settings instead')
            if name:
                command['variableName'] = name
            if kind == 'choice':
                for index, option in enumerate(command.get('choices', [])):
                    option['value'] = canonical_integer(option['value'], index) if 'value' in option else index
            elif kind == 'variable' and command.get('operation') == 'define' and name and name not in initial:
                # MD hoists the first DEFINE, and also executes every DEFINE as
                # SET when reached. Retain those commands, including duplicates.
                initial[name] = canonical_integer(command.get('value', 0))
                command['value'] = initial[name]
    initial = {name: value for name, value in initial.items() if value != 0}
    if initial:
        existing = {scene['id'] for scene in doc['scenes']}
        identifier = '__md_initial_variables'
        while identifier in existing:
            identifier += '_'
        entry = {'id': identifier, 'commands': [
            {'type': 'variable', 'variableName': name, 'operation': 'set', 'value': value}
            for name, value in initial.items()
        ] + [{'type': 'jump', 'sceneId': doc['startScene']}]}
        # A private entry scene runs once; jumps back to the original start
        # scene must not reset the initial values again.
        doc['scenes'].insert(0, entry)
        doc['startScene'] = identifier


def normalize_sprite(src, dest, options, flip_x=False, flip_y=False):
    """Pad up to two 1/2-frame animations into the fixed MCD cache layout."""
    image = Image.open(src).convert('RGBA')
    animations = options.get('animations', [])
    if not 1 <= len(animations) <= 2:
        raise ValueError('MCD supports one or two sprite animations per asset')
    result = Image.new('RGBA', (128, 256))
    normalized = []
    for row in range(2):
        source_row = min(row, len(animations) - 1)
        a = animations[source_row]
        width = int(a.get('frameWidth', options.get('spriteEditor', {}).get('frameWidth', 64)))
        height = int(a.get('frameHeight', options.get('spriteEditor', {}).get('frameHeight', 128)))
        count = int(a.get('frameCount', 1))
        if not 0 < width <= 64 or not 0 < height <= 128 or count not in (1, 2):
            raise ValueError('MCD sprite frame must fit 64x128 with at most two frames')
        if image.width % width or image.height % height:
            raise ValueError('Sprite sheet is not a complete grid')
        columns = image.width // width
        first = int(a.get('firstCell', source_row * columns))
        stride = int(a.get('frameStrideCells', 1))
        if first < 0 or stride < 1:
            raise ValueError('Invalid sprite frame grid offset')
        for frame in range(2):
            cell = first + min(frame, count - 1) * stride
            left, top = (cell % columns) * width, (cell // columns) * height
            if top + height > image.height:
                raise ValueError('Sprite frame points outside sheet')
            crop = image.crop((left, top, left + width, top + height))
            if flip_x:
                crop = ImageOps.mirror(crop)
            if flip_y:
                crop = ImageOps.flip(crop)
            result.paste(crop, (frame * 64, row * 128))
        normalized.append(dict(a, frameWidth=64, frameHeight=128, firstCell=row * 2,
                               frameCount=count, frameStrideCells=1))
    result.save(dest)
    return dict(options, animations=normalized)


def prepare_project(project, stage):
    project = project.resolve()
    source_documents = ('project.json', 'assets/pce-vn-scenes.json', 'assets/pce-assets.json',
                        'data/md-novel/target-profile.json', 'data/md-novel/asset-bindings.json',
                        'assets/md-novel/video-assets.json')
    document_hashes = {rel: file_hash(project / rel) for rel in source_documents if (project / rel).is_file()}
    config = read_json(project / 'project.json')
    doc = copy.deepcopy(read_json(project / 'assets/pce-vn-scenes.json'))
    catalog = read_json(project / 'assets/pce-assets.json')
    profile = read_json(project / 'data/md-novel/target-profile.json', {})
    bindings = read_json(project / 'data/md-novel/asset-bindings.json', {}).get('assets', {})
    videos = read_json(project / 'assets/md-novel/video-assets.json', {}).get('assets', {})
    if doc.get('version') != 2 or not doc.get('scenes'):
        raise ValueError('Expected canonical PCE VN v2 scene document')
    normalize_md_semantics(doc)
    ids = [a['id'] for a in catalog.get('assets', [])]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate asset IDs')
    assets = {a['id']: a for a in catalog['assets']}
    scene_ids = [s['id'] for s in doc['scenes']]
    if len(scene_ids) != len(set(scene_ids)) or doc.get('startScene') not in scene_ids:
        raise ValueError('Invalid start scene or duplicate scene IDs')
    legacy = profile.get('coordinateMode', 'pce-legacy-256') == 'pce-legacy-256'
    (stage / 'assets/converted').mkdir(parents=True, exist_ok=True)
    converted = {}
    fingerprint = dict(document_hashes)
    palette_banks = {}

    def source_for(a, binding=True):
        b = bindings.get(a['id'], {})
        rel = 'res/' + b['sourcePath'] if binding and b.get('sourcePath') else a.get('source')
        src = project_file(project, rel)
        fingerprint[rel] = file_hash(src)
        return src

    def copy_asset(asset_id):
        if asset_id in converted:
            return asset_id
        if asset_id not in assets:
            raise ValueError('Missing asset: ' + asset_id)
        a = copy.deepcopy(assets[asset_id])
        if a['type'] == 'video':
            v = videos.get(asset_id)
            if not v or v.get('assetId') != asset_id:
                raise ValueError('Video settings missing: ' + asset_id)
            src = project_file(project, v.get('sourcePath'))
            actual = file_hash(src)
            if actual != v.get('sha256') or a.get('source') != v['sourcePath']:
                raise ValueError('Video source/settings hash mismatch: ' + asset_id)
            fingerprint[v['sourcePath']] = actual
            a['options'] = dict(a.get('options', {}), profile=v.get('profile', 'medium12'))
        elif a.get('source'):
            src = source_for(a, binding=False)
        else:
            src = None
        if src:
            rel = 'assets/converted/' + hashlib.sha256(asset_id.encode()).hexdigest()[:16] + src.suffix
            shutil.copyfile(src, stage / rel)
            a['source'] = rel
        converted[asset_id] = a
        return asset_id

    for scene in doc['scenes']:
        if scene.get('nextSceneId') and scene['nextSceneId'] not in scene_ids:
            raise ValueError('Unknown next scene: ' + scene['nextSceneId'])
        for command in scene.get('commands', []):
            if any(command.get(k) for k in ('skip', 'skipped', 'debugSkip')):
                continue
            kind = command['type']
            aid = command.get('assetId')
            if kind == 'sprite' and command.get('visible') is False:
                aid = None
                command['assetId'] = ''
            if kind in ('sprite', 'spritemove') and not 0 <= int(command.get('slot', 0)) <= 3:
                raise ValueError('MCD actor slots are 0..3')
            if kind == 'spritemove' and (command.get('animationId') or command.get('animationAssetId')):
                raise ValueError('MCD sprite movement cannot switch animation; use a sprite command first')
            if kind == 'spritetext' and int(command.get('slot', 0)) != 0:
                raise ValueError('MCD currently supports SpriteText slot 0 only')
            if kind in ('sprite', 'spritemove', 'spritetext') and not legacy:
                command['x'] = int(command.get('x', 0)) - 32
            if kind in ('background', 'sprite') and aid and (kind != 'sprite' or command.get('visible', True)):
                if aid not in assets or assets[aid]['type'] != ('image' if kind == 'background' else 'sprite'):
                    raise ValueError('Incorrect visual asset reference: ' + aid)
                a = assets[aid]
                b = bindings.get(aid, {})
                src = source_for(a)
                settings = (aid, kind, command.get('x', 0), command.get('y', 0)) if kind == 'background' else (
                    aid, kind, command.get('flipX', False), command.get('flipY', False), portrait_palette(command, b))
                variant = aid + '_mcd_' + hashlib.sha256(json.dumps(settings).encode()).hexdigest()[:10]
                if variant not in converted:
                    rel = 'assets/converted/' + hashlib.sha256(variant.encode()).hexdigest()[:16] + '.png'
                    out_asset = copy.deepcopy(a)
                    if kind == 'background':
                        image = Image.open(src).convert('RGB')
                        x, y = int(command.get('x', 0)), int(command.get('y', 0))
                        if b.get('placementMode') == 'md-native-tiles':
                            x, y = x * 8, y * 8
                        elif legacy:
                            x, y = (4 + x) * 8, y * 8
                        else:
                            x, y = (x // 8) * 8, (y // 8) * 8
                        if image.width > 320 or image.height > 224:
                            raise ValueError('MCD background must fit a 320x224 viewport')
                        canvas = Image.new('RGB', (320, 224))
                        canvas.paste(image, (x, y))
                        canvas.save(stage / rel)
                    else:
                        pal = portrait_palette(command, b)
                        if pal not in palette_banks:
                            if len(palette_banks) == 2:
                                raise ValueError('MCD supports two shared portrait palette groups')
                            palette_banks[pal] = len(palette_banks) + 1
                        out_asset['mcdPalette'] = palette_banks[pal]
                        out_asset['options'] = normalize_sprite(src, stage / rel, a.get('options', {}),
                            bool(command.get('flipX')), bool(command.get('flipY')))
                    out_asset.update(id=variant, source=rel)
                    converted[variant] = out_asset
                command['assetId'] = variant
                if kind == 'sprite':
                    command['flipX'] = command['flipY'] = False
            elif aid:
                copy_asset(aid)
            for key in ('voiceAssetId', 'animationAssetId'):
                if command.get(key):
                    copy_asset(command[key])
    (stage / 'assets/pce-vn-scenes.json').write_text(json.dumps(doc, ensure_ascii=False), 'utf-8')
    (stage / 'assets/pce-assets.json').write_text(json.dumps({'version': 2, 'assets': list(converted.values())}, ensure_ascii=False), 'utf-8')
    for rel, expected in document_hashes.items():
        if file_hash(project / rel) != expected:
            raise ValueError('Project changed during conversion: ' + rel)
    return {'title': config.get('title', config.get('name', 'MD Novel')), 'sourceHashes': fingerprint,
            'warnings': ['MCD uses its own message renderer and two shared portrait palettes.',
                         'PSG is rendered to PCM/IMA; XGM2 bindings are not executed by MCD.']}
