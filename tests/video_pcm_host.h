#ifndef MCD_VIDEO_PCM_HOST_H
#define MCD_VIDEO_PCM_HOST_H
#include <types.h>
void mcd_test_pcm_disable(void);
void mcd_test_pcm_play(void);
u16 mcd_test_pcm_position(void);
void mcd_test_pcm_write(u16 start,const u8 *source,u16 count);
#endif
