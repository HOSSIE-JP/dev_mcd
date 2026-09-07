/* Adapted from Megadev v1.2.0 new_project/src/ip.s (MIT). */
#include <main/memmap.def.h>
#include <main/gate_arr.macros.s>
#include <main/bios.def.h>
#include <system.macros.s>
#include <mcd/protocol.h>
.section .text
  DISABLE_INTERRUPTS
  jsr BIOS_LOAD_DEFAULT_VDP_REGS
  jsr BIOS_CLEAR_VRAM
  jsr BIOS_CLEAR_COMM
  move.b #0, BIOS_VBLANK_HANDLER_FLAGS
  move.l #BIOS_VBLANK_HANDLER, EXVEC_VBLANK
  ENABLE_INTERRUPTS
  move.w #1800, d7
1:cmpi.w #MCD_READY_MAGIC, GA_REG_COMSTAT7
  beq 2f
  jsr BIOS_VBLANK_WAIT_DEFAULT
  dbf d7, 1b
  bra boot_error
2:GRANT_2M
  move.w #MCD_ASSET_BOOT, GA_REG_COMCMD1
  move.w #MCD_CMD_READ, GA_REG_COMCMD0
  move.w #1800, d7
3:tst.w GA_REG_COMSTAT0
  bne 4f
  jsr BIOS_VBLANK_WAIT_DEFAULT
  dbf d7, 3b
  bra boot_error
4:tst.w GA_REG_COMSTAT1
  bne boot_error
  move.w #0, GA_REG_COMCMD0
  move.w #1800, d7
5:tst.w GA_REG_COMSTAT0
  beq 6f
  jsr BIOS_VBLANK_WAIT_DEFAULT
  dbf d7, 5b
  bra boot_error
6:WAIT_2M
  movea.l (0), sp
  jmp WORD_RAM + 0x100
boot_error:
  move.l #0xC0000000, 0xC00004
  move.w #0x000E, 0xC00000
  jsr BIOS_VDP_DISP_ENABLE
7:bra 7b
