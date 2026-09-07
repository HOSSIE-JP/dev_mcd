#include <mcd/bridge.h>

/* Original two-tile checkerboard; no ResComp assets or SGDK runtime required. */
static const u16 tiles[] = {
  0x1111,0x2222,0x1111,0x2222,0x1111,0x2222,0x1111,0x2222,
  0x2222,0x1111,0x2222,0x1111,0x2222,0x1111,0x2222,0x1111,
  0x3333,0x3333,0x3111,0x1113,0x3122,0x2213,0x3122,0x2213,
  0x3122,0x2213,0x3122,0x2213,0x3111,0x1113,0x3333,0x3333
};
static const u16 colors[16] = {0,0x420,0x840,0xEEE};
static const u16 black[16] = {0};
typedef struct { u32 magic,frame; u16 error,io,fade,pressed; } Telemetry;
#define T ((volatile Telemetry *)0xFFF000)

void main(void) {
  u16 row[64]; s16 scroll_x=0,scroll_y=0;
  bool reading=false,bright_text=true;
  MCD_init(); T->magic=0x4D434442; T->io=0; T->error=0;
  MCD_clearPlane(BG_A); MCD_clearPlane(BG_B);
  T->error=MCD_loadTiles(tiles,1,2);
  PAL_setPalette(PAL1,colors);
  for (u16 y=0;y<32;++y) {
    for (u16 x=0;x<64;++x) row[x]=TILE_ATTR_FULL(PAL1,false,false,false,1+((x+y)&1));
    MCD_setTileMapRect(BG_B,row,64,0,y,64,1,64);
  }
  VDP_setTextPriority(true);
  VDP_drawText("MCD BRIDGE - TILE / PALETTE / INPUT",2,2);
  VDP_drawText("D-PAD: SCROLL BACKGROUND",2,5);
  VDP_drawText("A: FADE OUT  B: FADE IN",2,7);
  VDP_drawText("C: TEXT COLOR  START: CD READ",2,9);
  VDP_drawText("FADE AND INPUT KEEP CD I/O RUNNING",2,12);
  for (;;) {
    u16 held,pressed;
    SYS_doVBlankProcess();
    T->frame=MCD_getFrameCount(); T->fade=PAL_isDoingFade();
    held=JOY_readJoypad(JOY_1); pressed=MCD_readJoypadPressed(JOY_1); T->pressed=pressed;
    /* Scroll registers wrap at 10 bits. Bound the C state to avoid overflow. */
    scroll_x=(scroll_x+((held&BUTTON_RIGHT)?2:0)-((held&BUTTON_LEFT)?2:0))&1023;
    scroll_y=(scroll_y+((held&BUTTON_DOWN)?2:0)-((held&BUTTON_UP)?2:0))&1023;
    VDP_setHorizontalScroll(BG_B,scroll_x); VDP_setVerticalScroll(BG_B,scroll_y);
    if (pressed&BUTTON_A) MCD_fadePaletteTo(16,black,16,45);
    if (pressed&BUTTON_B) MCD_fadePaletteTo(16,colors,16,45);
    if (pressed&BUTTON_C) {
      bright_text=!bright_text; PAL_setColor(49,bright_text?0xEEE:0x0EE);
    }
    if ((pressed&BUTTON_START) && !MCD_isBusy()) {
      reading=MCD_readFileAsync(MCD_ASSET_IMAGE);
      VDP_clearTextLine(17);
      VDP_drawText(reading?"CD READING - SCROLL AND FADE WORK":"CD REQUEST REJECTED",2,17);
    }
    if (reading && !MCD_isBusy()) {
      reading=false; T->error=MCD_getResult(); ++T->io;
      VDP_clearTextLine(17);
      VDP_drawText(T->error?"CD READ FAILED":"CD IMAGE READY IN WORD RAM",2,17);
    }
    if (!(T->frame&15)) VDP_drawText((T->frame&16)?">":" ",37,2);
  }
}
