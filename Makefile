MEGADEV ?= .deps/megadev
CROSS ?= m68k-linux-gnu-
CC68 = $(CROSS)gcc
LD68 = $(CROSS)ld
LDFLAGS = -nostdlib -z noexecstack
OBJCOPY = $(CROSS)objcopy
NM68 = $(CROSS)nm
PYTHON ?= python3
REGION ?= JP
ifneq ($(REGION),JP)
$(error This sample currently supports REGION=JP / NTSC only)
endif
DEFS = -imacros build.def.h -DTARGET=MEGACD -DREGION=$(REGION) -DVIDEO=NTSC \
 -DVRAM_SIZE=VRAM_64K -DPROJECT_ID=mcd_demo -DPROJECT_NAME='MCD BRIDGE MEDIA DEMO' \
 -DPROJECT_NAME_DOMESTIC='MCD BRIDGE MEDIA DEMO' -DHEADER_HARDWARE_ID='SEGA MEGA DRIVE' \
 -DHEADER_COPYRIGHT='(C)2026 HOSSIE-JP' -DHEADER_SOFTWARE_ID='GM MCDK-0001' \
 -DHEADER_REGION='J' -DHEADER_DISC_ID='SEGADISCSYSTEM' \
 -DHEADER_SYS_ID='MCDK' -DHEADER_VOL_ID='MCDK'
INCS = -Iinclude -I$(MEGADEV)/lib -Ibuild
CFLAGS = -std=gnu11 -O2 -m68000 -ffreestanding -fno-builtin -fno-pic -fno-pie \
 -fno-common -fomit-frame-pointer -fno-asynchronous-unwind-tables -fno-unwind-tables \
 -Wall -Wextra -Wno-main -MMD -MP -Wa,--register-prefix-optional $(INCS) $(DEFS)
ASFLAGS = $(CFLAGS) -Wa,--bitwise-or -Wa,-Ibuild -x assembler-with-cpp
MAIN_OBJS = build/main_init.o build/main_layout.o build/main_bridge.o build/main_bios.o build/demo.o
SUB_OBJS = build/sp_header.o build/sp.o build/sub_kernel.o build/sub_ima.o build/sub_bios.o
.DEFAULT_GOAL := all
-include $(wildcard build/*.d)
$(MAIN_OBJS) $(SUB_OBJS) build/security.o build/ip.o: Makefile
.PHONY: all clean assets doctor host-test smoke
.DELETE_ON_ERROR:
all: build/disc/IPX.MMD build/boot.bin build/assets.stamp
	$(PYTHON) tools/disc.py
build:
	mkdir -p build/disc dist
build/assets.stamp: tools/assets.py | build
	$(PYTHON) tools/assets.py
	touch $@
build/font.h: build/assets.stamp
build/main_init.o: $(MEGADEV)/lib/main/ipx_init.s | build
	$(CC68) $(ASFLAGS) -c $< -o $@
build/main_layout.o: src/main/layout.s | build
	$(CC68) $(ASFLAGS) -c $< -o $@
build/main_bridge.o: src/main/bridge.c build/font.h include/mcd/bridge.h include/mcd/protocol.h
	$(CC68) $(CFLAGS) -c $< -o $@
build/main_bios.o: src/main/bios_calls.s | build
	$(CC68) $(ASFLAGS) -c $< -o $@
build/demo.o: examples/media_demo/main.c include/mcd/bridge.h include/mcd/protocol.h | build
	$(CC68) $(CFLAGS) -c $< -o $@
build/disc/IPX.MMD: $(MAIN_OBJS)
	$(LD68) $(LDFLAGS) -T $(MEGADEV)/cfg/module_mmd.ld -Map build/main.map $^ -o build/main.elf
	$(NM68) -n build/main.elf > build/main.sym
	$(OBJCOPY) -O binary build/main.elf $@
build/sp_header.o: $(MEGADEV)/lib/sub/sp_header.s | build
	$(CC68) $(ASFLAGS) -c $< -o $@
build/sp.o: src/boot/sp.s | build
	$(CC68) $(ASFLAGS) -c $< -o $@
build/sub_kernel.o: src/sub/kernel.c include/mcd/protocol.h include/mcd/ima.h | build
	$(CC68) $(CFLAGS) -c $< -o $@
build/sub_ima.o: src/sub/ima.c include/mcd/ima.h | build
	$(CC68) $(CFLAGS) -c $< -o $@
build/sub_bios.o: src/sub/bios_calls.s | build
	$(CC68) $(ASFLAGS) -c $< -o $@
build/sp.bin: $(SUB_OBJS)
	$(LD68) $(LDFLAGS) -T $(MEGADEV)/cfg/sp.ld -Map build/sub.map $^ -o build/sub.elf
	$(NM68) -n build/sub.elf > build/sub.sym
	$(OBJCOPY) -O binary build/sub.elf $@
build/security.o: $(MEGADEV)/lib/security.c | build
	$(CC68) $(CFLAGS) -c $< -o $@
build/ip.o: src/boot/ip.s include/mcd/protocol.h | build
	$(CC68) $(ASFLAGS) -c $< -o $@
build/ip.bin: build/security.o build/ip.o
	$(LD68) $(LDFLAGS) -T $(MEGADEV)/cfg/ip.ld $^ -o build/ip.elf
	$(OBJCOPY) -O binary build/ip.elf $@
build/boot.bin: build/ip.bin build/sp.bin
	$(CC68) $(ASFLAGS) -c $(MEGADEV)/lib/cd_boot.s -o build/boot.o
	$(OBJCOPY) -O binary build/boot.o $@
assets: build/assets.stamp
doctor:
	$(PYTHON) tools/doctor.py --cross $(CROSS)
host-test:
	$(PYTHON) -m unittest discover -s tests -v
smoke: all
	$(PYTHON) tools/smoke.py --bios "$(BIOS)"
clean:
	rm -rf build dist
