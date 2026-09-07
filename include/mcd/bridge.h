#ifndef MCD_BRIDGE_H
#define MCD_BRIDGE_H
#include <types.h>
#include <mcd/protocol.h>

/* A small SGDK-style source API, not an SGDK ABI or complete replacement. */
typedef enum { BG_A = 0, BG_B = 1 } VDPPlane;
#define PAL0 0
#define PAL1 1
#define PAL2 2
#define PAL3 3
#define TILE_ATTR(pal, priority, vflip, hflip) \
  ((((pal) & 3) << 13) | ((priority) ? 0x8000 : 0) | \
   ((vflip) ? 0x1000 : 0) | ((hflip) ? 0x0800 : 0))
#define TILE_ATTR_FULL(pal, priority, vflip, hflip, tile) \
  (TILE_ATTR(pal, priority, vflip, hflip) | ((tile) & 0x07FF))
/* Fixed H40 / 224-line layout. Tile zero, font and VDP tables are reserved. */
#define MCD_SCREEN_COLUMNS 40
#define MCD_SCREEN_ROWS 28
#define MCD_PLANE_COLUMNS 64
#define MCD_PLANE_ROWS 32
#define MCD_USER_TILE_FIRST 1
#define MCD_USER_TILE_END 1152
#define JOY_1 0
#define BUTTON_UP 0x01
#define BUTTON_DOWN 0x02
#define BUTTON_LEFT 0x04
#define BUTTON_RIGHT 0x08
#define BUTTON_B 0x10
#define BUTTON_C 0x20
#define BUTTON_A 0x40
#define BUTTON_START 0x80

void SYS_doVBlankProcess(void);
u16 JOY_readJoypad(u16 joy);
/* Edges are sampled once by SYS_doVBlankProcess(), never consumed by reads. */
u16 MCD_readJoypadPressed(u16 joy);
u16 MCD_readJoypadReleased(u16 joy);
u32 MCD_getFrameCount(void);
void MCD_waitFrames(u16 frames);
/* Immediate CPU writes; these do not accept SGDK TransferMethod arguments. */
void PAL_setPalette(u16 palette, const u16 *colors);
void PAL_setColors(u16 index, const u16 *colors, u16 count);
void PAL_setColor(u16 index, u16 color);
/* Shadow value: direct CRAM writes outside this API are not reflected. */
u16 PAL_getColor(u16 index);
/* One cooperative fade at a time, advanced by SYS_doVBlankProcess().
 * Copies colors before returning. Any PAL_set* call cancels the active fade.
 * frames == 0 applies immediately. Valid range: index + count <= 64. */
u16 MCD_fadePaletteTo(u16 index, const u16 *colors, u16 count, u16 frames);
bool PAL_isDoingFade(void);
void MCD_cancelPaletteFade(void);
void VDP_setTextPlane(VDPPlane plane);
void VDP_setTextPalette(u16 palette);
void VDP_setTextPriority(bool priority);
void VDP_drawTextBG(VDPPlane plane, const char *text, u16 x, u16 y);
void VDP_drawText(const char *text, u16 x, u16 y);
void VDP_clearText(u16 x, u16 y, u16 width);
void VDP_clearTextLine(u16 y);
/* Tilemap writes use 64 x 32 plane coordinates, text uses visible 40 x 28.
 * Invalid rectangles are rejected in full; no wrapping into other VRAM areas. */
void VDP_setTileMapXY(VDPPlane plane, u16 attributes, u16 x, u16 y);
void VDP_fillTileMapRect(VDPPlane plane, u16 attributes, u16 x, u16 y, u16 width, u16 height);
u16 MCD_setTileMapRect(VDPPlane plane, const u16 *data, u32 sourceCells,
                       u16 x, u16 y, u16 width, u16 height, u16 stride);
u16 MCD_clearPlane(VDPPlane plane);
/* Immediate CPU tile upload, word-aligned source, 1 <= tile < 1152.
 * Large uploads can exceed VBlank: split transfers across application frames. */
