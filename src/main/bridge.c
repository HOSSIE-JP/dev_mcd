#include <mcd/bridge.h>
#include <main/bios.def.h>
#include "font.h"
#define CMD ((volatile u16 *)0xA12010)
#define STAT ((volatile u16 *)0xA12020)
#define MEMMODE (*(volatile u8 *)0xA12003)
#define VDPC (*(volatile u32 *)0xC00004)
#define VDPR (*(volatile u16 *)0xC00004)
#define VDPD (*(volatile u16 *)0xC00000)
extern void mcd_wait_frame(void);
static u16 state, command, elapsed, last_result;
static u32 file_size;
static bool valid_word;

static void barrier(void) { asm volatile("" ::: "memory"); }
static u16 irq_off(void) {
  u16 sr; asm volatile("move.w %%sr,%0\nori.w #0x700,%%sr" : "=d"(sr) :: "cc","memory"); return sr;
}
static void irq_restore(u16 sr) { asm volatile("move.w %0,%%sr" :: "d"(sr) : "cc","memory"); }
static void vram(u16 addr) { VDPC = 0x40000000UL | ((u32)(addr & 0x3FFF)<<16) | (addr>>14); }

static bool submit(u16 op, u16 p1, u16 p2)
{
  if (state || CMD[0] || STAT[0]) return false;
  if (STAT[7] != MCD_READY_MAGIC || STAT[6] != MCD_ABI_VERSION) {
    last_result = MCD_ERR_NOT_READY; return false;
  }
  if (op == MCD_CMD_READ) {
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
    CMD[0] = 0;
    state = 2;
  } else if (state == 2 && !STAT[0]) {
    if (command == MCD_CMD_READ && !(MEMMODE & 1)) return;
    valid_word = command == MCD_CMD_READ && last_result == MCD_OK;
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
void SYS_doVBlankProcess(void) { mcd_wait_frame(); MCD_update(); }
u16 JOY_readJoypad(u16 joy) { return joy == JOY_1 ? *(volatile u8 *)BIOS_JOY1_HOLD : 0; }

void PAL_setPalette(u16 palette, const u16 *colors)
{
  u16 sr, i;
  if (palette > 3 || !colors) return;
  sr = irq_off();
  VDPC = 0xC0000000UL | ((u32)palette << 21);
  for (i=0; i<16; ++i) VDPD = colors[i] & 0xEEE;
  irq_restore(sr);
}
void VDP_drawText(const char *text, u16 x, u16 y)
{
  u16 sr;
  if (!text || x >= 40 || y >= 28) return;
  sr = irq_off(); vram(0xC000 + y*128 + x*2);
  while (*text && x++ < 40) {
    unsigned char ch = *text++;
    if (ch < 32 || ch > 127) ch = '?';
    VDPD = 0x6000 | (1152 + ch - 32);
  }
  irq_restore(sr);
}
void VDP_clearTextLine(u16 y) { VDP_drawText("                                        ", 0, y); }
u16 VDP_drawImage(VDPPlane plane, const void *image, u32 bytes)
{
  const u16 *p = image;
  u16 count, x, y, sr;
  if (!image || ((u32)image & 1) || bytes < 44 || plane > BG_B) return MCD_ERR_ARGUMENT;
  if (p[0] != 0x4D49 || p[1] != 0x4D47 || p[2] != 40 || p[3] != 28) return MCD_ERR_FORMAT;
  count = p[4];
  if (!count || count > 1120 || p[5] != 0 || bytes != 44UL + (u32)count*32 + 2240) return MCD_ERR_SIZE;
  for (x=0; x<1120; ++x) if (p[22 + (u32)count*16 + x] >= count) return MCD_ERR_FORMAT;
  VDPR = 0x8124; /* Keep VBlank/INT2 alive while the display is blanked. */
  PAL_setPalette(0, p+6);
  sr = irq_off(); vram(32); irq_restore(sr);
  p += 22;
  for (u32 i=0; i<(u32)count*16; ++i) VDPD = *p++;
  for (y=0; y<28; ++y) {
    sr = irq_off(); vram((plane == BG_A ? 0xC000 : 0xE000) + y*128);
    for (x=0; x<40; ++x) VDPD = 1 + *p++;
    irq_restore(sr);
  }
  VDPR = 0x8164;
  return MCD_OK;
}
void MCD_init(void)
{
  u16 sr = irq_off();
  *(volatile u8 *)BIOS_VDP_UPDATE_FLAGS = 0;
  *(volatile u8 *)BIOS_VBLANK_HANDLER_FLAGS = 0;
  vram(0x9000);
  for (u16 i=0; i<sizeof(mcd_font)/2; ++i) VDPD = mcd_font[i];
  VDPC = 0xC0620000UL; VDPD = 0xEEE; /* Palette 3 color 1. */
  VDPR = 0x8164;
  irq_restore(sr);
  asm volatile("move.w #0x2000,%%sr" ::: "memory");
}
