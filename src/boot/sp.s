/* Megadev CD access coroutine remains resident with our Sub kernel. */
#include <sub/sub.macro.s>
#include <sub/bios.def.h>
#include <sub/cdrom.macro.s>
#include <macros.s>
.section .text
GLABEL sp_init
  moveq #0, d0
  lea _BSS_ORIGIN, a0
  move.l #_BSS_LENGTH, d1
  lsr.l #2, d1
  bra 2f
1:move.l d0, (a0)+
2:dbf d1, 1b
  lea tracklist, a0
  BIOSCALL #BIOS_DRV_INIT
1:BIOSCALL #BIOS_CDB_STAT
  andi.b #0xF0, (CDSTAT).w
  bne 1b
  CLEAR_COMM_REGS
  andi.w #~(GA_MASK_RETURN_2M | GA_MASK_WORDRAM_LAYOUT), GA_REG_MEMMODE
  INIT_ACC_LOOP
  rts
tracklist: .byte 1, 0xFF
.align 2
GLABEL sp_int2
  addq.w #1, sub_ticks
  PROCESS_ACC_LOOP
GLABEL sp_main
  jmp sub_main
GLABEL sp_user
  rts
#include <sub/cdrom.s>
