# Firmware build rules for MiniSAT-XL SoC
#
# Requires riscv64-unknown-elf-gcc (or riscv32-unknown-elf-gcc) on PATH.
# Tested with GCC 12+ targeting RV32I.
#
# Usage:
#   make              # build firmware.hex and firmware.bin
#   make clean        # remove build artefacts
#
# The firmware.hex file (plain hex, one 32-bit word per line) is loaded
# by the simulation testbench (test/test_soc.py).

CROSS ?= riscv64-unknown-elf

CC      = $(CROSS)-gcc
OBJCOPY = $(CROSS)-objcopy
OBJDUMP = $(CROSS)-objdump

ARCH    = -march=rv32i -mabi=ilp32
CFLAGS  = $(ARCH) -O1 -Wall -ffreestanding -nostdlib -nostartfiles
LDFLAGS = $(ARCH) -T link.ld -nostdlib -nostartfiles

SRCS = start.S main.c
OBJS = $(SRCS:.S=.o)
OBJS := $(OBJS:.c=.o)

all: firmware.hex firmware.bin

firmware.elf: $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $^

firmware.bin: firmware.elf
	$(OBJCOPY) -O binary $< $@

firmware.hex: firmware.bin
	python3 bin2hex.py $< $@

%.o: %.S
	$(CC) $(CFLAGS) -c -o $@ $<

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

disasm: firmware.elf
	$(OBJDUMP) -d $<

clean:
	rm -f *.o firmware.elf firmware.bin firmware.hex

.PHONY: all clean disasm
