/* Native adapter for the original MTV1 demux / bounded VRAM upload core.
 * Uses two 62 KiB Word windows backed by asynchronous Sub PRG read-ahead.
 * Four resident actor caches are saved in Sub PRG for the duration; resident
 * script/font Word memory is never overwritten. */
#include <mcd/video.h>
#include <mcd/video_upload.h>
#define DESCRIPTORS_OFFSET 0x30000UL
#define CACHE_BYTES 63488UL
#define AUDIO_CAPACITY 65279UL
#define VC (*(volatile u32 *)0xC00004)
#define VR (*(volatile u16 *)0xC00004)
#define VD (*(volatile u16 *)0xC00000)
#define MEMMODE (*(volatile u8 *)0xA12003)
#define SKIP_BUTTONS (BUTTON_B|BUTTON_C|BUTTON_START)
#define VBLANK_BYTES 2048

typedef struct {const u8 *data;u32 start,bytes,limit;} VideoCache;
typedef struct {
  u32 offset,bytes,clockBase,fedSamples,feedCursor,nextCursor;
  u32 silentClock,silentRemainder,clockValue;
  u16 oldButtons,lastTick,clockTick;
  /* Word-sized control flags avoid GCC store merging an odd-address pair
   * of _Bool fields into an illegal M68000 word store. */
  u16 skipEnabled,skipped,audio,audioStarted,audioOpen,sourceOpen,workspaceSaved;
  VideoCache cache[2];
  MCDV_Header header;
  MCDVideoStatus status;
  u32 fedFrames;
} Playback;
static void vram(u16 a) {VC=0x40000000UL|((u32)(a&0x3FFF)<<16)|(a>>14);}
static void poll(Playback *p) {
  u16 now=JOY_readJoypad(JOY_1);
  if(p->skipEnabled && ((now&~p->oldButtons)&SKIP_BUTTONS))p->skipped=true;
  p->oldButtons=now;
}
static void step(Playback *p) {SYS_doVBlankProcess();poll(p);}
static void publish(Playback *p,u16 bank) {
  /* Reuse the last upload/PTS wait's VBlank when ample time remains. The
   * inactive tile/map/palette transfers are already complete; only this
   * register store is left. Late blank or active display waits normally.
   * HV is sampled before status so a crossed frame boundary rejects reuse. */
  u16 line=(*(volatile u16 *)0xC00008)>>8;
  if(!MCDV_canPublishNtsc224(VR,line))step(p);
  VR=bank?0x8407:0x8405;
}
static u16 complete(Playback *p,bool accepted) {
  if(!accepted)return MCD_getResult()?MCD_getResult():MCD_ERR_BUSY;
  while(MCD_isBusy())step(p);
  return MCD_getResult();
}
static u16 load_cache(Playback *p,u32 cursor,u16 window) {
  u32 start=cursor&~2047UL,n;
  if(start>=p->bytes)return MCD_ERR_SIZE;
  n=p->bytes-start;if(n>CACHE_BYTES)n=CACHE_BYTES;
  u16 sector=window?97:65;
  u16 result=complete(p,MCD_videoSourceReadAsync(start,n,sector));
  if(result)return result;
  const u8 *word=MCD_getWordRAM();if(!word)return MCD_ERR_NOT_READY;
  p->cache[window].data=word+(u32)sector*2048;
  p->cache[window].start=start;p->cache[window].bytes=n;
  ++p->status.cacheReads;return MCD_OK;
}
static const u8 *cached(const Playback *p,u32 cursor,u32 n) {
  for(u16 i=0;i<2;++i) {
    const VideoCache *c=&p->cache[i];
    if(c->data && cursor>=c->start && cursor-c->start<=c->bytes && n<=c->bytes-(cursor-c->start))
      return c->data+cursor-c->start;
  }
  return 0;
}
/* Locate complete records without repeating payload scans. Full frame
 * validation still runs before PCM submission and display. */
