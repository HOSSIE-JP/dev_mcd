"""Validate saved MD Novel inputs before the direct Mega-CD CLI consumes res/.

This checks transaction and visual conversion provenance, not the MD renderer's
sprite/VRAM budgets. Hashes follow the editor's scene-schema / novel-service v5.
"""
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

TRANSACTION = 'data/md-novel/transaction.json'
SCENE = 'assets/pce-vn-scenes.json'
CATALOG = 'assets/pce-assets.json'
PROFILE = 'data/md-novel/target-profile.json'
BINDINGS = 'data/md-novel/asset-bindings.json'
REQUIRED = (SCENE, CATALOG, PROFILE, BINDINGS)
VISUAL_VERSION = 5
SHA256 = re.compile(r'^[0-9a-f]{64}$')


def _path(root, relative):
    if not isinstance(relative, str) or not relative or '\0' in relative:
        raise ValueError('Invalid project-relative freshness path')
    relative = relative.replace('\\', '/')
    parts = relative.split('/')
    if relative.startswith('/') or re.match(r'^[a-z]:', relative, re.I) or any(part in ('', '.', '..') for part in parts):
        raise ValueError('Unsafe freshness path: ' + relative)
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError('Missing freshness input or path outside project: ' + relative)
    return target, relative


def _file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _read_json(path):
    def invalid(value):
        raise ValueError('Invalid JSON number: ' + value)
    return json.loads(path.read_text('utf-8-sig'), parse_constant=invalid)


def _utf16(value):
    return value.encode('utf-16-be', 'surrogatepass')


def _json_string(value):
    text = json.dumps(value, ensure_ascii=False)
    return ''.join('\\u%04x' % ord(char) if 0xD800 <= ord(char) <= 0xDFFF else char for char in text)


