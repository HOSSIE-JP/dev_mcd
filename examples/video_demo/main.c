#include <mcd/video.h>
#define VR (*(volatile u16 *)0xC00004)
typedef struct {
  u32 magic;
  u16 stage,error;
  u32 framesShown,framesDropped,cacheReads,rebufferCount,audioSamplesPlayed;
  u16 skipped;
} VideoTrace;
static volatile VideoTrace *const trace=(volatile VideoTrace *)0xFFF080UL;
/* tools/video_convert.py --demo writes MTV1 at offset zero of NOVEL.PAK.
 * A procedural fixture keeps the sample reproducible without copyrighted
 * source media. Use --source to test the original video's chosen profile. */
void main(void) {
  MCD_init();trace->magic=0x4D565431UL;trace->stage=0;trace->error=0;
  for(;;) {
    trace->stage=1;
    VDP_drawText("MEGA-CD MTV1 VIDEO",10,9);
    VDP_drawText("B/C/START: PLAY WITH AUDIO",5,12);
    VDP_drawText("A: SILENT DIAGNOSTIC",8,14);
    u16 buttons=0;
    while(!buttons) {SYS_doVBlankProcess();buttons=JOY_readJoypad(JOY_1);}
    bool audio=(buttons&BUTTON_A)==0;
    while(JOY_readJoypad(JOY_1))SYS_doVBlankProcess();
    /* Read the file header first to obtain file size from build-generated
     * metadata. The asset generator defines VIDEO_DEMO_BYTES. */
    MCDVideoStatus status;trace->stage=2;trace->error=0;
    u16 result=MCD_playVideoEx(0,VIDEO_DEMO_BYTES,true,audio,&status);
    trace->error=result;trace->framesShown=status.framesShown;trace->framesDropped=status.framesDropped;
    trace->cacheReads=status.cacheReads;trace->rebufferCount=status.rebufferCount;
    trace->audioSamplesPlayed=status.audioSamplesPlayed;trace->skipped=status.skipped;
    trace->stage=result?4:3;
    if(result==MCD_ERR_TIMEOUT)for(;;)SYS_doVBlankProcess();
    VR=0x8407;VR=0x8164;
    for(u16 y=0;y<28;++y)VDP_clearTextLine(y);
    VDP_drawText(result?"VIDEO ERROR - PRESS TO RETRY":status.skipped?"SKIPPED - PRESS TO RETURN":"END - PRESS TO RETURN",6,18);
    while(JOY_readJoypad(JOY_1))SYS_doVBlankProcess();
    while(!JOY_readJoypad(JOY_1))SYS_doVBlankProcess();
    while(JOY_readJoypad(JOY_1))SYS_doVBlankProcess();
  }
}
