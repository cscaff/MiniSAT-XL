"""
SoC Simulation Harness (no PicoRV32).

Instantiates only the hardware peripherals (BCPAccelerator + CSR block +
memory write windows) and exposes a thin Python API that mimics what the
firmware would do via Wishbone MMIO.

This harness is used by test/test_soc.py to run the CDCL firmware logic
as a Python co-routine, exercising the exact same hardware paths that
the firmware uses on real silicon.

Usage
-----
    harness = SoCSimHarness()
    sim = Simulator(harness)
    sim.add_clock(1e-8)
    sim.add_testbench(my_firmware_coro)
    sim.run()

The testbench uses the async helper methods on ``SoCSimHarness`` (or the
Wishbone read/write helpers from ``soc_wb_helpers``).
"""

import os
import sys

from amaranth import *

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC  = os.path.join(_ROOT, "src")
for p in (_ROOT, _SRC):
    if p not in sys.path:
        sys.path.insert(0, p)

from top import BCPAccelerator
from memory.clause_memory import MAX_CLAUSES, LIT_WIDTH
from memory.assignment_memory import MAX_VARS
from memory.watch_list_memory import NUM_LITERALS, MAX_WATCH_LEN

from soc.bcp_csr import BcpCsrBlock, REG_CONTROL, REG_FALSE_LIT, REG_STATUS
from soc.bcp_csr import REG_CC_ID, REG_IMPL, REG_RESULT
from soc.mem_windows import (
    ClauseMemoryWindow, AssignmentMemoryWindow, OccurrenceListWindow
)

# Assignment encoding (mirrors assignment_memory.py)
UNASSIGNED = 0
FALSE      = 1
TRUE       = 2


class SoCSimHarness(Elaboratable):
    """
    Simulation-only SoC minus PicoRV32.

    All hardware peripherals are wired together.  The Python testbench
    drives the BCPAccelerator directly via its port signals (same signals
    as the CSR block drives in the real SoC).
    """

    def __init__(self):
        # Result register visible to the testbench
        self.result = Signal(2)

        # Expose BCPAccelerator for direct testbench access
        self.accel = BCPAccelerator()

    def elaborate(self, platform):
        m = Module()

        accel = self.accel
        m.submodules.accel = accel

        m.d.comb += self.result.eq(0)  # harness-level result (unused in pure-Py sim)

        return m


# ---------------------------------------------------------------------------
# Python-level MMIO helpers used by the testbench
# These functions drive the BCPAccelerator signals directly, mirroring what
# the firmware does via Wishbone MMIO.
# ---------------------------------------------------------------------------

async def hw_write_clause(ctx, accel, clause_id, sat_bit, size, lits):
    """Write a clause to the hardware clause memory."""
    ctx.set(accel.clause_wr_addr,    clause_id)
    ctx.set(accel.clause_wr_sat_bit, sat_bit)
    ctx.set(accel.clause_wr_size,    size)
    ctx.set(accel.clause_wr_lit0,    lits[0] if len(lits) > 0 else 0)
    ctx.set(accel.clause_wr_lit1,    lits[1] if len(lits) > 1 else 0)
    ctx.set(accel.clause_wr_lit2,    lits[2] if len(lits) > 2 else 0)
    ctx.set(accel.clause_wr_lit3,    lits[3] if len(lits) > 3 else 0)
    ctx.set(accel.clause_wr_lit4,    lits[4] if len(lits) > 4 else 0)
    ctx.set(accel.clause_wr_en,      1)
    await ctx.tick()
    ctx.set(accel.clause_wr_en, 0)


async def hw_write_occurrence_list(ctx, accel, lit, clause_ids):
    """Write the occurrence list (watch list) for a literal."""
    ctx.set(accel.wl_wr_lit,    lit)
    ctx.set(accel.wl_wr_len,    len(clause_ids))
    ctx.set(accel.wl_wr_len_en, 1)
    await ctx.tick()
    ctx.set(accel.wl_wr_len_en, 0)
    for idx, cid in enumerate(clause_ids):
        ctx.set(accel.wl_wr_lit,  lit)
        ctx.set(accel.wl_wr_idx,  idx)
        ctx.set(accel.wl_wr_data, cid)
        ctx.set(accel.wl_wr_en,   1)
        await ctx.tick()
        ctx.set(accel.wl_wr_en, 0)


async def hw_write_assignment(ctx, accel, var_id, value):
    """Write a variable assignment (0=UNASSIGNED,1=FALSE,2=TRUE)."""
    ctx.set(accel.assign_wr_addr, var_id)
    ctx.set(accel.assign_wr_data, value)
    ctx.set(accel.assign_wr_en,   1)
    await ctx.tick()
    ctx.set(accel.assign_wr_en, 0)


async def hw_start_bcp(ctx, accel, false_lit):
    """Pulse start and set false_lit."""
    ctx.set(accel.false_lit, false_lit)
    ctx.set(accel.start,     1)
    await ctx.tick()
    ctx.set(accel.start, 0)


async def hw_wait_done(ctx, accel, max_cycles=2000):
    """Spin until done is asserted."""
    for _ in range(max_cycles):
        if ctx.get(accel.done):
            return
        await ctx.tick()
    raise AssertionError(f"BCP timed out after {max_cycles} cycles")


async def hw_drain_implications(ctx, accel):
    """Pop all pending implications from the FIFO."""
    implications = []
    for _ in range(1024):
        if not ctx.get(accel.impl_valid):
            break
        var    = ctx.get(accel.impl_var)
        value  = ctx.get(accel.impl_value)
        reason = ctx.get(accel.impl_reason)
        ctx.set(accel.impl_ready, 1)
        await ctx.tick()
        ctx.set(accel.impl_ready, 0)
        implications.append((var, value, reason))
    return implications


async def hw_ack_conflict(ctx, accel):
    """Acknowledge a conflict and wait for DONE -> IDLE transition."""
    ctx.set(accel.conflict_ack, 1)
    await ctx.tick()
    ctx.set(accel.conflict_ack, 0)
    await ctx.tick()


async def hw_run_bcp(ctx, accel, false_lit):
    """
    Full BCP cycle: start → wait done → drain implications → return.

    Returns
    -------
    dict with:
      'conflict'     : int   -1 if no conflict, else conflict_clause_id
      'implications' : list of (var, value, reason_clause_id)
    """
    await hw_start_bcp(ctx, accel, false_lit)
    await hw_wait_done(ctx, accel)

    conflict_cid = -1
    if ctx.get(accel.conflict):
        conflict_cid = ctx.get(accel.conflict_clause_id)
        await hw_ack_conflict(ctx, accel)
    else:
        await ctx.tick()  # DONE -> IDLE

    implications = await hw_drain_implications(ctx, accel)
    return {"conflict": conflict_cid, "implications": implications}
