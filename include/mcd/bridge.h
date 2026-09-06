#ifndef MCD_BRIDGE_H
#define MCD_BRIDGE_H
#include <types.h>
#include <mcd/protocol.h>

/* A small SGDK-style source API, not an SGDK ABI or complete replacement. */
typedef enum { BG_A = 0, BG_B = 1 } VDPPlane;
#define JOY_1 0
#define BUTTON_UP 0x01
#define BUTTON_DOWN 0x02
#define BUTTON_LEFT 0x04
#define BUTTON_RIGHT 0x08
#define BUTTON_B 0x10
#define BUTTON_C 0x20
#define BUTTON_A 0x40
#define BUTTON_START 0x80

void SYS_doVBlankProcess(void);
u16 JOY_readJoypad(u16 joy);
void PAL_setPalette(u16 palette, const u16 *colors);
void VDP_drawText(const char *text, u16 x, u16 y);
void VDP_clearTextLine(u16 y);
u16 VDP_drawImage(VDPPlane plane, const void *image, u32 bytes);
void MCD_init(void);
void MCD_update(void);
bool MCD_isBusy(void);
u16 MCD_getResult(void);
u32 MCD_getFileSize(void);
const void *MCD_getWordRAM(void);
u16 MCD_getAudioFlags(void);
u16 MCD_getSubTicks(void);
bool MCD_readFileAsync(u16 asset);
bool MCD_prepareADPCMAsync(void);
bool MCD_playADPCM(void);
bool MCD_stopADPCM(void);
bool MCD_playCDDA(u16 track, bool repeat);
bool MCD_stopCDDA(void);
bool MCD_pauseCDDA(void);
bool MCD_resumeCDDA(void);
#endif
