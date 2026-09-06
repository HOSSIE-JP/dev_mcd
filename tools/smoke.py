#!/usr/bin/env python3
"""Boot the actual disc in unmodified Genesis Plus GX with a local user BIOS.

No save states or firmware snapshots are written. Captures contain game pixels
and audio only. libretro RAM is read solely for the demo's 24-byte telemetry.
"""
import argparse
import array
import ctypes as C
import hashlib
import json
import math
import shutil
import struct
import sys
import wave
import zlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class Variable(C.Structure): _fields_=[('key',C.c_char_p),('value',C.c_char_p)]
class GameInfo(C.Structure): _fields_=[('path',C.c_char_p),('data',C.c_void_p),('size',C.c_size_t),('meta',C.c_char_p)]
ENV=C.CFUNCTYPE(C.c_bool,C.c_uint,C.c_void_p)
VIDEO=C.CFUNCTYPE(None,C.c_void_p,C.c_uint,C.c_uint,C.c_size_t)
AUDIO=C.CFUNCTYPE(None,C.c_int16,C.c_int16)
BATCH=C.CFUNCTYPE(C.c_size_t,C.POINTER(C.c_int16),C.c_size_t)
POLL=C.CFUNCTYPE(None)
INPUT=C.CFUNCTYPE(C.c_int16,C.c_uint,C.c_uint,C.c_uint,C.c_uint)

def png(path,w,h,rgb):
    def chunk(tag,data): return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xFFFFFFFF)
    scan=b''.join(b'\0'+rgb[y*w*3:(y+1)*w*3] for y in range(h))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b''))

