#ifndef MCD_STREAM_H
#define MCD_STREAM_H
#include <types.h>
u8 *mcd_stream_buffer(u16 channel);
u32 mcd_stream_capacity(u16 channel);
void mcd_stream_stop(u16 channel);
/* Invalidate resident sources before another service takes over PCM Wave RAM. */
void mcd_stream_reset(void);
u16 mcd_stream_prepare(u16 channel, u32 bytes, bool loop);
bool mcd_stream_ready(u16 channel);
u16 mcd_stream_play(u16 channel);
void mcd_stream_update(void);
u16 mcd_stream_flags(void);
#endif