def _number(value):
    # JSON.parse/JSON.stringify use binary64 even for integer literals. Python's
    # shortest float representation has different exponent formatting thresholds.
    if isinstance(value, int) and abs(value) <= 9007199254740991:
        return str(value)
    number = float(value)
    if not math.isfinite(number):
        return 'null'
    if number == 0:
        return '0'
    text = repr(number).lower()
    if 1e-6 <= abs(number) < 1e21:
        text = format(Decimal(text), 'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text
    if 'e' in text:
        mantissa, exponent = text.split('e')
        exponent = int(exponent)
        return mantissa.removesuffix('.0') + 'e' + ('+' if exponent >= 0 else '') + str(exponent)
    return text.removesuffix('.0')


def _canonical(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return _json_string(value)
    if isinstance(value, list):
        return '[' + ','.join(_canonical(item) for item in value) + ']'
    if isinstance(value, dict):
        # JS objects enumerate array-index keys before other UTF-16-sorted keys.
        indexes = sorted((key for key in value if re.fullmatch(r'0|[1-9][0-9]*', key) and int(key) < 4294967295), key=int)
        keys = indexes + sorted((key for key in value if key not in indexes), key=_utf16)
        return '{' + ','.join(_json_string(key) + ':' + _canonical(value[key]) for key in keys) + '}'
    raise ValueError('Unsupported value in editor JSON')


def hash_document(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _palette(value):
    normalized = str(value or '').strip().upper()
    return normalized if normalized in ('PAL0', 'PAL1', 'PAL2', 'PAL3') else ''


def _profile(palette, sprite):
    if sprite:
        return 'shadow-safe-pal3' if _palette(palette) == 'PAL3' else 'shadow-safe-pal012'
    return 'pal0-reserved' if _palette(palette) == 'PAL0' else 'general'


def _compatible(profiles):
    values = set(profiles)
    if len(values) == 1:
        return next(iter(values))
    if values and values <= {'shadow-safe-pal012', 'shadow-safe-pal3'}:
        return 'shadow-safe-pal3'
    return None


def _satisfies(actual, required):
    return bool(actual and required and (actual == required or (actual == 'shadow-safe-pal3' and required == 'shadow-safe-pal012')))


def _requirements(scene, assets):
    result = {}
    for entry in scene.get('scenes', []):
        for command in entry.get('commands', []):
            kind = command.get('type')
            if kind not in ('background', 'sprite') or any(command.get(key) is True for key in ('skip', 'skipped', 'debugSkip')):
                continue
            identifier = str(command.get('assetId') or '').strip()
            if not identifier:
                continue
            binding = assets.get(identifier, {})
            palette = _palette(command.get('palette')) or _palette(binding.get('legacyPalette') or binding.get('palette'))
            palette = palette or ('PAL1' if kind == 'background' else 'PAL2')
            result.setdefault(identifier, set()).add(_profile(palette, kind == 'sprite'))
    return result


def _input_hash_matches(document, expected):
    # The editor uses localeCompare for group source order. Accept only exact
    # cryptographic matches, trying a small deterministic set of common orders.
    sources = document['sources']
    orders = [sources, sorted(sources, key=lambda item: _utf16(item['assetId'])),
              sorted(sources, key=lambda item: item['assetId']),
              sorted(sources, key=lambda item: (item['assetId'].casefold(), item['assetId'].swapcase()))]
    for ordered in orders:
        if hash_document(dict(document, sources=ordered)) == expected:
            return True
    if len(sources) <= 1:
        return False
    node = shutil.which('node')
    if not node:
        raise ValueError('Palette group conversion hash differs. Save/reconvert the Novel project; '
                         'if its locale-sorted asset IDs are unchanged, install Node.js on PATH to verify this group exactly.')
    # Fixed program text, input through stdin; no shell interpolation or imports
    # from the project. Optional Node uses the editor's own ICU ordering rules.
    program = """const fs=require('node:fs'),crypto=require('node:crypto');
const x=JSON.parse(fs.readFileSync(0,'utf8'));x.sources.sort((a,b)=>a.assetId.localeCompare(b.assetId));
function stable(v){if(Array.isArray(v))return v.map(stable);if(v&&typeof v==='object'){const o={};Object.keys(v).sort().forEach(k=>o[k]=stable(v[k]));return o;}return v;}
process.stdout.write(crypto.createHash('sha256').update(JSON.stringify(stable(x)),'utf8').digest('hex'));
"""
    result = subprocess.run([node, '-e', program], input=json.dumps(document, ensure_ascii=True),
                            text=True, capture_output=True, check=True, timeout=15)
    return result.stdout == expected


def validate_editor_freshness(project):
    root = Path(project).resolve()
    snapshot = {}

    def remember(relative):
        target, normalized = _path(root, relative)
        digest = _file_hash(target)
        if normalized in snapshot and snapshot[normalized] != digest:
            raise ValueError('Project changed during freshness validation: ' + normalized)
        snapshot[normalized] = digest
        return target, normalized, digest

    transaction_path, _, _ = remember(TRANSACTION)
    transaction = _read_json(transaction_path)
    if not isinstance(transaction, dict) or transaction.get('schemaVersion') != 1 or not isinstance(transaction.get('documents'), dict):
        raise ValueError('Invalid Novel transaction manifest; save the Novel project before building')
    committed = transaction['documents']
    for relative in REQUIRED:
        if relative not in committed:
            raise ValueError('Novel transaction is missing a required document: ' + relative)
    for relative, expected in committed.items():
        if not isinstance(expected, str) or not SHA256.fullmatch(expected):
            raise ValueError('Invalid transaction SHA-256: ' + relative)
        _, _, actual = remember(relative)
        if actual != expected:
            raise ValueError('Novel transaction hash mismatch: ' + relative)
    scene = _read_json(root / SCENE)
    catalog = _read_json(root / CATALOG)
    bindings = _read_json(root / BINDINGS)
    if not isinstance(bindings, dict) or not isinstance(bindings.get('assets'), dict):
        raise ValueError('Invalid visual asset bindings')
    revision = hash_document(scene)
    if bindings.get('sourceSceneRevision') != revision or transaction.get('sourceSceneRevision') != revision:
        raise ValueError('Novel bindings/transaction scene revision is stale; save the Novel project')
    assets = bindings['assets']
    catalog_by_id = {str(asset.get('id') or '').strip(): asset for asset in catalog.get('assets', [])}
    requirements = _requirements(scene, assets)
    visual_sources = {}
    for identifier, binding in assets.items():
        if not isinstance(binding, dict) or binding.get('runtimeType') not in ('IMAGE', 'SPRITE'):
            continue
        asset = catalog_by_id.get(str(binding.get('assetId') or ''))
        if not asset or asset.get('type') not in ('image', 'sprite') or binding.get('assetId') != identifier:
            raise ValueError('Visual asset is missing from catalog: ' + identifier)
        output = 'res/' + str(binding.get('sourcePath') or '').replace('\\', '/')
        if output not in committed:
            raise ValueError('Converted visual is missing from transaction: ' + output)
        if binding.get('contentHash') != committed[output]:
            raise ValueError('Converted visual content hash mismatch: ' + identifier)
        remember(output)
        _, _, original_hash = remember(binding.get('originalSource') or asset.get('source'))
        conversion = binding.get('conversion')
        if not isinstance(conversion, dict) or conversion.get('converterVersion') != VISUAL_VERSION:
            raise ValueError('Visual converter version is stale; save/reconvert: ' + identifier)
        required = _compatible(requirements.get(identifier, ()))
        if identifier in requirements and not required:
            raise ValueError('Conflicting visual conversion profiles: ' + identifier)
        current = conversion.get('paletteProfile')
        if required and not _satisfies(current, required):
            raise ValueError('Visual palette conversion is stale: ' + identifier)
        profile = current if _satisfies(current, required) else required or current or _profile(binding.get('legacyPalette') or binding.get('palette'), binding['runtimeType'] == 'SPRITE')
        source = {'assetId': asset['id'], 'sha256': original_hash}
        if conversion.get('resize'):
            source['resize'] = conversion['resize']
        visual_sources[identifier] = (source, profile, asset['type'] == 'sprite')
    grouped = set()
    groups = bindings.get('paletteGroups') or {}
    if not isinstance(groups, dict):
        raise ValueError('Invalid palette group bindings')
    for key, group in groups.items():
        if not isinstance(group, dict):
            raise ValueError('Invalid palette group: ' + key)
        identifier = group.get('id', key)
        members = list(dict.fromkeys(group.get('members', [])))
        if not members or any(member not in visual_sources for member in members):
            raise ValueError('Palette group has missing visual members: ' + key)
        if any(assets[member].get('paletteGroup') != identifier for member in members):
            raise ValueError('Palette group member binding is stale: ' + key)
        grouped.update(members)
        document = {'converterVersion': VISUAL_VERSION,
                    'paletteProfile': group.get('profile') or assets[members[0]]['conversion'].get('paletteProfile') or 'general',
                    'reserveTransparent': bool(group.get('reserveTransparent')), 'paletteGroup': identifier,
                    'sources': [visual_sources[member][0] for member in members]}
        expected = group.get('inputHash')
        if any(assets[member]['conversion'].get('inputHash') != expected for member in members) or not _input_hash_matches(document, expected):
            raise ValueError('Palette group source changed; requantize the group: ' + key)
    for identifier, (source, profile, transparent) in visual_sources.items():
        if identifier in grouped:
            continue
        if assets[identifier].get('paletteGroup'):
            raise ValueError('Missing palette group: ' + identifier)
        document = {'converterVersion': VISUAL_VERSION, 'paletteProfile': profile,
                    'reserveTransparent': transparent, 'paletteGroup': None, 'sources': [source]}
        if not _input_hash_matches(document, assets[identifier]['conversion'].get('inputHash')):
            raise ValueError('Visual source changed; save/reconvert the Novel project: ' + identifier)
    recheck_editor_freshness(root, snapshot)
    return snapshot


def recheck_editor_freshness(project, snapshot):
    root = Path(project).resolve()
    for relative, expected in snapshot.items():
        target, _ = _path(root, relative)
        if _file_hash(target) != expected:
            raise ValueError('Project changed during build: ' + relative)
