/* Standalone MCD implementation of the MD Game Editor VN command model.
 * Scripts/font/actor sheets live in Word RAM; target code stays in Work RAM.
 * No editor code, SGDK binary or firmware is linked into the game. */
#include <mcd/novel.h>
#include <mcd/video.h>
#define WORD ((u8 *)0x200000UL)
#define FONT ((const u16 *)(WORD+0x18000))
#define SCRATCH (WORD+0x30000)
#define MEMMODE (*(volatile u8 *)0xA12003)
#define VC (*(volatile u32 *)0xC00004)
#define VR (*(volatile u16 *)0xC00004)
#define VD (*(volatile u16 *)0xC00000)
#define NONE 65535
#define ADVANCE (BUTTON_B|BUTTON_C|BUTTON_START)
enum {RUN,WAIT,MESSAGE,CHOICE,MOVE,EFFECT,INPUT,HALT,LOADING};
typedef struct {
  s16 asset,x,y,sx,sy,tx,ty;
  u16 flags,anim,shown,timer,elapsed,duration,bank,counts,delays[4];
  bool moving;
} Actor;
typedef struct {
  u32 magic,frame;
  u16 scene,current_pc,mode,error,page,choice,flags,io_count,voice_count,bgm_count;
  u16 branches,completed,variable0,variable1,resource,underruns;
} Telemetry;
static volatile Telemetry *const trace=(volatile Telemetry *)0xFFF000;
static Actor actors[4];
static s16 background_asset=-1;
static u16 cdda_track;
static bool cdda_repeat;
static s16 bgm_asset=-1;
static bool bgm_repeat;
static u16 scene,current_pc,mode,error,scene_count,command_count,resource_count,font_count;
static u16 speed,auto_wait,wait_counter,old_buttons,buttons,pressed,watch_mask,watch_target;
static u16 page_index,page_count,reveal,total_chars,message_timer,choice_count,selected,choice_variable;
static u16 mouth=NONE,st_blink,st_x,st_y,st_color,effect_kind,effect_duration,effect_elapsed;
static s16 effect_intensity;
static s16 variables[32];
static u32 scenes_offset,commands_offset,resources_offset,script_size,message_data,page_text,choice_data,st_text;
static u32 frame;
static bool auto_mode,st_visible,st_shown;
static u16 colors[64],display_colors[64],arrow_glyph;
static s16 clamp16(s32 v) {return v<-32768?-32768:v>32767?32767:v;}
static u16 be16(const void *v) {const u8 *p=v;return ((u16)p[0]<<8)|p[1];}
static u32 be32(const void *v) {return ((u32)be16(v)<<16)|be16((const u8 *)v+2);}
static void vram(u16 a) {VC=0x40000000UL|((u32)(a&0x3FFF)<<16)|(a>>14);}
static void palette(u16 bank,const u16 *p) {
  for(u16 i=0;i<16;++i)colors[bank*16+i]=display_colors[bank*16+i]=p[i];
  PAL_setPalette(bank,p);
}
static void cell(u16 x,u16 y,u16 value) {vram(0xC000+y*128+x*2);VD=value;}
static void clear_ui(void) {
  for(u16 y=0;y<28;++y) {vram(0xC000+y*128);for(u16 x=0;x<40;++x)VD=0;}
}
static void draw_glyph(u16 glyph,u16 x,u16 y,u16 position,u16 ink) {
  u16 tile=1024+position*4;
  if(glyph>=font_count || x>38 || y>26 || position>=96)return;
  vram(tile*32);
  for(u16 ty=0;ty<2;++ty)for(u16 tx=0;tx<2;++tx)for(u16 row=0;row<8;++row) {
    u16 bits=FONT[glyph*16+ty*8+row]<<(tx*8);
    for(u16 group=0;group<2;++group) {
      u16 value=0;for(u16 bit=0;bit<4;++bit) {value=(value<<4)|((bits&0x8000)?ink:0);bits<<=1;}VD=value;
    }
  }
  cell(x,y,0xE000|tile);cell(x+1,y,0xE000|(tile+1));
  cell(x,y+1,0xE000|(tile+2));cell(x+1,y+1,0xE000|(tile+3));
}
static u16 draw_from;
static u16 draw_string(u32 offset,u16 x,u16 y,u16 position,u16 limit,u16 ink) {
  u16 count=0,start=x;const u16 *p=(const u16 *)(WORD+offset);
  if(offset>=script_size)return 0;
  while(*p!=NONE && count<limit) {
    u16 glyph=*p++;
    if(glyph==0xFFFE) {x=start;y+=2;position=((position/19)+1)*19;continue;}
    if(count>=draw_from)draw_glyph(glyph,x,y,position,ink);
    ++position;x+=2;++count;
  }
  return count;
}
static void upload_actor(u16 slot,u16 f) {
  const u16 *p=(const u16 *)(WORD+0x20000UL+slot*0x4000UL+f*4096UL);
  vram((512+slot*128)*32);for(u16 i=0;i<2048;++i)VD=*p++;
}
static void sprite_table(void) {
  u16 sat[4*8*4],n=0;
  for(u16 s=0;s<4;++s) {
    Actor *a=&actors[s];if(a->asset<0 || !(a->flags&1))continue;
    u16 bank=a->bank;
    for(u16 y=0;y<4;++y)for(u16 x=0;x<2;++x) {
      u16 piece=y*2+x;
      s16 px=a->x+32+((a->flags&2)?(1-x):x)*32;
      s16 py=a->y+((a->flags&4)?(3-y):y)*32;
      sat[n*4]=(py+128)&1023;sat[n*4+1]=0x0F00|(n+1);
      sat[n*4+2]=0x8000|(bank<<13)|(a->flags&2?0x0800:0)|(a->flags&4?0x1000:0)|(512+s*128+piece*16);
      sat[n*4+3]=(px+128)&511;++n;
    }
  }
  if(n)sat[(n-1)*4+1]&=0xFF00;
  vram(0xF000);
  if(!n) {VD=0;VD=0;VD=0;VD=0;}
  else for(u16 i=0;i<n*4;++i)VD=sat[i];
}
static bool animate(void) {
  bool moving=false;
  for(u16 i=0;i<4;++i) {
    Actor *a=&actors[i];u16 row,counts,f,delay;
    if(a->asset<0 || !(a->flags&1))continue;
    if(a->moving) {
      if(++a->elapsed>=a->duration) {a->x=a->tx;a->y=a->ty;a->moving=false;}
      else {a->x=a->sx+(s32)(a->tx-a->sx)*a->elapsed/a->duration;a->y=a->sy+(s32)(a->ty-a->sy)*a->elapsed/a->duration;moving=true;}
    }
    row=(mode==MESSAGE && mouth==i && (reveal<total_chars || (MCD_getAudioFlags()&MCD_STREAM_VOICE_PLAYING)))?1:a->anim;
    counts=a->counts;counts=row?(counts&255):(counts>>8);
    f=a->shown;
    if(f/2!=row) {f=row*2;a->timer=0;}
    delay=a->delays[f];
    if(++a->timer>=delay) {a->timer=0;f=row*2+((f+1)%counts);}
    if(f!=a->shown && (MEMMODE&1)) {upload_actor(i,f);a->shown=f;}
  }
  sprite_table();return moving;
}
static void tick(void) {
  SYS_doVBlankProcess();++frame;
  buttons=JOY_readJoypad(JOY_1);pressed=buttons&~old_buttons;old_buttons=buttons;
  trace->frame=frame;trace->scene=scene;trace->current_pc=current_pc;trace->mode=mode;trace->error=error;
  trace->page=page_index;trace->choice=selected;trace->flags=MCD_getAudioFlags();
  trace->underruns=(MCD_getAudioFlags()&MCD_STREAM_UNDERRUN)>>8;
  trace->variable0=variables[0];trace->variable1=variables[1];
}
static bool io_done(bool accepted) {
  u16 saved=mode;mode=LOADING;
  if(!accepted) {error=MCD_ERR_BUSY;mode=HALT;return false;}
  ++trace->io_count;
  while(MCD_isBusy()) {tick();animate();}
  if(MCD_getResult()) {error=MCD_getResult();mode=HALT;return false;}
  mode=saved;return true;
}
static const u8 *resource(u16 index) {
  if(index>=resource_count) {error=MCD_ERR_ARGUMENT;mode=HALT;return WORD;}
  trace->resource=index;return WORD+resources_offset+(u32)index*12;
}
static bool read_asset(u16 id,u16 destination) {
  const u8 *p=resource(id);u32 offset=be32(p),size=be32(p+4);
  return io_done(MCD_readRangeAsync(offset,size,destination));
}
static bool play_stream(u16 id,u16 channel,bool loop) {
  const u8 *p=resource(id);u32 offset=be32(p),size=be32(p+4);
  if(!io_done(MCD_prepareStreamAsync(offset,size,channel,loop)))return false;
  if(!io_done(MCD_playStream(channel)))return false;
  if(channel)++trace->voice_count;else {++trace->bgm_count;bgm_asset=id;bgm_repeat=loop;}
  return true;
}
static void fade(u16 duration,bool in) {
  u16 p[16];if(!duration)return;
  for(u16 step=0;step<=duration;++step) {
    tick();u16 scale=in?step:duration-step;
    for(u16 b=0;b<4;++b) {
      for(u16 c=0;c<16;++c) {u16 v=colors[b*16+c];p[c]=((((v>>9)&7)*scale/duration)<<9)|((((v>>5)&7)*scale/duration)<<5)|((((v>>1)&7)*scale/duration)<<1);}
      for(u16 c=0;c<16;++c)display_colors[b*16+c]=p[c];
      PAL_setPalette(b,p);
    }
  }
}
static void enter_scene(u16 index) {
  if(index>=scene_count) {error=MCD_ERR_ARGUMENT;mode=HALT;return;}
  scene=index;current_pc=0;watch_mask=0;mouth=NONE;mode=RUN;st_text=0;st_visible=st_shown=false;clear_ui();
  const u8 *s=WORD+scenes_offset+scene*8;
  for(u16 i=0;i<4;++i) {
    actors[i].moving=false;
    if(be16(s+6)) {actors[i].asset=-1;actors[i].flags=0;}
  }
  sprite_table();
}
static void prepare_page(void) {
  u16 ui[16]={0};ui[1]=be16(WORD+message_data+6);ui[2]=0xEEE;palette(3,ui);
  clear_ui();draw_string(be32(WORD+message_data),1,18,0,19,2);
  page_text=be32(WORD+message_data+12+page_index*4);reveal=0;total_chars=0;message_timer=0;
  const u16 *p=(const u16 *)(WORD+page_text);while(*p!=NONE) {if(*p!=0xFFFE)++total_chars;++p;}
  mode=MESSAGE;
}
static void choices_draw(void) {
  u16 ui[16]={0};ui[1]=0xEEE;ui[2]=0x0EE;palette(3,ui);clear_ui();
  for(u16 i=0;i<choice_count;++i) {
    draw_glyph(i==selected?arrow_glyph:arrow_glyph,1,18+i*2,i*19,i==selected?2:0);
    draw_string(be32(WORD+choice_data+i*8),3,18+i*2,i*19+1,18,i==selected?2:1);
  }
}
/* Video and its restoration cooperate with CD I/O without advancing the VN
 * clock, watched inputs, actor movement, mouth animation or auto-message timer. */
