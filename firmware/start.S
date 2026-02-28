/* Minimal RISC-V startup for MiniSAT-XL SoC firmware.
 *
 * Sets up stack pointer and calls main().
 * Firmware is linked to run from 0x00000000 (firmware RAM).
 */

    .section .init, "ax", @progbits
    .global _start
    .type   _start, @function

_start:
    /* Set stack pointer to top of firmware RAM (64 KB) */
    li   sp, 0x00010000

    /* Clear BSS */
    la   t0, _bss_start
    la   t1, _bss_end
.bss_loop:
    bge  t0, t1, .bss_done
    sw   zero, 0(t0)
    addi t0, t0, 4
    j    .bss_loop
.bss_done:

    /* Call main */
    call main

    /* Spin forever after main returns */
.halt:
    j .halt

    .size _start, . - _start
