#ifndef MCD_VIDEO_H
#define MCD_VIDEO_H
#include <mcd/bridge.h>
#include <mcd/video_format.h>

/* Exact MTV1 format from the earlier Mega-CD video study. This native adapter
 * uses two 62 KiB 2M Word windows, Sub PRG read-ahead and two VRAM banks.
 * Word 0x00000..0x1ffff stays resident; 0x20000..0x2ffff is saved in Sub
 * PRG and restored on return. A timeout retains the ownership quarantine.
 * Intended profile FPS is not a general throughput guarantee. */
typedef struct {
  u32 framesShown,framesDropped,cacheReads,rebufferCount,audioSamplesPlayed;
  bool skipped;
} MCDVideoStatus;
/* Blocking and cooperative. B/C/Start skip on a fresh press. Takes over Plane
 * B, both palettes 0/1, video VRAM banks and SAT. Caller restores its scene.
 * Stops CDDA and resident PCM. Audio underrun is silenced and rebuffered at
 * the exact consumed sample; never replays stale ring data. On timeout do not
 * reuse Word RAM: the bridge remains latched until reset. */
u16 MCD_playVideo(u32 offset,u32 bytes,bool skipEnabled,MCDVideoStatus *status);
/* Silent mode is available for diagnostics and constrained configurations. */
u16 MCD_playVideoEx(u32 offset,u32 bytes,bool skipEnabled,bool audioEnabled,MCDVideoStatus *status);
#endif
