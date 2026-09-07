#!/usr/bin/env python3
"""Exercise the real novel disc with controller input, without save states.
Only the game's 40-byte NVN1 telemetry block is read from Main Work RAM.
"""
import argparse,ctypes as C,hashlib,json,shutil,struct,sys
from pathlib import Path
from smoke import Emulator,ROOT
class NovelEmulator(Emulator):
    def telemetry(self):
        ptr=self.lib.retro_get_memory_data(2)
        if not ptr or self.lib.retro_get_memory_size(2)<0xF028:return {}
        data=C.string_at(ptr+0xF000,4)
        if sys.byteorder=='little':data=data[0:2][::-1]+data[2:4][::-1]
        if data!=b'NVN1':return {}
        data=C.string_at(ptr+0xF000,40)
        if sys.byteorder=='little':data=b''.join(data[i:i+2][::-1] for i in range(0,40,2))
        names=('magic','frame','scene','pc','mode','error','page','choice','flags','io_count','voice_count','bgm_count','branches','completed','variable0','variable1','resource','underruns')
        return dict(zip(names,struct.unpack('>II16H',data)))
def run(args):
    if args.bios.stat().st_size!=131072:raise ValueError('Expected user-owned 128 KiB Japanese BIOS')
    system=ROOT/'.local/smoke'/('novel-'+args.output.name);system.mkdir(parents=True,exist_ok=True);shutil.copyfile(args.bios,system/'bios_CD_J.bin')
    args.output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/'examples/ishinoura_ep01/data/manifest.json').read_text())
    scene_names={s['index']:s['id'] for s in manifest['scenes']}
    commands={(r['scene'],r['pc']):r for r in manifest['command_map']}
    emu=NovelEmulator(args.core,system,args.output,args.disc)
    report={'disc_sha256':hashlib.sha256(args.disc.with_suffix('.iso').read_bytes()).hexdigest(),'route':args.route,'scenes':[],'messages':[],'choices':[],'checks':{},'emulator':'Genesis Plus GX','hardware_tested':False}
    seen=set();messages=set();captures=set();last=None;age=0;last_progress=0;pulse=0;audio_until=0;audio_name='';natural_done=False;title_done=False
    route=[int(x) for x in args.route.split(',')]
    try:
        t={}
        for frame in range(args.max_frames):
            keys=[]
            if not t:
                if frame%240 in range(180,188):keys=[3]
            else:
                assert not t['error'],f"Target error {t['error']}: {t}"
                assert not (t['flags']&768),f"PCM ring underrun: flags {t['flags']}"
                state=(t['scene'],t['pc'],t['mode'],t['page'])
                if state!=last:age=0;last=state;last_progress=frame
                else:age+=1
                assert frame-last_progress<6000,f'Target stalled: {t}'
                name=scene_names.get(t['scene'],'loading')
                if t['mode']!=8 and name not in seen:seen.add(name);report['scenes'].append(name);print('Scene',name,flush=True)
                if t['mode']==1 and name=='logo' and age==10:keys=[0]
                if t['mode']==1 and name=='title' and t['pc']>=6:
                    if not title_done:
                        if age==90:
                            emu.capture('title');captures.add('title');emu.audio.clear();audio_name='title-cdda';audio_until=frame+180
                        if age>=280:title_done=True
                    elif age%30==10:keys=[0]
                if t['mode']==2:
                    message=(name,t['pc']-1);messages.add(message)
                    # Let the second opening voice cross the PCM ring boundary.
                    natural=args.listen and not natural_done and name=='ep01_01_openning' and t['pc']==5
                    if age==2:keys=[0]
                    elif natural:
                        if age==5:emu.audio.clear();audio_name='voice-with-bgm';audio_until=frame+600
                        if age==40:emu.capture('opening-dialogue');report['checks']['concurrent_voice_bgm']=(t['flags']&0xA0)==0xA0
                        if age>610:
                            report['checks']['long_voice_finished_bgm_continues']=(t['flags']&0xA0)==0x20
                            natural_done=True;keys=[0]
                    elif age>=12 and age%12==0:keys=[0]
                    if age==8 and name not in captures:
                        emu.capture(name);captures.add(name)
                if t['mode']==3:
                    branch=t['branches'];desired=route[min(branch,len(route)-1)]
                    if age==5:
                        emu.capture(f'choice-{branch+1}');report['choices'].append({'scene':name,'selection':desired})
                    if age>=12 and age%12==0:keys=[5 if t['choice']!=desired else 0]
                if t['completed'] and t['branches']>=2 and name=='eye_catch' and t['pc']>=3 and 'ending' not in captures:
                    emu.capture('ending');captures.add('ending');report['checks']['ending_reached']=True
                    emu.audio.clear();audio_name='ending-cdda';audio_until=frame+140
                if t['completed'] and t['branches']>=2 and name=='logo':
                    report['checks']['returned_to_logo']=True;break
            t=emu.run(1,keys)
            if audio_until and frame>=audio_until:
                metric=emu.audio_metrics(audio_name);report['checks'][audio_name]=metric
                assert min(metric['rms_left'],metric['rms_right'])>100,'Silent '+audio_name
                emu.audio.clear();audio_until=0
            elif not audio_until and frame%120==0:emu.audio.clear()
            if frame%3000==2999:print('Frame',frame+1,t,flush=True)
        else:raise AssertionError('Novel did not finish within frame budget')
        report['messages']=[{'scene':s,'pc':p} for s,p in sorted(messages)]
        report['final_telemetry']=t;report['frames']=frame+1
        assert report['checks'].get('ending_reached') and len(report['choices'])==2
        if args.listen:
            assert natural_done and report['checks']['concurrent_voice_bgm'] and report['checks']['long_voice_finished_bgm_continues']
        report['status']='pass'
    except Exception as e:
        report['status']='fail';report['error']=str(e);report['final_telemetry']=emu.telemetry();emu.capture('failure');raise
    finally:
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');emu.close()
    print('PASS',len(messages),'messages',len(seen),'scenes',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bios',required=True,type=Path);p.add_argument('--route',default='0,0');p.add_argument('--listen',action='store_true');p.add_argument('--max-frames',type=int,default=180000)
    p.add_argument('--core',type=Path,default=ROOT/'.deps/genesis-plus-gx/genesis_plus_gx_libretro.so');p.add_argument('--disc',type=Path,default=ROOT/'dist/ishinoura_ep01/ishinoura_ep01.cue');p.add_argument('--output',type=Path,default=ROOT/'build/novel-validation');run(p.parse_args())
