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

/* Bounded range adapter to the pinned Megadev CDC coroutine. Its source stays
 * unmodified. The caller has validated extent, rounded length and destination. */
.section .text
GLABEL mcd_read_range
  move.w sr,d0
  ori.w #0x700,sr
  move.l 4(sp),cdread_sector_start
  move.l 8(sp),cdread_sector_count
  move.l 12(sp),filebuff
  move.b #CDC_DEST_SUBREAD,cdc_dev_dest
  move.l #mcd_range_entry,acc_loop_jump
  move.w #6,access_op
  move.w d0,sr
  rts
mcd_range_entry:
  bsr load_data_sub
  clr.w access_op
  bra access_op_idle