static u16 scan_cache(Playback *p,u32 cursor,u16 window) {
  VideoCache *c=&p->cache[window];
  while(cursor>=c->start && cursor-c->start+32<=c->bytes) {
    const u8 *record=c->data+cursor-c->start;
    if(MCDV_be32(record)!=0x46524D31UL) {
      if(p->bytes-cursor<=2047)break;
      return MCD_ERR_FORMAT;
    }
    u32 n=MCDV_be32(record+4);
    if(n<64 || n>p->header.max_record || (n&1))return MCD_ERR_FORMAT;
    if(n>c->bytes-(cursor-c->start))break;
    cursor+=n;
  }
  c->limit=cursor;p->nextCursor=cursor;return MCD_OK;
}
static u16 frame_at(Playback *p,u32 cursor,u32 sequence,MCDV_Frame *f) {
  const u8 *record=cached(p,cursor,32);u32 bytes;
  if(!record)return MCD_ERR_SIZE;
  bytes=MCDV_be32(record+4);
  if(bytes<64 || bytes>p->header.max_record || (bytes&1))return MCD_ERR_FORMAT;
  record=cached(p,cursor,bytes);if(!record)return MCD_ERR_SIZE;
  return MCDV_parseFrame(&p->header,record,bytes,sequence,0,f)?MCD_ERR_FORMAT:MCD_OK;
}
static void clear_scene(void) {
  VR=0x8124; /* display off for initial setup only; VBlank/INT2 remain enabled */
  VR=0x8230;VR=0x8405;VR=0x8578;VR=0x8D3F;VR=0x8B00;VR=0x9001;VR=0x9100;VR=0x9200;VR=0x8700;
  vram(0);for(u16 i=0;i<16;++i)VD=0;
  for(u16 y=0;y<32;++y)for(u16 bank=0;bank<3;++bank) {
    vram((bank==0?0xA000:bank==1?0xC000:0xE000)+y*128);
    for(u16 x=0;x<64;++x)VD=0;
  }
  vram(0xF000);for(u16 i=0;i<4;++i)VD=0;
  vram(0xFC00);VD=0;VD=0;
  VC=0x40000010UL;VD=0;VD=0; /* vertical scroll zero */
  VR=0x8164;
}
static u16 upload(Playback *p,const MCDV_Frame *frame,u16 bank) {
  MCDV_UploadPlan plan;MCDV_Upload transfer;
  if(MCDV_uploadBegin(&plan,&p->header,frame,bank))return MCD_ERR_FORMAT;
  while(!MCDV_uploadComplete(&plan) && !p->skipped) {
    step(p);u16 budget=VBLANK_BYTES;
    while(MCDV_uploadNext(&plan,budget,&transfer)) {
      if(transfer.kind==MCDV_UPLOAD_CRAM)VC=0xC0000000UL|((u32)transfer.destination<<16);
      else vram(transfer.destination);
      /* MTV1 records and upload-plan rows are even-aligned. The target is
       * big-endian, so avoid a portable byte decoder call for every VDP word. */
      const u16 *words=(const u16 *)transfer.source;
      for(u16 count=transfer.bytes>>1;count;--count)VD=*words++;
      budget-=transfer.bytes;
    }
  }
  return MCD_OK;
}
static u16 clock_read(Playback *p,u32 *clock) {
  if(p->audio) {
    u16 result=complete(p,MCD_videoAudioClockAsync());
    *clock=p->clockBase+MCD_getVideoAudioClock();
    p->status.audioSamplesPlayed=*clock;

    return result;
  }
  u16 now=MCD_getSubTicks(),elapsed=now-p->lastTick;p->lastTick=now;
  u32 n=p->silentRemainder+(u32)elapsed*16000;
  p->silentClock+=n/60;p->silentRemainder=n%60;*clock=p->silentClock;return MCD_OK;
}
/* CLOCK does not give up Word RAM. Submit before the inactive-bank upload
 * and let its existing VBlank waits service the IPC acknowledgement. */
