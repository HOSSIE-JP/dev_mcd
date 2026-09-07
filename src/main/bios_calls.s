#include <main/bios.def.h>
.section .text
.global mcd_wait_frame
mcd_wait_frame:
  movem.l d2-d7/a2-a6, -(sp)
  jsr BIOS_VBLANK_WAIT_DEFAULT
  movem.l (sp)+, d2-d7/a2-a6
  rts
