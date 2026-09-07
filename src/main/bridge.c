#include <mcd/bridge.h>
#ifdef MCD_BRIDGE_HOST_TEST
#include "bridge_host.h"
#define CMD mcd_test_cmd
#define STAT mcd_test_stat
#define MEMMODE mcd_test_memmode
static u16 irq_off(void) { return 0; }
static void irq_restore(u16 sr) { (void)sr; }
static void control(u32 value) { mcd_test_control(value); }
static void reg(u16 value) { mcd_test_register(value); }
static void data(u16 value) { mcd_test_data(value); }
static u16 joy_hold(void) { return mcd_test_joy; }
#else
#include <main/bios.def.h>
#define CMD ((volatile u16 *)0xA12010)
#define STAT ((volatile u16 *)0xA12020)
#define MEMMODE (*(volatile u8 *)0xA12003)
#define VDPC (*(volatile u32 *)0xC00004)
#define VDPR (*(volatile u16 *)0xC00004)
#define VDPD (*(volatile u16 *)0xC00000)
static u16 irq_off(void) {
  u16 sr; asm volatile("move.w %%sr,%0\nori.w #0x700,%%sr" : "=d"(sr) :: "cc","memory"); return sr;
}
static void irq_restore(u16 sr) { asm volatile("move.w %0,%%sr" :: "d"(sr) : "cc","memory"); }
static void control(u32 value) { VDPC = value; }
static void reg(u16 value) { VDPR = value; }
static void data(u16 value) { VDPD = value; }
static u16 joy_hold(void) { return *(volatile u8 *)BIOS_JOY1_HOLD; }
#endif
#include "font.h"
extern void mcd_wait_frame(void);
static u16 state, command, elapsed, last_result;
static u32 file_size, video_audio_clock;
static bool valid_word;
static u32 frames;
static u16 held_keys, pressed_keys, released_keys;
static VDPPlane text_plane;
static u16 text_attributes;
static u16 palette_colors[64], fade_source[64], fade_target[64];
static u16 fade_first, fade_count, fade_frames, fade_elapsed;

static void barrier(void) { asm volatile("" ::: "memory"); }
static void vram(u16 addr) { control(0x40000000UL | ((u32)(addr & 0x3FFF)<<16) | (addr>>14)); }
static bool aligned(const void *p) { return !((__UINTPTR_TYPE__)p & 1); }
static bool plane_valid(VDPPlane plane) { return plane == BG_A || plane == BG_B; }
static u16 plane_address(VDPPlane plane) { return plane == BG_A ? 0xC000 : 0xE000; }

