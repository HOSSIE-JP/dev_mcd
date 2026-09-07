#!/usr/bin/env python3
"""Run the real MTV1 demo in Genesis Plus GX using a user-owned BIOS.

Separate emulator sessions check audio EOF, silent EOF and controller skip.
Only the demo's 30-byte telemetry is read from RAM. Outputs contain game
screenshots, emitted audio and a JSON report; no BIOS or save states are saved.
"""
import argparse
import array
import ctypes as C
import hashlib
import json
import shutil
import struct
import sys
import time
from pathlib import Path
from smoke import Emulator, ROOT

TRACE = struct.Struct('>IHHIIIIIH')
TRACE_NAMES = ('magic', 'stage', 'error', 'frames_shown', 'frames_dropped',
               'cache_reads', 'rebuffer_count', 'audio_samples_played', 'skipped')


class Geometry(C.Structure):
    _fields_ = [(name, C.c_uint) for name in
                ('base_width', 'base_height', 'max_width', 'max_height')] + [('aspect_ratio', C.c_float)]


class Timing(C.Structure):
    _fields_ = [('fps', C.c_double), ('sample_rate', C.c_double)]


class AVInfo(C.Structure):
    _fields_ = [('geometry', Geometry), ('timing', Timing)]


class AudioTimeline:
    """Locate emitted sound; intentional source silence remains unclassified."""
    def __init__(self):
        self.bytes_seen = 0
        self.first_frame = self.last_frame = None
        self.first_sample = self.last_sample = None
        self.nonzero_frames = 0

    def observe(self, audio, frame):
        values = array.array('h', audio[self.bytes_seen:])
        if sys.byteorder != 'little':
            values.byteswap()
        start_sample = self.bytes_seen // 4
        self.bytes_seen = len(audio)
        first = next((i for i, value in enumerate(values) if abs(value) > 1), None)
        if first is None:
            return
        last = next(i for i in range(len(values) - 1, -1, -1) if abs(values[i]) > 1)
        if self.first_frame is None:
            self.first_frame = frame
            self.first_sample = start_sample + first // 2
        self.last_frame = frame
        self.last_sample = start_sample + last // 2
        self.nonzero_frames += 1

    def summary(self, request_frame, playing_frame, fps, sample_rate):
        emitted = self.first_frame is not None
        return {
            'frame_indices_zero_based': True,
            'nonzero_threshold_int16': 1,
            'emulator_fps': fps,
            'output_sample_rate_hz': sample_rate,
            'first_nonzero_frame': self.first_frame,
            'last_nonzero_frame': self.last_frame,
            'first_nonzero_output_sample': self.first_sample,
            'last_nonzero_output_sample': self.last_sample,
            'frames_with_nonzero_audio': self.nonzero_frames,
            'request_to_first_nonzero_frames': self.first_frame - request_frame if emitted else None,
            'playback_to_first_nonzero_frames': self.first_frame - playing_frame if emitted and playing_frame is not None else None,
            'request_to_first_nonzero_seconds': round(self.first_sample / sample_rate, 6) if emitted else None,
            'audible_span_frames': self.last_frame - self.first_frame + 1 if emitted else None,
            'audible_span_seconds': round((self.last_sample - self.first_sample + 1) / sample_rate, 6) if emitted else None,
            'note': 'Audible span covers first through last nonzero output, including any intervening source silence; it does not classify silent gaps or establish continuity.',
        }


class VideoEmulator(Emulator):
    def timing(self):
        info = AVInfo()
        self.lib.retro_get_system_av_info.argtypes = [C.POINTER(AVInfo)]
        self.lib.retro_get_system_av_info.restype = None
        self.lib.retro_get_system_av_info(C.byref(info))
        return info.timing.fps, info.timing.sample_rate

    def telemetry(self):
        pointer = self.lib.retro_get_memory_data(2)
        if not pointer or self.lib.retro_get_memory_size(2) < 0xF080 + TRACE.size:
            return {}
        data = C.string_at(pointer + 0xF080, TRACE.size)
        if sys.byteorder == 'little':
            data = b''.join(data[i:i + 2][::-1] for i in range(0, len(data), 2))
        values = TRACE.unpack(data)
        return dict(zip(TRACE_NAMES, values)) if values[0] == 0x4D565431 else {}


def sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def run_case(args, system, case, expected):
    output = args.out / case
    output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'fail', 'case': case, 'checks': {}}
    emulator = None
    audio_timeline = None
    playing_frame = None
    started = time.perf_counter()
    frame = 0
    try:
        emulator = VideoEmulator(args.core, system, output, args.cue)
        telemetry = {}
        for frame in range(args.frames):
            telemetry = emulator.run(1, [3] if frame % 240 in range(180, 188) else [])
            if telemetry.get('stage') == 1:
                break
            if telemetry.get('stage') == 4:
                raise AssertionError('Target reported an error during boot: ' + str(telemetry))
        else:
            raise AssertionError('Demo did not reach its menu within the frame budget')
        report['boot_frames'] = frame + 1
        emulator.capture('menu')
        emulator.audio.clear()
        fps, sample_rate = emulator.timing()
        audio_timeline = AudioTimeline()
        request_frame = frame + 1
        report['play_request_frame'] = request_frame
        play_key = 1 if case == 'silent_eof' else 8  # Genesis A / C.
        for _ in range(4):
            emulator.run(1, [play_key])
            frame += 1
            audio_timeline.observe(emulator.audio, frame)
        skip_sent = False
        captures = set()
        report['captures'] = []
        while frame + 1 < args.frames:
            keys = []
            skip_base = audio_timeline.first_frame if args.skip_after_audio else playing_frame
            if case == 'skip' and skip_base is not None and args.skip_after <= frame - skip_base < args.skip_after + 8:
                keys = [3]  # Fresh Start press while the player is running.
                if not skip_sent:
                    report['skip_timer_start_frame'] = skip_base
                    report['skip_requested_frame'] = frame + 1
                skip_sent = True
            telemetry = emulator.run(1, keys)
            frame += 1
            audio_timeline.observe(emulator.audio, frame)
            stage = telemetry.get('stage')
            if stage == 2:
                if playing_frame is None:
                    playing_frame = frame
                    report['play_start_frame'] = frame
                else:
                    for moment in (30, 120, 240):
                        if frame - playing_frame >= moment and moment not in captures:
                            name = 'playing-' + str(moment).zfill(4)
                            emulator.capture(name)
                            report['captures'].append({'file': name + '.png', 'play_frame': frame - playing_frame})
                            captures.add(moment)
            if stage in (3, 4):
                break
            if frame % 300 == 0:
                print(case, 'frame', frame, telemetry, flush=True)
        report['final_telemetry'] = telemetry
        report['emulated_frames'] = frame + 1
        if playing_frame is not None:
            report['play_frames'] = frame - playing_frame
        emulator.capture('final')
        report['audio'] = emulator.audio_metrics('playback')
        assert telemetry.get('stage') == 3, 'Playback failed or exceeded the frame budget: ' + str(telemetry)
        assert telemetry['error'] == 0, 'Target reported an error: ' + str(telemetry)
        report['checks']['target_completed_without_error'] = True
        if args.require_no_rebuffer:
            assert telemetry['rebuffer_count'] == 0, 'Performance gate failed: playback required audio rebuffering'
            report['checks']['no_audio_rebuffer'] = True
        if case == 'skip':
            if args.skip_after_audio:
                assert audio_timeline.first_frame is not None, 'No audible output observed to start the skip timer; omit --skip-after-audio for a silent source'
            assert skip_sent and telemetry['skipped'] == 1, 'Controller skip was not acknowledged'
            report['checks']['controller_skip_acknowledged'] = True
        else:
            assert telemetry['skipped'] == 0, 'EOF run unexpectedly skipped'
            assert telemetry['frames_shown'] > 0, 'No video frames were displayed'
            assert telemetry['frames_shown'] + telemetry['frames_dropped'] == expected['frames'], 'Video frame accounting does not match the source'
            report['checks']['all_video_frames_accounted_for'] = True
            if case == 'audio_eof':
                assert telemetry['audio_samples_played'] == expected['audio_samples'], 'Audio EOF does not match the source sample count'
                assert max(report['audio']['rms_left'], report['audio']['rms_right']) > 1, 'Procedural fixture produced no audible audio'
                report['checks']['exact_audio_eof'] = True
                report['checks']['nonzero_audio_energy'] = True
        report['status'] = 'pass'
    except Exception as error:
        report['error'] = str(error)
        if emulator is not None:
            report['final_telemetry'] = emulator.telemetry()
            if emulator.telemetry():  # Capture game pixels only, never the BIOS UI.
                emulator.capture('failure')
        print(case, 'FAIL:', error, flush=True)
    finally:
        report['wall_seconds'] = round(time.perf_counter() - started, 3)
        if audio_timeline is not None:
            report['audio_timing'] = audio_timeline.summary(request_frame, playing_frame, fps, sample_rate)
        if emulator is not None:
            emulator.close()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(case, report['status'].upper(), report.get('final_telemetry', {}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bios', required=True, type=Path)
    parser.add_argument('--cue', type=Path, default=ROOT / 'dist/video_demo.cue')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/video-smoke')
    parser.add_argument('--frames', type=int, default=1800, help='Total emulated frame ceiling per case, including boot')
    parser.add_argument('--skip-after', type=int, default=120, help='Frames after entering playback before pressing Start in the skip case')
    parser.add_argument('--skip-after-audio', action='store_true', help='Start the skip timer at the first nonzero emitted audio frame instead of entering playback')
    parser.add_argument('--require-no-rebuffer', action='store_true', help='Fail if target telemetry reports any audio rebuffering')
    parser.add_argument('--core', type=Path, default=ROOT / '.deps/genesis-plus-gx/genesis_plus_gx_libretro.so')
    parser.add_argument('--video', type=Path, default=ROOT / 'build/video/NOVEL.PAK', help='MTV1 fixture used to build the disc')
    parser.add_argument('--case', choices=('all', 'audio_eof', 'silent_eof', 'skip'), default='all')
    args = parser.parse_args()
    if not args.bios.is_file() or args.bios.stat().st_size != 131072:
        parser.error('Provide your own 128 KiB Japanese Mega CD BIOS')
    if args.frames < 60:
        parser.error('--frames must be at least 60')
    if args.skip_after < 1:
        parser.error('--skip-after must be positive')
    for path in (args.core, args.cue, args.cue.with_suffix('.iso'), args.video):
        if not path.is_file():
            parser.error('Required input does not exist: ' + str(path))
    with args.video.open('rb') as source:
        header = source.read(2048)
    if len(header) != 2048 or header[:4] != b'MTV1':
        parser.error('--video must be the MTV1 file used to build the disc')
    expected = {'frames': struct.unpack_from('>I', header, 16)[0],
                'audio_samples': struct.unpack_from('>I', header, 24)[0],
                'video_sha256': sha256(args.video)}
    args.out.mkdir(parents=True, exist_ok=True)
    system = ROOT / '.local/smoke/video-system'
    system.mkdir(parents=True, exist_ok=True)
    destination = system / 'bios_CD_J.bin'
    if args.bios.resolve() != destination.resolve():
        shutil.copyfile(args.bios, destination)
    report = {'emulator': 'Genesis Plus GX', 'hardware_tested': False,
              'core_commit': json.loads((ROOT / 'toolchain.lock.json').read_text())['genesis-plus-gx']['commit'],
              'disc_sha256': sha256(args.cue.with_suffix('.iso')),
              'require_no_rebuffer': args.require_no_rebuffer,
              'skip_after_audio': args.skip_after_audio,
              'expected': expected, 'cases': {}}
    cases = ('audio_eof', 'silent_eof', 'skip') if args.case == 'all' else (args.case,)
    for case in cases:
        report['cases'][case] = run_case(args, system, case, expected)
    report['status'] = 'pass' if all(case['status'] == 'pass' for case in report['cases'].values()) else 'fail'
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(report['status'].upper(), str(args.out / 'report.json'), flush=True)
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