static bool frozen_io(bool accepted) {
  if(!accepted) {error=MCD_getResult()?MCD_getResult():MCD_ERR_BUSY;return false;}
  while(MCD_isBusy())SYS_doVBlankProcess();
  if(MCD_getResult()) {error=MCD_getResult();return false;}
  return true;
}
static bool frozen_asset(u16 id) {
  const u8 *r=resource(id);if(mode==HALT)return false;
  u32 offset=be32(r),bytes=be32(r+4);
  return frozen_io(MCD_readRangeAsync(offset,bytes,96));
}
static bool restore_video_scene(void) {
  /* The video bank at A000 overwrites some dynamic glyph tiles. Recreate UI
   * from resident font and text; all four pixel-only actor caches survive. */
  VR=0x8124;VR=0x8230;VR=0x8407;VR=0x8578;VR=0x8D3F;VR=0x9001;
  if(background_asset>=0) {
    if(!frozen_asset(background_asset))return false;
    u32 bytes=be32(resource(background_asset)+4);
    error=VDP_drawImage(BG_B,SCRATCH,bytes);if(error)return false;
    VR=0x8124;
  } else {
    for(u16 y=0;y<28;++y) {vram(0xE000+y*128);for(u16 x=0;x<40;++x)VD=0;}
  }
  for(u16 i=0;i<4;++i) {
    if(actors[i].asset>=0 && (actors[i].flags&1))upload_actor(i,actors[i].shown);
    PAL_setPalette(i,display_colors+i*16);
  }
  clear_ui();sprite_table();
  if(st_text && st_visible && st_shown) {draw_from=0;draw_string(st_text,st_x,st_y,0,19,1);}
  vram(0xFC00);VD=0;VD=0;VR=0x8164;
  return true;
}
static void play_video(u16 id,bool can_skip) {
  const u8 *r=resource(id);if(mode==HALT)return;
  if(be16(r+8)!=7) {error=MCD_ERR_FORMAT;mode=HALT;return;}
  u32 offset=be32(r),bytes=be32(r+4);
  bool restore_cdda=cdda_track && (MCD_getAudioFlags()&MCD_CDDA_REQUESTED);
  bool restore_bgm=bgm_asset>=0 && (MCD_getAudioFlags()&MCD_STREAM_BGM_PLAYING);
  MCDVideoStatus status;u16 result=MCD_playVideo(offset,bytes,can_skip,&status);
  /* On a timed-out write request Word RAM may still belong to Sub. Halting
   * without touching resident pointers is mandatory even when skipped. */
  if(result==MCD_ERR_TIMEOUT || !MCD_getWordRAM()) {error=result?result:MCD_ERR_NOT_READY;mode=HALT;return;}
  if(!restore_video_scene()) {mode=HALT;return;}
  if(restore_bgm) {
    const u8 *b=resource(bgm_asset);u32 bg_offset=be32(b),bg_bytes=be32(b+4);
    if(!frozen_io(MCD_prepareStreamAsync(bg_offset,bg_bytes,0,bgm_repeat)) || !frozen_io(MCD_playStream(0))) {mode=HALT;return;}
  }
  if(restore_cdda && !frozen_io(MCD_playCDDA(cdda_track,cdda_repeat))) {mode=HALT;return;}
  /* Remember the held state so skip cannot advance the following message. */
  buttons=old_buttons=JOY_readJoypad(JOY_1);pressed=0;
  error=result;if(result)mode=HALT;
}
static void execute(void) {
  const u8 *s=WORD+scenes_offset+scene*8;
  if(current_pc>=be16(s+2)) {s16 next=be16(s+4);if(next>=0)enter_scene(next);else mode=HALT;return;}
  const u8 *c=WORD+commands_offset+((u32)be16(s)+current_pc)*32;
  u16 op=c[0],flags=c[1],slot=be16(c+2),frames=be16(c+8),aux=be16(c+12),count=be16(c+14);
  s16 x=be16(c+4),y=be16(c+6),target=be16(c+10);u32 data=be32(c+16);
  ++current_pc;
  switch(op) {
  case 0:break;
  case 1: {
    if(flags&16)fade(frames,false);
    if(!read_asset(target,96))return;
    u16 p[16];for(u16 i=0;i<16;++i)p[i]=be16(SCRATCH+12+i*2);
    u32 n=be32(resource(target)+4);error=VDP_drawImage(BG_B,SCRATCH,n);
    if(error) {mode=HALT;return;}palette(0,p);background_asset=target;
    if(flags&16)fade(aux,true);
    break;
  }
  case 2: {
    if(slot>3) {error=MCD_ERR_ARGUMENT;mode=HALT;return;}
    Actor *a=&actors[slot];a->flags=flags;a->x=x;a->y=y;a->anim=aux?1:0;a->moving=false;
    if(!(flags&1)) {sprite_table();break;}
    if(target<0) {error=MCD_ERR_ARGUMENT;mode=HALT;return;}
    if(a->asset!=target) {
      if(!read_asset(target,96))return;
      if(be32(SCRATCH)!=0x4E535052UL || be32(resource(target)+4)!=16432) {error=MCD_ERR_FORMAT;mode=HALT;return;}
      /* Four 16 KiB pixel-only caches fill 0x20000..0x2ffff.
       * Metadata is retained in Actor, leaving all 64 KiB scratch intact. */
      u16 *dest=(u16 *)(WORD+0x20000UL+slot*0x4000UL);const u16 *src=(const u16 *)(SCRATCH+48);
      for(u16 i=0;i<8192;++i)dest[i]=src[i];
      a->asset=target;
      a->bank=be16(SCRATCH+4);a->counts=be16(SCRATCH+14);
      for(u16 i=0;i<4;++i)a->delays[i]=be16(SCRATCH+6+i*2);
      u16 p[16];for(u16 i=0;i<16;++i)p[i]=be16(SCRATCH+16+i*2);palette(be16(SCRATCH+4),p);
    }
    a->shown=a->anim*2;a->timer=0;upload_actor(slot,a->shown);sprite_table();break;
  }
  case 3: {
    if(slot>3) {error=MCD_ERR_ARGUMENT;mode=HALT;return;}
    Actor *a=&actors[slot];a->sx=a->x;a->sy=a->y;a->tx=x;a->ty=y;a->duration=frames?frames:1;a->elapsed=0;a->moving=true;
    if(!(flags&8))mode=MOVE;
    break;
  }
  case 4: {
    message_data=data;page_index=0;page_count=be16(WORD+data+4);mouth=be16(WORD+data+10);
    u16 voice=be16(WORD+data+8);
    if(voice!=NONE && !play_stream(voice,1,false))return;
    prepare_page();break;
  }
  case 5: {
    if(flags&2) {
      if(aux==1) {if(io_done(MCD_stopCDDA()))cdda_track=0;}
      else {if(!io_done(MCD_stopStream(0)))return;bgm_asset=-1;io_done(MCD_stopStream(1));}
    } else if(target>=0) {
      const u8 *r=resource(target);u16 kind=be16(r+8);
      if(kind==5) {u16 track=be16(r+10);if(io_done(MCD_playCDDA(track,count!=0))) {cdda_track=track;cdda_repeat=count!=0;}}
      else play_stream(target,kind==4?0:1,count!=0);
    }break;
  }
  case 6:wait_counter=frames;if(frames)mode=WAIT;break;
  case 7:enter_scene(target);break;
  case 8:
    if(flags&1)watch_mask=0;
    else {watch_mask=aux;watch_target=target;if(!(flags&8))mode=INPUT;}break;
  case 9:
    clear_ui();st_text=data;st_x=(x+32)/8;st_y=y/8;st_color=aux;st_blink=frames;st_visible=(flags&1)!=0;st_shown=false;break;
  case 10:
    choice_count=count;selected=target;choice_data=data;choice_variable=aux;
    if(!choice_count || choice_count>4 || selected>=choice_count || aux>=32) {error=MCD_ERR_FORMAT;mode=HALT;return;}
    mode=CHOICE;choices_draw();break;
  case 11:
    effect_kind=aux;effect_duration=frames;effect_elapsed=0;effect_intensity=x;
    if(aux==0)fade(frames,false);else if(aux==1)fade(frames,true);else if(aux==2)clear_ui();else mode=EFFECT;break;
  case 12:
    if(target<0 || target>=32) {error=MCD_ERR_ARGUMENT;mode=HALT;return;}
    if(aux<2)variables[target]=x;else if(aux==2)variables[target]=clamp16((s32)variables[target]+x);else if(aux==3)variables[target]=clamp16((s32)variables[target]-x);
    else variables[target]=x+(frame%((u16)(y-x)+1UL));
    break;
  case 13: {
    if(target<0 || target>=32) {error=MCD_ERR_ARGUMENT;mode=HALT;return;}
    s16 v=variables[target],rhs=aux;bool yes=flags==0?v==rhs:flags==1?v!=rhs:flags==2?v<rhs:flags==3?v<=rhs:flags==4?v>rhs:v>=rhs;
    s16 branch=yes?x:y;if(branch>=0)current_pc=branch;break;
  }
  case 14: {
    if(target<0 || target>=32 || count>16) {error=MCD_ERR_ARGUMENT;mode=HALT;return;}
    s16 branch=x;for(u16 i=0;i<count;++i)if((s16)be16(WORD+data+i*4)==variables[target]) {branch=be16(WORD+data+i*4+2);break;}
    if(branch>=0)current_pc=branch;
    break;
  }
  case 15:if(target>=0)current_pc=target;break;
  case 16:play_video(target,(flags&1)!=0);break;
  default:error=MCD_ERR_FORMAT;mode=HALT;break;
  }
}
void NOVEL_run(void) {
  MCD_init();trace->magic=0x4E564E31UL;frame=0;mode=LOADING;
  for(u16 i=0;i<4;++i)actors[i].asset=-1;
  VR=0x8200|0x30;VR=0x8400|7;VR=0x8500|0x78;VR=0x8D00|0x3F;
  clear_ui();sprite_table();VDP_drawText("LOADING NOVEL FROM CD",6,13);
  if(!io_done(MCD_readRangeAsync(0,98304,0)))goto failed;
  if(be32(WORD)!=0x4D4E564EUL || be16(WORD+4)!=1) {error=MCD_ERR_FORMAT;goto failed;}
  scene_count=be16(WORD+6);command_count=be16(WORD+8);speed=be16(WORD+12);
  auto_mode=be16(WORD+14)!=0;auto_wait=be16(WORD+16);resource_count=be16(WORD+18);arrow_glyph=be16(WORD+22);
  scenes_offset=be32(WORD+24);commands_offset=be32(WORD+28);resources_offset=be32(WORD+32);script_size=be32(WORD+36);
  if(script_size>98304 || scenes_offset+scene_count*8UL>script_size || commands_offset+command_count*32UL>script_size || resources_offset+resource_count*12UL>script_size) {error=MCD_ERR_FORMAT;goto failed;}
  font_count=be16(resource(0)+10);
  if(!font_count || font_count>1024 || !read_asset(0,48))goto failed;
  enter_scene(be16(WORD+10));
  for(;;) {
    tick();
    if(mode==HALT)continue;
    bool moving=animate();
    if(pressed&BUTTON_A)auto_mode=!auto_mode;
    if(watch_mask && (pressed&watch_mask)) {
      if(watch_target!=NONE)current_pc=watch_target;
      mode=RUN;watch_mask=0;wait_counter=0;
    }
    if(st_text && st_visible && mode!=MESSAGE && mode!=CHOICE) {
      bool show=!st_blink || (frame/st_blink)%2==0;
      if(show!=st_shown) {
        clear_ui();st_shown=show;
        if(show) {u16 p[16]={0};p[1]=st_color;palette(3,p);draw_string(st_text,st_x,st_y,0,19,1);}
      }
    }
    switch(mode) {
    case RUN:execute();break;
    case WAIT:if(wait_counter && !--wait_counter)mode=RUN;break;
    case MOVE:if(!moving)mode=RUN;break;
    case MESSAGE:
      ++message_timer;
      if(reveal<total_chars) {
        u16 before=reveal;
        if(pressed&ADVANCE)reveal=total_chars;
        else if(!speed || message_timer%speed==0)++reveal;
        if(before!=reveal) {draw_from=before;draw_string(page_text,1,20,19,reveal,1);draw_from=0;}
        if(reveal==total_chars)message_timer=0;
      } else if((pressed&ADVANCE) || (auto_mode && message_timer>=auto_wait && !(MCD_getAudioFlags()&MCD_STREAM_VOICE_PLAYING))) {
        if(++page_index<page_count)prepare_page();
        else {mouth=NONE;if(io_done(MCD_stopStream(1))) {clear_ui();mode=RUN;}}
      }
      break;
    case CHOICE:
      if(pressed&BUTTON_UP) {selected=(selected+choice_count-1)%choice_count;choices_draw();}
      if(pressed&BUTTON_DOWN) {selected=(selected+1)%choice_count;choices_draw();}
      if(pressed&ADVANCE) {
        variables[choice_variable]=(s16)be16(WORD+choice_data+selected*8+6);++trace->branches;
        s16 next=be16(WORD+choice_data+selected*8+4);if(next>=0)enter_scene(next);else {clear_ui();mode=RUN;}
      }break;
    case EFFECT:
      if(effect_kind==3) {s16 shift=(effect_elapsed&1)?effect_intensity:-effect_intensity;vram(0xFC00);VD=shift;VD=shift;}
      if(++effect_elapsed>=effect_duration) {vram(0xFC00);VD=0;VD=0;mode=RUN;}break;
    default:break;
    }
    if(scene==scene_count-1)trace->completed=1;
  }
failed:
  mode=HALT;if(!error)error=MCD_ERR_FORMAT;
  for(;;)tick();
}
