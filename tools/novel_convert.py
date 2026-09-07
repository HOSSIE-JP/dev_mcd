#!/usr/bin/env python3
"""PCE VN v2 -> MCD VN v1, following MD Game Editor's command semantics.

Conversion only needs Pillow/NumPy; building the committed sample does not.
Unknown commands, missing assets and capacity overflow are hard errors.
"""
import argparse, hashlib, json, math, struct, zlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from assets import ima_encode, tile_bytes

OPS={k:i for i,k in enumerate(('nop','background','sprite','spritemove','message','audio','wait','jump','inputcheck','spritetext','choice','effect','variable','if','switch','goto','video'))}
BUTTONS={'up':1,'down':2,'left':4,'right':8,'i':16,'ii':32,'select':64,'run':128}
NONE=65535
def mdcolor(rgb):
    if rgb=='':rgb='#ffffff'
    if isinstance(rgb,str):rgb=tuple(int(rgb[i:i+2],16) for i in (1,3,5))
    r,g,b=(int(v*7/255+0.5) for v in rgb[:3]);return (b<<9)|(g<<5)|(r<<1)
def padded(b,unit=2048):return b+b'\0'*(-len(b)%unit)
def sha(b):return hashlib.sha256(b).hexdigest()
def paginate(text):
    pages=[];lines=[];line=''
    def commit():
        nonlocal lines,line
        lines.append(line);line=''
        if len(lines)==4:pages.append('\n'.join(lines));lines=[]
    for ch in str(text):
        if ch=='\r':continue
        if ch=='\n':commit();continue
        if len(line)>=(18 if len(lines)==3 else 19):commit()
        line+=ch
    if line or lines or not pages:commit()
    if lines:pages.append('\n'.join(lines))
    return pages
def read_wave(path,rate,stereo=False):
    b=path.read_bytes();assert b[:4]==b'RIFF' and b[8:12]==b'WAVE',path
    chunks={};pos=12
    while pos+8<=len(b):
        n=struct.unpack_from('<I',b,pos+4)[0];chunks[b[pos:pos+4]]=b[pos+8:pos+8+n];pos+=8+n+(n&1)
    fmt,channels,hz,_,_,bits=struct.unpack_from('<HHIIHH',chunks[b'fmt ']);data=chunks[b'data']
    if fmt==1 and bits==16:v=np.frombuffer(data,'<i2').astype(np.float64)/32768
    elif fmt==1 and bits==8:v=(np.frombuffer(data,'u1').astype(np.float64)-128)/128
    elif fmt==3 and bits==32:v=np.frombuffer(data,'<f4').astype(np.float64)
    else:raise ValueError(f'Unsupported WAV format {fmt}/{bits}: {path.name}')
    v=v.reshape(-1,channels)
    if not stereo:v=v.mean(axis=1,keepdims=True)
    elif channels==1:v=np.repeat(v,2,axis=1)
    elif channels!=2:raise ValueError('Only mono/stereo sources supported')
    # Average integer downsampling groups before interpolation to reduce aliasing.
    if hz>=rate*2:
        factor=hz//rate;v=v[:len(v)//factor*factor].reshape(-1,factor,v.shape[1]).mean(axis=1);hz=hz/factor
    n=round(len(v)*rate/hz);x=np.arange(n)*hz/rate
    result=np.stack([np.interp(x,np.arange(len(v)),v[:,c]) for c in range(v.shape[1])],axis=1)
    return np.rint(np.clip(result,-1,32767/32768)*32768).astype('<i2')
def render_psg(options,rate):
    """Render six PCE wavetable/noise voices from the source event pattern.
    Wave IDs select a deterministic approximation (no PCE driver/emulator).
    The approximation is recorded explicitly in the conversion manifest.
    """
    bpm=float(options.get('bpm',120));steps=int(options.get('steps',16))
    step_samples=rate*60/bpm/4;n=round(steps*step_samples)
    events={}
    for e in options.get('pattern',[]):events.setdefault(int(e['step']),[]).append(e)
    states=[{'period':0,'volume':0,'wave':0,'phase':0.0,'noise':0} for _ in range(6)]
    result=np.zeros(n,dtype=np.float64);rng=np.random.default_rng(0)
    for step in range(steps):
        for e in events.get(step,[]):states[int(e.get('channel',0))].update(e)
        start=round(step*step_samples);end=min(n,round((step+1)*step_samples));t=np.arange(end-start)
        for state in states:
            period=int(state.get('period',0));volume=int(state.get('volume',0))
            if period<=0 or volume<=0:continue
            freq=3579545/(32*period);phase=state['phase']+t*freq/rate
            if state.get('noise'):v=rng.choice([-1.,1.],len(t))
            else:
                shape=int(state.get('wave',0))%4
                if shape==0:v=np.sin(phase*2*np.pi)
                elif shape==1:v=np.where(phase%1<0.5,0.75,-0.75)
                elif shape==2:v=1-4*np.abs(phase%1-0.5)
                else:v=(phase%1*2-1)*0.8
            result[start:end]+=v*(volume/31)*0.16
            state['phase']=(state['phase']+len(t)*freq/rate)%1
    return np.rint(np.clip(result,-0.95,0.95)*32767).astype('<i2')
