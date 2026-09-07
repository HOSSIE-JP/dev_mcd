"""Exact MTV1 agreement, streaming corruption and bounded target uploads.

Fixtures need no BIOS or external movie. Native checks compile the same format
and upload modules used on the target, without a replacement decoder.
"""
import ctypes as C
import os
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zlib
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from video_convert import PROFILES, RATE, encode_frame, encode_frames, demo_frames, validate_video

OK, ARGUMENT, FORMAT, BOUNDS, CRC, SEQUENCE, TRUNCATED = range(7)
U8P = C.POINTER(C.c_uint8)


class Header(C.Structure):
    _fields_ = [(name, C.c_uint16) for name in
                ('width', 'height', 'fps_num', 'fps_den', 'max_tiles')] + [
                (name, C.c_uint32) for name in
                ('frame_count', 'rate', 'total_samples', 'max_record')]


class Frame(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ('bytes', 'sequence', 'pts', 'audio_samples')] + [
                ('tile_count', C.c_uint16), ('map_count', C.c_uint16)] + [
                (name, U8P) for name in ('palette', 'tiles', 'map', 'audio')]


class Demux(C.Structure):
    _fields_ = [('scratch', U8P)] + [(name, C.c_uint32) for name in
                ('capacity', 'used', 'want', 'index', 'bytes_read', 'padding_left')] + [
                (name, C.c_uint) for name in
                ('ready', 'header_ready', 'eof', 'error', 'verify_payload_crc')] + [
                ('header', Header), ('frame', Frame)]


class Upload(C.Structure):
    _fields_ = [('kind', C.c_uint), ('destination', C.c_uint16),
                ('bytes', C.c_uint16), ('source', U8P)]


class UploadPlan(C.Structure):
    _fields_ = [('header', C.POINTER(Header)), ('frame', C.POINTER(Frame)),
                ('tile_bytes_done', C.c_uint32), ('row', C.c_uint16),
                ('bank', C.c_uint16), ('palette_done', C.c_uint),
                ('map_row', C.c_uint8 * 80)]


def records(movie):
    """Read framing only; C/Python acceptance is checked independently."""
    position = 2048
    for _ in range(struct.unpack_from('>I', movie, 16)[0]):
        size = struct.unpack_from('>I', movie, position + 4)[0]
        yield position, movie[position:position + size]
        position += size


class VideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='mcd-video-test-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        library = cls.directory / ('video.dll' if os.name == 'nt' else 'video.so')
        subprocess.run([
            os.environ.get('HOST_CC', 'gcc'), '-std=c11', '-shared', '-fPIC',
            '-Wall', '-Wextra', '-Werror', '-I' + str(ROOT / 'include'),
            str(ROOT / 'src/common/video_format.c'),
            str(ROOT / 'src/common/video_upload.c'), '-o', str(library),
        ], check=True)
        cls.native = C.CDLL(str(library))
        if os.name == 'nt':
            # Windows keeps loaded DLLs locked; unload before temporary cleanup.
            import _ctypes
            cls.addClassCleanup(_ctypes.FreeLibrary, cls.native._handle)
        signatures = {
            'parseHeader': ([C.c_void_p, C.c_uint32, C.POINTER(Header)], C.c_uint),
            'parseFrame': ([C.POINTER(Header), C.c_void_p, C.c_uint32,
                            C.c_uint32, C.c_uint, C.POINTER(Frame)], C.c_uint),
            'init': ([C.POINTER(Demux), U8P, C.c_uint32, C.c_uint], C.c_uint),
            'feed': ([C.POINTER(Demux), C.c_void_p, C.c_size_t], C.c_size_t),
            'release': ([C.POINTER(Demux)], C.c_uint),
            'finish': ([C.POINTER(Demux)], C.c_uint),
            'uploadBegin': ([C.POINTER(UploadPlan), C.POINTER(Header),
                             C.POINTER(Frame), C.c_uint], C.c_uint),
            'uploadNext': ([C.POINTER(UploadPlan), C.c_uint16, C.POINTER(Upload)], C.c_uint),
            'uploadComplete': ([C.POINTER(UploadPlan)], C.c_uint),
            'planeBRegister': ([C.POINTER(UploadPlan)], C.c_uint16),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(cls.native, 'MCDV_' + name)
            function.argtypes, function.restype = arguments, result
        cls.movies = {}
        for profile in ('medium12', 'full6'):
            output = cls.directory / (profile + '.mtv')
            encode_frames(demo_frames(profile, seconds=1), output, profile)
            cls.movies[profile] = output.read_bytes()

    def parse_header(self, data):
        header = Header()
        result = self.native.MCDV_parseHeader(bytes(data[:2048]), min(len(data), 2048), C.byref(header))
        return result, header

    def parse_frame(self, header, data, sequence=0):
        storage = C.create_string_buffer(bytes(data))
        frame = Frame()
        result = self.native.MCDV_parseFrame(C.byref(header), storage, len(data), sequence, 1, C.byref(frame))
        return result, frame, storage  # Retain storage while accessing frame pointers.

    def demux(self):
        scratch = (C.c_uint8 * 32768)()
        demux = Demux()
        self.assertEqual(self.native.MCDV_init(C.byref(demux), scratch, len(scratch), 1), OK)
        return demux, scratch

    def stream(self, data, chunk=997):
        demux, scratch = self.demux()
        position, count = 0, 0
        while position < len(data) and not demux.error:
            offered = bytes(data[position:position + chunk])
            used = self.native.MCDV_feed(C.byref(demux), offered, len(offered))
            position += used
            if demux.ready:
                count += 1
                self.assertEqual(self.native.MCDV_release(C.byref(demux)), OK)
            elif not used:
                self.assertTrue(demux.error, 'No progress without backpressure/error')
        return self.native.MCDV_finish(C.byref(demux)), count

    def test_generated_profiles_agree_with_native_decoder(self):
        for profile, movie in self.movies.items():
            with self.subTest(profile=profile):
                info = validate_video(movie)
                result, header = self.parse_header(movie)
                self.assertEqual(result, OK)
                width, height, numerator, denominator, limit = PROFILES[profile]
                self.assertEqual((header.width, header.height, header.fps_num, header.fps_den),
                                 (width, height, numerator, denominator))
                self.assertEqual(header.frame_count, info['frames'])
                self.assertEqual(header.total_samples, RATE)
                audio_samples = 0
                for sequence, (_, data) in enumerate(records(movie)):
                    result, frame, storage = self.parse_frame(header, data, sequence)
                    self.assertEqual(result, OK)
                    self.assertLessEqual(frame.tile_count, limit)
                    self.assertEqual(frame.map_count, width // 8 * (height // 8))
                    self.assertLessEqual(frame.bytes, 32768)
                    audio_samples += frame.audio_samples
                self.assertEqual(audio_samples, RATE)

    def test_arbitrary_chunks_backpressure_release_and_eof(self):
        for profile, movie in self.movies.items():
            for chunk in (7, 997, 8192):
                with self.subTest(profile=profile, chunk=chunk):
                    demux, scratch = self.demux()
                    self.assertEqual(self.native.MCDV_finish(C.byref(demux)), TRUNCATED)
                    self.assertEqual(self.native.MCDV_release(C.byref(demux)), ARGUMENT)
                    position, seen = 0, []
                    while position < len(movie):
                        offered = movie[position:position + chunk]
                        consumed = self.native.MCDV_feed(C.byref(demux), offered, len(offered))
                        self.assertGreater(consumed, 0)
                        self.assertLessEqual(consumed, len(offered))
                        position += consumed
                        self.assertEqual(demux.error, OK)
                        if demux.ready:
                            seen.append(demux.frame.sequence)
                            held, count_before = bytes(scratch[:demux.used]), demux.bytes_read
                            self.assertEqual(self.native.MCDV_feed(C.byref(demux), b'blocked', 7), 0)
                            self.assertEqual(bytes(scratch[:demux.used]), held)
                            self.assertEqual(demux.bytes_read, count_before)
                            self.assertEqual(self.native.MCDV_finish(C.byref(demux)), TRUNCATED)
                            self.assertEqual(self.native.MCDV_release(C.byref(demux)), OK)
                            self.assertEqual(self.native.MCDV_release(C.byref(demux)), ARGUMENT)
                    self.assertEqual(seen, list(range(demux.header.frame_count)))
                    self.assertEqual(demux.bytes_read, len(movie))
                    self.assertTrue(demux.eof)
                    self.assertEqual(self.native.MCDV_finish(C.byref(demux)), OK)

    def test_truncated_and_extra_stream_data_are_rejected(self):
        movie = self.movies['medium12']
        frame_start, final_frame = list(records(movie))[-1]
        final_end = frame_start + len(final_frame)
        self.assertLess(final_end, len(movie), 'Fixture must exercise terminal padding')
        for cut in (0, 7, 2047, 2048, 2087, final_end - 1, final_end, len(movie) - 1):
            with self.subTest(cut=cut):
                self.assertEqual(self.stream(movie[:cut])[0], TRUNCATED)
                with self.assertRaises(ValueError):
                    validate_video(movie[:cut])
        bad_padding = bytearray(movie)
        bad_padding[-1] = 1
        for corrupt in (bad_padding, movie + bytes(2048)):
            self.assertEqual(self.stream(corrupt)[0], FORMAT)
            with self.assertRaises(ValueError):
                validate_video(corrupt)

    def test_invalid_headers_rejected_in_native_and_python(self):
        cases = [
            (0, '>I', 0), (4, '>H', 2), (6, '>H', 64),
            (8, '>H', 0), (8, '>H', 328), (8, '>H', 223), (10, '>H', 232),
            (12, '>H', 0), (12, '>H', 31), (14, '>H', 0), (14, '>H', 3),
            (16, '>I', 0), (16, '>I', 0xFFFFFFFF), (20, '>I', 22050),
            (24, '>I', 0), (24, '>I', RATE * 7200 + 1),
            (28, '>I', 32), (28, '>I', 32770), (28, '>I', 32767),
            (32, '>H', 0), (32, '>H', 513), (34, '>H', 0),
            (36, '>B', 1), (2047, '>B', 1),
        ]
        for offset, format_string, value in cases:
            with self.subTest(offset=offset, value=value):
                corrupt = bytearray(self.movies['medium12'])
                struct.pack_into(format_string, corrupt, offset, value)
                struct.pack_into('>I', corrupt, 60, zlib.crc32(corrupt[:60]))
                self.assertNotEqual(self.parse_header(corrupt)[0], OK)
                with self.assertRaises(ValueError):
                    validate_video(corrupt)
        corrupt = bytearray(self.movies['medium12'])
        corrupt[60] ^= 1
        self.assertEqual(self.parse_header(corrupt)[0], CRC)
        self.assertEqual(self.stream(corrupt)[0], CRC)
        with self.assertRaises(ValueError):
            validate_video(corrupt)

    def test_crc_sequence_sizes_palette_map_and_pcm_rejected(self):
        movie = self.movies['medium12']
        _, original = next(records(movie))
        tile_count, cells = struct.unpack_from('>HH', original, 16)
        map_start = 64 + tile_count * 32
        cases = [
            ('magic', 0, '>I', 0, FORMAT), ('length', 4, '>I', len(original) + 2, FORMAT),
            ('sequence', 8, '>I', 1, SEQUENCE), ('timestamp', 12, '>I', 1, SEQUENCE),
            ('no tiles', 16, '>H', 0, BOUNDS), ('too many tiles', 16, '>H', 513, BOUNDS),
            ('map cells', 18, '>H', cells - 1, BOUNDS), ('audio size', 20, '>I', 0xFFFFFFFF, BOUNDS),
            ('reserved', 28, '>I', 1, FORMAT), ('transparent color', 32, '>H', 2, FORMAT),
            ('RGB333 color', 34, '>H', 1, FORMAT),
            ('map reference', map_start, '>H', tile_count, BOUNDS),
            ('PCM marker', map_start + cells * 2, '>B', 255, FORMAT),
            ('record padding', len(original) - 1, '>B', 1, FORMAT),
        ]
        _, header = self.parse_header(movie)
        self.assertEqual(struct.unpack_from('>I', original, 20)[0] % 2, 1)
        for name, offset, format_string, value, expected in cases:
            with self.subTest(case=name):
                corrupt = bytearray(movie)
                struct.pack_into(format_string, corrupt, 2048 + offset, value)
                if offset >= 32:  # Repair payload CRC to exercise semantic validation.
                    struct.pack_into('>I', corrupt, 2072, zlib.crc32(corrupt[2080:2048 + len(original)]))
                frame = corrupt[2048:2048 + len(original)]
                self.assertEqual(self.parse_frame(header, frame)[0], expected)
                self.assertNotEqual(self.stream(corrupt)[0], OK)
                with self.assertRaises(ValueError):
                    validate_video(corrupt)
        corrupt = bytearray(movie)
        corrupt[2048 + 64] ^= 1
        self.assertEqual(self.parse_frame(header, corrupt[2048:2048 + len(original)])[0], CRC)
        self.assertEqual(self.stream(corrupt)[0], CRC)
        with self.assertRaises(ValueError):
            validate_video(corrupt)
        self.assertEqual(self.parse_frame(header, original[:-1])[0], BOUNDS)

    def verify_upload(self, movie):
        result, header = self.parse_header(movie)
        self.assertEqual(result, OK)
        _, data = next(records(movie))
        result, frame, storage = self.parse_frame(header, data)
        self.assertEqual(result, OK)
        tiles = C.string_at(frame.tiles, frame.tile_count * 32)
        palette = C.string_at(frame.palette, 32)
        mapping = struct.unpack('>' + str(frame.map_count) + 'H', C.string_at(frame.map, frame.map_count * 2))
        for bank in (0, 1):
            with self.subTest(bank=bank, tiles=frame.tile_count):
                plan, transfer = UploadPlan(), Upload()
                self.assertEqual(self.native.MCDV_uploadBegin(C.byref(plan), C.byref(header), C.byref(frame), bank), OK)
                unchanged = bytes(plan)
                self.assertEqual(self.native.MCDV_uploadNext(C.byref(plan), 31, C.byref(transfer)), 0)
                self.assertEqual(bytes(plan), unchanged)
                vram, cram = bytearray(65536), bytearray(128)
                writes, blank_totals = [], []
                tile_base, map_base = 0x20 + bank * 0x4000, (0xA000, 0xE000)[bank]
                while not self.native.MCDV_uploadComplete(C.byref(plan)):
                    budget = 2048
                    while self.native.MCDV_uploadNext(C.byref(plan), budget, C.byref(transfer)):
                        self.assertGreater(transfer.bytes, 0)
                        self.assertLessEqual(transfer.bytes, budget)
                        self.assertEqual(transfer.bytes % 2, 0)
                        address, length = transfer.destination, transfer.bytes
                        contents = C.string_at(transfer.source, length)
                        if transfer.kind == 1:
                            self.assertTrue(tile_base <= address < address + length <= tile_base + 512 * 32
                                            or map_base <= address < address + length <= map_base + 4096)
                            vram[address:address + length] = contents
                        else:
                            self.assertEqual(transfer.kind, 2)
                            self.assertEqual((address, length), (bank * 32, 32))
                            cram[address:address + length] = contents
                        writes.append((transfer.kind, address, length))
                        budget -= length
                    self.assertLess(budget, 2048, 'Incomplete upload must make VBlank progress')
                    blank_totals.append(2048 - budget)
                    self.assertLess(len(blank_totals), 32)
                self.assertTrue(all(total <= 2048 for total in blank_totals))
                self.assertEqual(sum(blank_totals), len(tiles) + frame.map_count * 2 + 32)
                self.assertEqual(len({(kind, address) for kind, address, size in writes}), len(writes))
                self.assertEqual(vram[tile_base:tile_base + len(tiles)], tiles)
                self.assertEqual(cram[bank * 32:bank * 32 + 32], palette)
                columns, rows = header.width // 8, header.height // 8
                x, y = (40 - columns) // 2, (28 - rows) // 2
                for row in range(rows):
                    address = map_base + (y + row) * 128 + x * 2
                    displayed = struct.unpack_from('>' + str(columns) + 'H', vram, address)
                    for column, attribute in enumerate(displayed):
                        self.assertEqual((attribute >> 13) & 3, bank)
                        self.assertEqual(attribute & 0x9800, 0)  # No priority or flips.
                        tile_id, source_id = attribute & 0x7FF, mapping[row * columns + column]
                        self.assertEqual(vram[tile_id * 32:(tile_id + 1) * 32], tiles[source_id * 32:(source_id + 1) * 32])
                self.assertEqual(self.native.MCDV_planeBRegister(C.byref(plan)), (0x8405, 0x8407)[bank])
                self.assertEqual(self.native.MCDV_uploadNext(C.byref(plan), 2048, C.byref(transfer)), 0)

    def test_both_vram_banks_upload_with_bounded_vblank_budget(self):
        for movie in self.movies.values():
            self.verify_upload(movie)

    def test_maximum_dictionary_uploads_without_bank_overlap(self):
        rng = random.Random(512)
        image = Image.frombytes('RGB', (320, 224), rng.randbytes(320 * 224 * 3))
        output = self.directory / 'maximum.mtv'
        with patch.dict(PROFILES, {'test512': (320, 224, 6, 1, 512)}):
            encode_frames([image], output, 'test512', total_samples=2666)
        movie = output.read_bytes()
        validate_video(movie)
        _, frame = next(records(movie))
        self.assertEqual(struct.unpack_from('>H', frame, 16)[0], 512)
        self.verify_upload(movie)

    def test_random_images_respect_every_profile_dictionary_cap(self):
        rng = random.Random(4)
        for name, (width, height, numerator, denominator, limit) in PROFILES.items():
            with self.subTest(profile=name):
                image = Image.frombytes('RGB', (width, height), rng.randbytes(width * height * 3))
                palette, tiles, mapping = encode_frame(image, width, height, limit)
                self.assertEqual(len(palette), 32)
                self.assertEqual(len(tiles), limit * 32)
                self.assertEqual(len(mapping), width // 8 * (height // 8) * 2)
                references = struct.unpack('>' + str(len(mapping) // 2) + 'H', mapping)
                self.assertLess(max(references), limit)
                self.assertGreater(len(set(references)), 1)
                worst = 64 + len(tiles) + len(mapping) + (RATE * denominator + numerator - 1) // numerator
                self.assertLessEqual((worst + 1) & ~1, 32768)

    def test_partial_duration_and_rational_fps_exact_audio_timeline(self):
        for profile, total, count in (
            ('medium12', 1, 1), ('medium12', 1401, 2), ('medium12', 16001, 13),
            ('full75', 4267, 3), ('full75', 16000, 8),
        ):
            with self.subTest(profile=profile, samples=total):
                image = Image.new('RGB', (16, 16), '#e0a040')
                output = self.directory / 'duration.mtv'
                info = encode_frames([image] * count, output, profile, total_samples=total)
                movie = output.read_bytes()
                self.assertEqual(validate_video(movie)['audio_samples'], total)
                self.assertEqual(info['frames'], count)
                self.assertEqual(self.stream(movie), (OK, count))
                _, header = self.parse_header(movie)
                cursor = 0
                for sequence, (_, data) in enumerate(records(movie)):
                    result, frame, storage = self.parse_frame(header, data, sequence)
                    self.assertEqual(result, OK)
                    self.assertEqual(frame.pts, cursor)
                    self.assertGreater(frame.audio_samples, 0)
                    cursor += frame.audio_samples
                self.assertEqual(cursor, total)
                if profile == 'full75':
                    self.assertEqual((header.fps_num, header.fps_den), (15, 2))

    def test_pcm_extremes_and_short_audio_are_valid_rf5c164_samples(self):
        audio = self.directory / 'samples.s16le'
        audio.write_bytes(struct.pack('<5h', -32768, -1, 0, 1, 32767))
        output = self.directory / 'pcm.mtv'
        encode_frames([Image.new('RGB', (8, 8))], output, total_samples=9, audio_pcm16=audio)
        movie = output.read_bytes()
        validate_video(movie)
        _, header = self.parse_header(movie)
        _, data = next(records(movie))
        result, frame, storage = self.parse_frame(header, data)
        self.assertEqual(result, OK)
        self.assertEqual(C.string_at(frame.audio, frame.audio_samples), bytes([127, 0, 128, 128, 254, 128, 128, 128, 128]))

    def test_failed_conversion_preserves_existing_output(self):
        output = self.directory / 'preserve.mtv'
        image = Image.new('RGB', (8, 8))

        def broken_decoder():
            yield image
            raise ValueError('Decoder failed after emitting a frame')

        cases = [([], {}, ValueError), ([], {'profile': 'invalid'}, ValueError),
                 ([image], {'total_samples': 0}, ValueError),
                 ([image], {'total_samples': RATE * 7200 + 1}, ValueError),
                 ([image], {'total_samples': RATE}, ValueError),
                 ([image, object()], {}, AttributeError), (broken_decoder(), {}, ValueError)]
        for frames, arguments, exception in cases:
            with self.subTest(arguments=arguments, exception=exception.__name__):
                output.write_bytes(b'previous movie')
                with self.assertRaises(exception):
                    encode_frames(frames, output, **arguments)
                self.assertEqual(output.read_bytes(), b'previous movie')


if __name__ == '__main__':
    unittest.main()
