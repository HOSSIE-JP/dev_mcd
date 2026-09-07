#include <assert.h>
#include <string.h>
#include <mcd/video_stream.h>
#include <mcd/protocol.h>
#include "video_pcm_host.h"
static u8 wave[65536],source[32768],word[0x40000];
static u16 cursor;
static bool enabled;
static unsigned writes;
static u16 advance_during_copy;
void mcd_test_pcm_disable(void) { enabled=false; }
void mcd_test_pcm_play(void) { enabled=true;cursor=0; }
u16 mcd_test_pcm_position(void) { return cursor; }
void mcd_test_pcm_write(u16 start,const u8 *data,u16 count) {
  assert((u32)start+count<=65536 && (start&4095)+count<=4096);
  for(u16 i=0;i<count;++i)wave[start+i]=data?data[i]:0x80;
  writes+=count;
  if(enabled && data && advance_during_copy) {
    cursor=((u32)cursor+advance_during_copy)%65535;
    advance_during_copy=0;
  }
}
static void advance(u16 samples) {
  assert(enabled);cursor=((u32)cursor+samples)%65535;
  mcd_video_pcm_update();
}
static void descriptor(u32 table,u16 index,u32 offset,u16 count,u16 reserved) {
  u8 *p=word+table+(u32)index*8;
  p[0]=offset>>24;p[1]=offset>>16;p[2]=offset>>8;p[3]=offset;
  p[4]=count>>8;p[5]=count;p[6]=reserved>>8;p[7]=reserved;
}
static void batch_tests(void) {
  const u32 table=0x30000;
  memset(word,0x42,sizeof(word));
  assert(mcd_video_pcm_feed_batch(word,table,1)==MCD_ERR_NOT_READY);
  assert(mcd_video_pcm_begin(100000)==MCD_OK);
  unsigned before=writes;
  assert(mcd_video_pcm_feed_batch(0,0,1)==MCD_ERR_ARGUMENT);
  assert(mcd_video_pcm_feed_batch(word,0,0)==MCD_ERR_ARGUMENT);
  assert(mcd_video_pcm_feed_batch(word,0,65)==MCD_ERR_ARGUMENT);
  assert(mcd_video_pcm_feed_batch(word,0x40000,1)==MCD_ERR_ARGUMENT);
  assert(mcd_video_pcm_feed_batch(word,0x3FFF9,1)==MCD_ERR_ARGUMENT);
  assert(mcd_video_pcm_feed_batch(word,0x3FE01,64)==MCD_ERR_ARGUMENT);
  assert(mcd_video_pcm_feed_batch(word,0xFFFFFFFFUL,1)==MCD_ERR_ARGUMENT);
  descriptor(table,0,0,32768,0);
  descriptor(table,1,32768,32511,1);
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_ERR_ARGUMENT); /* Late reserved. */
  descriptor(table,1,0x3FFFF,2,0);
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_ERR_ARGUMENT);
  descriptor(table,1,0xFFFFFFFFUL,2,0);
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_ERR_ARGUMENT);
  descriptor(table,1,32768,32769,0);
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_ERR_ARGUMENT);
  descriptor(table,1,32768,0,0);
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_ERR_ARGUMENT);
  descriptor(table,1,32768,32512,0);
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_ERR_BUSY); /* Guard excluded. */
  descriptor(table,1,32768,32511,0);word[65278]=0xFF;
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_ERR_FORMAT);
  assert(writes==before && mcd_video_pcm_clock()==0 && wave[0]==0x80);
  word[65278]=0x42;
  /* Exact full capacity succeeding proves every rejected request kept counters. */
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_OK);
  assert(wave[0]==0x42 && wave[65278]==0x42 && wave[65535]==0xFF);
  for(u32 i=65279;i<65535;++i)assert(wave[i]==0x80);
  before=writes;
  descriptor(table,0,0,1,0);
  assert(mcd_video_pcm_feed_batch(word,table,1)==MCD_ERR_BUSY && writes==before);
  assert(mcd_video_pcm_play()==MCD_OK);advance(60000);
  descriptor(table,0,0x3FFFF,1,0);word[0x3FFFF]=0x43;
  descriptor(table,1,0,32768,0);
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_OK); /* Source boundary + ring wrap. */
  assert(wave[65279]==0x43 && wave[65535]==0xFF);
  descriptor(table,0,0,1952,0);
  assert(mcd_video_pcm_feed_batch(word,table,1)==MCD_OK);
  before=writes;
  assert(mcd_video_pcm_feed_batch(word,table,1)==MCD_ERR_SIZE && writes==before);
  advance(40000);
  assert(mcd_video_pcm_clock()==100000 && (mcd_video_pcm_flags()&MCD_VIDEO_AUDIO_ENDED));
  mcd_video_pcm_stop();

  /* Maximum count and last legal table byte; failed total-size check is atomic. */
  assert(mcd_video_pcm_begin(64)==MCD_OK);
  for(u16 i=0;i<64;++i)descriptor(0x3FE00,i,i,1,0);
  descriptor(0x3FE00,63,63,2,0);before=writes;
  assert(mcd_video_pcm_feed_batch(word,0x3FE00,64)==MCD_ERR_SIZE && writes==before);
  descriptor(0x3FE00,63,63,1,0);
  assert(mcd_video_pcm_feed_batch(word,0x3FE00,64)==MCD_OK);
  assert(mcd_video_pcm_play()==MCD_OK);advance(64);
  assert(mcd_video_pcm_clock()==64 && (mcd_video_pcm_flags()&MCD_VIDEO_AUDIO_ENDED));
  mcd_video_pcm_stop();

  /* Invalid late PCM must not even poll a moving playback cursor. */
  assert(mcd_video_pcm_begin(1000)==MCD_OK);
  assert(mcd_video_pcm_feed(source,100)==MCD_OK);
  assert(mcd_video_pcm_play()==MCD_OK);
  cursor=50;before=writes;
  descriptor(table,0,0,10,0);descriptor(table,1,10,10,0);word[19]=0xFF;
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_ERR_FORMAT);
  assert(writes==before && mcd_video_pcm_clock()==0 && wave[0]==0x42);
  word[19]=0x42;
  descriptor(table,0,0,150,0);descriptor(table,1,150,150,0);
  /* Once copying begins, an underrun reports the fully committed batch through
   * status; success lets Main account for all 300 samples before recovering. */
  advance_during_copy=400;
  assert(mcd_video_pcm_feed_batch(word,table,2)==MCD_OK);
  assert(mcd_video_pcm_clock()==400 && mcd_video_pcm_result()==MCD_ERR_AUDIO_UNDERRUN);
  assert(!enabled);
  mcd_video_pcm_stop();
}
int main(void) {
  memset(source,0x42,sizeof(source));
  assert(mcd_video_pcm_begin(0)==MCD_ERR_ARGUMENT);
  assert(mcd_video_pcm_begin(115200001UL)==MCD_ERR_ARGUMENT);
  assert(mcd_video_pcm_play()==MCD_ERR_NOT_READY);
  assert(mcd_video_pcm_begin(100000)==MCD_OK);
  assert(mcd_video_pcm_begin(100000)==MCD_ERR_BUSY);
  assert(wave[65535]==0xFF && wave[0]==0x80 && wave[65534]==0x80);
  assert(mcd_video_pcm_feed(source,32768)==MCD_OK);
  assert(wave[32767]==0x42 && wave[32768]==0x80);
  assert(mcd_video_pcm_feed(source,32768)==MCD_ERR_BUSY);
  assert(mcd_video_pcm_feed(source,32000)==MCD_OK);
  assert(mcd_video_pcm_play()==MCD_OK && enabled);
  advance(40000);assert(mcd_video_pcm_clock()==40000);
  assert(wave[0]==0x80 && wave[39999]==0x80 && wave[40000]==0x42);
  assert(mcd_video_pcm_feed(source,32768)==MCD_OK); /* PCM bank + ring wrap. */
  advance(30000);assert(mcd_video_pcm_clock()==70000);
  assert(mcd_video_pcm_feed(source,2464)==MCD_OK);
  advance(30000);
  assert(mcd_video_pcm_clock()==100000 && !enabled);
  assert(mcd_video_pcm_flags()&MCD_VIDEO_AUDIO_ENDED);
  assert(mcd_video_pcm_result()==MCD_OK && wave[65535]==0xFF);
  mcd_video_pcm_stop();assert(!mcd_video_pcm_active() && mcd_video_pcm_flags()==0);

  assert(mcd_video_pcm_begin(1000)==MCD_OK);
  unsigned before=writes;source[99]=0xFF;
  assert(mcd_video_pcm_feed(source,100)==MCD_ERR_FORMAT && writes==before);
  source[99]=0x42;
  assert(mcd_video_pcm_feed(source,1001)==MCD_ERR_SIZE);
  assert(mcd_video_pcm_feed(source,100)==MCD_OK);
  for(u16 i=100;i<356;++i)assert(wave[i]==0x80);
  assert(mcd_video_pcm_play()==MCD_OK);advance(101);
  assert(!enabled && mcd_video_pcm_clock()==100);
  assert(mcd_video_pcm_result()==MCD_ERR_AUDIO_UNDERRUN);
  assert(mcd_video_pcm_flags()&MCD_VIDEO_AUDIO_UNDERRUN);
  assert(mcd_video_pcm_feed(source,1)==MCD_ERR_AUDIO_UNDERRUN);
  mcd_video_pcm_stop();
  assert(mcd_video_pcm_begin(900)==MCD_OK); /* Explicit rebuffer, new local clock. */
  assert(mcd_video_pcm_clock()==0 && mcd_video_pcm_result()==MCD_OK);
  assert(mcd_video_pcm_feed(source,900)==MCD_OK);
  assert(mcd_video_pcm_play()==MCD_OK);advance(901);
  assert(!enabled && mcd_video_pcm_clock()==900);
  assert(mcd_video_pcm_result()==MCD_OK && (mcd_video_pcm_flags()&MCD_VIDEO_AUDIO_ENDED));
  mcd_video_pcm_stop();
  batch_tests();
  return 0;
}
