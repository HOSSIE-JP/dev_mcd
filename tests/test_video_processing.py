import sys
import tempfile
import unittest
import shutil
import subprocess
import json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from video_convert import processing_options, video_metadata, convert_video, validate_video, RATE, FRAME, SECTOR

class VideoProcessingTests(unittest.TestCase):
    def test_fractional_sample_source_end(self):
        metadata=video_metadata({'streams':[dict(codec_type='video',width=64,height=48,duration='20.041667')]})
        self.assertEqual(metadata['total_samples'],320666)
        for options in [{},dict(trimEnd=20.041667),dict(trimEnd=20.04164)]:
            with self.subTest(options=options):
                result=processing_options(options,metadata)
                self.assertEqual(result['trimEnd'],320666/RATE)
        self.assertEqual(processing_options(dict(trimEnd=10.5),metadata)['trimEnd'],10.5)
        for value in [20.041668,21,True,float('inf'),float('nan'),'20.041667']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                processing_options(dict(trimEnd=value),metadata)
        with self.assertRaises(ValueError):
            processing_options(dict(trimStart=20.04164,trimEnd=20.041667),metadata)

    def test_invalid_processing(self):
        metadata=dict(width=100,height=80,total_samples=RATE*3)
        for value in [dict(trimStart=3),dict(trimEnd=0),dict(gamma=0),dict(volume=float('inf')),dict(mute=1),dict(crop=dict(x=90,y=0,width=20,height=20))]:
            with self.assertRaises(ValueError): processing_options(value,metadata)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_trim_crop_and_mute_reach_encoded_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'input.mkv';out=root/'result.mtv'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=64x48:r=15:d=2','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','ffv1','-c:a','pcm_s16le',str(source)],check=True)
            options=dict(trimStart=.5,trimEnd=1.25,mute=True,crop=dict(x=4,y=8,width=40,height=32),brightness=.1,gamma=1.2,volume=.5,dither='ordered',ditherStrength=.75)
            report=convert_video(source,out,'small15',options=options)
            data=out.read_bytes();info=validate_video(data)
            self.assertEqual(info['audio_samples'],12000)
            self.assertEqual(report['frames'],12)
            self.assertEqual((report['dither'],report['ditherStrength']),('ordered',.75))
            _,size,_,_,tiles,cells,samples,_,_=FRAME.unpack_from(data,SECTOR)
            start=SECTOR+64+tiles*32+cells*2
            self.assertEqual(data[start:start+samples],b'\x80'*samples)

if __name__=='__main__':unittest.main()
