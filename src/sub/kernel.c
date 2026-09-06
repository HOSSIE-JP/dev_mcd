#include <types.h>
#include <sub/cdrom.def.h>
#include <sub/bios.def.h>
#include <sub/pcm.h>
#include <mcd/protocol.h>
#include <mcd/ima.h>

#define CMD ((volatile u16 *)0xFF8010)
#define STAT ((volatile u16 *)0xFF8020)
#define MEMMODE (*(volatile u8 *)0xFF8003)
#define STAGING ((u8 *)0x20000)
#define STAGING_SIZE 0x10000UL
#define WORD ((u8 *)0x80000)
extern volatile u16 access_op, access_op_result;
extern volatile u32 filesize;
extern const char *filename;
extern u8 *filebuff;
extern void mcd_bios_call(u16 op, const void *param);
extern const u8 *mcd_find_file(const char *name);
volatile u16 sub_ticks;
static const char *const names[] = {"IPX.MMD;1", "IMAGE.MIM;1", "SOUND.IMA;1", "MISSING.DAT;1"};
static u16 active, flags, result, start_tick, audio_start_tick;
static u16 track_number;
static u32 loaded, sample_count, decoded;
static MCD_IMAState ima;
/* 0 idle, 1 reading, 2 decoding, 3 waiting for Main's acknowledgement. */
static u16 phase;
static bool returning_word;

static u32 be32(const u8 *p) { return ((u32)p[0]<<24)|((u32)p[1]<<16)|((u32)p[2]<<8)|p[3]; }
static u16 be16(const u8 *p) { return ((u16)p[0]<<8)|p[1]; }
static void barrier(void) { asm volatile("" ::: "memory"); }

static void finish(u16 error)
{
  if (returning_word) { MEMMODE |= 1; returning_word = false; }
  result = error;
  STAT[1] = error;
  STAT[2] = loaded >> 16;
  STAT[3] = loaded;
  STAT[4] = flags;
  barrier();
  STAT[0] = active;
  phase = 3;
}

static void begin_read(u16 asset, bool prepare)
{
  const u8 *info;
  u32 size, rounded;
  if (asset > MCD_ASSET_MISSING || (prepare && asset != MCD_ASSET_AUDIO)) {
    finish(MCD_ERR_ARGUMENT); return;
  }
  info = mcd_find_file(names[asset]);
  if (!info) { finish(MCD_ERR_NOT_FOUND); return; }
  size = be32(info + 18);
  rounded = (size + 2047) & ~2047UL;
  if (!size || size > (prepare ? STAGING_SIZE : 0x40000UL) ||
      rounded > (prepare ? STAGING_SIZE : 0x40000UL)) {
    finish(MCD_ERR_SIZE); return;
  }
  if (!prepare && !(MEMMODE & 2)) { finish(MCD_ERR_BUSY); return; }
  /* The optical drive cannot seek data and continue CD-DA at the same time. */
  if (flags & (MCD_CDDA_REQUESTED | MCD_CDDA_PAUSED)) mcd_bios_call(BIOS_MSC_STOP, 0);
  flags &= ~(MCD_CDDA_REQUESTED | MCD_CDDA_PAUSED);
  if (prepare) { *PCM_CDISABLE = 0xFF; flags &= ~(MCD_AUDIO_READY | MCD_AUDIO_PLAYING); }
  filename = names[asset];
  filebuff = prepare ? STAGING : WORD;
  barrier(); /* Publish the operation LAST: INT2 can run at any instruction. */
  access_op = CDROM_LOAD_CDC;
  start_tick = sub_ticks;
  phase = 1;
}

static void decode_begin(void)
{
  if (loaded < 16 || be32(STAGING) != 0x4D494D41UL || be16(STAGING+4) != 1 ||
      be16(STAGING+6) != 22050 || STAGING[14] > 88 || STAGING[15] != 0) {
    finish(MCD_ERR_FORMAT); return;
  }
  sample_count = be32(STAGING+8);
  if (!sample_count || sample_count > 65534 || loaded != 16 + ((sample_count+1)>>1)) {
    finish(MCD_ERR_SIZE); return;
  }
  ima.predictor = (s16)be16(STAGING+12);
  ima.index = STAGING[14];
  decoded = 0;
  phase = 2;
}

static void pcm_put(u32 pos, u8 value)
{
  *PCM_CTRL = 0x80 | (pos >> 12);
  *(volatile u8 *)(0xFF2001UL + ((pos & 0xFFF) << 1)) = value;
}

