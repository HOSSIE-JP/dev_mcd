#ifndef MCD_VIDEO_STREAM_H
#define MCD_VIDEO_STREAM_H
#include <types.h>
/* Sub-only, exclusive 16 kHz PCM8 video ring. Caller stops resident IMA first. */
u16 mcd_video_pcm_begin(u32 total_samples);
u16 mcd_video_pcm_feed(const u8 *data, u16 samples);
/* Word RAM table: 1..64 BE {u32 source offset, u16 samples, u16 zero}.
 * Reject invalid tables, payloads and capacity before mutating the ring.
 * MCD_OK commits the entire batch; check PCM status for a playback underrun
 * detected after the copy. Caller retains Sub ownership until this returns. */
u16 mcd_video_pcm_feed_batch(const u8 *word_base, u32 descriptor_offset, u16 count);
u16 mcd_video_pcm_play(void);
void mcd_video_pcm_stop(void);
void mcd_video_pcm_update(void);
bool mcd_video_pcm_active(void);
u16 mcd_video_pcm_flags(void);
u16 mcd_video_pcm_result(void);
u32 mcd_video_pcm_clock(void);
#endif
