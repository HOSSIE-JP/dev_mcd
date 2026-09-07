#!/usr/bin/env python3
"""Exercise bridge_demo pixels and input in Genesis Plus GX with a local BIOS.

Only the demo's 16-byte telemetry block is read. Reports and captures contain
game data only; no BIOS image, save state, or firmware snapshot is exported.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys

from smoke import Emulator, ROOT


class BridgeEmulator(Emulator):
    def telemetry(self):
        pointer = self.lib.retro_get_memory_data(2)
        if not pointer or self.lib.retro_get_memory_size(2) < 0xF010:
            return {}
        data = C.string_at(pointer + 0xF000, 16)
        if sys.byteorder == 'little':
            data = b''.join(data[i:i + 2][::-1] for i in range(0, 16, 2))
        values = struct.unpack('>II4H', data)
        return dict(zip(('magic', 'frame', 'error', 'io', 'fade', 'pressed'), values)) if values[0] == 0x4D434442 else {}


def region(picture, left=16, top=176, right=304, bottom=216):
    width, height, rgb = picture
    assert (width, height) == (320, 224), 'Expected H40 NTSC game image'
    return b''.join(rgb[(y * width + left) * 3:(y * width + right) * 3] for y in range(top, bottom))


def run(args):
    system = ROOT / '.local/smoke/bridge-system'
    system.mkdir(parents=True, exist_ok=True)
    bios = system / 'bios_CD_J.bin'
    if args.bios.resolve() != bios.resolve():
        shutil.copyfile(args.bios, bios)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'emulator': 'Genesis Plus GX', 'hardware_tested': False, 'checks': {},
              'core_commit': json.loads((ROOT / 'toolchain.lock.json').read_text())['genesis-plus-gx']['commit'],
              'disc_sha256': hashlib.sha256(args.disc.with_suffix('.iso').read_bytes()).hexdigest()}
    emu = BridgeEmulator(args.core, system, args.output, args.disc)
    try:
        for frame in range(args.frames):
            telemetry = emu.run(1, [3] if frame % 240 in range(180, 188) else [])
            if telemetry.get('frame', 0) > 2:
                break
        else:
            raise AssertionError('Bridge demo did not boot within the frame budget')
        report['boot_frames'] = frame + 1
        emu.run(30)
        assert emu.telemetry()['error'] == 0, 'Initial tile upload failed'
        ready = emu.capture('ready')
        background = region(ready)
        assert len(set(background)) > 2 and sum(background) > 0, 'Checkerboard is missing'
        report['checks']['native_boot_and_tiles'] = True

        emu.run(3, [7])  # Right: move six pixels, avoiding the tile repeat period.
        emu.run(2)
        right = emu.capture('scroll-right')
        assert region(right) != background, 'Horizontal scroll did not change the background'
        emu.run(3, [5])  # Down.
        emu.run(2)
        scrolled = emu.capture('scroll-down')
        assert region(scrolled) != region(right), 'Vertical scroll did not change the background'
        report['checks']['horizontal_and_vertical_scroll'] = True

        emu.run(2, [1])  # Genesis A = libretro Y.
        emu.run(18)
        mid = emu.capture('fade-midpoint')
        assert emu.telemetry()['fade'] == 1, 'Fade did not remain asynchronous'
        emu.run(50)
        dark = emu.capture('fade-out')
        assert sum(region(scrolled)) > sum(region(mid)) > sum(region(dark)), 'Fade pixels are not progressively darker'
        assert not any(region(dark)) and emu.telemetry()['fade'] == 0, 'Fade did not reach black'
        # Text pixels remain fixed while Plane B scrolls and its own palette fades.
        white = []
        width, _, pixels = dark
        for y in range(16, 24):
            for x in range(16, 272):
                offset = (y * width + x) * 3
                if min(pixels[offset:offset + 3]) > 200:
                    white.append(offset)
        assert len(white) > 50, 'Title text disappeared during the background fade'
        for picture in (ready, right, scrolled, mid):
            assert all(picture[2][offset:offset + 3] == pixels[offset:offset + 3] for offset in white), 'Plane A title moved or changed during Plane B updates'
        report['checks']['palette_range_fade_and_fixed_text'] = True

        emu.press(0)  # B restores the background.
        emu.run(40)
        restored = emu.capture('fade-in')
        assert region(restored) == region(scrolled), 'Fade in did not restore the palette'
        report['checks']['fade_in_restores_colors'] = True
        emu.run(2, [1])
        emu.run(5)
        assert emu.telemetry()['fade'] == 1
        emu.run(2, [8])  # C changes text color and cancels any active palette fade.
        emu.run(3)
        colored = emu.capture('text-color')
        assert emu.telemetry()['fade'] == 0, 'Immediate palette change did not cancel the fade'
        assert any(colored[2][offset:offset + 3] != pixels[offset:offset + 3] for offset in white), 'Text color did not change'
        report['checks']['text_color_and_fade_cancel'] = True

        emu.run(80, [1])  # A held beyond 45 frames must not continually restart the fade.
        emu.run(2)
        assert emu.telemetry()['fade'] == 0 and not any(region(emu.capture('held-input'))), 'Held input retriggered the fade'
        report['checks']['pressed_input_is_an_edge'] = True

        before = emu.telemetry()
        emu.run(2, [3, 0, 7])  # Start a CD read, fade in, and scroll together.
        overlap = False
        for elapsed in range(600):
            telemetry = emu.run(1, [7])
            if telemetry['io'] == before['io'] and telemetry['fade']:
                overlap = True
            if telemetry['io'] > before['io']:
                break
        else:
            raise AssertionError('Asynchronous CD image load did not complete')
        assert telemetry['io'] == before['io'] + 1 and telemetry['error'] == 0, 'CD read reported an error'
        assert overlap and telemetry['frame'] > before['frame'], 'Did not observe fade/frame progress while CD read was pending'
        emu.run(60)
        emu.capture('cd-complete')
        report['checks']['cd_read_while_scrolling_and_fading'] = {'observed_overlap': overlap, 'frames_until_complete': elapsed + 3}
        report['final_telemetry'] = emu.telemetry()
        report['status'] = 'pass'
    except Exception as error:
        report['status'] = 'fail'
        report['error'] = str(error)
        report['final_telemetry'] = emu.telemetry()
        if emu.telemetry():
            emu.capture('failure')
    finally:
        emu.close()
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'pass' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bios', required=True, type=Path)
    parser.add_argument('--core', type=Path, default=ROOT / '.deps/genesis-plus-gx/genesis_plus_gx_libretro.so')
    parser.add_argument('--disc', type=Path, default=ROOT / 'dist/bridge_demo.cue')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/bridge-smoke')
    parser.add_argument('--frames', type=int, default=2400, help='Maximum frames allowed to reach the demo')
    args = parser.parse_args()
    if not args.bios.is_file() or args.bios.stat().st_size != 131072:
        parser.error('Provide your own 128 KiB Japanese Mega CD BIOS')
    for source in (args.core, args.disc, args.disc.with_suffix('.iso')):
        if not source.is_file():
            parser.error('Required input does not exist: ' + str(source))
    if args.frames < 1:
        parser.error('--frames must be positive')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