static bool submit(u16 op, u16 p1, u16 p2)
{
  if (state || CMD[0] || STAT[0]) return false;
  if (STAT[7] != MCD_READY_MAGIC || STAT[6] != MCD_ABI_VERSION) {
    last_result = MCD_ERR_NOT_READY; return false;
  }
  if (op == MCD_CMD_READ || op == MCD_CMD_READ_RANGE || op == MCD_CMD_VIDEO_AUDIO_FEED ||
      op == MCD_CMD_VIDEO_AUDIO_FEED_BATCH ||
      op == MCD_CMD_VIDEO_SOURCE_READ || op == MCD_CMD_VIDEO_WORKSPACE_SAVE ||
      op == MCD_CMD_VIDEO_WORKSPACE_RESTORE) {
    valid_word = false;
    MEMMODE |= 2;
  }
  CMD[1] = p1; CMD[2] = p2;
  command = op; elapsed = 0; file_size = 0; last_result = MCD_OK;
  state = 1;
  barrier();
  CMD[0] = op;
  return true;
}
void MCD_update(void)
{
  if (state != 1 && state != 2) return;
  if (++elapsed > 1800) { last_result = MCD_ERR_TIMEOUT; valid_word = false; state = 3; return; }
  if (state == 1 && STAT[0] == command) {
    last_result = STAT[1];
    file_size = ((u32)STAT[2]<<16) | STAT[3];
    if ((command >= MCD_CMD_VIDEO_AUDIO_BEGIN && command <= MCD_CMD_VIDEO_AUDIO_CLOCK) ||
        command == MCD_CMD_VIDEO_AUDIO_FEED_BATCH)
      video_audio_clock = file_size;
    CMD[0] = 0;
    state = 2;
  } else if (state == 2 && !STAT[0]) {
    bool word_command = command == MCD_CMD_READ || command == MCD_CMD_READ_RANGE ||
      command == MCD_CMD_VIDEO_AUDIO_FEED || command == MCD_CMD_VIDEO_AUDIO_FEED_BATCH ||
      command == MCD_CMD_VIDEO_SOURCE_READ || command == MCD_CMD_VIDEO_WORKSPACE_SAVE ||
      command == MCD_CMD_VIDEO_WORKSPACE_RESTORE;
    if (word_command && !(MEMMODE & 1)) return;
    /* Commands such as CLOCK neither transfer nor overwrite Word RAM. */
    if (word_command)
      valid_word = last_result == MCD_OK || command == MCD_CMD_VIDEO_AUDIO_FEED ||
        command == MCD_CMD_VIDEO_AUDIO_FEED_BATCH;
    state = 0;
  }
}
bool MCD_isBusy(void) { return state == 1 || state == 2; }
u16 MCD_getResult(void) { return last_result; }
u32 MCD_getFileSize(void) { return file_size; }
const void *MCD_getWordRAM(void) { return valid_word && (MEMMODE & 1) ? (const void *)0x200000 : 0; }
u16 MCD_getAudioFlags(void) { return STAT[4]; }
u16 MCD_getSubTicks(void) { return STAT[5]; }
bool MCD_readFileAsync(u16 asset) { return submit(MCD_CMD_READ, asset, 0); }
bool MCD_prepareADPCMAsync(void) { return submit(MCD_CMD_PREPARE_ADPCM, 0, 0); }
bool MCD_playADPCM(void) { return submit(MCD_CMD_PLAY_ADPCM, 0, 0); }
bool MCD_stopADPCM(void) { return submit(MCD_CMD_STOP_ADPCM, 0, 0); }
bool MCD_playCDDA(u16 track, bool repeat) { return submit(MCD_CMD_PLAY_CDDA, track, repeat); }
bool MCD_stopCDDA(void) { return submit(MCD_CMD_STOP_CDDA, 0, 0); }
bool MCD_pauseCDDA(void) { return submit(MCD_CMD_PAUSE_CDDA, 0, 0); }
bool MCD_resumeCDDA(void) { return submit(MCD_CMD_RESUME_CDDA, 0, 0); }
static bool range_submit(u16 op, u32 offset, u32 bytes, u16 option)
{
  if (state || CMD[0] || STAT[0]) return false;
  /* The command word is still zero while all five parameters are published. */
  CMD[3] = (u16)offset; CMD[4] = bytes >> 16; CMD[5] = (u16)bytes;
  return submit(op, option, offset >> 16);
}
bool MCD_readRangeAsync(u32 o, u32 n, u16 d) { return range_submit(MCD_CMD_READ_RANGE,o,n,d); }
bool MCD_prepareStreamAsync(u32 o,u32 n,u16 c,bool loop) {
  if (c>1) return false;
  return range_submit(MCD_CMD_PREPARE_STREAM,o,n,c | (loop ? 2 : 0));
}
bool MCD_playStream(u16 c) { return submit(MCD_CMD_PLAY_STREAM,c,0); }
bool MCD_stopStream(u16 c) { return submit(MCD_CMD_STOP_STREAM,c,0); }
bool MCD_videoAudioBeginAsync(u32 total) {
  if (!total || total > 115200000UL) return false;
  return submit(MCD_CMD_VIDEO_AUDIO_BEGIN,total>>16,(u16)total);
}
bool MCD_videoAudioFeedAsync(u32 offset,u16 count) {
  if (state || CMD[0] || STAT[0] || !count || count > 32768 || offset >= 0x40000UL ||
      count > 0x40000UL-offset || !(MEMMODE&1)) return false;
  CMD[3] = count;
  return submit(MCD_CMD_VIDEO_AUDIO_FEED,offset>>16,(u16)offset);
}
bool MCD_videoAudioFeedBatchAsync(u32 offset,u16 count) {
  if (state || CMD[0] || STAT[0] || !count || count > 64 || offset >= 0x40000UL ||
      (u32)count*8 > 0x40000UL-offset || !(MEMMODE&1)) return false;
  CMD[3] = count;
  return submit(MCD_CMD_VIDEO_AUDIO_FEED_BATCH,offset>>16,(u16)offset);
}
bool MCD_videoAudioPlayAsync(void) { return submit(MCD_CMD_VIDEO_AUDIO_PLAY,0,0); }
bool MCD_videoAudioStopAsync(void) { return submit(MCD_CMD_VIDEO_AUDIO_STOP,0,0); }
bool MCD_videoAudioClockAsync(void) { return submit(MCD_CMD_VIDEO_AUDIO_CLOCK,0,0); }
u32 MCD_getVideoAudioClock(void) { return video_audio_clock; }
bool MCD_videoSourceOpenAsync(u32 offset,u32 bytes) {
  if (!bytes || (offset&2047) || (bytes&2047) || offset>0xFFFFFFFFUL-bytes) return false;
  return range_submit(MCD_CMD_VIDEO_SOURCE_OPEN,offset,bytes,0);
}
bool MCD_videoSourceReadAsync(u32 offset,u32 bytes,u16 destination) {
  if (!bytes || bytes>0x10000UL || (offset&2047) || (bytes&2047) ||
      offset>0xFFFFFFFFUL-bytes || destination>=128 ||
      bytes>0x40000UL-((u32)destination<<11) || !(MEMMODE&1)) return false;
  return range_submit(MCD_CMD_VIDEO_SOURCE_READ,offset,bytes,destination);
}
bool MCD_videoSourceCloseAsync(void) { return submit(MCD_CMD_VIDEO_SOURCE_CLOSE,0,0); }
bool MCD_videoWorkspaceSaveAsync(void) {
  if (!(MEMMODE&1)) return false;
  return submit(MCD_CMD_VIDEO_WORKSPACE_SAVE,0,0);
}
bool MCD_videoWorkspaceRestoreAsync(void) {
  if (!(MEMMODE&1)) return false;
  return submit(MCD_CMD_VIDEO_WORKSPACE_RESTORE,0,0);
}
static bool palette_range(u16 first, u16 count) {
  return first < 64 && count && count <= 64 - first;
}
static void palette_write(u16 first, const u16 *colors, u16 count) {
  u16 sr = irq_off();
  control(0xC0000000UL | ((u32)first << 17));
  for (u16 i=0; i<count; ++i) {
    palette_colors[first+i] = colors[i] & 0xEEE;
    data(palette_colors[first+i]);
  }
  irq_restore(sr);
}
static void fade_tick(void) {
  if (!fade_frames) return;
  ++fade_elapsed;
  for (u16 i=fade_first; i<fade_first+fade_count; ++i) {
    u16 color = 0;
    for (u16 shift=1; shift<=9; shift+=4) {
      s16 source = (fade_source[i] >> shift) & 7;
      s16 target = (fade_target[i] >> shift) & 7;
      color |= (u16)(source + ((s32)(target-source)*fade_elapsed)/fade_frames) << shift;
    }
    palette_colors[i] = color;
  }
  palette_write(fade_first, palette_colors+fade_first, fade_count);
  if (fade_elapsed == fade_frames) fade_frames = 0;
}
void SYS_doVBlankProcess(void) {
  u16 keys;
  mcd_wait_frame(); MCD_update(); ++frames;
  keys = joy_hold();
  pressed_keys = keys & ~held_keys;
  released_keys = held_keys & ~keys;
  held_keys = keys;
  fade_tick();
}
u16 JOY_readJoypad(u16 joy) { return joy == JOY_1 ? joy_hold() : 0; }
u16 MCD_readJoypadPressed(u16 joy) { return joy == JOY_1 ? pressed_keys : 0; }
u16 MCD_readJoypadReleased(u16 joy) { return joy == JOY_1 ? released_keys : 0; }
u32 MCD_getFrameCount(void) { return frames; }
void MCD_waitFrames(u16 count) { while (count--) SYS_doVBlankProcess(); }

