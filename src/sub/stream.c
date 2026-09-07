/* Two resident IMA sources feed independent RF5C164 rings. No disc streaming
 * while playing: compressed data remains in separate bounded PRG RAM regions. */
#include <sub/pcm.h>
#include <mcd/ima.h>
#include <mcd/protocol.h>
#include <mcd/stream.h>
#define RING 32767UL
typedef struct {
  MCD_IMAState ima;
  u32 count, source, written, played;
  u16 rate, previous, write_pos;
  s16 predictor;
  u8 index;
  bool priming, ready, playing, loop;
} Stream;
static Stream streams[2];
static u8 disable_mask=0xFF;
static u16 underruns;
u8 *mcd_stream_buffer(u16 c) { return (u8 *)(c ? 0x20000UL : 0x40000UL); }
u32 mcd_stream_capacity(u16 c) { return c ? 0x20000UL : 0x3E000UL; }
static u16 be16(const u8 *p) { return ((u16)p[0]<<8)|p[1]; }
static u32 be32(const u8 *p) { return ((u32)be16(p)<<16)|be16(p+2); }
static void put(u16 c,u16 pos,u8 v) {
  u32 address=(c ? 0x8000UL : 0)+pos;
  *PCM_CTRL=0x80|(address>>12);
  *(volatile u8 *)(0xFF2001UL+((address&4095)<<1))=v;
}
void mcd_stream_stop(u16 c) {
  if(c>1)return;
  disable_mask|=1<<c; *PCM_CDISABLE=disable_mask;
  streams[c].playing=false;
}
u16 mcd_stream_prepare(u16 c,u32 bytes,bool loop) {
  const u8 *p;Stream *s;
  if(c>1)return MCD_ERR_ARGUMENT;
  mcd_stream_stop(c);s=&streams[c];s->ready=s->priming=false;p=mcd_stream_buffer(c);
  if(bytes<16 || be32(p)!=0x4D494D41UL || be16(p+4)!=1 || p[14]>88 || p[15])return MCD_ERR_FORMAT;
  s->count=be32(p+8);s->rate=be16(p+6);
  if(s->rate<8000 || s->rate>22050 || !s->count || s->count>1000000UL ||
     bytes!=16+((s->count+1)>>1) || bytes>mcd_stream_capacity(c))return MCD_ERR_SIZE;
  s->predictor=(s16)be16(p+12);s->index=p[14];
  s->ima.predictor=s->predictor;s->ima.index=s->index;
  s->source=s->written=s->played=0;s->previous=s->write_pos=0;s->loop=loop;s->priming=true;
  put(c,32767,0xFF);
  return MCD_OK;
}
bool mcd_stream_ready(u16 c) {return c<2 && streams[c].ready;}
u16 mcd_stream_play(u16 c) {
  Stream *s;u16 step,base;
  if(c>1)return MCD_ERR_ARGUMENT;
  s=&streams[c];if(!s->ready || s->played)return MCD_ERR_NOT_READY;
  Stream *other=&streams[c^1];
  if(other->playing && (s->loop || s->count>RING) &&
     (other->loop || other->count>RING) && (u32)s->rate+other->rate>19025)
    return MCD_ERR_AUDIO_BUDGET;
  base=c?0x8000:0;
  /* rate * 384 * 2048 / 12500000, rounded; avoid a 64-bit runtime helper. */
  step=((u32)s->rate*8192UL+65104UL)/130208UL;
  *PCM_CTRL=0xC0|c;*PCM_ENV=c?0xFF:0x70;*PCM_PAN=0xFF;
  *PCM_FDL=step;*PCM_FDH=step>>8;*PCM_LSL=base;*PCM_LSH=base>>8;*PCM_ST=base>>8;
  disable_mask&=~(1<<c);*PCM_CDISABLE=disable_mask;s->playing=true;
  return MCD_OK;
}
void mcd_stream_update(void) {
  for(u16 c=0;c<2;++c) {
    Stream *s=&streams[c];u16 budget=256;
    if(s->playing) {
      volatile u8 *reg=(volatile u8 *)(0xFF0021UL+c*4);u16 hi,pos,delta;
      do {hi=reg[2];pos=(hi<<8)|reg[0];} while(hi!=reg[2]);
      pos&=0x7FFF;if(pos==32767)pos=0;
      delta=pos>=s->previous?pos-s->previous:32767-s->previous+pos;
      s->played+=delta;s->previous=pos;
      if(s->played>s->written) {underruns|=1<<c;mcd_stream_stop(c);s->ready=false;continue;}
      if(!s->loop && s->played>=s->count) {mcd_stream_stop(c);s->ready=false;continue;}
    }
    if(!s->priming && !s->playing)continue;
    u32 ahead=s->written-s->played;
    if(ahead>=RING)continue;
    if(budget>RING-ahead)budget=RING-ahead;
    u16 bank_remaining=4096-(s->write_pos&4095),ring_remaining=32767-s->write_pos;
    if(budget>bank_remaining)budget=bank_remaining;
    if(budget>ring_remaining)budget=ring_remaining;
    u16 filled=budget;
    /* Select the wave bank once per run, then use consecutive byte writes.
     * Reprogramming CTRL and computing a 32-bit address for each sample wastes
     * enough Sub CPU time to starve a second stream during repeated preloads. */
    *PCM_CTRL=0x80|(c<<3)|(s->write_pos>>12);
    volatile u8 *dest=(volatile u8 *)(0xFF2001UL+((u32)(s->write_pos&4095)<<1));
    const u8 *data=mcd_stream_buffer(c)+16;
    while(budget--) {
      u8 sample=0x80;
      if(s->source==s->count && s->loop) {
        s->source=0;s->ima.predictor=s->predictor;s->ima.index=s->index;
      }
      if(s->source<s->count) {
        u8 b=data[s->source>>1];
        sample=MCD_imaDecodePCM(&s->ima,(s->source&1)?b>>4:b&15);
        ++s->source;
      }
      *dest=sample;dest+=2;
    }
    s->written+=filled;s->write_pos+=filled;
    if(s->write_pos==32767)s->write_pos=0;
    if(s->priming && s->written==RING) {s->priming=false;s->ready=true;}
  }
}
u16 mcd_stream_flags(void) {
  u16 f=underruns<<8;
  for(u16 c=0;c<2;++c) {if(streams[c].ready)f|=16<<(c*2);if(streams[c].playing)f|=32<<(c*2);}
  return f;
}
