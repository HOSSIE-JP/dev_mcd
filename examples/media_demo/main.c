#include <mcd/bridge.h>
/* Fixed, BIOS-free progress telemetry used by the libretro smoke test. */
typedef struct {
  u32 magic, frame;
  u16 stage, error, image_ok, prepared, flags, sub_ticks, event, completed;
} Telemetry;
#define T ((volatile Telemetry *)0xFFF000)
static u16 old_keys;
static void hud(const char *s) { VDP_clearTextLine(23); VDP_drawText(s, 2, 23); }
static bool wait_request(void)
{
  while (MCD_isBusy()) { SYS_doVBlankProcess(); ++T->frame; }
  T->error = MCD_getResult();
  return T->error == MCD_OK;
}
void main(void)
{
  MCD_init();
  T->magic = 0x4D434442; T->frame = 0; T->stage = 1;
  T->error = T->image_ok = T->prepared = T->event = T->completed = 0;
  VDP_drawText("MCD BRIDGE - NATIVE CD", 2, 1);
  hud("LOADING IMAGE FROM CD...");
  if (!MCD_readFileAsync(MCD_ASSET_IMAGE) || !wait_request()) goto error;
  T->error = VDP_drawImage(BG_B, MCD_getWordRAM(), MCD_getFileSize());
  if (T->error) goto error;
  T->image_ok = 1; T->stage = 2;
  VDP_drawText("MCD BRIDGE - NATIVE CD", 2, 1);
  VDP_drawText("320 X 224   16 COLORS", 2, 3);
  hud("LOADING AND DECODING IMA ADPCM...");
  if (!MCD_prepareADPCMAsync() || !wait_request()) goto error;
  T->prepared = 1; T->stage = 3;
  VDP_drawText("A: ADPCM   B: CD-DA   C: STOP", 2, 19);
  VDP_drawText("UP: PAUSE  DOWN: RESUME", 2, 20);
  VDP_drawText("START: RELOAD IMAGE", 2, 21);
  hud("READY - AUDIO TRACK 02");
  for (;;) {
    u16 keys, hit;
    SYS_doVBlankProcess(); ++T->frame;
    T->flags = MCD_getAudioFlags(); T->sub_ticks = MCD_getSubTicks();
    keys = JOY_readJoypad(JOY_1); hit = keys & ~old_keys; old_keys = keys;
    if (MCD_isBusy()) continue;
    if (T->event != T->completed) { T->completed = T->event; T->error = MCD_getResult(); }
    if (hit & BUTTON_A) {
      if (MCD_playADPCM()) { T->event++; hud("IMA ADPCM -> RF5C164 PCM"); }
    } else if (hit & BUTTON_B) {
      if (MCD_playCDDA(2, true)) { T->event++; hud("CD-DA TRACK 02 - REPEAT"); }
    } else if (hit & BUTTON_C) {
      if (MCD_stopADPCM()) wait_request();
      if (MCD_stopCDDA()) { T->event++; hud("AUDIO STOPPED"); }
    } else if (hit & BUTTON_UP) {
      if (MCD_pauseCDDA()) { T->event++; hud("CD-DA PAUSED"); }
    } else if (hit & BUTTON_DOWN) {
      if (MCD_resumeCDDA()) { T->event++; hud("CD-DA RESUMED"); }
    } else if (hit & BUTTON_START) {
      if (MCD_readFileAsync(MCD_ASSET_IMAGE) && wait_request()) {
        T->error = VDP_drawImage(BG_B, MCD_getWordRAM(), MCD_getFileSize());
        hud("IMAGE RELOADED - CD-DA STOPPED");
        T->event++; T->completed = T->event;
      }
    }
    /* Small changing marker: rendering and input remain alive during requests. */
    if (!(T->frame & 15)) VDP_drawText((T->frame & 16) ? ">" : " ", 37, 1);
  }
error:
  T->stage = 0xFFFF;
  hud("ERROR - CHECK DISC / RESET");
  for (;;) { SYS_doVBlankProcess(); ++T->frame; }
}