static void decode_chunk(void)
{
  u16 budget = 256;
  while (budget-- && decoded < sample_count) {
    u8 byte = STAGING[16 + (decoded >> 1)];
    unsigned nibble = (decoded & 1) ? byte >> 4 : byte & 15;
    pcm_put(decoded++, MCD_pcmSignMagnitude(MCD_imaDecodeNibble(&ima, nibble)));
  }
  if (decoded == sample_count) {
    /* One-shot tail: sample zero then marker loops into that same silent tail. */
    pcm_put(sample_count, 0x80);
    pcm_put(sample_count+1, 0xFF);
    *PCM_CTRL = 0xC0;
    *PCM_ENV = 0xFF;
    *PCM_PAN = 0xFF;
    *PCM_FDL = 0x6B; *PCM_FDH = 0x05; /* 22048 Hz at 12.5 MHz / 384 */
    *PCM_LSL = sample_count; *PCM_LSH = sample_count >> 8;
    *PCM_ST = 0;
    flags |= MCD_AUDIO_READY;
    finish(MCD_OK);
  }
}

void sub_main(void)
{
  *PCM_CDISABLE = 0xFF;
  access_op = CDROM_LOAD_FILE_LIST;
  start_tick = sub_ticks;
  while (access_op) {
    if ((u16)(sub_ticks-start_tick) > 1800) { STAT[1] = MCD_ERR_TIMEOUT; for (;;) {} }
  }
  if (access_op_result != CDROM_RESULT_OK) { STAT[1] = MCD_ERR_READ; for (;;) {} }
  STAT[6] = MCD_ABI_VERSION;
  STAT[7] = MCD_READY_MAGIC;
  for (;;) {
    STAT[5] = sub_ticks;
    if (flags & MCD_AUDIO_PLAYING) {
      u16 pos = ((u16)*(volatile u8 *)0xFF0023 << 8) | *(volatile u8 *)0xFF0021;
      if (pos >= sample_count || (u16)(sub_ticks-audio_start_tick) > 240) {
        *PCM_CDISABLE = 0xFF;
        flags &= ~MCD_AUDIO_PLAYING;
      }
    }
    STAT[4] = flags;
    if (phase == 3) {
      if (!CMD[0]) { STAT[0] = 0; phase = 0; }
      continue;
    }
    if (phase == 1) {
      if (!access_op) {
        loaded = filesize;
        if (access_op_result != CDROM_RESULT_OK) { finish(MCD_ERR_READ); continue; }
        if (active == MCD_CMD_PREPARE_ADPCM) decode_begin();
        else finish(MCD_OK);
      } else if ((u16)(sub_ticks-start_tick) > 1200) {
        /* Quarantine a hung coroutine. Never return a buffer still being written. */
        STAT[1] = MCD_ERR_TIMEOUT;
        for (;;) { STAT[5] = sub_ticks; }
      }
      continue;
    }
    if (phase == 2) { decode_chunk(); continue; }
    active = CMD[0];
    if (!active || active != CMD[0]) continue;
    loaded = 0;
    returning_word = active == MCD_CMD_READ;
    switch (active) {
    case MCD_CMD_READ: begin_read(CMD[1], false); break;
    case MCD_CMD_PREPARE_ADPCM: begin_read(MCD_ASSET_AUDIO, true); break;
    case MCD_CMD_PLAY_ADPCM:
      if (!(flags & MCD_AUDIO_READY)) { finish(MCD_ERR_NOT_READY); break; }
      *PCM_CDISABLE = 0xFF;
      *PCM_CTRL = 0xC0; *PCM_ST = 0;
      *PCM_CDISABLE = 0xFE;
      flags |= MCD_AUDIO_PLAYING; audio_start_tick = sub_ticks;
      finish(MCD_OK); break;
    case MCD_CMD_STOP_ADPCM:
      *PCM_CDISABLE = 0xFF; flags &= ~MCD_AUDIO_PLAYING;
      finish(MCD_OK); break;
    case MCD_CMD_PLAY_CDDA:
      if (CMD[1] != 2 || CMD[2] > 1) { finish(MCD_ERR_ARGUMENT); break; }
      track_number = 2;
      mcd_bios_call(CMD[2] ? BIOS_MSC_PLAYR : BIOS_MSC_PLAY1, &track_number);
      flags = (flags & ~MCD_CDDA_PAUSED) | MCD_CDDA_REQUESTED;
      finish(MCD_OK); break;
    case MCD_CMD_STOP_CDDA:
      mcd_bios_call(BIOS_MSC_STOP, 0); flags &= ~(MCD_CDDA_REQUESTED | MCD_CDDA_PAUSED);
      finish(MCD_OK); break;
    case MCD_CMD_PAUSE_CDDA:
      mcd_bios_call(BIOS_MSC_PAUSEON, 0);
      flags = (flags & ~MCD_CDDA_REQUESTED) | MCD_CDDA_PAUSED;
      finish(MCD_OK); break;
    case MCD_CMD_RESUME_CDDA:
      mcd_bios_call(BIOS_MSC_PAUSEOFF, 0);
      flags = (flags & ~MCD_CDDA_PAUSED) | MCD_CDDA_REQUESTED;
      finish(MCD_OK); break;
    default: finish(MCD_ERR_ARGUMENT); break;
    }
  }
}
