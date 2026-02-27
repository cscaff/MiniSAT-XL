"""
Testbench for the Clause Prefetcher module.

Verifies:
  1. Single clause fetch returns correct data.
  2. Backpressure holds output stable until consumed.
  3. Buffer full deasserts clause_id_ready; resumes after drain.
  4. Flush clears pipeline/buffer.
"""

import os
import sys

# Add src/ to the path so we can import the module
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from amaranth import Elaboratable, Module
from amaranth.sim import Simulator

from memory.clause_memory import ClauseMemory
from submodules.clause_prefetcher import ClausePrefetcher


class PrefetcherTestWrapper(Elaboratable):
    def __init__(self):
        self.prefetcher = ClausePrefetcher()
        self.mem = ClauseMemory()

    def elaborate(self, platform):
        m = Module()
        m.submodules.prefetcher = self.prefetcher
        m.submodules.mem = self.mem

        m.d.comb += [
            self.mem.rd_addr.eq(self.prefetcher.clause_rd_addr),
            self.mem.rd_en.eq(self.prefetcher.clause_rd_en),
            self.prefetcher.clause_rd_sat_bit.eq(self.mem.rd_data_sat_bit),
            self.prefetcher.clause_rd_size.eq(self.mem.rd_data_size),
            self.prefetcher.clause_rd_lit0.eq(self.mem.rd_data_lit0),
            self.prefetcher.clause_rd_lit1.eq(self.mem.rd_data_lit1),
            self.prefetcher.clause_rd_lit2.eq(self.mem.rd_data_lit2),
            self.prefetcher.clause_rd_lit3.eq(self.mem.rd_data_lit3),
            self.prefetcher.clause_rd_lit4.eq(self.mem.rd_data_lit4),
        ]
        return m


