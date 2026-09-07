"""Configured probe executables reach every layer of the editor build path."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_editor_novel
import novel_convert


class ConversionReached(Exception):
    pass


class VideoToolchainTests(unittest.TestCase):
    def test_build_cli_passes_explicit_probe_as_one_argument(self):
        args = ['build_editor_novel.py', '--project', '/project dir', '--output', '/project dir/out/cd',
                '--font', '/fonts/font.ttf', '--ffmpeg', '/video tools/ffmpeg',
                '--ffprobe', '/probe tools/ffprobe $(literal)']
        with patch.object(sys, 'argv', args), patch.object(build_editor_novel, 'build', return_value={}) as build:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_editor_novel.main(), 0)
        self.assertEqual(build.call_args.args[-2:], ('/video tools/ffmpeg', '/probe tools/ffprobe $(literal)'))

    def test_editor_build_passes_probe_to_novel_conversion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, sdk = root / 'project', root / 'sdk'
            project.mkdir()
            dependency = sdk / '.deps/megadev/cfg'
            dependency.mkdir(parents=True)
            (dependency / 'module_mmd.ld').write_text('test dependency')
            (sdk / 'toolchain.lock.json').write_text(json.dumps({'megadev': {'commit': 'test-pin'}}))
            font = root / 'font.ttf'
            font.write_bytes(b'font checksum input')
            with patch.object(build_editor_novel, 'ROOT', sdk), \
                 patch.object(build_editor_novel.subprocess, 'check_output', return_value='test-pin\n'), \
                 patch.object(build_editor_novel.shutil, 'which', return_value='/compiler/gcc'), \
                 patch.object(build_editor_novel, 'validate_editor_freshness', return_value={}), \
                 patch.object(build_editor_novel, 'prepare_project', return_value={'sourceHashes': {}}), \
                 patch.object(build_editor_novel, 'convert', side_effect=ConversionReached) as convert:
                with self.assertRaises(ConversionReached):
                    build_editor_novel.build(project, project / 'out/cd', font,
                                             cross='m68k-test-', ffmpeg='/ffmpeg path', ffprobe='/probe path')
                self.assertEqual(convert.call_args.kwargs, {'ffmpeg': '/ffmpeg path', 'ffprobe': '/probe path'})

    def test_novel_conversion_passes_probe_to_video_conversion(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            (source / 'assets').mkdir(parents=True)
            (source / 'assets/pce-vn-scenes.json').write_text(json.dumps({
                'version': 2, 'startScene': 's', 'scenes': [{'id': 's', 'commands': [
                    {'type': 'video', 'assetId': 'v', 'skippable': True}]}]}))
            (source / 'assets/pce-assets.json').write_text(json.dumps({'assets': [
                {'id': 'v', 'type': 'video', 'source': 'assets/movie.mp4', 'options': {'profile': 'full6'}}]}))
            font = Mock()
            font.getmetrics.return_value = (12, 4)
            with patch.object(novel_convert.ImageFont, 'truetype', return_value=font), \
                 patch.object(novel_convert.ImageDraw, 'Draw', return_value=Mock()), \
                 patch('video_convert.convert_video', side_effect=ConversionReached) as convert:
                with self.assertRaises(ConversionReached):
                    novel_convert.convert(source, Path('font.ttf'), Path(temporary) / 'output',
                                          ffmpeg='/ffmpeg path', ffprobe='/probe path')
                self.assertEqual(convert.call_args.kwargs, {
                    'profile': 'full6', 'ffmpeg': '/ffmpeg path', 'ffprobe': '/probe path', 'options': None})


if __name__ == '__main__':
    unittest.main()
