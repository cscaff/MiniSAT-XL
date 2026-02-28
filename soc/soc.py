"""
MiniSAT-XL SoC Top Level.

Integrates:
  - PicoRV32 softcore (Wishbone master)
  - Firmware RAM         (Wishbone slave, 0x00000000)
  - Clause Memory window (Wishbone slave, 0x10000000)
  - Assignment Memory window (Wishbone slave, 0x20000000)
  - Occurrence List window   (Wishbone slave, 0x30000000)
  - BCP CSR block        (Wishbone slave, 0x40000000)
  - BCPAccelerator hardware engine

Memory map (byte addresses):
  0x00000000 – 0x0000FFFF  Firmware RAM       (64 KB)
  0x10000000 – 0x1001FFFF  Clause Memory      (128 KB, 8192 clauses × 16 B)
  0x20000000 – 0x200007FF  Assignment Memory  (2 KB, 512 vars × 4 B)
  0x30000000 – 0x300AFFFF  Occurrence Lists   (712 KB)
    0x30000000 – 0x30000FFF  Length table     (1024 lits × 4 B)
    0x30010000 – 0x300AFFFF  Clause-ID table  (102400 × 4 B)
  0x40000000 – 0x40000017  BCP CSRs           (6 × 4 B)
"""

import os
import sys

from amaranth import *

# Allow running from repo root
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC  = os.path.join(_ROOT, "src")
for p in (_ROOT, _SRC):
    if p not in sys.path:
        sys.path.insert(0, p)

from top import BCPAccelerator
from memory.clause_memory import MAX_CLAUSES
from memory.assignment_memory import MAX_VARS
from memory.watch_list_memory import NUM_LITERALS, MAX_WATCH_LEN

from soc.wishbone import WishboneBus, WishboneDecoder
from soc.firmware_ram import FirmwareRAM
from soc.bcp_csr import BcpCsrBlock
from soc.mem_windows import (
    ClauseMemoryWindow, AssignmentMemoryWindow, OccurrenceListWindow
)
from soc.picorv32_bridge import PicoRV32Bridge

# Slave window sizes (bytes)
FW_RAM_BASE  = 0x0000_0000;  FW_RAM_SIZE  = 0x0001_0000  # 64 KB
CLAUSE_BASE  = 0x1000_0000;  CLAUSE_SIZE  = 0x0002_0000  # 128 KB
ASSIGN_BASE  = 0x2000_0000;  ASSIGN_SIZE  = 0x0000_0800  # 2 KB
OCC_BASE     = 0x3000_0000;  OCC_SIZE     = 0x000B_0000  # 704 KB
CSR_BASE     = 0x4000_0000;  CSR_SIZE     = 0x0000_0020  # 32 B


class MiniSATXLSoC(Elaboratable):
    """
    Full MiniSAT-XL SoC (for synthesis / place-and-route).

    Instantiate PicoRV32 via Instance and connect everything together.
    The firmware binary must be provided as ``firmware_init`` (list of
    32-bit words in little-endian order).
    """

    def __init__(self, firmware_init=None):
        self.firmware_init = firmware_init or []

    def elaborate(self, platform):
        m = Module()

        # --- Sub-modules ---
        fw_ram       = FirmwareRAM(init=self.firmware_init)
        accel        = BCPAccelerator()
        clause_win   = ClauseMemoryWindow(max_clauses=MAX_CLAUSES)
        assign_win   = AssignmentMemoryWindow(max_vars=MAX_VARS)
        occ_win      = OccurrenceListWindow(
                           num_literals=NUM_LITERALS,
                           max_watch_len=MAX_WATCH_LEN)

        lit_width = accel.false_lit.shape().width
        var_width = accel.impl_var.shape().width
        cid_width = accel.conflict_clause_id.shape().width
        csr_block = BcpCsrBlock(
                        lit_width=lit_width,
                        var_width=var_width,
                        cid_width=cid_width)
        cpu_bridge = PicoRV32Bridge()

        m.submodules.fw_ram      = fw_ram
        m.submodules.accel       = accel
        m.submodules.clause_win  = clause_win
        m.submodules.assign_win  = assign_win
        m.submodules.occ_win     = occ_win
        m.submodules.csr_block   = csr_block
        m.submodules.cpu_bridge  = cpu_bridge

        # --- Wishbone interconnect ---
        m.submodules.decoder = WishboneDecoder(
            master=cpu_bridge.wb,
            slaves=[
                (fw_ram.bus,     FW_RAM_BASE, FW_RAM_SIZE),
                (clause_win.bus, CLAUSE_BASE, CLAUSE_SIZE),
                (assign_win.bus, ASSIGN_BASE, ASSIGN_SIZE),
                (occ_win.bus,    OCC_BASE,    OCC_SIZE),
                (csr_block.bus,  CSR_BASE,    CSR_SIZE),
            ],
        )

        # --- Connect memory write windows -> BCPAccelerator ---
        m.d.comb += [
            accel.clause_wr_addr.eq(clause_win.clause_wr_addr),
            accel.clause_wr_sat_bit.eq(clause_win.clause_wr_sat_bit),
            accel.clause_wr_size.eq(clause_win.clause_wr_size),
            accel.clause_wr_lit0.eq(clause_win.clause_wr_lit0),
            accel.clause_wr_lit1.eq(clause_win.clause_wr_lit1),
            accel.clause_wr_lit2.eq(clause_win.clause_wr_lit2),
            accel.clause_wr_lit3.eq(clause_win.clause_wr_lit3),
            accel.clause_wr_lit4.eq(clause_win.clause_wr_lit4),
            accel.clause_wr_en.eq(clause_win.clause_wr_en),

            accel.assign_wr_addr.eq(assign_win.assign_wr_addr),
            accel.assign_wr_data.eq(assign_win.assign_wr_data),
            accel.assign_wr_en.eq(assign_win.assign_wr_en),

            accel.wl_wr_lit.eq(occ_win.wl_wr_lit),
            accel.wl_wr_idx.eq(occ_win.wl_wr_idx),
            accel.wl_wr_data.eq(occ_win.wl_wr_data),
            accel.wl_wr_len.eq(occ_win.wl_wr_len),
            accel.wl_wr_en.eq(occ_win.wl_wr_en),
            accel.wl_wr_len_en.eq(occ_win.wl_wr_len_en),
        ]

        # --- Connect BCPAccelerator <-> CSR block ---
        m.d.comb += [
            accel.start.eq(csr_block.accel_start),
            accel.false_lit.eq(csr_block.accel_false_lit),
            csr_block.accel_busy.eq(accel.busy),
            csr_block.accel_done.eq(accel.done),
            csr_block.accel_conflict.eq(accel.conflict),
            accel.conflict_ack.eq(csr_block.accel_conflict_ack),
            csr_block.accel_conflict_cid.eq(accel.conflict_clause_id),
            csr_block.accel_impl_valid.eq(accel.impl_valid),
            csr_block.accel_impl_var.eq(accel.impl_var),
            csr_block.accel_impl_value.eq(accel.impl_value),
            csr_block.accel_impl_reason.eq(accel.impl_reason),
            accel.impl_ready.eq(csr_block.accel_impl_ready),
        ]

        return m
