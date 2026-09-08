#ifndef MCD_VIDEO_UPLOAD_H
#define MCD_VIDEO_UPLOAD_H
#include <mcd/video_format.h>
/* Plan bounded uploads into an INACTIVE video bank. This module does not
 * touch hardware. The adapter must execute each transfer synchronously before
 * asking for another one (map row data is a reused 80-byte scratch).
 * Plane B banks: A000/E000, 64x32. Tile banks: 0020/4020, 512 tiles each.
 * On entry clear tile zero and both maps. Leave Plane A at C000.
 */
enum { MCDV_UPLOAD_VRAM=1, MCDV_UPLOAD_CRAM=2 };
typedef struct {
    unsigned kind;
    uint16_t destination,bytes;
    const uint8_t *source;
} MCDV_Upload;
typedef struct {
    const MCDV_Header *header;
    const MCDV_Frame *frame;
    uint32_t tile_bytes_done;
    uint16_t row,bank;
    unsigned palette_done;
    uint8_t map_row[80];
} MCDV_UploadPlan;
unsigned MCDV_uploadBegin(MCDV_UploadPlan *plan,const MCDV_Header *header,
                          const MCDV_Frame *frame,unsigned bank);
/* Returns 1 for a transfer, 0 when complete OR budget is insufficient.
 * Subtract transfer.bytes from the VBlank byte budget after success.
 * The adapter must additionally bound register setup time and DMA source
 * boundaries. Do not interpret a byte budget as measured hardware timing.
 */
unsigned MCDV_uploadNext(MCDV_UploadPlan *plan,uint16_t budget,MCDV_Upload *out);
unsigned MCDV_uploadComplete(const MCDV_UploadPlan *plan);
/* After all DMA completes and audio clock reaches PTS, switch Plane B base to
 * this register word DURING VBlank. Do not blank the active display per frame.
 */
uint16_t MCDV_planeBRegister(const MCDV_UploadPlan *plan);
/* Native playback is H40, NTSC, 224 active lines. Permit an already prepared
 * bank to be published in the current blank only when the sampled V counter
 * leaves at least 16 scanlines before active display. The repeated E5..EA
 * range in the NTSC counter is also safely inside this window. This is not a
 * transfer budget: all tile/map/CRAM writes and the PTS wait must be complete.
 * Other display modes must use their own timing rather than this predicate. */
unsigned MCDV_canPublishNtsc224(uint16_t status,uint16_t vertical_counter);
#endif