void PAL_setPalette(u16 palette, const u16 *colors) {
  if (palette <= 3) PAL_setColors(palette*16, colors, 16);
}
void PAL_setColors(u16 first, const u16 *colors, u16 count) {
  if (!colors || !aligned(colors) || !palette_range(first,count)) return;
  fade_frames = 0;
  palette_write(first,colors,count);
}
void PAL_setColor(u16 first, u16 color) { PAL_setColors(first,&color,1); }
u16 PAL_getColor(u16 first) { return first < 64 ? palette_colors[first] : 0; }
u16 MCD_fadePaletteTo(u16 first, const u16 *colors, u16 count, u16 duration) {
  if (!colors || !aligned(colors) || !palette_range(first,count)) return MCD_ERR_ARGUMENT;
  if (!duration) { PAL_setColors(first,colors,count); return MCD_OK; }
  for (u16 i=0; i<count; ++i) {
    fade_source[first+i] = palette_colors[first+i];
    fade_target[first+i] = colors[i] & 0xEEE;
  }
  fade_first = first; fade_count = count; fade_frames = duration; fade_elapsed = 0;
  return MCD_OK;
}
bool PAL_isDoingFade(void) { return fade_frames != 0; }
void MCD_cancelPaletteFade(void) { fade_frames = 0; }

