#ifndef MCD_VIDEO_SOURCE_H
#define MCD_VIDEO_SOURCE_H
#include <types.h>

/* Sub-only sequential NOVEL.PAK source. The two 192 KiB banks at PRG RAM
 * 0x10000 and 0x40000 reserve all legacy IMA staging/cache storage until CLOSE.
 * The kernel owns command/Word RAM validation and services PCM between updates.
 * OPEN acknowledges reservation immediately after scheduling the first read.
 * READ/CLOSE return immediate validation errors or accept an asynchronous
 * operation. Poll pending/result/loaded while calling update from the Sub loop.
 * A timeout never abandons the pinned CDC coroutine or releases its buffers. */
#define MCD_VIDEO_SOURCE_BANK_BYTES 0x30000UL
u16 mcd_video_source_open(u32 file_sector, u32 file_bytes, u32 offset, u32 bytes);
u16 mcd_video_source_read(u32 offset, u32 bytes, u8 *destination);
u16 mcd_video_source_close(void);
void mcd_video_source_update(void);
bool mcd_video_source_active(void);
bool mcd_video_source_pending(void);
bool mcd_video_source_quarantined(void);
u16 mcd_video_source_result(void);
u32 mcd_video_source_loaded(void);
/* Save/restore the caller's 64 KiB actor workspace before using two Word RAM
 * windows. The split PRG backup is disjoint from the source banks and SP:
 * 0x70000..0x7dfff (56 KiB), 0xe000..0xffff (8 KiB). The kernel rejects active
 * video PCM and reserves legacy IMA memory until restoration completes. */
u16 mcd_video_workspace_save(u8 *word_actors);
u16 mcd_video_workspace_restore(u8 *word_actors);
bool mcd_video_workspace_saved(void);

#endif
