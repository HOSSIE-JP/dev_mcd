#include <mcd/video_format.h>
uint16_t MCDV_be16(const uint8_t *p) {return (uint16_t)(((uint16_t)p[0]<<8)|p[1]);}
uint32_t MCDV_be32(const uint8_t *p) {return ((uint32_t)MCDV_be16(p)<<16)|MCDV_be16(p+2);}
uint32_t MCDV_crc32(const uint8_t *p,uint32_t n) {
    uint32_t c=0xFFFFFFFFu;
    while(n--) {
        c^=*p++;
        for(unsigned i=0;i<8;i++)c=(c>>1)^(0xEDB88320u & (0u-(c&1u)));
    }
    return ~c;
}
static uint32_t timestamp(const MCDV_Header *h,uint32_t index) {
    uint32_t period=h->rate*h->fps_den;
    return (index/h->fps_num)*period+((index%h->fps_num)*period)/h->fps_num;
}
unsigned MCDV_parseHeader(const uint8_t *p,uint32_t n,MCDV_Header *out) {
    MCDV_Header h;
    uint32_t period,frames;
    if(!p || !out)return MCDV_ARGUMENT;
    if(n!=2048)return MCDV_BOUNDS;
    if(MCDV_be32(p)!=0x4D545631u || MCDV_be16(p+4)!=1 || MCDV_be16(p+6)!=2048)
        return MCDV_FORMAT;
    if(MCDV_crc32(p,60)!=MCDV_be32(p+60))return MCDV_CRC;
    for(unsigned i=36;i<60;i++)if(p[i])return MCDV_FORMAT;
    for(unsigned i=64;i<2048;i++)if(p[i])return MCDV_FORMAT;
    h.width=MCDV_be16(p+8);h.height=MCDV_be16(p+10);
    h.fps_num=MCDV_be16(p+12);h.fps_den=MCDV_be16(p+14);
    h.frame_count=MCDV_be32(p+16);h.rate=MCDV_be32(p+20);
    h.total_samples=MCDV_be32(p+24);h.max_record=MCDV_be32(p+28);
    h.max_tiles=MCDV_be16(p+32);
    if(!h.width || h.width>320 || h.width%8 || !h.height || h.height>224 || h.height%8 ||
       !h.fps_num || h.fps_num>30 || !h.fps_den || h.fps_den>2 ||
       h.rate!=16000 || !h.total_samples || h.total_samples>115200000u ||
       !h.frame_count || h.max_record<64 || h.max_record>32768 || (h.max_record&1) ||
       !h.max_tiles || h.max_tiles>512 || MCDV_be16(p+34)!=1)return MCDV_BOUNDS;
    period=h.rate*h.fps_den;
    frames=(h.total_samples/period)*h.fps_num+
           ((h.total_samples%period)*h.fps_num+period-1)/period;
    if(h.frame_count!=frames)return MCDV_SEQUENCE;
    *out=h;return MCDV_OK;
}
unsigned MCDV_parseFrame(const MCDV_Header *h,const uint8_t *p,uint32_t n,
                         uint32_t sequence,unsigned crc,MCDV_Frame *out) {
    MCDV_Frame f;
    uint32_t expected,end;
    if(!h || !p || !out)return MCDV_ARGUMENT;
    if(n<64 || n>h->max_record || (n&1))return MCDV_BOUNDS;
    if(MCDV_be32(p)!=0x46524D31u || MCDV_be32(p+4)!=n || MCDV_be32(p+28))return MCDV_FORMAT;
    f.bytes=n;f.sequence=MCDV_be32(p+8);f.pts=MCDV_be32(p+12);
    f.tile_count=MCDV_be16(p+16);f.map_count=MCDV_be16(p+18);f.audio_samples=MCDV_be32(p+20);
    if(sequence>=h->frame_count || f.sequence!=sequence || f.pts!=timestamp(h,sequence))
        return MCDV_SEQUENCE;
    end=timestamp(h,sequence+1);if(end>h->total_samples)end=h->total_samples;
    if(f.audio_samples!=end-f.pts || !f.tile_count || f.tile_count>h->max_tiles ||
       f.map_count!=(h->width/8)*(h->height/8))return MCDV_BOUNDS;
    expected=64u+32u*f.tile_count+2u*f.map_count+f.audio_samples;
    if(n!=((expected+1)&~1u))return MCDV_BOUNDS;
    if(crc && MCDV_crc32(p+32,n-32)!=MCDV_be32(p+24))return MCDV_CRC;
    f.palette=p+32;f.tiles=p+64;f.map=f.tiles+32u*f.tile_count;
    f.audio=f.map+2u*f.map_count;
    if(MCDV_be16(f.palette))return MCDV_FORMAT;
    for(unsigned i=0;i<16;i++)if(MCDV_be16(f.palette+i*2)&~0x0EEEu)return MCDV_FORMAT;
    for(unsigned i=0;i<f.map_count;i++)if(MCDV_be16(f.map+i*2)>=f.tile_count)return MCDV_BOUNDS;
    for(uint32_t i=0;i<f.audio_samples;i++)if(f.audio[i]==255)return MCDV_FORMAT;
    if((expected&1) && p[n-1])return MCDV_FORMAT;
    *out=f;return MCDV_OK;
}
unsigned MCDV_init(MCDV_Demux *d,uint8_t *scratch,uint32_t capacity,unsigned crc) {
    if(!d || !scratch || capacity<32768)return MCDV_ARGUMENT;
    d->scratch=scratch;d->capacity=capacity;d->used=0;d->want=2048;d->index=0;
    d->bytes_read=0;d->padding_left=0;d->ready=0;d->header_ready=0;d->eof=0;
    d->error=0;d->verify_payload_crc=crc;return MCDV_OK;
}
size_t MCDV_feed(MCDV_Demux *d,const uint8_t *p,size_t n) {
    size_t consumed=0;
    if(!d || !p || d->error || d->ready)return 0;
    while(consumed<n && !d->ready && !d->error) {
        if(d->eof) {
            if(!d->padding_left || p[consumed]){d->error=MCDV_FORMAT;break;}
            --d->padding_left;++consumed;++d->bytes_read;continue;
        }
        uint32_t take=d->want-d->used;
        if((size_t)take>n-consumed)take=(uint32_t)(n-consumed);
        for(uint32_t i=0;i<take;i++)d->scratch[d->used+i]=p[consumed+i];
        d->used+=take;d->bytes_read+=take;consumed+=take;
        if(d->used<d->want)break;
        if(!d->header_ready) {
            d->error=MCDV_parseHeader(d->scratch,d->used,&d->header);
            if(d->error)break;
            d->header_ready=1;d->used=0;d->want=32;
        } else if(d->want==32) {
            uint32_t length=MCDV_be32(d->scratch+4);
            if(MCDV_be32(d->scratch)!=0x46524D31u || length<64 ||
               length>d->header.max_record || length>d->capacity || (length&1)) {
                d->error=MCDV_BOUNDS;break;
            }
            d->want=length;
        } else {
            d->error=MCDV_parseFrame(&d->header,d->scratch,d->used,d->index,
                                     d->verify_payload_crc,&d->frame);
            if(!d->error)d->ready=1;
        }
    }
    return consumed;
}
unsigned MCDV_release(MCDV_Demux *d) {
    if(!d || !d->ready || d->error)return MCDV_ARGUMENT;
    d->ready=0;d->used=0;d->want=32;++d->index;
    if(d->index==d->header.frame_count) {
        d->eof=1;d->padding_left=(2048u-(d->bytes_read&2047u))&2047u;
    }
    return MCDV_OK;
}
unsigned MCDV_finish(const MCDV_Demux *d) {
    if(!d)return MCDV_ARGUMENT;
    if(d->error)return d->error;
    return d->eof && !d->ready && !d->padding_left ? MCDV_OK : MCDV_TRUNCATED;
}
