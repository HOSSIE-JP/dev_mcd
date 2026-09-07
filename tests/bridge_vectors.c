/* Exercise actual bridge C against VDP ports, never an alternative renderer. */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <mcd/bridge.h>
#include "bridge_host.h"
volatile u16 mcd_test_cmd[8], mcd_test_stat[8];
volatile u8 mcd_test_memmode, mcd_test_joy;
static u16 vram_words[32768], cram[64], vsram[40], registers[24];
static u16 address, space, increment = 2;
static unsigned writes, waits;
void mcd_test_control(u32 value) {
  address = ((value >> 16) & 0x3FFF) | ((value & 3) << 14);
  space = value & 0x10 ? 2 : (value & 0xC0000000) == 0xC0000000 ? 1 : 0;
}
void mcd_test_register(u16 value) {
  u16 index = (value >> 8) & 0x1F;
  /* Some Windows CRT assert declarations are not marked noreturn. Keep the
   * invalid path explicitly terminal for GCC's array-bounds analysis. */
  if (index >= 24) { assert(index < 24); abort(); }
  registers[index] = value & 255;
  if (index == 15) increment = value & 255;
}
void mcd_test_data(u16 value) {
  assert(!(address & 1));
  if (space == 2) { assert(address/2 < 40); vsram[address/2] = value; }
  else if (space == 1) { assert(address/2 < 64); cram[address/2] = value; }
  else vram_words[address/2] = value;
  address += increment; ++writes;
}
void mcd_wait_frame(void) { ++waits; }
static void palette_tests(void) {
  u16 colors[16]; unsigned before;
  for (u16 i=0;i<16;++i) colors[i] = 0xFFFF;
  PAL_setPalette(2,colors);
  assert(cram[31] == 0 && cram[32] == 0xEEE && cram[47] == 0xEEE);
  assert(PAL_getColor(32) == 0xEEE && PAL_getColor(64) == 0);
  before = writes;
  PAL_setColors(63,colors,2); PAL_setColors(0,colors,65535);
  PAL_setColors(0,(const u16 *)((const u8 *)colors+1),1);
  PAL_setPalette(4,colors); PAL_setColors(64,colors,1); PAL_setColors(0,0,1);
  assert(writes == before);
  PAL_setColor(5,0); colors[0] = 0xEEE;
  assert(MCD_fadePaletteTo(5,colors,1,7) == MCD_OK);
  colors[0] = 0; /* The fade owns a copy, not the caller's lifetime. */
  SYS_doVBlankProcess(); assert(cram[5] == 0x222 && PAL_isDoingFade());
  MCD_waitFrames(6); assert(cram[5] == 0xEEE && !PAL_isDoingFade());
  assert(MCD_fadePaletteTo(5,colors,1,65535) == MCD_OK);
  SYS_doVBlankProcess(); assert(cram[5] == 0xEEE);
  assert(MCD_fadePaletteTo(63,colors,2,1) == MCD_ERR_ARGUMENT);
  assert(PAL_isDoingFade()); /* Invalid requests don't disturb the current fade. */
  PAL_setColor(6,0x1234); assert(!PAL_isDoingFade() && cram[6] == 0x224);
  assert(MCD_fadePaletteTo(5,colors,1,0) == MCD_OK && cram[5] == 0);
  assert(MCD_fadePaletteTo(5,colors,1,7) == MCD_OK);
  MCD_cancelPaletteFade(); assert(!PAL_isDoingFade());
}
static void map_tests(void) {
  u16 tiles[] = {1,2,99,3,4}; unsigned before;
  assert(MCD_setTileMapRect(BG_A,tiles,5,62,30,2,2,3) == MCD_OK);
  assert(vram_words[0xC000/2+30*64+62] == 1);
  assert(vram_words[0xC000/2+31*64+63] == 4);
  before = writes;
  assert(MCD_setTileMapRect(BG_A,tiles,4,62,30,2,2,3) == MCD_ERR_SIZE);
  assert(MCD_setTileMapRect(BG_A,tiles,5,63,30,2,2,3) == MCD_ERR_ARGUMENT);
  assert(MCD_setTileMapRect(BG_A,tiles,5,62,31,2,2,3) == MCD_ERR_ARGUMENT);
  assert(MCD_setTileMapRect(BG_A,tiles,5,62,30,2,2,1) == MCD_ERR_ARGUMENT);
  assert(MCD_setTileMapRect(BG_A,tiles,5,0,0,65535,2,65535) == MCD_ERR_ARGUMENT);
  assert(MCD_setTileMapRect((VDPPlane)2,tiles,5,0,0,1,1,1) == MCD_ERR_ARGUMENT);
  VDP_fillTileMapRect(BG_A,1,63,31,2,2); VDP_setTileMapXY(BG_A,1,65535,65535);
  assert(writes == before);
  VDP_setTileMapXY(BG_B,TILE_ATTR_FULL(PAL2,true,true,false,12),63,31);
  assert(vram_words[0xE000/2+2047] == 0xD00C);
  vram_words[0xF000/2] = 0xCAFE;
  assert(MCD_clearPlane(BG_B) == MCD_OK);
  for (u16 i=0;i<2048;++i) assert(vram_words[0xE000/2+i] == 0);
  assert(vram_words[0xF000/2] == 0xCAFE);
  assert(MCD_clearPlane((VDPPlane)2) == MCD_ERR_ARGUMENT);
}
static void tile_text_scroll_tests(void) {
  u16 tile[32]; unsigned before;
  for (u16 i=0;i<32;++i) tile[i] = 0x1234;
  vram_words[0x9000/2] = 0xCAFE;
  assert(MCD_loadTiles(tile,1151,1) == MCD_OK);
  assert(vram_words[0x8FFE/2] == 0x1234 && vram_words[0x9000/2] == 0xCAFE);
  before = writes;
  assert(MCD_loadTiles(tile,1151,2) == MCD_ERR_SIZE);
  assert(MCD_loadTiles(tile,0,1) == MCD_ERR_ARGUMENT);
  assert(MCD_loadTiles(tile,1152,1) == MCD_ERR_ARGUMENT);
  assert(MCD_loadTiles(tile,65535,65535) == MCD_ERR_ARGUMENT);
  assert(MCD_loadTiles((const u8 *)tile+1,1,1) == MCD_ERR_ARGUMENT);
  assert(MCD_loadTiles(0,1,1) == MCD_ERR_ARGUMENT);
  assert(writes == before);
  VDP_setTextPlane(BG_B); VDP_setTextPalette(PAL1); VDP_setTextPriority(true);
  VDP_drawText("AB",39,27);
  assert(vram_words[0xE000/2+27*64+39] == (0xA000|1185));
  assert(vram_words[0xE000/2+27*64+40] == 0);
  VDP_clearText(39,27,65535);
  assert(vram_words[0xE000/2+27*64+39] == (0xA000|1152));
  VDP_drawTextBG(BG_A,"\1",0,0);
  assert(vram_words[0xC000/2] == (0xA000|1183));
  before = writes;
  VDP_drawText("A",40,27); VDP_drawText("A",39,28);
  VDP_drawTextBG((VDPPlane)2,"A",0,0); assert(writes == before);
  VDP_setHorizontalScroll(BG_A,-1); VDP_setHorizontalScroll(BG_B,512);
  VDP_setVerticalScroll(BG_A,-8); VDP_setVerticalScroll(BG_B,7);
  assert(vram_words[0xFC00/2] == 1023 && vram_words[0xFC02/2] == 512);
  assert(vsram[0] == 1016 && vsram[1] == 7);
  before = writes; VDP_setHorizontalScroll((VDPPlane)2,1);
  VDP_setVerticalScroll((VDPPlane)2,1); assert(writes == before);
}
static void frame_input_ipc_tests(void) {
  u32 first = MCD_getFrameCount();
  mcd_test_joy = BUTTON_A|BUTTON_LEFT;
  SYS_doVBlankProcess(); assert(MCD_getFrameCount() == first+1);
  assert(JOY_readJoypad(JOY_1) == (BUTTON_A|BUTTON_LEFT));
  assert(MCD_readJoypadPressed(JOY_1) == (BUTTON_A|BUTTON_LEFT));
  assert(MCD_readJoypadPressed(JOY_1) == (BUTTON_A|BUTTON_LEFT));
  SYS_doVBlankProcess(); assert(MCD_readJoypadPressed(JOY_1) == 0);
  mcd_test_joy = BUTTON_A; SYS_doVBlankProcess();
  assert(MCD_readJoypadReleased(JOY_1) == BUTTON_LEFT);
  assert(MCD_readJoypadReleased(1) == 0 && MCD_readJoypadPressed(1) == 0);
  assert(JOY_readJoypad(1) == 0);
  assert(MCD_playCDDA(2,true)); assert(MCD_isBusy());
  mcd_test_stat[0] = MCD_CMD_PLAY_CDDA;
  SYS_doVBlankProcess(); assert(mcd_test_cmd[0] == 0 && MCD_isBusy());
  mcd_test_stat[0] = 0; SYS_doVBlankProcess(); assert(!MCD_isBusy());
  assert(MCD_getResult() == MCD_OK && waits == MCD_getFrameCount());
}
static void video_audio_ipc_tests(void) {
  assert(!MCD_videoAudioBeginAsync(0));
  assert(!MCD_videoAudioBeginAsync(115200001UL));
  assert(MCD_videoAudioBeginAsync(100000));
  assert(mcd_test_cmd[0]==MCD_CMD_VIDEO_AUDIO_BEGIN);
  assert(mcd_test_cmd[1]==1 && mcd_test_cmd[2]==34464);
  mcd_test_stat[0]=MCD_CMD_VIDEO_AUDIO_BEGIN; MCD_update();
  mcd_test_stat[0]=0; MCD_update(); assert(!MCD_isBusy());
  mcd_test_memmode=1;
  assert(!MCD_videoAudioFeedAsync(0x3FFFF,2));
  assert(!MCD_videoAudioFeedAsync(0,32769));
  assert(MCD_videoAudioFeedAsync(0x31000,1333));
  assert(mcd_test_cmd[1]==3 && mcd_test_cmd[2]==0x1000 && mcd_test_cmd[3]==1333);
  assert(!MCD_getWordRAM());
  mcd_test_memmode=2; /* Hardware hands Word RAM to Sub. */
  mcd_test_stat[0]=MCD_CMD_VIDEO_AUDIO_FEED; mcd_test_stat[3]=1234; MCD_update();
  mcd_test_stat[0]=0; MCD_update();
  assert(MCD_isBusy() && !MCD_getWordRAM()); /* Ack alone cannot reclaim data. */
  mcd_test_memmode=1; MCD_update();
  assert(!MCD_isBusy() && MCD_getWordRAM());
  assert(MCD_getVideoAudioClock()==1234);
  assert(MCD_videoAudioClockAsync());
  assert(MCD_getWordRAM()); /* CLOCK leaves the current Word contents accessible. */
  mcd_test_stat[0]=MCD_CMD_VIDEO_AUDIO_CLOCK; MCD_update();
  mcd_test_stat[0]=0; MCD_update();
  assert(!MCD_isBusy() && MCD_getWordRAM());
}
static void video_source_ipc_tests(void) {
  assert(!MCD_videoSourceOpenAsync(1,2048));
  assert(!MCD_videoSourceOpenAsync(0,2049));
  assert(!MCD_videoSourceOpenAsync(0xFFFFF800UL,4096));
  assert(MCD_videoSourceOpenAsync(0x1234800,0x68000));
  assert(mcd_test_cmd[0]==MCD_CMD_VIDEO_SOURCE_OPEN && mcd_test_cmd[1]==0);
  assert(mcd_test_cmd[2]==0x123 && mcd_test_cmd[3]==0x4800);
  assert(mcd_test_cmd[4]==6 && mcd_test_cmd[5]==0x8000);
  mcd_test_stat[0]=MCD_CMD_VIDEO_SOURCE_OPEN;MCD_update();
  mcd_test_stat[0]=0;MCD_update();
  assert(!MCD_isBusy());
  mcd_test_memmode=1;
  assert(!MCD_videoSourceReadAsync(1,2048,96));
  assert(!MCD_videoSourceReadAsync(0,65536,97));
  assert(!MCD_videoSourceReadAsync(0,67584,96));
  assert(MCD_videoSourceReadAsync(0x2F800,65536,96));
  assert(mcd_test_cmd[0]==MCD_CMD_VIDEO_SOURCE_READ && mcd_test_cmd[1]==96);
  assert(mcd_test_cmd[2]==2 && mcd_test_cmd[3]==0xF800);
  assert(mcd_test_cmd[4]==1 && mcd_test_cmd[5]==0);
  mcd_test_memmode=2;mcd_test_stat[0]=MCD_CMD_VIDEO_SOURCE_READ;
  mcd_test_stat[2]=1;mcd_test_stat[3]=0;MCD_update();
  mcd_test_stat[0]=0;MCD_update();assert(MCD_isBusy() && !MCD_getWordRAM());
  mcd_test_memmode=1;MCD_update();assert(!MCD_isBusy() && MCD_getWordRAM());
  assert(MCD_getFileSize()==65536 && MCD_getVideoAudioClock()==1234);
  assert(MCD_videoSourceCloseAsync());
  mcd_test_stat[0]=MCD_CMD_VIDEO_SOURCE_CLOSE;MCD_update();
  mcd_test_stat[0]=0;MCD_update();assert(!MCD_isBusy());
}
static void video_workspace_ipc_tests(void) {
  mcd_test_memmode=2;assert(!MCD_videoWorkspaceSaveAsync());
  mcd_test_memmode=1;assert(MCD_videoWorkspaceSaveAsync());
  assert(mcd_test_cmd[0]==MCD_CMD_VIDEO_WORKSPACE_SAVE && !MCD_getWordRAM());
  mcd_test_memmode=2;mcd_test_stat[0]=MCD_CMD_VIDEO_WORKSPACE_SAVE;MCD_update();
  mcd_test_stat[0]=0;MCD_update();assert(MCD_isBusy());
  mcd_test_memmode=1;MCD_update();assert(!MCD_isBusy() && MCD_getWordRAM());
  assert(MCD_videoWorkspaceRestoreAsync());
  mcd_test_memmode=2;mcd_test_stat[0]=MCD_CMD_VIDEO_WORKSPACE_RESTORE;MCD_update();
  mcd_test_stat[0]=0;MCD_update();assert(MCD_isBusy());
  mcd_test_memmode=1;MCD_update();assert(!MCD_isBusy() && MCD_getWordRAM());
}
static void video_audio_batch_ipc_tests(void) {
  mcd_test_memmode=1;
  assert(!MCD_videoAudioFeedBatchAsync(0,0));
  assert(!MCD_videoAudioFeedBatchAsync(0,65));
  assert(!MCD_videoAudioFeedBatchAsync(0x40000,1));
  assert(!MCD_videoAudioFeedBatchAsync(0x3FFF9,1));
  assert(!MCD_videoAudioFeedBatchAsync(0x3FE01,64));
  assert(!MCD_videoAudioFeedBatchAsync(0xFFFFFFFFUL,1));
  mcd_test_memmode=2;
  assert(!MCD_videoAudioFeedBatchAsync(0x30000,64));
  mcd_test_memmode=1;
  assert(MCD_videoAudioFeedBatchAsync(0x3FE00,64));
  assert(mcd_test_cmd[0]==MCD_CMD_VIDEO_AUDIO_FEED_BATCH);
  assert(mcd_test_cmd[1]==3 && mcd_test_cmd[2]==0xFE00 && mcd_test_cmd[3]==64);
  assert(!MCD_getWordRAM());
  assert(!MCD_videoAudioFeedBatchAsync(0,1));
  mcd_test_memmode=2;
  mcd_test_stat[0]=MCD_CMD_VIDEO_AUDIO_FEED_BATCH;
  mcd_test_stat[1]=MCD_ERR_BUSY;
  mcd_test_stat[2]=1;mcd_test_stat[3]=4321;MCD_update();
  mcd_test_stat[0]=0;MCD_update();
  assert(MCD_isBusy() && !MCD_getWordRAM());
  assert(MCD_getVideoAudioClock()==65536UL+4321);
  mcd_test_memmode=1;MCD_update();
  assert(!MCD_isBusy() && MCD_getWordRAM() && MCD_getResult()==MCD_ERR_BUSY);
  /* A rejected batch still returns its unchanged descriptors for retry. */
  assert(MCD_videoAudioFeedBatchAsync(0x3FFF8,1));
  mcd_test_memmode=2;mcd_test_stat[0]=MCD_CMD_VIDEO_AUDIO_FEED_BATCH;
  mcd_test_stat[1]=MCD_OK;mcd_test_stat[2]=2;mcd_test_stat[3]=0;MCD_update();
  mcd_test_stat[0]=0;MCD_update();assert(MCD_isBusy());
  mcd_test_memmode=1;MCD_update();
  assert(!MCD_isBusy() && MCD_getWordRAM() && MCD_getVideoAudioClock()==131072UL);
}
int main(void) {
  memset(vram_words,0,sizeof(vram_words));
  mcd_test_stat[7] = MCD_READY_MAGIC; mcd_test_stat[6] = MCD_ABI_VERSION;
  MCD_init();
  assert(registers[2] == 0x30 && registers[4] == 7 && registers[16] == 1);
  assert(registers[11] == 0 && registers[13] == 0x3F && registers[15] == 2);
  assert(cram[49] == 0xEEE && MCD_getFrameCount() == 0);
  palette_tests(); map_tests(); tile_text_scroll_tests(); frame_input_ipc_tests(); video_audio_ipc_tests();
  video_source_ipc_tests();
  video_workspace_ipc_tests();
  video_audio_batch_ipc_tests();
  return 0;
}
