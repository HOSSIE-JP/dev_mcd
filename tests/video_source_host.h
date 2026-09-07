#ifndef MCD_VIDEO_SOURCE_HOST_H
#define MCD_VIDEO_SOURCE_HOST_H
#include <types.h>

/* Megadev lib/sub/cdrom.def.h: completed CDC read. */
#define CDROM_RESULT_OK 0x64

extern volatile u16 access_op, access_op_result, sub_ticks;
u8 *mcd_video_source_test_buffer(u16 bank);
u8 *mcd_video_source_test_backup(u16 segment);
void mcd_read_range(u32 sector, u32 count, u8 *destination);

#endif