void VDP_setTextPlane(VDPPlane plane) { if (plane_valid(plane)) text_plane = plane; }
void VDP_setTextPalette(u16 palette) {
  if (palette <= 3) text_attributes = (text_attributes & 0x8000) | (palette << 13);
}
void VDP_setTextPriority(bool priority) {
  text_attributes = (text_attributes & 0x6000) | (priority ? 0x8000 : 0);
}
void VDP_drawTextBG(VDPPlane plane, const char *text, u16 x, u16 y) {
  u16 sr;
  if (!plane_valid(plane) || !text || x >= MCD_SCREEN_COLUMNS || y >= MCD_SCREEN_ROWS) return;
  sr = irq_off(); vram(plane_address(plane) + y*128 + x*2);
  while (*text && x++ < MCD_SCREEN_COLUMNS) {
    unsigned char ch = *text++;
    if (ch < 32 || ch > 127) ch = '?';
    data(text_attributes | (1152 + ch - 32));
  }
  irq_restore(sr);
}
void VDP_drawText(const char *text, u16 x, u16 y) { VDP_drawTextBG(text_plane,text,x,y); }
void VDP_clearText(u16 x, u16 y, u16 width) {
  if (x >= MCD_SCREEN_COLUMNS || y >= MCD_SCREEN_ROWS) return;
  if (width > MCD_SCREEN_COLUMNS-x) width = MCD_SCREEN_COLUMNS-x;
  VDP_fillTileMapRect(text_plane, text_attributes | 1152, x,y,width,1);
}
void VDP_clearTextLine(u16 y) { VDP_clearText(0,y,MCD_SCREEN_COLUMNS); }
static bool map_rect(VDPPlane plane, u16 x, u16 y, u16 width, u16 height) {
  return plane_valid(plane) && x < MCD_PLANE_COLUMNS && y < MCD_PLANE_ROWS &&
    width && height && width <= MCD_PLANE_COLUMNS-x && height <= MCD_PLANE_ROWS-y;
}
void VDP_setTileMapXY(VDPPlane plane, u16 attributes, u16 x, u16 y) {
  VDP_fillTileMapRect(plane,attributes,x,y,1,1);
}
void VDP_fillTileMapRect(VDPPlane plane,u16 attributes,u16 x,u16 y,u16 width,u16 height) {
  if (!map_rect(plane,x,y,width,height)) return;
  for (u16 row=0; row<height; ++row) {
    u16 sr = irq_off(); vram(plane_address(plane)+(y+row)*128+x*2);
    for (u16 col=0; col<width; ++col) data(attributes);
    irq_restore(sr);
  }
}
u16 MCD_setTileMapRect(VDPPlane plane,const u16 *tiles,u32 sourceCells,
                       u16 x,u16 y,u16 width,u16 height,u16 stride) {
  if (!tiles || !aligned(tiles) || !map_rect(plane,x,y,width,height) || stride < width)
    return MCD_ERR_ARGUMENT;
  if ((u32)(height-1)*stride+width > sourceCells) return MCD_ERR_SIZE;
  for (u16 row=0; row<height; ++row) {
    u16 sr = irq_off(); vram(plane_address(plane)+(y+row)*128+x*2);
    for (u16 col=0; col<width; ++col) data(tiles[(u32)row*stride+col]);
    irq_restore(sr);
  }
  return MCD_OK;
}
u16 MCD_clearPlane(VDPPlane plane) {
  if (!plane_valid(plane)) return MCD_ERR_ARGUMENT;
  VDP_fillTileMapRect(plane,0,0,0,MCD_PLANE_COLUMNS,MCD_PLANE_ROWS);
  return MCD_OK;
}
u16 MCD_loadTiles(const void *tiles,u16 tile,u16 count) {
  const u16 *words = tiles;
  if (!tiles || !aligned(tiles) || tile < MCD_USER_TILE_FIRST || tile >= MCD_USER_TILE_END || !count)
    return MCD_ERR_ARGUMENT;
  if (count > MCD_USER_TILE_END-tile) return MCD_ERR_SIZE;
  /* At most 16 words with interrupts masked: CD INT2 remains serviced. */
  for (u16 t=0; t<count; ++t) {
    u16 sr = irq_off(); vram((tile+t)*32);
    for (u16 word=0; word<16; ++word) data(*words++);
    irq_restore(sr);
  }
  return MCD_OK;
}
void VDP_setHorizontalScroll(VDPPlane plane,s16 value) {
  if (!plane_valid(plane)) return;
  u16 sr = irq_off(); vram(0xFC00+plane*2); data((u16)value & 0x03FF); irq_restore(sr);
}
void VDP_setVerticalScroll(VDPPlane plane,s16 value) {
  if (!plane_valid(plane)) return;
  u16 sr = irq_off(); control(0x40000010UL|((u32)plane<<17));
  data((u16)value & 0x03FF); irq_restore(sr);
}
u16 VDP_drawImage(VDPPlane plane, const void *image, u32 bytes)
{
  const u16 *p = image;
  u16 count, x, y, sr;
  if (!image || !aligned(image) || bytes < 44 || !plane_valid(plane)) return MCD_ERR_ARGUMENT;
  if (p[0] != 0x4D49 || p[1] != 0x4D47 || p[2] != 40 || p[3] != 28) return MCD_ERR_FORMAT;
  count = p[4];
  if (!count || count > 1120 || p[5] != 0 || bytes != 44UL + (u32)count*32 + 2240) return MCD_ERR_SIZE;
  for (x=0; x<1120; ++x) if (p[22 + (u32)count*16 + x] >= count) return MCD_ERR_FORMAT;
  reg(0x8124); /* Keep VBlank/INT2 alive while the display is blanked. */
  PAL_setPalette(0, p+6);
  sr = irq_off(); vram(32); irq_restore(sr);
  p += 22;
  for (u32 i=0; i<(u32)count*16; ++i) data(*p++);
  for (y=0; y<28; ++y) {
    sr = irq_off(); vram((plane == BG_A ? 0xC000 : 0xE000) + y*128);
    for (x=0; x<40; ++x) data(1 + *p++);
    irq_restore(sr);
  }
  reg(0x8164);
  return MCD_OK;
}
void MCD_init(void)
{
  u16 sr = irq_off();
#ifndef MCD_BRIDGE_HOST_TEST
  *(volatile u8 *)BIOS_VDP_UPDATE_FLAGS = 0;
  *(volatile u8 *)BIOS_VBLANK_HANDLER_FLAGS = 0;
#endif
  frames = 0; held_keys = joy_hold(); pressed_keys = released_keys = 0;
  text_plane = BG_A; text_attributes = 0x6000; fade_frames = 0;
  /* Fixed layout shared by image, text, scroll and novel rendering. */
  reg(0x8230); reg(0x8407); reg(0x8B00); reg(0x8C81); reg(0x8D3F); reg(0x8F02); reg(0x9001);
  vram(0); for (u16 i=0; i<16; ++i) data(0);
  vram(0x9000);
  for (u16 i=0; i<sizeof(mcd_font)/2; ++i) data(mcd_font[i]);
  for (u16 i=0; i<64; ++i) palette_colors[i] = 0;
  palette_colors[49] = 0xEEE;
  palette_write(0,palette_colors,64);
  VDP_setHorizontalScroll(BG_A,0); VDP_setHorizontalScroll(BG_B,0);
  VDP_setVerticalScroll(BG_A,0); VDP_setVerticalScroll(BG_B,0);
  reg(0x8164);
  irq_restore(sr);
#ifndef MCD_BRIDGE_HOST_TEST
  asm volatile("move.w #0x2000,%%sr" ::: "memory");
#endif
}
