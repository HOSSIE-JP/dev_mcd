import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mcd_disc', ROOT / 'tools/disc.py')
disc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(disc)
image = disc.make_iso((ROOT / 'build/boot.bin').read_bytes(), {
    'IPX.MMD': (ROOT / 'build/video/IPX.MMD').read_bytes(),
    'NOVEL.PAK': (ROOT / 'build/video/NOVEL.PAK').read_bytes()})
out = ROOT / 'dist'
out.mkdir(exist_ok=True)
(out / 'video_demo.iso').write_bytes(image)
(out / 'video_demo.cue').write_text('FILE "video_demo.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n')
print('Video disc:', len(image), 'bytes')
