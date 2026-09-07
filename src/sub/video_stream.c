/* MTV1 already contains RF5C164 sign/magnitude PCM8. No decoder or libc.
 * One 65535-byte ring plus FF loop marker. A silent 256-byte guard follows
 * the committed tail; capacity excludes that guard to protect unread samples.
 * Consumed bytes are cleared, so free space cannot replay a previous cycle.
 * The kernel must poll faster than a ring revolution (about 4.09 seconds). */
#include <mcd/video_stream.h>
#include <mcd/protocol.h>
#ifdef MCD_VIDEO_PCM_HOST_TEST
#include "video_pcm_host.h"
#else
#include <sub/pcm.h>
#endif
#define RING 65535UL
#define GUARD 256UL
static u32 total, written, played;
static u16 previous, write_position, error;
static bool active, playing, ended;

static void disable(void) {
#ifdef MCD_VIDEO_PCM_HOST_TEST
  mcd_test_pcm_disable();
#else
  *PCM_CDISABLE=0xFF;
#endif
}
static u16 position(void) {
#ifdef MCD_VIDEO_PCM_HOST_TEST
  return mcd_test_pcm_position();
#else
  volatile u8 *reg=(volatile u8 *)0xFF0021UL;
  u16 hi,pos;
  do { hi=reg[2]; pos=(hi<<8)|reg[0]; } while(hi!=reg[2]);
  return pos;
#endif
}
static void bank_write(u16 start,const u8 *source,u16 count) {
#ifdef MCD_VIDEO_PCM_HOST_TEST
  mcd_test_pcm_write(start,source,count);
#else
  *PCM_CTRL=0x80|(start>>12);
  volatile u8 *dest=(volatile u8 *)(0xFF2001UL+((u32)(start&4095)<<1));
  while(count--) { *dest=source?*source++:0x80; dest+=2; }
#endif
}
static u16 copy_ring(u16 start,const u8 *source,u32 count) {
  while(count) {
    u16 run=4096-(start&4095);
    if(run>RING-start)run=RING-start;
    if(run>count)run=count;
    bank_write(start,source,run);
    if(source)source+=run;
    count-=run; start+=run;
    if(start==RING)start=0;
  }
  return start;
}
u16 mcd_video_pcm_begin(u32 samples) {
  static const u8 marker=0xFF;
  if(!samples || samples>115200000UL)return MCD_ERR_ARGUMENT;
  if(active)return MCD_ERR_BUSY;
  disable(); total=samples; written=played=0; previous=write_position=0;
  error=MCD_OK; playing=ended=false; active=true;
  copy_ring(0,0,RING); bank_write(65535,&marker,1);
  return MCD_OK;
}
void mcd_video_pcm_update(void) {
  if(!playing)return;
  u16 pos=position(); if(pos==65535)pos=0;
  u16 delta=pos>=previous?(u32)pos-previous:RING-previous+pos;
  u16 consumed_start=previous;
  played+=delta; previous=pos;
  if(written==total && played>=total) {
    played=total; disable(); playing=false; ended=true;
  } else if(played>written) {
    disable(); playing=false; played=written; error=MCD_ERR_AUDIO_UNDERRUN;
    /* No restart after an underrun: stop and reopen with a new prefill. */
  }
  if(delta)copy_ring(consumed_start,0,delta);
}
u16 mcd_video_pcm_feed(const u8 *data,u16 samples) {
  if(!active)return MCD_ERR_NOT_READY;
  mcd_video_pcm_update();
  if(error)return error;
  if(!data || !samples || samples>32768)return MCD_ERR_ARGUMENT;
  if(samples>total-written)return MCD_ERR_SIZE;
  if((u32)samples>RING-GUARD-(written-played))return MCD_ERR_BUSY;
  /* Validate the full source before changing ring contents or counters. */
  for(u16 i=0;i<samples;++i)if(data[i]==0xFF)return MCD_ERR_FORMAT;
  write_position=copy_ring(write_position,data,samples);
  copy_ring(write_position,0,GUARD);
  written+=samples;
  return MCD_OK;
}
static u16 read_be16(const u8 *p) { return ((u16)p[0]<<8)|p[1]; }
static u32 read_be32(const u8 *p) { return ((u32)read_be16(p)<<16)|read_be16(p+2); }
u16 mcd_video_pcm_feed_batch(const u8 *word_base,u32 descriptor_offset,u16 count) {
  u32 samples=0;
  if(!active)return MCD_ERR_NOT_READY;
  if(error)return error;
  if(!word_base || !count || count>64 || descriptor_offset>=0x40000UL ||
      (u32)count*8>0x40000UL-descriptor_offset)return MCD_ERR_ARGUMENT;
  const u8 *table=word_base+descriptor_offset;
  /* Word RAM remains Sub-owned for both passes. Do not service PCM until all
   * validation succeeds: a late bad descriptor must leave even the clock and
   * cleared samples unchanged. Kernel polling refreshes played before dispatch. */
  for(u16 i=0;i<count;++i) {
    const u8 *entry=table+(u32)i*8;
    u32 offset=read_be32(entry);
    u16 length=read_be16(entry+4);
    if(!length || length>32768 || read_be16(entry+6) || offset>=0x40000UL ||
        length>0x40000UL-offset)return MCD_ERR_ARGUMENT;
    samples+=length;
  }
  if(samples>total-written)return MCD_ERR_SIZE;
  if(samples>RING-GUARD-(written-played))return MCD_ERR_BUSY;
  for(u16 i=0;i<count;++i) {
    const u8 *entry=table+(u32)i*8;
    const u8 *data=word_base+read_be32(entry);
    u16 length=read_be16(entry+4);
    for(u16 j=0;j<length;++j)if(data[j]==0xFF)return MCD_ERR_FORMAT;
  }
  mcd_video_pcm_update();
  if(error)return error;
  for(u16 i=0;i<count;++i) {
    const u8 *entry=table+(u32)i*8;
    const u8 *data=word_base+read_be32(entry);
    u16 length=read_be16(entry+4);
    write_position=copy_ring(write_position,data,length);
  }
  copy_ring(write_position,0,GUARD);
  written+=samples;
  /* Publish the complete batch before servicing playback again. Once accepted,
   * every sample is committed even if playback underruns during the copy; the
   * audio status reports that event separately, never a partially failed feed.
   * Copying at most 65279 bytes must finish within one ring revolution. */
  mcd_video_pcm_update();
  return MCD_OK;
}
u16 mcd_video_pcm_play(void) {
  if(!active || !written || playing || ended || played)return MCD_ERR_NOT_READY;
  if(error)return error;
#ifdef MCD_VIDEO_PCM_HOST_TEST
  mcd_test_pcm_play();
#else
  /* round(16000 * 384 * 2048 / 12500000) = 1007; the hardware sample
   * address is the media clock, so divider rounding cannot accumulate A/V drift. */
  *PCM_CTRL=0xC0; *PCM_ENV=0xFF; *PCM_PAN=0xFF;
  *PCM_FDL=0xEF; *PCM_FDH=3; *PCM_LSL=0; *PCM_LSH=0; *PCM_ST=0;
  *PCM_CDISABLE=0xFE;
#endif
  playing=true; return MCD_OK;
}
void mcd_video_pcm_stop(void) {
  if(active)disable();
  active=playing=false;
}
bool mcd_video_pcm_active(void) { return active; }
u16 mcd_video_pcm_flags(void) {
  if(!active)return 0;
  return (active?MCD_VIDEO_AUDIO_READY:0)|(playing?MCD_VIDEO_AUDIO_PLAYING:0)|
    (error?MCD_VIDEO_AUDIO_UNDERRUN:0)|(ended?MCD_VIDEO_AUDIO_ENDED:0);
}
u16 mcd_video_pcm_result(void) { return error; }
u32 mcd_video_pcm_clock(void) { return played; }
