// PicoRV32 - A Size-Optimized RISC-V CPU
//
// This is a minimal stub of the PicoRV32 CPU for interface documentation.
// Replace with the full picorv32.v from https://github.com/YosysHQ/picorv32
// for actual synthesis.
//
// Vendored here for MiniSAT-XL SoC integration under rtl/picorv32.v
//
// SPDX-License-Identifier: ISC
// Copyright (C) 2015-2020  Claire Xenia Wolf <claire@clairexenia.de>

`default_nettype none
`timescale 1 ns / 1 ps

module picorv32 #(
    parameter ENABLE_COUNTERS      = 1,
    parameter ENABLE_COUNTERS64    = 1,
    parameter ENABLE_REGS_16_31    = 1,
    parameter ENABLE_REGS_DUALPORT = 1,
    parameter LATCHED_MEM_RDATA    = 0,
    parameter TWO_STAGE_SHIFT      = 1,
    parameter TWO_CYCLE_COMPARE    = 0,
    parameter TWO_CYCLE_ALU        = 0,
    parameter COMPRESSED_ISA       = 0,
    parameter CATCH_MISALIGN       = 1,
    parameter CATCH_ILLINSN        = 1,
    parameter ENABLE_PCPI          = 0,
    parameter ENABLE_MUL           = 0,
    parameter ENABLE_FAST_MUL      = 0,
    parameter ENABLE_DIV           = 0,
    parameter ENABLE_IRQ           = 0,
    parameter ENABLE_IRQ_QREGS     = 1,
    parameter ENABLE_IRQ_TIMER     = 1,
    parameter ENABLE_TRACE         = 0,
    parameter REGS_INIT_ZERO       = 0,
    parameter MASKED_IRQ           = 32'h 0000_0000,
    parameter LATCHED_IRQ          = 32'h ffff_ffff,
    parameter PROGADDR_RESET       = 32'h 0000_0000,
    parameter PROGADDR_IRQ         = 32'h 0000_0010,
    parameter STACKADDR            = 32'h ffff_ffff
) (
    input  wire        clk,
    input  wire        resetn,

    // Memory interface
    output reg         mem_valid,
    output reg         mem_instr,
    input  wire        mem_ready,
    output reg  [31:0] mem_addr,
    output reg  [31:0] mem_wdata,
    output reg  [ 3:0] mem_wstrb,
    input  wire [31:0] mem_rdata,

    // Pipelined look-ahead interface (unused in this stub)
    output wire        mem_la_read,
    output wire        mem_la_write,
    output wire [31:0] mem_la_addr,
    output wire [31:0] mem_la_wdata,
    output wire [ 3:0] mem_la_wstrb,

    // Co-processor interface (PCPI, unused)
    output wire        pcpi_valid,
    output wire [31:0] pcpi_insn,
    output wire [31:0] pcpi_rs1,
    output wire [31:0] pcpi_rs2,
    input  wire        pcpi_wr,
    input  wire [31:0] pcpi_rd,
    input  wire        pcpi_wait,
    input  wire        pcpi_ready,

    // IRQ interface (unused when ENABLE_IRQ=0)
    input  wire [31:0] irq,
    output wire [31:0] eoi,

    // Trace interface (unused when ENABLE_TRACE=0)
    output wire        trace_valid,
    output wire [35:0] trace_data
);
    // -----------------------------------------------------------------------
    // NOTE: This is a STUB for interface documentation only.
    // Replace with the real PicoRV32 source for synthesis.
    //
    // The real picorv32.v is available at:
    //   https://github.com/YosysHQ/picorv32/blob/main/picorv32.v
    // -----------------------------------------------------------------------

    // Suppress unused-port warnings
    assign mem_la_read  = 0;
    assign mem_la_write = 0;
    assign mem_la_addr  = 0;
    assign mem_la_wdata = 0;
    assign mem_la_wstrb = 0;
    assign pcpi_valid   = 0;
    assign pcpi_insn    = 0;
    assign pcpi_rs1     = 0;
    assign pcpi_rs2     = 0;
    assign eoi          = 0;
    assign trace_valid  = 0;
    assign trace_data   = 0;

    // Minimal FSM: halt immediately after reset
    initial begin
        mem_valid = 0;
        mem_instr = 0;
        mem_addr  = PROGADDR_RESET;
        mem_wdata = 0;
        mem_wstrb = 0;
    end

    always @(posedge clk) begin
        if (!resetn) begin
            mem_valid <= 0;
            mem_addr  <= PROGADDR_RESET;
            mem_wdata <= 0;
            mem_wstrb <= 0;
        end
    end

endmodule
`default_nettype wire
