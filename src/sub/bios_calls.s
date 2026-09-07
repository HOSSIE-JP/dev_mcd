#include <sub/bios.def.h>
.section .text
/* Ordinary C ABI. All BIOS documented volatile registers accounted for. */
.global mcd_bios_call
mcd_bios_call:
  move.w 6(sp), d0
  movea.l 8(sp), a0
  jsr CDBIOS
  rts
.global mcd_find_file
mcd_find_file:
  move.l a2, -(sp)
  movea.l 8(sp), a0
  jsr find_file
  bcs 1f
  move.l a0, d0
  move.l d0, a0
  movea.l (sp)+, a2
  rts
1:moveq #0, d0
  movea.l d0, a0
  movea.l (sp)+, a2
  rts