def mima(samples,rate):
    samples=np.asarray(samples).reshape(-1)
    return b'MIMA'+struct.pack('>HHIhBB',1,rate,len(samples),0,0,0)+ima_encode(samples.tolist())
def quantize(image,colors=16,palette=None):
    rgb=image.convert('RGB')
    if palette is None:q=rgb.quantize(colors=colors,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
    else:q=rgb.quantize(palette=palette,dither=Image.Dither.NONE)
    return q
def background(path,full):
    image=Image.open(path).convert('RGB')
    expected=(256,224) if full else (224,136)
    if image.size not in (expected,(320,224)):raise ValueError(f'Background {path.name}: {image.size}, expected {expected} or prepared 320x224')
    canvas=Image.new('RGB',(320,224));canvas.paste(image,(0,0) if image.size==(320,224) else (32,0) if full else (48,8))
    q=quantize(canvas);p=q.getpalette();p+=([0]*(48-len(p)));colors=[mdcolor(p[i*3:i*3+3]) for i in range(16)]
    pixels=np.array(q);tiles=[];indices=[];dedup={}
    for y in range(0,224,8):
        for x in range(0,320,8):
            t=tile_bytes(pixels[y:y+8,x:x+8].reshape(-1).tolist())
            if t not in dedup:dedup[t]=len(tiles);tiles.append(t)
            indices.append(dedup[t])
    if len(tiles)>(896 if full else 511):raise ValueError('Background VRAM budget exceeded')
    return b'MIMG'+struct.pack('>4H',40,28,len(tiles),0)+struct.pack('>16H',*colors)+b''.join(tiles)+struct.pack('>1120H',*indices)
def sprite(path,options,palette,bank):
    image=Image.open(path).convert('RGBA');q=quantize(image,palette=palette)
    indices=np.array(q,dtype=np.uint8);indices[indices>=15]=0
    pixels=indices+1;rgba=np.array(image)
    # PCE sheets use either alpha or their top-left color as transparent index 0.
    transparent=(rgba[:,:,3]<128)|np.all(rgba[:,:,:3]==rgba[0,0,:3],axis=2);pixels[transparent]=0
    p=palette.getpalette();colors=[0]+[mdcolor(p[i*3:i*3+3]) for i in range(15)]
    animations=options.get('animations',[]);frames=[];delays=[];counts=[]
    for row in range(2):
        a=animations[min(row,len(animations)-1)];count=min(2,int(a.get('frameCount',1)));counts.append(count)
        for f in range(2):
            idx=min(f,count-1);crop=pixels[row*128:(row+1)*128,idx*64:(idx+1)*64]
            if crop.shape!=(128,64):raise ValueError('Sprite must contain two 64x128 rows')
            tiles=[]
            # Eight 32x32 hardware sprites, each in VDP column-major tile order.
            for by in range(0,128,32):
                for bx in range(0,64,32):
                    for tx in range(0,32,8):
                        for ty in range(0,32,8):tiles.append(tile_bytes(crop[by+ty:by+ty+8,bx+tx:bx+tx+8].reshape(-1).tolist()))
            frames.append(b''.join(tiles));ds=a.get('frameDelays',[a.get('frameDelay',8)])
            delays.append(max(1,int(ds[min(idx,len(ds)-1)])))
    return b'NSPR'+struct.pack('>6H',bank,*delays,(counts[0]<<8)|counts[1])+struct.pack('>16H',*colors)+b''.join(frames)

def convert(source,font,out,ffmpeg='ffmpeg',ffprobe=None):
    scene_doc=json.loads((source/'assets/pce-vn-scenes.json').read_text('utf-8-sig'))
    catalog=json.loads((source/'assets/pce-assets.json').read_text('utf-8-sig'))['assets'];assets={a['id']:a for a in catalog}
    scenes=scene_doc['scenes'];scene_ids={s['id']:i for i,s in enumerate(scenes)}
    commands=[];scene_rows=[];labels=[];refs=set();fullrefs=set();texts=['▶','はじめる']
    for s in scenes:
        rows=[c for c in s['commands'] if not any(c.get(k) for k in ('skip','skipped','debugSkip')) and c['type']!='comment'];label={};emitted=[]
        for c in rows:
            if c['type']=='label':label[c['name']]=len(emitted);continue
            if c['type'] not in OPS and c['type']!='cache':raise ValueError('Unsupported command '+c['type'])
            emitted.append(c)
            for k in ('assetId','voiceAssetId','animationAssetId'):
                if c.get(k):refs.add(c[k])
            if c['type']=='background' and s.get('fullScreenBg'):fullrefs.add(c['assetId'])
            texts.extend([c.get('text',''),c.get('speaker','')]);texts.extend(o['label'] for o in c.get('choices',[]))
        scene_rows.append((len(commands),len(emitted),scene_ids.get(s.get('nextSceneId'),-1),int(s.get('fullScreenBg',False))))
        commands.extend((i,c) for i,c in [(len(labels),c) for c in emitted]);labels.append(label)
    missing=refs-assets.keys()
    if missing:raise ValueError('Missing assets: '+str(sorted(missing)))
    glyphs=sorted(set(''.join(texts))-{'\r','\n'});gid={c:i for i,c in enumerate(glyphs)}
    if len(glyphs)>1024:raise ValueError('Font cache exceeds 32 KiB')
    f=ImageFont.truetype(str(font),16);font_data=bytearray()
    for ch in glyphs:
        im=Image.new('L',(16,16));ImageDraw.Draw(im).text((0,f.getmetrics()[0]),ch,font=f,fill=255,anchor='ls')
        a=np.array(im)>=80
        for row in a:font_data.extend(struct.pack('>H',sum(int(v)<<(15-i) for i,v in enumerate(row))))
    sprite_assets=[assets[k] for k in sorted(refs) if assets[k]['type']=='sprite']
    # Shared character palette per group leaves palette 3 exclusively for UI.
    palettes={}
    for bank in (1,2):
        images=[Image.open(source/a['source']).convert('RGB') for a in sprite_assets if a.get('mcdPalette',2 if 'ren' in a['id'] else 1)==bank]
        strip=Image.new('RGB',(128,256*max(1,len(images))))
        for i,im in enumerate(images):
            rgb=np.array(im);rgb[np.all(rgb==rgb[0,0],axis=2)]=0;strip.paste(Image.fromarray(rgb),(0,i*256))
        palettes[bank]=quantize(strip,15)
        pal=palettes[bank].getpalette()[:45];pal+=[0]*(45-len(pal));palettes[bank].putpalette(pal+pal[:3]*(256-15))
    payload=bytearray(131072);payload[98304:98304+len(font_data)]=font_data
    resources=[(98304,len(font_data),0,len(glyphs))];resource_ids={};manifest_assets=[];tracks=[]
    out.mkdir(parents=True,exist_ok=True);(out/'cdda').mkdir(exist_ok=True)
    for asset_id in sorted(refs):
        a=assets[asset_id];kind=a['type'];src=source/a['source'] if a.get('source') else None;opt=a.get('options',{})
        aux=0
        if kind=='image':data=background(src,asset_id in fullrefs);rk=1
        elif kind=='sprite':
            bank=a.get('mcdPalette',2 if 'ren' in asset_id else 1);data=sprite(src,opt,palettes[bank],bank);rk=2
        elif kind=='adpcm':data=mima(read_wave(src,11025),11025);rk=3
        elif kind in ('psg-song','psg-sfx'):
            rate=8000 if kind=='psg-song' else 16000;data=mima(render_psg(opt,rate),rate);rk=4 if kind=='psg-song' else 6
        elif kind=='cdda-track':
            pcm=read_wave(src,44100,True).tobytes();pcm=padded(pcm,2352);pcm+=b'\0'*max(0,4*44100*4-len(pcm))
            track=len(tracks)+2;name=f'track{track:02}.pcmz';(out/'cdda'/name).write_bytes(zlib.compress(pcm,9))
            tracks.append({'assetId':asset_id,'track':track,'file':name,'samples':len(pcm)//4,'sha256':sha(pcm),'loop':bool(opt.get('loop'))})
            data=b'';rk=5;aux=track
        elif kind=='video':
            from video_convert import convert_video, validate_video
            video_path=out/(sha(asset_id.encode())[:16]+'.mtv')
            if src.suffix.lower()=='.mtv':
                data=src.read_bytes();validate_video(data)
            else:
                convert_video(src,video_path,profile=opt.get('profile','medium12'),ffmpeg=ffmpeg,ffprobe=ffprobe)
                data=video_path.read_bytes();video_path.unlink()
            rk=7
        else:raise ValueError(f'Unsupported asset type {kind}: {asset_id}')
        if rk in (3,6) and len(padded(data))>131072:raise ValueError('Voice/SFX capacity exceeded: '+asset_id)
        if rk==4 and len(padded(data))>253952:raise ValueError('BGM capacity exceeded: '+asset_id)
        resource_ids[asset_id]=len(resources);offset=len(payload);resources.append((offset,len(data),rk,aux));payload.extend(padded(data))
        manifest_assets.append({'id':asset_id,'kind':kind,'resource':resource_ids[asset_id],'offset':offset,'bytes':len(data),'sha256':sha(data),'source':a.get('source',''),'source_sha256':sha(src.read_bytes()) if src else None})
        if len(manifest_assets)%40==0:print('Converted',len(manifest_assets),'/',len(refs),flush=True)
    scene_offset=48;command_offset=scene_offset+len(scenes)*8;resource_offset=command_offset+len(commands)*32
    pool_offset=resource_offset+len(resources)*12;pool=bytearray();variables={}
    def add(b):
        while len(pool)%2:pool.append(0)
        pos=pool_offset+len(pool);pool.extend(b);return pos
    def string(s):return add(struct.pack('>'+str(len(s)+1)+'H',*[0xFFFE if c=='\n' else gid[c] for c in s],NONE))
    def var(name):
        if name not in variables:variables[name]=len(variables)
        if len(variables)>32:raise ValueError('32 variables maximum')
        return variables[name]
    encoded=[];command_map=[]
    for index,(si,c) in enumerate(commands):
        typ=c['type'];op=OPS.get(typ,0);flags=slot=x=y=frames=aux=count=data=e1=e2=e3=0;target=-1
        slot=int(c.get('slot',0));x=int(c.get('x',0));y=int(c.get('y',0));frames=int(c.get('frames',0))
        if not 0<=slot<=3 and typ in ('sprite','spritemove'):raise ValueError('Renderer supports actor slots 0..3')
        if typ=='background':target=resource_ids[c['assetId']];flags=int(c.get('transition')=='fade')*16;frames=int(c.get('fadeOutFrames',0));aux=int(c.get('fadeInFrames',0))
        elif typ=='sprite':
            target=resource_ids.get(c.get('assetId'),-1);flags=int(c.get('visible',True))|int(c.get('flipX',False))*2|int(c.get('flipY',False))*4
            if target>=0:
                animations=assets[c['assetId']].get('options',{}).get('animations',[])
                requested=c.get('animationId','default')
                matches=[i for i,a in enumerate(animations) if a.get('id','default')==requested]
                if not matches:raise ValueError('Unknown sprite animation: '+str(requested))
                aux=matches[0]
                if aux>1:raise ValueError('MCD supports two sprite animations')
        elif typ=='video':
            if type(c.get('skippable',True)) is not bool:raise ValueError('Video skippable must be Boolean')
            target=resource_ids[c['assetId']];flags=int(c.get('skippable',True))
            if assets[c['assetId']]['type']!='video':raise ValueError('Video command requires video asset')
        elif typ=='spritemove':flags=int(c.get('async',False))*8
        elif typ=='message':
            pages=[string(p) for p in paginate(c.get('text',''))];speaker=string(c.get('speaker',''))
            mouth=c.get('mouthSlot');mouth=-1 if mouth is None else int(mouth)
            data=add(struct.pack('>I4H',speaker,len(pages),mdcolor(c.get('textColor','#ffffff')),resource_ids.get(c.get('voiceAssetId'),NONE),mouth&65535)+struct.pack('>'+str(len(pages))+'I',*pages))
        elif typ=='audio':
            target=resource_ids.get(c.get('assetId'),-1);flags=2 if c.get('action')=='stop' else 1
            aux={'psg':0,'cdda':1,'adpcm':2}[c.get('kind','psg')]
            if target>=0:count=int(assets[c['assetId']].get('options',{}).get('loop',assets[c['assetId']]['type']=='psg-song'))
        elif typ=='jump':target=scene_ids[c['sceneId']]
        elif typ=='inputcheck':
            flags=1 if c.get('mode')=='cancel' else 8 if c.get('mode')=='async' else 0
            aux=sum(BUTTONS[b] for b in set(c.get('buttons',[])));target=labels[si].get(c.get('targetLabel'),-1)
            if c.get('targetLabel') and target<0:raise ValueError('Unresolved input label')
        elif typ=='spritetext':data=string(c.get('text',''));flags=int(c.get('visible',True));aux=mdcolor(c.get('color','#ffffff'));frames=int(c.get('blinkFrames',0))
        elif typ=='choice':
            options=c['choices'];count=len(options);aux=var(c.get('variableName','choice'));target=int(c.get('defaultIndex',0))
            if not 1<=count<=4:raise ValueError('1..4 choices required')
            data=add(b''.join(struct.pack('>Ihh',string(o['label']),scene_ids.get(o.get('targetSceneId'),-1),int(o.get('value',i+1))) for i,o in enumerate(options)))
        elif typ=='effect':aux=['fadeOut','fadeIn','blank','shake','flash'].index(c.get('effect','shake'));x=int(c.get('intensity',4));e1=mdcolor(c.get('color','#ffffff'))
        elif typ=='variable':
            target=var(c.get('variableName',c.get('name',c.get('variable',''))));aux=['define','set','add','sub','random'].index(c.get('operation','set'));x=int(c.get('value',0));y=0
            if aux==4:x,y=sorted([int(c.get('min',0)),int(c.get('max',9))])
        elif typ in ('if','goto','switch'):
            def label(name):
                if not name:return -1
                if name not in labels[si]:raise ValueError('Unknown label '+name)
                return labels[si][name]
            if typ=='goto':target=label(c.get('targetLabel'))
            else:
                target=var(c.get('variableName',c.get('name',c.get('variable',''))))
                if typ=='if':
                    flags=['eq','ne','lt','lte','gt','gte'].index(c.get('operator','eq'));aux=int(c.get('value',0))&65535;x=label(c.get('targetLabel'));y=label(c.get('elseLabel'))
                else:
                    rows=c.get('cases',[]);count=len(rows);x=label(c.get('defaultLabel'))
                    if count>16:raise ValueError('Maximum 16 switch cases')
                    data=add(b''.join(struct.pack('>hh',int(row.get('value',0)),label(row.get('targetLabel'))) for row in rows))
        encoded.append(struct.pack('>BBHhhHhHHIIII',op,flags,slot,x,y,frames,target,aux,count,data,e1,e2,e3))
        command_map.append({'index':index,'scene':scenes[si]['id'],'pc':index-scene_rows[si][0],'type':typ})
    script=bytearray(48)+b''.join(struct.pack('>HHhH',*r) for r in scene_rows)+b''.join(encoded)+b''.join(struct.pack('>IIHH',*r) for r in resources)+pool
    settings=scene_doc.get('settings',{})
    struct.pack_into('>4s10H6I',script,0,b'MNVN',1,len(scenes),len(commands),scene_ids[scene_doc['startScene']],int(settings.get('messageSpeedFrames',10)),int(settings.get('messageAdvanceMode')=='auto'),int(settings.get('messageAutoWaitFrames',60)),len(resources),len(variables),gid['▶'],scene_offset,command_offset,resource_offset,len(script),len(font_data),0)
    if len(script)>98304:raise ValueError('Script cache exceeds 96 KiB')
    payload[:len(script)]=script;(out/'novel.pak').write_bytes(payload)
    manifest={'format':'MCD-NVN-1','source_repositories':{'md-game-editor':'26f0cda3d9869acd3c44961d89e42e102af6381d','pce-novel-game-projects':'6e0ff601e7ac2af69ce39677b623781ff01f1e0c'},'title':'いしのうらにいる！？ 第1話 部室の白い箱','scenes':[{'id':s['id'],'index':i,'commands':scene_rows[i][1]} for i,s in enumerate(scenes)],'script_bytes':len(script),'glyphs':len(glyphs),'commands':len(commands),'variables':variables,'pack_bytes':len(payload),'pack_sha256':sha(payload),'tracks':tracks,'assets':manifest_assets,'command_map':command_map,'conversion_notes':['PCE legacy coordinates centered in a 320x224 viewport.','Japanese font uses JF-Dot-Shinonome16, 19 columns x 4 lines.','Character palettes: one shared 15-color palette for Mu/Chika, one for Ren.','PSG patterns rendered to 8 kHz mono IMA; waveform IDs use documented approximations.','Voice: 11.025 kHz mono IMA; short SFX: 16 kHz. No duration truncation.']}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'scenario.json').write_text(json.dumps(scene_doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Converted',len(scenes),'scenes,',len(commands),'commands,',len(glyphs),'glyphs,',len(payload),'pack bytes',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--font',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--ffmpeg',default='ffmpeg');p.add_argument('--ffprobe');a=p.parse_args();convert(a.source,a.font,a.output,a.ffmpeg,a.ffprobe)
