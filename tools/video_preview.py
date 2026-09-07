#!/usr/bin/env python3
"""Decode the actual MTV1 conversion into a lossless browser proof movie."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import numpy as np
from PIL import Image
from video_convert import convert_video, validate_video, HEADER, FRAME, SECTOR, RATE


def preview(source, output, profile='medium12', ffmpeg='ffmpeg', ffprobe=None, options=None):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='proof-') as directory:
        root = Path(directory)
        movie = root/'video.mtv'
        print('MTV1への変換を開始', flush=True)
        report = convert_video(source, movie, profile, ffmpeg, ffprobe, options)
        data = movie.read_bytes()
        info = validate_video(data)
        pos = SECTOR
        audio = bytearray()
        w,h = info['width'],info['height']
        print('MTV1のタイル・RGB333・PCMを復号', flush=True)
        with (root/'video.rgb').open('wb') as raw:
            for sequence in range(info['frames']):
                _,size,_,_,tile_count,cells,samples,_,_ = FRAME.unpack_from(data,pos)
                words = struct.unpack_from('>16H',data,pos+32)
                palette = np.array([[((c>>1)&7)*255//7,((c>>5)&7)*255//7,((c>>9)&7)*255//7] for c in words],dtype=np.uint8)
                tiles = np.frombuffer(data,dtype=np.uint8,count=tile_count*32,offset=pos+64).reshape(tile_count,32)
                pixels = np.empty((tile_count,64),dtype=np.uint8)
                pixels[:,::2]=tiles>>4; pixels[:,1::2]=tiles&15
                offset = pos+64+tile_count*32
                mapping = np.frombuffer(data,dtype='>u2',count=cells,offset=offset)
                frame = pixels[mapping].reshape(h//8,w//8,8,8).transpose(0,2,1,3).reshape(h,w)
                raw.write(palette[frame].tobytes())
                pcm = np.frombuffer(data,dtype=np.uint8,count=samples,offset=offset+cells*2).astype(np.int16)
                decoded = np.where(pcm&128,pcm&127,-(pcm&127))*256
                audio.extend(decoded.astype('<i2').tobytes())
                pos += size
        (root/'audio.s16le').write_bytes(audio)
        subprocess.run([ffmpeg,'-nostdin','-y','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{w}x{h}',
            '-framerate',f"{info['fps_num']}/{info['fps_den']}",'-i',str(root/'video.rgb'),'-f','s16le','-ar',str(RATE),'-ac','1','-i',str(root/'audio.s16le'),
            '-c:v','libvpx-vp9','-lossless','1','-c:a','libopus','-b:a','64k','-t',str(info['audio_samples']/RATE),str(output)],check=True)
        print(json.dumps(report),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--profile',default='medium12');parser.add_argument('--ffmpeg',default='ffmpeg');parser.add_argument('--ffprobe')
    parser.add_argument('--options',type=Path)
    args=parser.parse_args()
    preview(args.source,args.output,args.profile,args.ffmpeg,args.ffprobe,json.loads(args.options.read_text()) if args.options else None)