static u16 clock_begin(Playback *p) {
  p->clockTick=MCD_getSubTicks();
  if(!MCD_videoAudioClockAsync())return MCD_getResult()?MCD_getResult():MCD_ERR_BUSY;
  return MCD_OK;
}
static u16 clock_finish(Playback *p) {
  u16 result=complete(p,true);
  p->clockValue=p->clockBase+MCD_getVideoAudioClock();
  p->status.audioSamplesPlayed=p->clockValue;
  if(result==MCD_ERR_AUDIO_UNDERRUN && p->clockValue==p->fedSamples)return MCD_OK;
  return result;
}
static u32 clock_estimate(Playback *p) {
  u32 clock=p->clockValue+(u32)(u16)(MCD_getSubTicks()-p->clockTick)*16000/60;
  return clock>p->fedSamples?p->fedSamples:clock;
}
static u16 restart_audio(Playback *p) {
  u16 result=complete(p,MCD_videoAudioStopAsync());if(result)return result;
  p->audioOpen=false;p->audioStarted=false;
  p->clockBase=p->fedSamples;
  if(p->clockBase>=p->header.total_samples)return MCD_OK;
  result=complete(p,MCD_videoAudioBeginAsync(p->header.total_samples-p->clockBase));
  if(!result) {p->audioOpen=true;++p->status.rebufferCount;}
  return result;
}
/* Only read data in the current owned cache. Stop at the incomplete boundary
 * record, retaining its offset for the next sector-aligned overlapping read. */
