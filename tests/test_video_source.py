"""Exercise the Sub CPU's asynchronous optical cache without an emulator/BIOS."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VideoSourceTests(unittest.TestCase):
    def test_asynchronous_source_vectors(self):
        with tempfile.TemporaryDirectory(prefix='mcd-video-source-') as temporary:
            output = Path(temporary)
            (output / 'types.h').write_text(
                '#include <stdint.h>\n#include <stdbool.h>\n'
                'typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;\n',
                encoding='utf-8')
            executable = output / 'video_source_vectors.exe'
            subprocess.run([
                os.environ.get('HOST_CC', 'gcc'), '-std=gnu11', '-O2',
                '-Wall', '-Wextra', '-Werror', '-DMCD_VIDEO_SOURCE_HOST_TEST',
                '-Iinclude', '-Itests', '-I' + str(output),
                'tests/video_source_vectors.c', 'src/sub/video_source.c',
                '-o', str(executable),
            ], cwd=ROOT, check=True)
            # Fresh processes also prove quarantine is not cleared by a reset
            # helper that does not exist on the real Sub CPU.
            for scenario in (
                    'open-prefetch', 'cross-bank', 'overlap-eviction',
                    'validation', 'rounded-tail', 'close-prefetch',
                    'open-error', 'prefetch-error', 'timeout-wrap',
                    'workspace-cycle', 'workspace-prefetch', 'workspace-validation'):
                with self.subTest(scenario=scenario):
                    subprocess.run([str(executable), scenario], check=True)


if __name__ == '__main__':
    unittest.main()
