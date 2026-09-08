"""RGB333 palette assignment and screen-anchored MTV1 ordered dithering."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from video_convert import encode_frame, encode_frames, processing_options, validate_video, FRAME, SECTOR, RATE


def decode_frame(palette, tiles, mapping, width, height):
    colors = np.array(struct.unpack('>16H', palette), dtype=np.uint16)
    colors = np.stack(((colors >> 1) & 7, (colors >> 5) & 7, (colors >> 9) & 7), axis=1) * (255 / 7)
    packed = np.frombuffer(tiles, dtype=np.uint8).reshape(-1, 32)
    indices = np.empty((len(packed), 64), dtype=np.uint8)
    indices[:, ::2] = packed >> 4
    indices[:, 1::2] = packed & 15
    mapped = indices[np.frombuffer(mapping, dtype='>u2')]
    pixels = mapped.reshape(height//8, width//8, 8, 8).transpose(0, 2, 1, 3).reshape(height, width)
    return colors[pixels]


def grayscale_ramp(width=256, height=64):
    ramp = np.broadcast_to(np.linspace(0, 255, width, dtype=np.uint8)[None, :, None], (height, width, 3)).copy()
    return Image.fromarray(ramp)


class VideoDitherTests(unittest.TestCase):
    def test_default_none_and_zero_strength_keep_identical_output(self):
        image = grayscale_ramp()
        default = encode_frame(image, 256, 64, 64, pre_fitted=True)
        self.assertEqual(default, encode_frame(image, 256, 64, 64, True, 'none', 1))
        self.assertEqual(default, encode_frame(image, 256, 64, 64, True, 'ordered', 0))
        metadata = dict(width=256, height=64, total_samples=RATE)
        recipe = processing_options({}, metadata)
        self.assertEqual((recipe['dither'], recipe['ditherStrength']), ('none', 0.5))

    def test_reassignment_reduces_error_against_the_actual_cram_palette(self):
        # No dictionary replacement: isolate the incorrect RGB888 -> RGB333
        # index carry-over that used to add error before tile compression.
        image = Image.fromarray(np.random.default_rng(6).integers(0, 256, (64, 64, 3), dtype=np.uint8))
        encoded = encode_frame(image, 64, 64, 64, pre_fitted=True)
        actual = decode_frame(*encoded, 64, 64)
        quantized = image.quantize(colors=15, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        raw = np.array(quantized.getpalette()[:45], dtype=np.int32).reshape(15, 3)
        old_palette = ((raw * 7 + 127)//255) * (255/7)
        previous = old_palette[np.asarray(quantized)]
        original = np.asarray(image, dtype=np.float64)
        new_error = np.mean((actual-original)**2)
        old_error = np.mean((previous-original)**2)
        self.assertLess(new_error, old_error * 0.99)
        self.assertTrue(np.all(np.sum((actual-original)**2, axis=2) <= np.sum((previous-original)**2, axis=2) + 1e-8))

    def test_ordered_reduces_gradient_banding_at_a_small_spatial_scale(self):
        image = grayscale_ramp()
        original = np.asarray(image, dtype=np.float64)
        normal = decode_frame(*encode_frame(image, 256, 64, 64, True), 256, 64)
        ordered = decode_frame(*encode_frame(image, 256, 64, 64, True, 'ordered', 0.5), 256, 64)
        def local_mean(frame):
            return frame.reshape(16, 4, 64, 4, 3).mean(axis=(1, 3))
        reference = local_mean(original)
        # Dither intentionally trades per-pixel noise for smoother local tone.
        self.assertLess(np.mean((local_mean(ordered)-reference)**2), np.mean((local_mean(normal)-reference)**2)*0.8)
        self.assertFalse(np.array_equal(normal, ordered))

    def test_pattern_is_deterministic_and_black_bars_stay_black_under_tile_cap(self):
        image = grayscale_ramp(64, 64)
        image.paste((0, 0, 0), (0, 0, 64, 8))
        image.paste((0, 0, 0), (0, 56, 64, 64))
        for strength in (0, 0.5, 1):
            with self.subTest(strength=strength):
                first = encode_frame(image, 64, 64, 8, True, 'ordered', strength)
                self.assertEqual(first, encode_frame(image, 64, 64, 8, True, 'ordered', strength))
                decoded = decode_frame(*first, 64, 64)
                self.assertTrue(np.all(decoded[:8] == 0))
                self.assertTrue(np.all(decoded[56:] == 0))
                self.assertLessEqual(len(first[1]), 8*32)
                self.assertLess(max(struct.unpack('>64H', first[2])), 8)
                self.assertTrue(all(color & ~0xEEE == 0 for color in struct.unpack('>16H', first[0])))

    def test_invalid_options_are_rejected_even_for_direct_encoder_calls(self):
        metadata = dict(width=8, height=8, total_samples=RATE)
        for options in [dict(dither='random'), dict(dither=True), dict(dither=None), dict(ditherStrength=True),
                        dict(ditherStrength=-0.01), dict(ditherStrength=1.01), dict(ditherStrength='0.5'),
                        dict(ditherStrength=float('nan')), dict(ditherStrength=float('inf'))]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    processing_options(options, metadata)
                with self.assertRaises(ValueError):
                    encode_frame(Image.new('RGB', (8, 8)), 8, 8, 1, True,
                                 options.get('dither', 'none'), options.get('ditherStrength', 0.5))

    def test_streamed_frames_retain_mtv1_abi_and_propagate_options(self):
        image = grayscale_ramp(160, 112)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'ordered.mtv'
            report = encode_frames([image]*3, output, 'small15', total_samples=3200,
                                   pre_fitted=True, dither='ordered', dither_strength=0.5)
            movie = output.read_bytes()
            info = validate_video(movie)
            self.assertEqual(info['frames'], 3)
            self.assertEqual((report['dither'], report['ditherStrength']), ('ordered', 0.5))
            expected = b''.join(encode_frame(image, 160, 112, 96, True, 'ordered', 0.5))
            offset = SECTOR
            for sequence in range(3):
                _, size, number, _, tiles, cells, _, _, _ = FRAME.unpack_from(movie, offset)
                self.assertEqual(number, sequence)
                self.assertEqual(movie[offset+32:offset+64+tiles*32+cells*2], expected)
                offset += size


if __name__ == '__main__':
    unittest.main()
