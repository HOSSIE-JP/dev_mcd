#include <mcd/video_upload.h>
unsigned MCDV_uploadBegin(MCDV_UploadPlan *p,const MCDV_Header *h,
                          const MCDV_Frame *f,unsigned bank) {
    if(!p || !h || !f || bank>1 || !h->width || h->width>320 || h->width%8 ||
       !h->height || h->height>224 || h->height%8 || !f->tile_count || f->tile_count>512 ||
       f->map_count!=(h->width/8)*(h->height/8))return MCDV_ARGUMENT;
    p->header=h;p->frame=f;p->bank=(uint16_t)bank;p->tile_bytes_done=0;p->row=0;p->palette_done=0;
    return MCDV_OK;
}
unsigned MCDV_uploadNext(MCDV_UploadPlan *p,uint16_t budget,MCDV_Upload *out) {
    uint32_t remaining=32u*p->frame->tile_count-p->tile_bytes_done;
    const MCDV_Header *h=p->header;
    if(!out)return 0;
    if(remaining) {
        uint16_t take=(uint16_t)(remaining<budget?remaining:budget);
        take&=(uint16_t)~31u;if(!take)return 0;
        out->kind=MCDV_UPLOAD_VRAM;out->destination=(uint16_t)(0x20u+p->bank*0x4000u+p->tile_bytes_done);
        out->source=p->frame->tiles+p->tile_bytes_done;out->bytes=take;
        p->tile_bytes_done+=take;return 1;
    }
    if(p->row<h->height/8) {
        unsigned columns=h->width/8;
        if(budget<columns*2)return 0;
        unsigned x=(40-columns)/2,y=(28-h->height/8)/2+p->row;
        for(unsigned i=0;i<columns;i++) {
            uint16_t id=MCDV_be16(p->frame->map+2u*(p->row*columns+i));
            id=(uint16_t)((id+1u+p->bank*512u)|(p->bank<<13));
            p->map_row[i*2]=(uint8_t)(id>>8);p->map_row[i*2+1]=(uint8_t)id;
        }
        out->kind=MCDV_UPLOAD_VRAM;out->destination=(uint16_t)((p->bank?0xE000:0xA000)+y*128+x*2);
        out->bytes=(uint16_t)(columns*2);out->source=p->map_row;++p->row;return 1;
    }
    if(!p->palette_done && budget>=32) {
        out->kind=MCDV_UPLOAD_CRAM;out->destination=(uint16_t)(p->bank*32);
        out->bytes=32;out->source=p->frame->palette;p->palette_done=1;return 1;
    }
    return 0;
}
unsigned MCDV_uploadComplete(const MCDV_UploadPlan *p) {return p && p->palette_done;}
uint16_t MCDV_planeBRegister(const MCDV_UploadPlan *p) {return (uint16_t)(p->bank?0x8407:0x8405);}