class Emulator:
    def __init__(self,core,system,out,disc):
        self.lib=C.CDLL(str(core.resolve()))
        self.directory=str(system.resolve()).encode()
        self.options={b'genesis_plus_gx_region_detect':b'ntsc-j',b'genesis_plus_gx_bios':b'enabled'}
        self.keys=set(); self.audio=bytearray(); self.picture=None; self.pixel_format=2; self.out=out
        self.callbacks=[ENV(self.env),VIDEO(self.video),AUDIO(self.sample),BATCH(self.batch),POLL(lambda:None),INPUT(self.input)]
        for name,cb in zip(('environment','video_refresh','audio_sample','audio_sample_batch','input_poll','input_state'),self.callbacks):
            f=getattr(self.lib,'retro_set_'+name); f.argtypes=[type(cb)]; f(cb)
        self.lib.retro_init()
        self.lib.retro_load_game.argtypes=[C.POINTER(GameInfo)]; self.lib.retro_load_game.restype=C.c_bool
        self.lib.retro_get_memory_data.argtypes=[C.c_uint]; self.lib.retro_get_memory_data.restype=C.c_void_p
        self.lib.retro_get_memory_size.argtypes=[C.c_uint]; self.lib.retro_get_memory_size.restype=C.c_size_t
        self.lib.retro_set_controller_port_device.argtypes=[C.c_uint,C.c_uint]
        self.lib.retro_set_controller_port_device(0,1)
        path=str(disc.resolve()).encode()
        if not self.lib.retro_load_game(C.byref(GameInfo(path,None,0,None))): raise RuntimeError('libretro rejected the disc')
    def env(self,cmd,data):
        if cmd in (9,30,31): C.cast(data,C.POINTER(C.c_char_p))[0]=self.directory; return True
        if cmd==10: self.pixel_format=C.cast(data,C.POINTER(C.c_uint))[0]; return self.pixel_format in (0,1,2)
        if cmd==3: C.cast(data,C.POINTER(C.c_bool))[0]=True; return True
        if cmd==15:
            var=C.cast(data,C.POINTER(Variable)).contents
            var.value=self.options.get(var.key)
            return var.value is not None
        if cmd==16:
            rows=C.cast(data,C.POINTER(Variable)); i=0
            while rows[i].key:
                self.options.setdefault(rows[i].key,rows[i].value.split(b'; ',1)[1].split(b'|',1)[0]); i+=1
            return True
        if cmd==17: C.cast(data,C.POINTER(C.c_bool))[0]=False; return True
        if cmd==52: C.cast(data,C.POINTER(C.c_uint))[0]=0; return True
        if cmd in (18,35): return True
        return False
    def video(self,data,w,h,pitch):
        if data: self.picture=(w,h,pitch,C.string_at(data,h*pitch))
    def sample(self,left,right): self.audio.extend(struct.pack('<hh',left,right))
    def batch(self,data,frames): self.audio.extend(C.string_at(data,frames*4)); return frames
    def input(self,port,device,index,key): return int(port==0 and key in self.keys)
    def telemetry(self):
        ptr=self.lib.retro_get_memory_data(2)
        if not ptr or self.lib.retro_get_memory_size(2)<0xF018: return {}
        magic=C.string_at(ptr+0xF000,4)
        if sys.byteorder=='little': magic=magic[0:2][::-1]+magic[2:4][::-1]
        if magic!=b'MCDB': return {}
        data=C.string_at(ptr+0xF000,24)
        # GPGX exposes native little-endian 16-bit work RAM words on this host.
        if sys.byteorder=='little': data=b''.join(data[i:i+2][::-1] for i in range(0,24,2))
        values=struct.unpack('>II8H',data)
        return dict(zip(('magic','frame','stage','error','image_ok','prepared','flags','sub_ticks','event','completed'),values))
    def run(self,count,keys=()):
        self.keys=set(keys)
        for _ in range(count): self.lib.retro_run()
        return self.telemetry()
    def press(self,key): self.run(8,[key]); return self.run(20)
    def capture(self,name):
        if not self.picture: raise RuntimeError('No video frames')
        w,h,pitch,data=self.picture; rgb=bytearray()
        for y in range(h):
            for x in range(w):
                if self.pixel_format==1:
                    value=int.from_bytes(data[y*pitch+x*4:y*pitch+x*4+4],sys.byteorder)
                    rgb.extend(((value>>16)&255,(value>>8)&255,value&255))
                else:
                    value=int.from_bytes(data[y*pitch+x*2:y*pitch+x*2+2],sys.byteorder)
                    if self.pixel_format==2: rgb.extend((((value>>11)&31)*255//31,((value>>5)&63)*255//63,(value&31)*255//31))
                    else: rgb.extend((((value>>10)&31)*255//31,((value>>5)&31)*255//31,(value&31)*255//31))
        png(self.out/(name+'.png'),w,h,bytes(rgb))
        return w,h,bytes(rgb)
    def audio_metrics(self,name):
        values=array.array('h',self.audio)
        if sys.byteorder!='little': values.byteswap()
        rms=[math.sqrt(sum(v*v for v in values[ch::2])/max(1,len(values)//2)) for ch in (0,1)]
        with wave.open(str(self.out/(name+'.wav')),'wb') as f:
            f.setparams((2,2,44100,0,'NONE','not compressed')); f.writeframes(self.audio)
        return {'samples':len(values)//2,'rms_left':round(rms[0],2),'rms_right':round(rms[1],2)}
    def tone(self,freq,channel):
        values=array.array('h',self.audio)
        if sys.byteorder!='little': values.byteswap()
        values=values[channel::2]
        # Direct Fourier amplitude at a diagnostic tone (no NumPy dependency).
        phase=2*math.pi*freq/44100
        real=sum(v*math.cos(phase*n) for n,v in enumerate(values))
        imag=sum(v*math.sin(phase*n) for n,v in enumerate(values))
        return 2*math.hypot(real,imag)/max(1,len(values))
    def close(self): self.lib.retro_unload_game(); self.lib.retro_deinit()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--bios',required=True,type=Path)
    ap.add_argument('--core',type=Path,default=ROOT/'.deps/genesis-plus-gx/genesis_plus_gx_libretro.so')
    ap.add_argument('--disc',type=Path,default=ROOT/'dist/mcd_demo.cue')
    ap.add_argument('--expect-error',type=int,default=0)
    ap.add_argument('--output',type=Path,default=ROOT/'build/validation')
    ap.add_argument('--debug-boot',action='store_true')
    args=ap.parse_args()
    if not args.bios.is_file() or args.bios.stat().st_size!=131072: ap.error('Provide your own 128 KiB Japanese Mega CD BIOS')
    system=ROOT/'.local/smoke/system'; system.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(args.bios,system/'bios_CD_J.bin')
    out=args.output; out.mkdir(parents=True,exist_ok=True)
    emu=Emulator(args.core,system,out,args.disc); report={'core_commit':json.loads((ROOT/'toolchain.lock.json').read_text())['genesis-plus-gx']['commit'],'checks':{}}
    report['disc_sha256']=hashlib.sha256(args.disc.with_suffix('.iso').read_bytes()).hexdigest()
    try:
        ready=False
        for frame in range(2400):
            t=emu.run(1,[3] if frame%240 in range(180,188) else []) # Start at BIOS menu
            if t.get('magic')==0x4D434442 and t.get('stage')==0xFFFF: break
            if t.get('magic')==0x4D434442 and t.get('stage')==3:
                ready=True; break
            if frame%300==299:
                print('Boot frame',frame+1,t,flush=True)
                if args.debug_boot: emu.capture('boot-'+str(frame+1))
        emu.capture('ready')
        report['boot_frames']=frame+1; report['telemetry']=t
        if args.expect_error:
            assert t.get('stage')==0xFFFF and t.get('error')==args.expect_error, 'Expected target error was not reported'
            before=t['frame']; emu.run(120)
            assert emu.telemetry()['frame']>before+100, 'Target froze after reporting an error'
            report['checks']['expected_target_error']=args.expect_error
            report['status']='pass'; print(json.dumps(report,indent=2)); return
        assert ready, 'Native CD boot did not reach READY'
        assert t['image_ok']==1 and t['prepared']==1 and t['error']==0
        report['checks']['native_boot_image_adpcm_prepare']=True
        for key in (4,5):
            emu.press(key)
            assert emu.telemetry()['error']==6, 'Pause/resume without an active track must reject safely'
        report['checks']['cdda_invalid_state_rejected']=True
        emu.run(60); emu.audio.clear(); emu.run(60)
        silence=emu.audio_metrics('silence'); assert max(silence['rms_left'],silence['rms_right'])<10
        emu.audio.clear(); before=emu.telemetry(); emu.press(1) # Genesis A = libretro Y
        emu.run(90); pcm=emu.audio_metrics('adpcm'); emu.capture('adpcm')
        assert min(pcm['rms_left'],pcm['rms_right'])>100, 'ADPCM produced no audio'
        assert emu.telemetry()['frame']>before['frame']+90, 'Main CPU stalled during ADPCM'
        emu.run(120); emu.audio.clear(); emu.run(60)
        tail=emu.audio_metrics('adpcm-tail'); assert max(tail['rms_left'],tail['rms_right'])<10, 'One-shot did not stop'
        report['checks']['adpcm_one_shot']=pcm
        emu.press(0); emu.run(120); emu.audio.clear(); emu.run(120) # B
        cdda=emu.audio_metrics('cdda'); emu.capture('cdda')
        assert min(cdda['rms_left'],cdda['rms_right'])>100, 'CD-DA produced no audio'
        report['checks']['cdda_play']=cdda
        emu.press(4); emu.run(120); emu.audio.clear(); emu.run(60) # Up
        paused=emu.audio_metrics('paused'); assert max(paused['rms_left'],paused['rms_right'])<10, 'Pause failed'
        emu.press(5); emu.run(120); emu.audio.clear(); emu.run(60) # Down
        resumed=emu.audio_metrics('resumed'); assert min(resumed['rms_left'],resumed['rms_right'])>100, 'Resume failed'
        report['checks']['cdda_pause_resume']=True
        emu.audio.clear(); emu.run(1,[1]); emu.run(14)
        mixed={'adpcm_440_left':round(emu.tone(440,0),2),'cdda_330_left':round(emu.tone(330,0),2),
               'cdda_550_right':round(emu.tone(550,1),2)}
        assert min(mixed.values())>1000, 'Both PCM and CD-DA tones must be present simultaneously'
        assert emu.telemetry()['flags'] & 3 == 3 and emu.telemetry()['error']==0
        emu.audio_metrics('mixed'); report['checks']['adpcm_while_cdda']=mixed
        emu.press(8); emu.run(120); emu.audio.clear(); emu.run(60) # C = libretro A
        stopped=emu.audio_metrics('stopped'); assert max(stopped['rms_left'],stopped['rms_right'])<10, 'Stop failed'
        report['checks']['stop']=True
        emu.press(3); emu.run(300); t=emu.telemetry(); emu.capture('reloaded')
        assert t['error']==0 and t['stage']==3
        report['checks']['image_reload']=True
        report['final_telemetry']=t; report['status']='pass'
        print(json.dumps(report,indent=2))
    except Exception as e:
        report['status']='fail'; report['error']=str(e); report['final_telemetry']=emu.telemetry()
        emu.capture('failure'); raise
    finally:
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        emu.close()
if __name__=='__main__': main()
