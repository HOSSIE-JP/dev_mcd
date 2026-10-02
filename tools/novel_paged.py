#!/usr/bin/env python3
"""Sector-addressed MNVN v2: one bounded script and font cache per scene.

Scene and resource IDs stay global; entering a scene changes no game variables,
BGM, or asset identity. The v1 command encoder is shared with the resident format.
"""
import json
import struct
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from novel_convert import compile_script, convert_resources, padded, sha

SCRIPT_LIMIT = 47 * 2048
FONT_LIMIT = 1024
RESOURCE_STRIDE = 16


def active_commands(scene):
    return [c for c in scene.get('commands', [])
            if not any(c.get(k) for k in ('skip', 'skipped', 'debugSkip'))
            and c['type'] not in ('comment', 'label')]


def scene_glyphs(scene):
    texts = ['▶', 'はじめる']
    for c in active_commands(scene):
        texts.extend([c.get('text', ''), c.get('speaker', '')])
        texts.extend(o['label'] for o in c.get('choices', []))
    return sorted(set(''.join(texts)) - {'\r', '\n'})


def convert_paged(source, font, out, ffmpeg='ffmpeg', ffprobe=None, cache=None):
    from novel_convert import OPS
    source, out = Path(source), Path(out)
    doc = json.loads((source / 'assets/pce-vn-scenes.json').read_text('utf-8-sig'))
    assets = {a['id']: a for a in json.loads((source / 'assets/pce-assets.json').read_text('utf-8-sig'))['assets']}
    scenes = doc['scenes']
    ids = {s['id']: i for i, s in enumerate(scenes)}
    if len(ids) != len(scenes) or not 1 <= len(scenes) <= 32768 or doc['startScene'] not in ids:
        raise ValueError('Paged MCD requires 1..32768 unique scenes and a valid start scene')
    refs, fullrefs = set(), set()
    actor_free = True
    for s in scenes:
        if s.get('nextSceneId') and s['nextSceneId'] not in ids:
            raise ValueError('Unknown next scene: ' + s['nextSceneId'])
        for c in active_commands(s):
            if c['type'] not in OPS and c['type'] != 'cache':
                raise ValueError('Unsupported command: ' + c['type'])
            if c['type'] == 'sprite' and c.get('visible', True):
                actor_free = False
            for k in ('assetId', 'voiceAssetId', 'animationAssetId'):
                if c.get(k): refs.add(c[k])
            if c['type'] == 'background' and s.get('fullScreenBg'):
                fullrefs.add(c['assetId'])
    if refs - assets.keys():
        raise ValueError('Missing assets: ' + str(sorted(refs - assets.keys())))
    resource_count = len(scenes) + len(refs)
    if resource_count > 32768:
        raise ValueError('Paged MCD signed resource IDs exceed 32768 entries')
    scene_offset = 2048
    resource_offset = len(padded(bytes(scene_offset + len(scenes) * 8)))
    metadata_size = len(padded(bytes(resource_offset + resource_count * RESOURCE_STRIDE)))
    payload = bytearray(metadata_size)
    resources = [(0, 0, 0, 0)] * len(scenes)
    resource_ids, manifest_assets, tracks = convert_resources(
        source, assets, refs, fullrefs, out, payload, resources, ffmpeg, ffprobe,
        cache=cache, background_limit=1023 if actor_free else None, adaptive_bgm=True)
    f = ImageFont.truetype(str(font), 16)
    raster = {}
    packets, command_map, variables, font_cache = [], [], {}, {}
    for index, scene in enumerate(scenes):
        glyphs = scene_glyphs(scene)
        if len(glyphs) > FONT_LIMIT:
            raise ValueError(f"Scene {scene['id']}: {len(glyphs)} glyphs exceed {FONT_LIMIT}")
        for ch in glyphs:
            if ch in raster: continue
            im = Image.new('L', (16, 16))
            if ch == '▶':
                # Bundled Shinonome has no U+25B6. Reserve a deterministic UI cursor.
                ImageDraw.Draw(im).polygon(((4, 2), (12, 7), (4, 13)), fill=255)
            else:
                ImageDraw.Draw(im).text((0, f.getmetrics()[0]), ch, font=f, fill=255, anchor='ls')
            pixels = np.array(im) >= 80
            raster[ch] = b''.join(struct.pack('>H', sum(int(v) << (15-i) for i,v in enumerate(row))) for row in pixels)
        font_data = b''.join(raster[ch] for ch in glyphs)
        key = sha(font_data)
        if key not in font_cache:
            font_cache[key] = len(payload)
            payload.extend(padded(font_data))
        resources[index] = (font_cache[key], len(font_data), 0, len(glyphs))
        local_doc = dict(doc, scenes=[scene], startScene=scene['id'])
        script, rows, _, variables = compile_script(
            local_doc, assets, [], resource_ids, glyphs, font_data, variables, ids)
        struct.pack_into('>I', script, 44, index)
        if len(padded(script)) > SCRIPT_LIMIT:
            raise ValueError(f"Scene {scene['id']}: script {len(script)} exceeds {SCRIPT_LIMIT}")
        offset = len(payload)
        struct.pack_into('>II', payload, scene_offset + index*8, offset, len(script))
        payload.extend(padded(script))
        packets.append({'id': scene['id'], 'index': index, 'commands': len(rows),
                        'offset': offset, 'bytes': len(script), 'fontResource': index,
                        'fontBytes': len(font_data), 'glyphs': ''.join(glyphs), 'sha256': sha(script)})
        for row in rows:
            row['index'] = len(command_map)
            command_map.append(row)
        if (index+1) % 250 == 0:
            print('Packed scenes', index+1, '/', len(scenes), flush=True)
    for index, row in enumerate(resources):
        struct.pack_into('>IIHHI', payload, resource_offset + index*RESOURCE_STRIDE, *row, 0)
    settings = doc.get('settings', {})
    struct.pack_into('>4s10H6I', payload, 0, b'MNVN', 2, len(scenes), 0, ids[doc['startScene']],
                     int(settings.get('messageSpeedFrames', 10)), int(settings.get('messageAdvanceMode') == 'auto'),
                     int(settings.get('messageAutoWaitFrames', 60)), len(resources), len(variables), 0,
                     scene_offset, 0, resource_offset, metadata_size, 0, len(payload))
    # One 80-minute disc includes lead-in/pregaps and any explicit CD-DA tracks.
    data_sectors = (len(payload)+2047)//2048 + 256
    audio_sectors = sum((t['samples']+587)//588 + 150 for t in tracks)
    if data_sectors + audio_sectors > 359850:
        raise ValueError('Paged novel does not fit one 80-minute CD')
    manifest = {
        'format': 'MCD-NVN-2', 'scenes': packets, 'script_bytes': sum(p['bytes'] for p in packets),
        'max_scene_script_bytes': max(p['bytes'] for p in packets),
        'glyphs': len(raster), 'max_scene_glyphs': max(len(p['glyphs']) for p in packets),
        'commands': len(command_map), 'variables': variables, 'pack_bytes': len(payload),
        'pack_sha256': sha(payload), 'tracks': tracks, 'assets': manifest_assets,
        'command_map': command_map, 'resource_count': len(resources),
        'memory': {'script': SCRIPT_LIMIT, 'directory': 2048, 'font': 32768, 'actors': 65536, 'scratch': 65536},
        'conversion_notes': [
            'MNVN v2 pages scenes and local glyph subsets from one NOVEL.PAK; global scene/asset IDs remain stable.',
            'PSG uses deterministic PCM approximations. Long songs use 4 kHz instead of 8 kHz without duration truncation.',
            'Actor-free projects may use 1023 background tiles; projects with actors retain v1 budgets.']}
    (out / 'novel.pak').write_bytes(payload)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    (out / 'scenario.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print('Paged conversion complete:', len(scenes), 'scenes,', len(command_map), 'commands,', len(payload), 'bytes', flush=True)
    return manifest
