/* MiniSAT-XL SoC firmware linker script.
 *
 * Firmware RAM: 0x00000000 – 0x0000FFFF (64 KB)
 * Stack:        top of firmware RAM (grows down)
 */

ENTRY(_start)

MEMORY {
    RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 64K
}

SECTIONS {
    . = 0x00000000;

    .text : {
        *(.init)
        *(.text*)
        *(.rodata*)
    } > RAM

    .data : {
        *(.data*)
    } > RAM

    .bss : {
        _bss_start = .;
        *(.bss*)
        *(COMMON)
        _bss_end = .;
    } > RAM

    . = ALIGN(4);
    _end = .;
}
