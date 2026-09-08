#!/usr/bin/env python3
"""MTV1 converter, compatible with the previous Mega-CD video study format.

Host ffmpeg decoding, RGB333 palette quantization and a bounded lossy tile
codebook. Records retain 16 kHz RF5C164 PCM for the native guarded audio ring.
"""
import argparse
import contextlib
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

# width, height, fps numerator, fps denominator, maximum dictionary tiles
PROFILES = {'small15': (160,112,15,1,96), 'medium12': (224,160,12,1,128),
            'medium15': (224,160,15,1,128), 'mediumhq12': (224,160,12,1,192),
            'balanced10': (256,176,10,1,192), 'full6': (320,224,6,1,256),
            'full75': (320,224,15,2,256), 'full10': (320,224,10,1,256),
            'fullhq6': (320,224,6,1,384)}
SECTOR = 2048
RATE = 16000
MAX_SAMPLES = RATE*7200
HEADER = struct.Struct('>4s6H4I2H')
FRAME = struct.Struct('>4s3I2H3I')
# Screen-anchored thresholds repeat exactly at the 8x8 tile boundaries. They
# never depend on frame number, so a still picture cannot acquire dither shimmer.
BAYER4 = np.array([[0,8,2,10], [12,4,14,6], [3,11,1,9], [15,7,13,5]], dtype=np.float32)


def _dither_options(dither, strength):
    if dither not in ('none', 'ordered'):
        raise ValueError('Invalid video dither')
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Invalid video option: ditherStrength')
    return dither, strength

def _profile(name):
    if name not in PROFILES:
        raise ValueError('Unknown video profile: '+str(name))
    return PROFILES[name]