u16 MCD_loadTiles(const void *data, u16 tile, u16 count);
/* Whole-plane scroll only. MCD_init() selects this VDP scroll mode. */
void VDP_setHorizontalScroll(VDPPlane plane, s16 value);
void VDP_setVerticalScroll(VDPPlane plane, s16 value);
u16 VDP_drawImage(VDPPlane plane, const void *image, u32 bytes);
void MCD_init(void);
void MCD_update(void);
bool MCD_isBusy(void);
u16 MCD_getResult(void);
u32 MCD_getFileSize(void);
const void *MCD_getWordRAM(void);
u16 MCD_getAudioFlags(void);
u16 MCD_getSubTicks(void);
bool MCD_readFileAsync(u16 asset);
bool MCD_prepareADPCMAsync(void);
bool MCD_playADPCM(void);
bool MCD_stopADPCM(void);
bool MCD_playCDDA(u16 track, bool repeat);
bool MCD_stopCDDA(void);
bool MCD_pauseCDDA(void);
bool MCD_resumeCDDA(void);
/* Sector-aligned offsets within NOVEL.PAK. Word destination is in 2 KiB units. */
bool MCD_readRangeAsync(u32 offset, u32 bytes, u16 destinationSector);
/* channel 0: resident BGM, channel 1: voice/SFX. MIMA, 4-bit IMA, mono. */
bool MCD_prepareStreamAsync(u32 offset, u32 bytes, u16 channel, bool loop);
bool MCD_playStream(u16 channel);
bool MCD_stopStream(u16 channel);
/* Exclusive MTV1 audio: 16000 Hz mono RF5C164 sign/magnitude PCM8.
 * BEGIN invalidates resident IMA audio. FEED transfers 2M Word RAM ownership,
 * copies count bytes (1..32768), then returns ownership before completion.
 * Offsets are bytes from Main Word RAM base 0x200000, not CD offsets.
 * FEED/PLAY/STOP/CLOCK completion updates the cumulative sample clock.
 * Wait for MCD_isBusy()==false and inspect MCD_getResult() before using it. */
bool MCD_videoAudioBeginAsync(u32 totalSamples);
bool MCD_videoAudioFeedAsync(u32 wordByteOffset, u16 count);
/* Batch FEED has the same ownership and clock rules. The descriptor table has
 * 1..64 entries of 8 big-endian bytes: source byte offset u32, sample count u16
 * (1..32768), reserved u16 (zero). All sources and the table must fit Word RAM.
 * PCM bytes cannot contain FF. Validation/capacity rejection commits no audio.
 * MCD_OK commits all samples; audio flags report any post-copy underrun. */
bool MCD_videoAudioFeedBatchAsync(u32 wordDescriptorOffset, u16 count);
bool MCD_videoAudioPlayAsync(void);
bool MCD_videoAudioStopAsync(void);
bool MCD_videoAudioClockAsync(void);
u32 MCD_getVideoAudioClock(void);
/* Video-only source read-ahead in Sub PRG RAM. OPEN reserves the CD reader and
 * invalidates resident IMA data. READ accepts monotonically increasing,
 * sector-aligned offsets relative to the opened resource (overlap is allowed),
 * copies at most 64 KiB into 2M Word RAM, and returns ownership on completion.
 * CLOSE waits for outstanding prefetch before releasing its PRG buffers.
 * Always close the source after stopping video PCM and before loading IMA/CDDA. */
bool MCD_videoSourceOpenAsync(u32 packOffset, u32 resourceBytes);
bool MCD_videoSourceReadAsync(u32 relativeOffset, u32 bytes, u16 destinationSector);
bool MCD_videoSourceCloseAsync(void);
/* Preserve Word RAM 0x20000..0x2ffff (the novel's four portrait caches) in
 * reserved Sub PRG RAM while two video windows use that space. SAVE/RESTORE
 * transfer Word RAM ownership and must complete before either CPU reuses it.
 * Restore once before closing the source; this is not a general save-state API. */
bool MCD_videoWorkspaceSaveAsync(void);
bool MCD_videoWorkspaceRestoreAsync(void);
#endif
