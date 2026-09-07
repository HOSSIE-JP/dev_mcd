#!/usr/bin/env python3
"""Build one canonical MD Novel project as a self-contained Mega-CD disc.

No generated files are written to dev_mcd or to the project's MD source tree.
artifacts.json is published only after conversion, link and disc checks succeed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import wave
import zlib

import disc
from editor_project import prepare_project, file_hash
from novel_convert import convert
from editor_freshness import validate_editor_freshness, recheck_editor_freshness

ROOT = Path(__file__).resolve().parents[1]


def build(project, output, font, cross=None, ffmpeg='ffmpeg', ffprobe=None):
    project, output, font = project.resolve(), output.resolve(), font.resolve()
    if not output.is_relative_to(project / 'out') or output == project / 'out':
        raise ValueError('Output must be a dedicated directory inside project/out')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty; choose a new build attempt directory')
    if not font.is_file():
        raise ValueError('Font file is missing: ' + str(font))
    freshness = validate_editor_freshness(project)
    megadev = ROOT / '.deps/megadev'
    if not (megadev / 'cfg/module_mmd.ld').is_file():
        raise ValueError('Run dev_mcd setup first: pinned Megadev dependency is missing')
    lock = json.loads((ROOT / 'toolchain.lock.json').read_text())
    head = subprocess.check_output(['git', '-C', str(megadev), 'rev-parse', 'HEAD'], text=True).strip()
    if head != lock['megadev']['commit']:
        raise ValueError('Megadev differs from toolchain.lock.json')
    if cross is None:
        portable = ROOT / '.deps/toolchain/bin/m68k-elf-gcc'
        cross = str(portable).removesuffix('gcc') if portable.is_file() or portable.with_suffix('.exe').is_file() else 'm68k-linux-gnu-'
    if not shutil.which(cross + 'gcc'):
        raise ValueError('Cross compiler missing: ' + cross + 'gcc')
    # A fixed ASCII runtime directory avoids injecting user paths into make syntax.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mcd-novel-') as temp:
        work = Path(temp)
        source, runtime, data, publish = (work / name for name in ('source', 'runtime', 'data', 'publish'))
        info = prepare_project(project, source)
        for relative, expected in freshness.items():
            if relative in info['sourceHashes'] and info['sourceHashes'][relative] != expected:
                raise ValueError('Project changed before conversion: ' + relative)
        info['sourceHashes'].update(freshness)
        font_hash = file_hash(font)
        convert(source, font, data, ffmpeg=ffmpeg, ffprobe=ffprobe)
        manifest = json.loads((data / 'manifest.json').read_text())
        manifest.update(title=info['title'], sourceHashes=info['sourceHashes'], fontSha256=font_hash)
        manifest.pop('source_repositories', None)
        manifest['conversion_notes'] = info['warnings']
        manifest['conversion_notes'].extend([
            'MCD portrait cache: four slots, at most 64x128 pixels, two animations with two frames each.',
            'Background VRAM budget: 511 dictionary tiles alongside actors; 896 in fullScreenBg scenes.',
            'Video uses the MTV1 format from the 2026-09-07 video study; throughput requires emulator/hardware validation.'
        ])
        runtime.mkdir()
        for folder in ('include', 'src', 'tools'):
            shutil.copytree(ROOT / folder, runtime / folder, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copyfile(ROOT / 'Makefile', runtime / 'Makefile')
        (runtime / 'examples/ishinoura_ep01').mkdir(parents=True)
        shutil.copyfile(ROOT / 'examples/ishinoura_ep01/main.c', runtime / 'examples/ishinoura_ep01/main.c')
        # Copy the dependency into a stable relative location through a symlink;
        # Windows without symlink support gets a local copy of the small source tree.
        (runtime / '.deps').mkdir()
        try:
            (runtime / '.deps/megadev').symlink_to(megadev, target_is_directory=True)
        except OSError:
            shutil.copytree(megadev, runtime / '.deps/megadev', ignore=shutil.ignore_patterns('.git'))
        # Make expands executable variables inside shell recipes. Keep those
        # variables as basenames and pass directory names through PATH instead.
        cross_tool = Path(shutil.which(cross + 'gcc')).resolve()
        python_tool = Path(sys.executable).resolve()
        build_env = dict(os.environ)
        build_env['PATH'] = os.pathsep.join((str(cross_tool.parent), str(python_tool.parent),
                                            build_env.get('PATH', '')))
        cross_name = Path(cross).name
        subprocess.run(['make', 'CROSS=' + cross_name, 'PYTHON=' + python_tool.name,
                        'build/novel/IPX.MMD', 'build/boot.bin'], cwd=runtime, env=build_env, check=True)
        pack = (data / 'novel.pak').read_bytes()
        if hashlib.sha256(pack).hexdigest() != manifest['pack_sha256']:
            raise ValueError('Generated pack hash mismatch')
        image = disc.make_iso((runtime / 'build/boot.bin').read_bytes(), {
            'IPX.MMD': (runtime / 'build/novel/IPX.MMD').read_bytes(), 'NOVEL.PAK': pack})
        publish.mkdir()
        (publish / 'novel.iso').write_bytes(image)
        cue = ['FILE "novel.iso" BINARY', '  TRACK 01 MODE1/2048', '    INDEX 01 00:00:00']
        artifacts = ['novel.iso', 'novel.cue', 'conversion.json']
        for track in manifest['tracks']:
            raw = zlib.decompress((data / 'cdda' / track['file']).read_bytes())
            if hashlib.sha256(raw).hexdigest() != track['sha256']:
                raise ValueError('CD-DA track hash mismatch')
            name = 'track%02d.wav' % track['track']
            with wave.open(str(publish / name), 'wb') as audio:
                audio.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0' * (44100 * 4 * 2) + raw)
            artifacts.append(name)
            cue.extend(['FILE "%s" WAVE' % name, '  TRACK %02d AUDIO' % track['track'],
                        '    INDEX 00 00:00:00', '    INDEX 01 00:02:00'])
        (publish / 'novel.cue').write_text('\n'.join(cue) + '\n', 'ascii')
        (publish / 'conversion.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        for relative, expected in info['sourceHashes'].items():
            if file_hash(project / relative) != expected:
                raise ValueError('Project changed during build: ' + relative)
        if file_hash(font) != font_hash:
            raise ValueError('Font changed during build')
        recheck_editor_freshness(project, freshness)
        result = {'schemaVersion': 1, 'targetMedia': 'cd', 'isoPath': 'novel.iso', 'cuePath': 'novel.cue',
                  'artifacts': [{'path': name, 'bytes': (publish / name).stat().st_size,
                                 'sha256': file_hash(publish / name)} for name in artifacts],
                  'warnings': manifest['conversion_notes']}
        (publish / 'artifacts.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        # Publish within the output filesystem; artifacts.json is copied last.
        output.mkdir(exist_ok=True)
        for name in artifacts:
            shutil.copyfile(publish / name, output / name)
        shutil.copyfile(publish / 'artifacts.json', output / 'artifacts.json')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--font', required=True, type=Path)
    parser.add_argument('--cross')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--ffprobe', help='ffprobe executable; defaults to alongside ffmpeg or PATH')
    args = parser.parse_args()
    try:
        result = build(args.project, args.output, args.font, args.cross, args.ffmpeg, args.ffprobe)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('Mega-CD build failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
