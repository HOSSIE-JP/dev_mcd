"""Prepare an original procedural movie, or use an existing MTV1/source video."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import math
import struct
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from video_convert import encode_frames, demo_frames, convert_video, validate_video

ROOT = Path(__file__).resolve().parents[2]


def prepare(source=None, profile='medium12'):
    out = ROOT / 'build/video'
    out.mkdir(parents=True, exist_ok=True)
    movie = out / 'NOVEL.PAK'
    if source:
        if source.suffix.lower() == '.mtv':
            raw = source.read_bytes()
            info = validate_video(raw)
            movie.write_bytes(raw)
        else:
            info = convert_video(source, movie, profile)
    else:
        # 440Hz beep aligned with frame changes; no external audio dependency.
        with tempfile.TemporaryDirectory(prefix='mtv-demo-audio-') as temp:
            audio = Path(temp) / 'tone.s16le'
            samples = [int(7000 * math.sin(2 * math.pi * 440 * i / 16000)) if i % 8000 < 3000 else 0 for i in range(48000)]
            audio.write_bytes(struct.pack('<%dh' % len(samples), *samples))
            info = encode_frames(demo_frames(profile), movie, profile, 48000, audio)
    (out / 'video_demo_config.h').write_text('#define VIDEO_DEMO_BYTES %dUL\n' % movie.stat().st_size)
    (out / 'manifest.json').write_text(json.dumps(info, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path)
    parser.add_argument('--profile', default='medium12')
    args = parser.parse_args()
    prepare(args.source, args.profile)
