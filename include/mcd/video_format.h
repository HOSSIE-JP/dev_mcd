#ifndef MCD_VIDEO_FORMAT_H
#define MCD_VIDEO_FORMAT_H
#ifdef __m68k__
/* Megadev owns stdint/size_t typedefs on the target. Including GCC headers
 * alongside types.h creates distinct int/long typedefs despite equal width. */
#include <types.h>
#else
#include <stdint.h>
#include <stddef.h>
#endif

/* Freestanding, normal M68000 GCC ABI. Caller owns a >=32768-byte scratch.
 * No allocation, libc, floating point, packed structs or unaligned word loads.
 * This is a portable streaming FORMAT library; CDC/PCM/VDP drivers are separate.
 */
#define MCDV_HEADER_BYTES 2048u
#define MCDV_MAX_RECORD 32768u
enum { MCDV_OK=0, MCDV_ARGUMENT=1, MCDV_FORMAT=2, MCDV_BOUNDS=3,
       MCDV_CRC=4, MCDV_SEQUENCE=5, MCDV_TRUNCATED=6 };
typedef struct {
    uint16_t width,height,fps_num,fps_den,max_tiles;
    uint32_t frame_count,rate,total_samples,max_record;
} MCDV_Header;
typedef struct {
    uint32_t bytes,sequence,pts,audio_samples;
    uint16_t tile_count,map_count;
    const uint8_t *palette,*tiles,*map,*audio;
} MCDV_Frame;
typedef struct {
    uint8_t *scratch;
    uint32_t capacity,used,want,index,bytes_read,padding_left;
    unsigned ready,header_ready,eof,error,verify_payload_crc;
    MCDV_Header header;
    MCDV_Frame frame;
} MCDV_Demux;
uint16_t MCDV_be16(const uint8_t *p);
uint32_t MCDV_be32(const uint8_t *p);
uint32_t MCDV_crc32(const uint8_t *p,uint32_t n);
unsigned MCDV_parseHeader(const uint8_t *p,uint32_t bytes,MCDV_Header *out);
unsigned MCDV_parseFrame(const MCDV_Header *header,const uint8_t *p,uint32_t bytes,
                         uint32_t sequence,unsigned crc,MCDV_Frame *out);
unsigned MCDV_init(MCDV_Demux *d,uint8_t *scratch,uint32_t capacity,unsigned crc);
/* Backpressure: stops consuming as soon as ready=1. Return consumed bytes.
 * Input may cross any sector/cache boundary. Preserve unconsumed input.
 * frame pointers remain valid until MCDV_release; finish every DMA first.
 */
size_t MCDV_feed(MCDV_Demux *d,const uint8_t *p,size_t bytes);
unsigned MCDV_release(MCDV_Demux *d);
unsigned MCDV_finish(const MCDV_Demux *d);
#endif