static void write16(u8 *p,u16 value) {p[0]=value>>8;p[1]=value;}
static void write32(u8 *p,u32 value) {write16(p,value>>16);write16(p+2,value);}
static u16 feed_cached(Playback *p) {
  while(p->fedFrames<p->header.frame_count && !p->skipped) {
    u32 cursor=p->feedCursor,sequence=p->fedFrames,samples=p->fedSamples;
    u16 count=0,result=0;
    const u8 *word=MCD_getWordRAM();if(!word)return MCD_ERR_NOT_READY;
    u8 *descriptors=(u8 *)(word+DESCRIPTORS_OFFSET);
    /* Two windows may hold more than the hardware ring. Submit only what
     * fits, and leave later records resident until subsequent frames drain
     * enough PCM; never wait for a ring that has not started playing. */
    u32 played=p->clockBase+MCD_getVideoAudioClock();
    u32 available=AUDIO_CAPACITY-(p->fedSamples-played);
    while(count<64 && sequence<p->header.frame_count) {
      MCDV_Frame frame;result=frame_at(p,cursor,sequence,&frame);
      if(result==MCD_ERR_SIZE)break;
      if(result)return result;
      if(p->audio && frame.audio_samples>available)break;
      if(p->audio) {
        write32(descriptors+count*8,(u32)(frame.audio-word));
        write16(descriptors+count*8+4,(u16)frame.audio_samples);
        write16(descriptors+count*8+6,0);
        available-=frame.audio_samples;
      }
      cursor+=frame.bytes;++sequence;++count;samples=frame.pts+frame.audio_samples;
    }
    if(!count)return MCD_OK;
    if(p->audio) {
      /* The Sub validates the entire batch before committing anything. The
       * descriptor sector and every audio byte remain owned until ack. */
      for(;;) {
        result=complete(p,MCD_videoAudioFeedBatchAsync(DESCRIPTORS_OFFSET,count));
        if(result==MCD_ERR_AUDIO_UNDERRUN && p->clockBase+MCD_getVideoAudioClock()==p->fedSamples) {
          result=restart_audio(p);if(result)return result;continue;
        }
        if(result==MCD_ERR_BUSY && p->audioStarted && !p->skipped) {step(p);continue;}
        if(result==MCD_ERR_BUSY && p->skipped)return MCD_OK;
        if(result)return result;
        break;
      }
    }
    p->feedCursor=cursor;p->fedFrames=sequence;p->fedSamples=samples;
  }
  return MCD_OK;
}
static u16 refill(Playback *p,u32 cursor,u16 window) {
  u16 result=load_cache(p,cursor,window);if(result || p->skipped)return result;
  result=scan_cache(p,cursor,window);if(result)return result;
  /* FEED_BATCH returns the exact underrun clock itself. Avoid a separate
   * CLOCK round trip in this latency-critical refill path. */
  result=feed_cached(p);if(result)return result;
  if(p->audio && !p->audioStarted && p->audioOpen && !p->skipped) {
    p->clockTick=MCD_getSubTicks();
    result=complete(p,MCD_videoAudioPlayAsync());if(!result) {p->audioStarted=true;p->clockValue=p->clockBase+MCD_getVideoAudioClock();}
  }
  if(!p->audio)p->lastTick=MCD_getSubTicks();
  return result;
}
static u16 advance_cache(Playback *p,u32 cursor) {
  /* Reuse only a window whose pictures have already been consumed and
   * whose PCM has been accepted. The other window keeps the next pictures
   * available while this read and batch feed run. */
  u16 older=p->cache[0].start<=p->cache[1].start?0:1;
  if(cursor>=p->cache[older].limit && p->feedCursor>=p->cache[older].limit &&
     p->nextCursor<p->bytes && p->bytes-p->nextCursor>2047)
    return refill(p,p->nextCursor,older);
  return MCD_OK;
}
u16 MCD_playVideoEx(u32 offset,u32 bytes,bool skipEnabled,bool audioEnabled,MCDVideoStatus *status) {
  Playback p={0};u16 result=0,bank=0;u32 cursor=2048;
  p.offset=offset;p.bytes=bytes;p.skipEnabled=skipEnabled;p.audio=audioEnabled;p.oldButtons=JOY_readJoypad(JOY_1);p.feedCursor=2048;
  if(status)*status=p.status;
  if((offset&2047) || (bytes&2047) || bytes<4096 || offset>0xFFFFFFFFUL-bytes)return MCD_ERR_ARGUMENT;
  if(MCD_isBusy())return MCD_ERR_BUSY;
  if(MCD_getAudioFlags()&MCD_CDDA_REQUESTED) {result=complete(&p,MCD_stopCDDA());if(result)goto done;}
  result=complete(&p,MCD_stopStream(0));if(result)goto done;
  result=complete(&p,MCD_stopStream(1));if(result)goto done;
  result=complete(&p,MCD_videoWorkspaceSaveAsync());if(result)goto done;
  p.workspaceSaved=true;
  result=complete(&p,MCD_videoSourceOpenAsync(offset,bytes));if(result)goto done;
  p.sourceOpen=true;
  result=load_cache(&p,0,0);if(result)goto done;
  if(MCDV_parseHeader(p.cache[0].data,2048,&p.header)) {result=MCD_ERR_FORMAT;goto done;}
  result=scan_cache(&p,2048,0);if(result)goto done;
  if(p.audio) {
    result=complete(&p,MCD_videoAudioBeginAsync(p.header.total_samples));if(result)goto done;
    p.audioOpen=true;
  }
  clear_scene();
  if(p.nextCursor<p.bytes && p.bytes-p.nextCursor>2047) {
    u32 next=p.nextCursor;
    result=load_cache(&p,next,1);if(result)goto done;
    result=scan_cache(&p,next,1);if(result)goto done;
  }
  result=feed_cached(&p);if(result)goto done;
  p.lastTick=MCD_getSubTicks();
  for(u32 sequence=0;sequence<p.header.frame_count && !p.skipped;++sequence) {
    MCDV_Frame frame;
    result=advance_cache(&p,cursor);if(result || p.skipped)break;
    result=frame_at(&p,cursor,sequence,&frame);
    if(result)break;
    /* Drop already-expired frames without spending their upload budget. */
    if(p.audio && p.audioStarted && sequence+1<p.header.frame_count && clock_estimate(&p)>=frame.pts+frame.audio_samples) {
      ++p.status.framesDropped;cursor+=frame.bytes;continue;
    }
    bool pending_clock=p.audio && p.audioStarted;
    if(pending_clock) {result=clock_begin(&p);if(result)break;}
    result=upload(&p,&frame,bank);
    /* A skip during upload must still consume the non-Word CLOCK request. */
    if(pending_clock) {u16 observed=clock_finish(&p);if(!result)result=observed;}
    if(result || p.skipped)break;
    if(p.audio && p.feedCursor<p.nextCursor && p.fedFrames<p.header.frame_count &&
       p.fedSamples-(p.clockBase+MCD_getVideoAudioClock())<16000) {
      result=feed_cached(&p);if(result || p.skipped)break;
    }
    u32 clock=0;
    if(!p.audio && sequence==0) {p.lastTick=MCD_getSubTicks();p.silentClock=0;p.silentRemainder=0;}
    if(p.audio && !p.audioStarted) {
      publish(&p,bank);
      p.clockTick=MCD_getSubTicks();
      result=complete(&p,MCD_videoAudioPlayAsync());if(result)break;p.audioStarted=true;
      p.clockValue=p.clockBase+MCD_getVideoAudioClock();
    }
    for(;;) {
      if(p.audio)clock=clock_estimate(&p);
      else result=clock_read(&p,&clock);
      if(result || clock>=frame.pts || p.skipped)break;
      step(&p);
    }
    if(result || p.skipped)break;
    /* Publish a prepared frame even when its upload finished late. Dropping
     * it here can starve the display indefinitely on a slower target; the
     * next iteration cheaply discards obsolete frames before uploading. */
    publish(&p,bank);bank^=1;++p.status.framesShown;
    cursor+=frame.bytes;
  }
  if(!result && !p.skipped) {
    /* Validate the exact terminal sector padding before draining the tail. */
    u32 padding=(-cursor)&2047UL;
    if(cursor+padding!=bytes)result=MCD_ERR_FORMAT;
    else {
      const u8 *tail=cached(&p,cursor,padding);
      if(!tail && padding) {result=load_cache(&p,cursor,0);tail=cached(&p,cursor,padding);}
      if(!result && padding && !tail)result=MCD_ERR_SIZE;
      if(!result)for(u32 i=0;i<padding;++i)if(tail[i]) {result=MCD_ERR_FORMAT;break;}
    }
    while(!result && !p.skipped) {
      u32 clock;result=clock_read(&p,&clock);
      if(result==MCD_ERR_AUDIO_UNDERRUN && clock==p.header.total_samples)result=MCD_OK;
      if(result || clock>=p.header.total_samples)break;
      step(&p);
    }
  }
done:
  /* Never issue a follow-on command after timeout, or touch Word RAM before
   * the bridge's acknowledged return. Pending skip always drains its request. */
  if(p.audioOpen && result!=MCD_ERR_TIMEOUT && !MCD_isBusy()) {
    u16 stop=complete(&p,MCD_videoAudioStopAsync());if(!result || stop==MCD_ERR_TIMEOUT)result=stop;
  }
  if(p.workspaceSaved && result!=MCD_ERR_TIMEOUT && !MCD_isBusy()) {
    u16 restored=complete(&p,MCD_videoWorkspaceRestoreAsync());if(!result || restored==MCD_ERR_TIMEOUT)result=restored;
  }
  if(p.sourceOpen && result!=MCD_ERR_TIMEOUT && !MCD_isBusy()) {
    u16 closed=complete(&p,MCD_videoSourceCloseAsync());if(!result || closed==MCD_ERR_TIMEOUT)result=closed;
  }
  p.status.skipped=p.skipped;if(status)*status=p.status;return result;
}
u16 MCD_playVideo(u32 offset,u32 bytes,bool skipEnabled,MCDVideoStatus *status) {
  return MCD_playVideoEx(offset,bytes,skipEnabled,true,status);
}
