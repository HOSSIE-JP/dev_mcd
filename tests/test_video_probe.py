"""Source-stream selection, display rotation and configured FFprobe coverage.

The integration fixture is generated locally and contains no external media or
BIOS. Pure metadata checks still run on hosts without FFmpeg and FFprobe.
"""
import copy
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import video_convert as video


def metadata(**overrides):
    stream = {'index': 3, 'codec_type': 'video', 'width': 128, 'height': 64,
              'duration': '0.25', 'disposition': {'attached_pic': 0}}
    stream.update(overrides)
    return {'streams': [stream], 'format': {'duration': '2.0'}}


class VideoMetadataTests(unittest.TestCase):
    def test_selects_actual_regular_video_index_after_cover_and_audio(self):
        source = metadata()
        source['streams'][:0] = [
            {'index': 0, 'codec_type': 'video', 'width': 512, 'height': 512,
             'disposition': {'attached_pic': 1}},
            {'index': 1, 'codec_type': 'audio', 'duration': '2.0'},
        ]
        source['streams'].append(dict(source['streams'][-1], index=7, width=320))
        original = copy.deepcopy(source)
        self.assertEqual(video.video_metadata(source), {
            'stream_index': 3, 'width': 128, 'height': 64,
            'total_samples': 4000, 'duration_seconds': 0.25, 'has_audio': True,
        })
        self.assertEqual(source, original, 'Probing must not mutate source metadata')

    def test_video_without_disposition_is_regular(self):
        source = metadata()
        del source['streams'][0]['disposition']
        info = video.video_metadata(source)
        self.assertEqual(info['stream_index'], 3)
        self.assertFalse(info['has_audio'])

    def test_cover_art_without_regular_video_is_rejected(self):
        with self.assertRaises(ValueError):
            video.video_metadata(metadata(disposition={'attached_pic': 1}))
        with self.assertRaises(ValueError):
            video.video_metadata({'streams': [{'codec_type': 'audio', 'index': 0}]})

    def test_display_matrix_rotation_controls_display_dimensions(self):
        for rotation, expected in ((90, (64, 128)), (-90, (64, 128)),
                                   (180, (128, 64)), (0, (128, 64))):
            with self.subTest(rotation=rotation):
                source = metadata(side_data_list=[
                    {'side_data_type': 'Display Matrix', 'rotation': rotation},
                ])
                info = video.video_metadata(source)
                self.assertEqual((info['width'], info['height']), expected)

    def test_rotation_tags_fallback_and_display_matrix_precedence(self):
        for rotation in ('90', '-90'):
            with self.subTest(rotation=rotation):
                info = video.video_metadata(metadata(tags={'rotate': rotation}))
                self.assertEqual((info['width'], info['height']), (64, 128))
        info = video.video_metadata(metadata(
            tags={'rotate': '90'},
            side_data_list=[{'side_data_type': 'Display Matrix', 'rotation': 0}],
        ))
        self.assertEqual((info['width'], info['height']), (128, 64))

    def test_duration_fallback_and_exact_two_hour_limit(self):
        for unavailable in (None, 'N/A', '0', '-1', 'invalid', 'NaN', 'Infinity'):
            with self.subTest(duration=unavailable):
                self.assertEqual(video.video_metadata(metadata(duration=unavailable))[
                    'total_samples'], 32000)
        self.assertEqual(video.video_metadata(metadata(duration='7200'))[
            'total_samples'], video.MAX_SAMPLES)
        self.assertEqual(video.video_metadata(metadata(duration='0.0000625'))[
            'total_samples'], 1)

    def test_invalid_durations_are_rejected_before_sample_truncation(self):
        for duration in ('0', '-1', '7200.00001', '7201', 'NaN', 'Infinity',
                         '-Infinity', 'invalid', '0.000001'):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                source = metadata(duration=duration)
                source['format']['duration'] = duration
                video.video_metadata(source)
        # A valid but excessive stream duration must not use a shorter fallback.
        with self.assertRaises(ValueError):
            video.video_metadata(metadata(duration='7200.00001'))
        source = metadata(duration='N/A')
        source['format'] = {}
        with self.assertRaises(ValueError):
            video.video_metadata(source)

    def test_invalid_video_dimensions_are_rejected(self):
        for dimension in ('width', 'height'):
            for value in (0, -1, None, 'N/A'):
                with self.subTest(dimension=dimension, value=value), self.assertRaises(ValueError):
                    video.video_metadata(metadata(**{dimension: value}))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'FFmpeg and FFprobe are required for real source conversion')
class VideoSourceConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='mcd-video-probe-test-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.ffmpeg, cls.ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        landscape = cls.directory / 'landscape source.mp4'
        cls.rotated = cls.directory / 'rotated portrait.mp4'
        subprocess.run([
            cls.ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=red:s=128x64:r=12:d=0.25', '-an', '-c:v', 'mpeg4',
            '-pix_fmt', 'yuv420p', str(landscape),
        ], check=True, capture_output=True, shell=False)
        rotated = subprocess.run([
            cls.ffmpeg, '-nostdin', '-v', 'error', '-display_rotation', '90',
            '-i', str(landscape), '-c', 'copy', str(cls.rotated),
        ], capture_output=True, text=True, shell=False)
        if rotated.returncode and 'Unrecognized option' in rotated.stderr:
            # Older FFmpeg versions set the same display matrix via metadata.
            subprocess.run([
                cls.ffmpeg, '-nostdin', '-v', 'error', '-i', str(landscape),
                '-c', 'copy', '-metadata:s:v:0', 'rotate=90', str(cls.rotated),
            ], check=True, capture_output=True, shell=False)
        else:
            rotated.check_returncode()
        result = subprocess.run([
            cls.ffprobe, '-v', 'error', '-show_streams', '-of', 'json',
            str(cls.rotated),
        ], check=True, capture_output=True, text=True, shell=False)
        streams = json.loads(result.stdout)['streams']
        if not any(abs(float(item.get('rotation', 0))) == 90
                   for item in streams[0].get('side_data_list', [])):
            raise AssertionError('FFmpeg fixture did not preserve display rotation')

    def assert_portrait_frame(self, output):
        movie = output.read_bytes()
        info = video.validate_video(movie)
        self.assertEqual((info['width'], info['height']), (160, 112))
        frame = video.FRAME.unpack_from(movie, video.SECTOR)
        tile_count, cell_count = frame[4:6]
        palette = np.array(struct.unpack_from('>16H', movie, video.SECTOR + 32))
        packed = np.frombuffer(movie, dtype=np.uint8, count=tile_count * 32,
                               offset=video.SECTOR + 64).reshape(tile_count, 32)
        tiles = np.empty((tile_count, 64), dtype=np.uint8)
        tiles[:, ::2], tiles[:, 1::2] = packed >> 4, packed & 15
        mapping = np.frombuffer(movie, dtype='>u2', count=cell_count,
                                offset=video.SECTOR + 64 + tile_count * 32)
        pixels = tiles[mapping].reshape(14, 20, 8, 8).transpose(0, 2, 1, 3).reshape(112, 160)
        ys, xs = np.nonzero(palette[pixels])
        self.assertGreater(len(xs), 0)
        # The 1:2 portrait fills height and occupies about 60 H40 pixels in width.
        # A lost display rotation produces a wide landscape stripe instead.
        self.assertGreaterEqual(ys.max() - ys.min() + 1, 108)
        self.assertGreaterEqual(xs.max() - xs.min() + 1, 56)
        self.assertLessEqual(xs.max() - xs.min() + 1, 64)
        self.assertLessEqual(abs((xs.min() + xs.max()) / 2 - 79.5), 1)
        self.assertEqual(info['audio_samples'], 4000)

    def test_rotated_mp4_keeps_portrait_aspect_in_encoded_mtv(self):
        output = self.directory / 'portrait.mtv'
        video.convert_video(self.rotated, output, 'small15', self.ffmpeg)
        self.assert_portrait_frame(output)

    def test_explicit_probe_path_with_spaces_is_passed_as_one_argument(self):
        output = self.directory / 'custom-probe.mtv'
        custom_probe = self.directory / 'probe tools' / ('custom ffprobe' + Path(self.ffprobe).suffix)
        custom_probe.parent.mkdir()
        custom_probe.write_bytes(b'configured probe placeholder')
        custom_probe.chmod(0o755)
        real_run, real_popen, real_which = subprocess.run, subprocess.Popen, shutil.which
        probe_calls, decode_calls = [], []

        def resolve(command, *args, **kwargs):
            return str(custom_probe) if str(command) == str(custom_probe) else real_which(command, *args, **kwargs)

        def run(command, *args, **kwargs):
            if str(command[0]) == str(custom_probe):
                probe_calls.append((list(command), dict(kwargs)))
                command = [self.ffprobe, *command[1:]]
            return real_run(command, *args, **kwargs)

        def popen(command, *args, **kwargs):
            if str(command[0]) == self.ffmpeg and 'rawvideo' in command:
                decode_calls.append((list(command), dict(kwargs)))
            return real_popen(command, *args, **kwargs)

        with patch.object(video.shutil, 'which', side_effect=resolve), \
             patch.object(video.subprocess, 'run', side_effect=run), \
             patch.object(video.subprocess, 'Popen', side_effect=popen):
            video.convert_video(self.rotated, output, 'small15', self.ffmpeg,
                                ffprobe=str(custom_probe))
        self.assertEqual(len(probe_calls), 1)
        self.assertEqual(probe_calls[0][0][0], str(custom_probe))
        self.assertFalse(probe_calls[0][1].get('shell', False))
        self.assertEqual(len(decode_calls), 1)
        arguments, options = decode_calls[0]
        self.assertEqual(arguments[arguments.index('-map') + 1], '0:0')
        self.assertFalse(options.get('shell', False))
        self.assert_portrait_frame(output)


if __name__ == '__main__':
    unittest.main()
