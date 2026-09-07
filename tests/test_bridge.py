"""Boundary and frame/IPC regression tests for the real bridge implementation."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BridgeTests(unittest.TestCase):
    def test_bridge_ports_on_host(self):
        with tempfile.TemporaryDirectory(prefix='mcd-bridge-') as temporary:
            output = Path(temporary)
            (output / 'types.h').write_text(
                '#include <stdint.h>\n#include <stdbool.h>\n'
                'typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;\n'
                'typedef int16_t s16; typedef int32_t s32;\n', encoding='utf-8')
            (output / 'font.h').write_text(
                'static const unsigned short mcd_font[] = {0};\n', encoding='utf-8')
            executable = output / 'bridge_vectors.exe'
            subprocess.run([
                os.environ.get('HOST_CC', 'gcc'), '-std=gnu11', '-O2',
                '-Wall', '-Wextra', '-Werror', '-DMCD_BRIDGE_HOST_TEST',
                '-Iinclude', '-Itests', '-I' + str(output),
                'tests/bridge_vectors.c', 'src/main/bridge.c', '-o', str(executable),
            ], cwd=ROOT, check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