def _fit(image, width, height):
    # H40 pixels have nominal 14:15 aspect on a 4:3 display.
    image = image.convert('RGB')
    aspect = image.width/image.height*15/14
    w = min(width, max(1, round(height*aspect)))
    h = min(height, max(1, round(w/aspect)))
    canvas = Image.new('RGB', (width,height))
    canvas.paste(image.resize((w,h), Image.Resampling.LANCZOS), ((width-w)//2,(height-h)//2))
    return canvas

def encode_frame(image, width, height, limit, pre_fitted=False, dither='none', dither_strength=0.5):
    """Return palette, capped dictionary and map using the actual RGB333 colors."""
    dither, dither_strength = _dither_options(dither, dither_strength)
    image = image.convert('RGB') if pre_fitted else _fit(image, width, height)
    if image.size != (width,height):raise ValueError('Pre-fitted video frame dimensions mismatch')
    q = image.quantize(colors=15, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw_palette = q.getpalette()[:45]
    raw_palette += [0]*(45-len(raw_palette))
    rgb = np.zeros((16,3), dtype=np.int32)
    rgb[1:] = (np.array(raw_palette).reshape(15,3)*7+127)//255
    source = np.asarray(image, dtype=np.float32)
    target = source
    if dither == 'ordered' and dither_strength:
        # At full strength the bias spans one RGB333 step; the default uses
        # half that span to avoid overwhelming the small tile dictionary.
        thresholds = np.tile((BAYER4 + 0.5)/16 - 0.5, ((height+3)//4, (width+3)//4))[:height,:width]
        target = np.clip(source + thresholds[:,:,None]*(255/7)*dither_strength, 0, 255)
    actual = rgb.astype(np.float32)*(255/7)
    # Median-cut indices refer to RGB888 palette entries. After rounding those
    # colors to CRAM RGB333, their old nearest-color assignments are no longer
    # valid. Reassign against the exact colors the hardware will display.
    distance = np.sum((target[:,:,None,:] - actual[None,None,:,:])**2, axis=3)
    pixels = np.argmin(distance, axis=2).astype(np.uint8)
    # Exact black stays index zero, especially letterboxing.
    pixels[np.all(source==0,axis=2)] = 0
    tile_pixels = pixels.reshape(height//8,8,width//8,8).transpose(0,2,1,3).reshape(-1,64)
    packed = (tile_pixels[:,::2]<<4)|tile_pixels[:,1::2]
    unique, inverse, counts = np.unique(packed, axis=0, return_inverse=True, return_counts=True)
    if len(unique)>limit:
        decoded = np.empty((len(unique),64),dtype=np.uint8)
        decoded[:,::2] = unique>>4
        decoded[:,1::2] = unique&15
        vectors = rgb[decoded].reshape(len(unique),192).astype(np.float32)
        # Deterministic farthest-point representatives over 2x2 RGB averages.
        features = vectors.reshape(-1,8,8,3).reshape(-1,2,4,2,4,3).mean(axis=(2,4)).reshape(-1,12)
        chosen = [int(np.argmin(np.sum(vectors*vectors,axis=1)))]
        distance = np.sum((features-features[chosen[0]])**2,axis=1)
        for _ in range(1,limit):
            candidate = int(np.argmax(distance))
            if distance[candidate]<=0:
                # Equal coarse features: include distinct high-frequency tiles.
                remaining = np.ones(len(unique),dtype=bool);remaining[chosen]=False
                candidate = int(np.argmax(np.where(remaining,counts,-1)))
            chosen.append(candidate)
            distance = np.minimum(distance,np.sum((features-features[candidate])**2,axis=1))
            distance[chosen] = -1
        codebook = vectors[chosen]
        costs = np.sum(vectors*vectors,axis=1)[:,None]+np.sum(codebook*codebook,axis=1)[None,:]-2*(vectors@codebook.T)
        nearest = np.argmin(costs,axis=1)
        # Preserve every selected tile exactly; avoid numeric tie remapping black.
        nearest[chosen] = np.arange(limit)
        indices = nearest[inverse]
        unique = unique[chosen]
    else:
        indices = inverse
    colors = [(int(c[2])<<9)|(int(c[1])<<5)|(int(c[0])<<1) for c in rgb]
    return struct.pack('>16H',*colors), unique.tobytes(), np.asarray(indices,dtype='>u2').tobytes()

def _pcm(raw, samples):
    raw += bytes(max(0,samples*2-len(raw)))
    values = np.frombuffer(raw,dtype='<i2').astype(np.int32)
    magnitude = (np.abs(values)*127+16384)//32768
    magnitude = np.where(values>=0,np.minimum(magnitude,126),np.minimum(magnitude,127))
    return np.where(values>=0,magnitude|128,magnitude).astype(np.uint8).tobytes()

def encode_frames(frames, output, profile='medium12', total_samples=None, audio_pcm16=None, pre_fitted=False, dither='none', dither_strength=0.5):
    """Atomically stream PIL frames and optional mono PCM16 into exact MTV1 v1."""
    width,height,fn,fd,limit = _profile(profile)
    dither, dither_strength = _dither_options(dither, dither_strength)
    if total_samples is not None and not 0<total_samples<=MAX_SAMPLES:
        raise ValueError('Video duration must be greater than zero and at most two hours')
    output = Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    count=peak=0;end=0
    with tempfile.TemporaryDirectory(prefix='mtv-',dir=output.parent) as temp:
        staged=Path(temp)/'movie.mtv'
        with staged.open('w+b') as out, (Path(audio_pcm16).open('rb') if audio_pcm16 else contextlib.nullcontext(None)) as audio:
            out.write(bytes(SECTOR))
            for image in frames:
                pts=count*RATE*fd//fn
                end=(count+1)*RATE*fd//fn
                if total_samples is not None:
                    if pts>=total_samples:break
                    end=min(end,total_samples)
                if end>MAX_SAMPLES:raise ValueError('Video exceeds two hours')
                palette,tiles,mapping=encode_frame(image,width,height,limit,pre_fitted,dither,dither_strength)
                samples=end-pts
                pcm=_pcm(audio.read(samples*2),samples) if audio else b'\x80'*samples
                body=palette+tiles+mapping+pcm
                body+=bytes(len(body)&1)
                record=FRAME.pack(b'FRM1',32+len(body),count,pts,len(tiles)//32,len(mapping)//2,samples,zlib.crc32(body),0)+body
                if len(record)>32768:raise ValueError('MTV1 record exceeds 32 KiB')
                out.write(record);count+=1;peak=max(peak,len(record))
            if not count:raise ValueError('Video has no decodable frames')
            total=total_samples if total_samples is not None else end
            expected=(total*fn+RATE*fd-1)//(RATE*fd)
            if count!=expected:raise ValueError(f'Expected {expected} video frames, decoded {count}')
            size=out.tell();out.write(bytes(-size%SECTOR));size=out.tell()
            header=bytearray(SECTOR)
            HEADER.pack_into(header,0,b'MTV1',1,SECTOR,width,height,fn,fd,count,RATE,total,peak,limit,1)
            struct.pack_into('>I',header,60,zlib.crc32(header[:60]))
            out.seek(0);out.write(header)
        os.replace(staged,output)
    return {'format':'MTV1','profile':profile,'width':width,'height':height,'fps_num':fn,'fps_den':fd,
            'fps':fn/fd,'frames':count,'max_record':peak,'dictionary_limit':limit,'bytes':size,
            'dither':dither,'ditherStrength':dither_strength,
            'nominal_seconds':total/RATE,'audio_samples':total,'video_bytes_per_second':size*RATE/total,
            'audio':'embedded RF5C164 PCM8; native player uses a guarded PCM ring',
            'timing':'target rate only; 2M cache refills may cause dropped frames or audio rebuffer pauses'}

def validate_video(data):
    """Validate exact previous MTV1 format including CRC, timestamps and PCM."""
    if len(data)<SECTOR or len(data)%SECTOR:raise ValueError('Truncated MTV1')
    magic,version,hb,w,h,fn,fd,count,rate,total,peak,limit,flags=HEADER.unpack_from(data)
    if (magic,version,hb,rate,flags)!=(b'MTV1',1,SECTOR,RATE,1):raise ValueError('Unsupported MTV1 header')
    if zlib.crc32(data[:60])!=struct.unpack_from('>I',data,60)[0] or any(data[36:60]) or any(data[64:SECTOR]):raise ValueError('Invalid header CRC/reserved bytes')
    if not (0<w<=320 and 0<h<=224 and w%8==h%8==0 and 0<fn<=30 and 0<fd<=2 and 0<total<=MAX_SAMPLES and 64<=peak<=32768 and peak%2==0 and 0<limit<=512):raise ValueError('Invalid MTV1 bounds')
    if count!=(total*fn+rate*fd-1)//(rate*fd):raise ValueError('Invalid frame count')
    pos=SECTOR
    for sequence in range(count):
        if pos+64>len(data):raise ValueError('Truncated frame')
        magic,n,number,pts,tiles,cells,samples,crc,flags=FRAME.unpack_from(data,pos)
        expected_pts=sequence*rate*fd//fn
        expected_samples=min((sequence+1)*rate*fd//fn,total)-expected_pts
        expected=64+tiles*32+cells*2+samples
        if magic!=b'FRM1' or flags or number!=sequence or pts!=expected_pts:raise ValueError('Invalid frame sequence')
        if not (0<tiles<=limit and cells==w//8*(h//8) and samples==expected_samples and n==((expected+1)&~1) and n<=peak and pos+n<=len(data)):raise ValueError('Invalid frame bounds')
        body=data[pos+32:pos+n]
        if zlib.crc32(body)!=crc:raise ValueError('Invalid frame CRC')
        colors=struct.unpack_from('>16H',data,pos+32)
        if colors[0] or any(c&~0xEEE for c in colors):raise ValueError('Invalid palette')
        map_start=pos+64+tiles*32
        if any(i>=tiles for i in struct.unpack_from('>'+str(cells)+'H',data,map_start)):raise ValueError('Invalid tile reference')
        if 255 in data[map_start+cells*2:map_start+cells*2+samples]:raise ValueError('Invalid PCM marker')
        if expected&1 and data[pos+n-1]:raise ValueError('Invalid record padding')
        pos+=n
    if len(data)!=((pos+2047)//2048)*2048 or any(data[pos:]):raise ValueError('Invalid terminal padding')
    return {'width':w,'height':h,'fps_num':fn,'fps_den':fd,'frames':count,'bytes':len(data),'audio_samples':total}

def video_metadata(metadata):
    """Select a regular video stream and use its autorotated display geometry."""
    streams=metadata.get('streams',[])
    selected=next(((position,stream) for position,stream in enumerate(streams)
                   if stream.get('codec_type')=='video' and not stream.get('disposition',{}).get('attached_pic')),None)
    if selected is None:raise ValueError('No regular video stream')
    position,stream=selected
    try:
        index=int(stream.get('index',position))
        width,height=int(stream['width']),int(stream['height'])
        rotation=next((entry['rotation'] for entry in stream.get('side_data_list',[]) if 'rotation' in entry),stream.get('tags',{}).get('rotate',0))
        rotation=Decimal(str(rotation))
        if not rotation.is_finite():raise ValueError('Invalid video rotation')
        if abs(rotation%180)==90:width,height=height,width
        if index<0 or not 0<width<=16384 or not 0<height<=16384:raise ValueError('Invalid video stream dimensions/index')
    except (KeyError,TypeError,InvalidOperation,OverflowError) as error:
        raise ValueError('Invalid video stream dimensions/index/rotation') from error
    try:
        duration=Decimal(str(stream.get('duration','NaN')))
    except (TypeError,InvalidOperation):duration=Decimal('NaN')
    if not duration.is_finite() or duration<=0:
        try:duration=Decimal(str(metadata.get('format',{}).get('duration','NaN')))
        except (TypeError,InvalidOperation):duration=Decimal('NaN')
    if not duration.is_finite() or not 0<duration<=7200:raise ValueError('Video duration must be greater than zero and at most two hours')
    total=int(duration*RATE)
    if not total:raise ValueError('Video duration is shorter than one audio sample')
    return {'stream_index':index,'width':width,'height':height,'total_samples':total,
            'duration_seconds':float(duration),
            'has_audio':any(stream.get('codec_type')=='audio' for stream in streams)}

def processing_options(options, metadata):
    options = options or {}
    if not isinstance(options, dict): raise ValueError('Video options must be an object')
    def number(key, default, low, high):
        value = options.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Invalid video option: ' + key)
        return value
    sample_duration = metadata['total_samples']/RATE
    # Validate against the probed duration before truncating to the output clock.
    duration = metadata.get('duration_seconds', sample_duration)
    start = number('trimStart', 0, 0, duration)
    end = number('trimEnd', duration, 0, duration) if options.get('trimEnd') is not None else duration
    end = min(end, sample_duration)
    if end-start < 1/RATE: raise ValueError('Empty video trim range')
    result = dict(trimStart=start, trimEnd=end)
    result['dither'], result['ditherStrength'] = _dither_options(options.get('dither', 'none'), options.get('ditherStrength', 0.5))
    for key, default, low, high in [('brightness',0,-1,1),('contrast',1,0,2),('gamma',1,0.1,3),('saturation',1,0,3),('volume',1,0,2)]:
        result[key] = number(key, default, low, high)
    result['fit'] = options.get('fit', 'pad')
    if result['fit'] not in ('pad','crop'): raise ValueError('Invalid video fit')
    result['mute'] = options.get('mute', False)
    if not isinstance(result['mute'], bool): raise ValueError('Invalid video mute')
    crop = options.get('crop') or dict(x=0,y=0,width=metadata['width'],height=metadata['height'])
    if not isinstance(crop,dict) or any(isinstance(crop.get(k),bool) or not isinstance(crop.get(k),int) for k in ('x','y','width','height')):
        raise ValueError('Invalid video crop')
    if crop['x']<0 or crop['y']<0 or crop['width']<1 or crop['height']<1 or crop['x']+crop['width']>metadata['width'] or crop['y']+crop['height']>metadata['height']:
        raise ValueError('Video crop outside source')
    result['crop'] = crop
    return result

def convert_video(source, output, profile='medium12', ffmpeg='ffmpeg', ffprobe=None, options=None):
    _profile(profile);source,output=Path(source),Path(output)
    if not source.is_file():raise ValueError('Video source does not exist: '+str(source))
    if source.resolve()==output.resolve():raise ValueError('Video output must differ from its source')
    exe=shutil.which(str(ffmpeg))
    if not exe:raise ValueError('ffmpeg is required: '+str(ffmpeg))
    if ffprobe:
        probe=shutil.which(str(ffprobe))
        if not probe:raise ValueError('Configured ffprobe is required: '+str(ffprobe))
    else:
        adjacent=Path(exe).with_name('ffprobe.exe' if str(exe).lower().endswith('.exe') else 'ffprobe')
        probe=str(adjacent) if adjacent.is_file() else shutil.which('ffprobe')
        if not probe:raise ValueError('ffprobe is required alongside ffmpeg or on PATH')
    result=subprocess.run([probe,'-v','error','-protocol_whitelist','file,pipe','-show_entries',
        'stream=index,codec_type,duration,width,height:stream_disposition=attached_pic:stream_tags=rotate:stream_side_data=rotation:format=duration',
        '-of','json',str(source.resolve())],capture_output=True,text=True,check=True,shell=False,timeout=30)
    metadata=video_metadata(json.loads(result.stdout))
    edit=processing_options(options, metadata)
    total=int(round((edit['trimEnd']-edit['trimStart'])*RATE))
    width,height,fn,fd,_=_profile(profile);count=(total*fn+RATE*fd-1)//(RATE*fd)
    # Bound the raw pipe to viewport scale while correcting H40 pixel aspect.
    # FFmpeg autorotates before -vf; precompute fit from those display dimensions.
    crop=edit['crop']
    aspect=crop['width']/crop['height']*15/14
    if edit['fit']=='pad':
        fw=min(width,max(1,round(height*aspect)));fh=min(height,max(1,round(fw/aspect)))
        fit=f'scale={fw}:{fh}:flags=area,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black'
    else:
        fw=max(width,round(height*aspect));fh=max(height,round(fw/aspect))
        fit=f'scale={fw}:{fh}:flags=area,crop={width}:{height}'
    vf=(f"crop={crop['width']}:{crop['height']}:{crop['x']}:{crop['y']}:exact=1,"
        f"eq=brightness={edit['brightness']}:contrast={edit['contrast']}:gamma={edit['gamma']}:saturation={edit['saturation']},"
        f'fps={fn}/{fd},{fit},tpad=stop_mode=clone:stop_duration=1')
    seek=['-ss',str(edit['trimStart'])]
    with tempfile.TemporaryDirectory(prefix='mcd-video-audio-') as temporary, tempfile.TemporaryFile() as errors:
        audio=Path(temporary)/'audio.s16le'
        if metadata['has_audio'] and not edit['mute']:
            subprocess.run([exe,'-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(source.resolve()),*seek,'-map','0:a:0','-af',f"volume={edit['volume']}",'-vn','-ac','1','-ar',str(RATE),'-t',str(Decimal(total)/RATE),'-f','s16le',str(audio)],check=True,shell=False)
        process=subprocess.Popen([exe,'-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(source.resolve()),*seek,'-map','0:'+str(metadata['stream_index']),'-an','-sn','-dn','-vf',vf,'-frames:v',str(count),'-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=errors,shell=False)
        def frames():
            size=width*height*3
            while True:
                chunks=[];got=0
                while got<size:
                    chunk=process.stdout.read(size-got)
                    if not chunk:break
                    chunks.append(chunk);got+=len(chunk)
                if not got:break
                if got!=size:raise ValueError('Truncated ffmpeg video frame')
                yield Image.frombytes('RGB',(width,height),b''.join(chunks))
            if process.wait()!=0:
                errors.seek(0);raise ValueError('ffmpeg failed: '+errors.read(4000).decode('utf-8','replace'))
        try:
            return encode_frames(frames(),output,profile,total,audio if audio.exists() else None,pre_fitted=True,
                                 dither=edit['dither'],dither_strength=edit['ditherStrength'])
        finally:
            process.stdout.close()
            if process.poll() is None:process.kill()
            process.wait()

def demo_frames(profile='medium12', seconds=3):
    width,height,fn,fd,_=_profile(profile)
    for frame in range((seconds*fn+fd-1)//fd):
        image=Image.new('RGB',(width,height),'#101828');draw=ImageDraw.Draw(image)
        for x in range(0,width,16):draw.line((x,0,x,height),fill='#304058')
        for y in range(0,height,16):draw.line((0,y,width,y),fill='#304058')
        x=(frame*4)%(width-24);draw.ellipse((x,height//2-12,x+24,height//2+12),fill='#ffb830')
        draw.text((8,8),f'MEGA-CD {frame+1:03}',fill='#ffffff');yield image

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profile',choices=PROFILES,default='medium12');parser.add_argument('--ffmpeg',default='ffmpeg');parser.add_argument('--ffprobe');parser.add_argument('--demo',action='store_true')
    parser.add_argument('--options',type=Path,help='JSON processing recipe')
    args=parser.parse_args()
    if args.demo==bool(args.source):parser.error('Specify exactly one of --source and --demo')
    try:
        info=encode_frames(demo_frames(args.profile),args.output,args.profile) if args.demo else convert_video(args.source,args.output,args.profile,args.ffmpeg,args.ffprobe,json.loads(args.options.read_text()) if args.options else None)
    except (ValueError,OSError,subprocess.SubprocessError) as exc:parser.exit(1,str(exc)+'\n')
    print(json.dumps(info,ensure_ascii=False,indent=2))