def test_clause_prefetcher():
    dut = PrefetcherTestWrapper()
    pf = dut.prefetcher
    mem = dut.mem
    sim = Simulator(dut)
    sim.add_clock(1e-8)

    async def testbench(ctx):
        async def write_clause(addr, sat_bit, size, lits):
            ctx.set(mem.wr_addr, addr)
            ctx.set(mem.wr_data_sat_bit, sat_bit)
            ctx.set(mem.wr_data_size, size)
            ctx.set(mem.wr_data_lit0, lits[0])
            ctx.set(mem.wr_data_lit1, lits[1])
            ctx.set(mem.wr_data_lit2, lits[2])
            ctx.set(mem.wr_data_lit3, lits[3])
            ctx.set(mem.wr_data_lit4, lits[4])
            ctx.set(mem.wr_en, 1)
            await ctx.tick()
            ctx.set(mem.wr_en, 0)

        async def send_clause_id(clause_id):
            while not ctx.get(pf.clause_id_ready):
                await ctx.tick()
            ctx.set(pf.clause_id_in, clause_id)
            ctx.set(pf.clause_id_valid, 1)
            await ctx.tick()
            ctx.set(pf.clause_id_valid, 0)

        async def wait_meta(expect, consume=True, max_cycles=20):
            for _ in range(max_cycles):
                if ctx.get(pf.meta_valid):
                    got = {
                        "clause_id": ctx.get(pf.clause_id_out),
                        "sat_bit": ctx.get(pf.out_sat_bit),
                        "size": ctx.get(pf.out_size),
                        "lit0": ctx.get(pf.out_lit0),
                        "lit1": ctx.get(pf.out_lit1),
                        "lit2": ctx.get(pf.out_lit2),
                        "lit3": ctx.get(pf.out_lit3),
                        "lit4": ctx.get(pf.out_lit4),
                    }
                    assert got == expect, f"Expected {expect}, got {got}"
                    if consume:
                        ctx.set(pf.meta_ready, 1)
                        await ctx.tick()
                        ctx.set(pf.meta_ready, 0)
                    return
                await ctx.tick()
            raise AssertionError("Timed out waiting for meta_valid")

        # ---- Test 1: Single clause fetch ----
        await write_clause(5, sat_bit=0, size=3, lits=[2, 4, 6, 0, 0])
        ctx.set(pf.meta_ready, 0)
        await send_clause_id(5)
        await wait_meta(
            {
                "clause_id": 5,
                "sat_bit": 0,
                "size": 3,
                "lit0": 2,
                "lit1": 4,
                "lit2": 6,
                "lit3": 0,
                "lit4": 0,
            }
        )
        print("Test 1 PASSED: Single clause fetch returns correct data.")

        # ---- Test 2: Backpressure holds output ----
        await write_clause(6, sat_bit=1, size=2, lits=[8, 9, 0, 0, 0])
        ctx.set(pf.meta_ready, 0)
        await send_clause_id(6)
        await wait_meta(
            {
                "clause_id": 6,
                "sat_bit": 1,
                "size": 2,
                "lit0": 8,
                "lit1": 9,
                "lit2": 0,
                "lit3": 0,
                "lit4": 0,
            },
            consume=False,
        )
        for _ in range(2):
            assert ctx.get(pf.meta_valid), "meta_valid dropped under backpressure"
            await ctx.tick()
        ctx.set(pf.meta_ready, 1)
        await ctx.tick()
        ctx.set(pf.meta_ready, 0)
        print("Test 2 PASSED: Backpressure holds output stable.")

        # ---- Test 3: Buffer full deasserts clause_id_ready ----
        await write_clause(7, sat_bit=0, size=1, lits=[10, 0, 0, 0, 0])
        await write_clause(8, sat_bit=0, size=1, lits=[12, 0, 0, 0, 0])
        await write_clause(9, sat_bit=0, size=1, lits=[14, 0, 0, 0, 0])
        ctx.set(pf.meta_ready, 0)
        await send_clause_id(7)
        await send_clause_id(8)
        await ctx.tick()
        assert ctx.get(pf.clause_id_ready) == 0, "clause_id_ready should deassert when full"
        ctx.set(pf.meta_ready, 1)
        await wait_meta(
            {
                "clause_id": 7,
                "sat_bit": 0,
                "size": 1,
                "lit0": 10,
                "lit1": 0,
                "lit2": 0,
                "lit3": 0,
                "lit4": 0,
            },
            consume=True,
        )
        await wait_meta(
            {
                "clause_id": 8,
                "sat_bit": 0,
                "size": 1,
                "lit0": 12,
                "lit1": 0,
                "lit2": 0,
                "lit3": 0,
                "lit4": 0,
            },
            consume=True,
        )
        ctx.set(pf.meta_ready, 0)
        await send_clause_id(9)
        ctx.set(pf.meta_ready, 1)
        await wait_meta(
            {
                "clause_id": 9,
                "sat_bit": 0,
                "size": 1,
                "lit0": 14,
                "lit1": 0,
                "lit2": 0,
                "lit3": 0,
                "lit4": 0,
            },
            consume=True,
        )
        ctx.set(pf.meta_ready, 0)
        print("Test 3 PASSED: Buffer full gating works.")

        # ---- Test 4: Flush clears pipeline/buffer ----
        await write_clause(12, sat_bit=0, size=1, lits=[16, 0, 0, 0, 0])
        await send_clause_id(12)
        ctx.set(pf.flush, 1)
        await ctx.tick()
        ctx.set(pf.flush, 0)
        for _ in range(3):
            assert ctx.get(pf.meta_valid) == 0, "meta_valid should be cleared by flush"
            await ctx.tick()
        print("Test 4 PASSED: Flush clears pipeline/buffer.")

        print("\nAll tests PASSED.")

    sim.add_testbench(testbench)
    vcd_path = os.path.join(REPO_ROOT, "test", "logs", "clause_prefetcher.vcd")
    with sim.write_vcd(vcd_path):
        sim.run()


if __name__ == "__main__":
    test_clause_prefetcher()
