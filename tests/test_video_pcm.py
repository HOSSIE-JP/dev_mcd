"""Native PCM ring boundaries, wraparound, marker rejection and underrun recovery."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VideoPCMTests(unittest.TestCase):
    def test_pcm_ring_on_host(self):
        with tempfile.TemporaryDirectory(prefix='mcd-video-pcm-') as temporary:
            output = Path(temporary)
            (output / 'types.h').write_text(
                '#include <stdint.h>\n#include <stdbool.h>\n'
                'typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;\n',
                encoding='utf-8')
            executable = output / 'video_pcm_vectors.exe'
            subprocess.run([
                os.environ.get('HOST_CC', 'gcc'), '-std=gnu11', '-O2',
                '-Wall', '-Wextra', '-Werror', '-DMCD_VIDEO_PCM_HOST_TEST',
                '-Iinclude', '-Itests', '-I' + str(output),
                'tests/video_pcm_vectors.c', 'src/sub/video_stream.c', '-o', str(executable),
            ], cwd=ROOT, check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
