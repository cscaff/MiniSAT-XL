"""
Testbench for the Watch List Manager module.

Uses a real WatchListMemory connected to the WLM so that the 2-cycle
read latency is exercised end-to-end.

Verifies:
  1. Spec example: 3-entry watch list streams clause IDs in order.
  2. Empty watch list: done asserted, no valid outputs.
  3. Single-entry watch list.
  4. Larger watch list (8 entries).
  5. Back-to-back invocations with different literals.
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

from submodules.watch_list_manager import WatchListManager
from memory.watch_list_memory import WatchListMemory


class WLMTestFixture(Elaboratable):
    def __init__(self):
        self.wlm = WatchListManager()
        self.mem = WatchListMemory()

    def elaborate(self, platform):
        m = Module()
        m.submodules.wlm = self.wlm
        m.submodules.mem = self.mem

        m.d.comb += [
            self.mem.rd_lit.eq(self.wlm.wl_rd_lit),
            self.mem.rd_idx.eq(self.wlm.wl_rd_idx),
            self.mem.rd_en.eq(self.wlm.wl_rd_en),
            self.wlm.wl_rd_data.eq(self.mem.rd_data),
            self.wlm.wl_rd_len.eq(self.mem.rd_len),
        ]
        return m


def test_watch_list_manager():
    dut = WLMTestFixture()
    wlm = dut.wlm
    mem = dut.mem
    sim = Simulator(dut)
    sim.add_clock(1e-8)

    async def testbench(ctx):
        async def write_watch_list(lit, clause_ids):
            ctx.set(mem.wr_lit, lit)
            ctx.set(mem.wr_len, len(clause_ids))
            ctx.set(mem.wr_len_en, 1)
            await ctx.tick()
            ctx.set(mem.wr_len_en, 0)
            for idx, cid in enumerate(clause_ids):
                ctx.set(mem.wr_lit, lit)
                ctx.set(mem.wr_idx, idx)
                ctx.set(mem.wr_data, cid)
                ctx.set(mem.wr_en, 1)
                await ctx.tick()
                ctx.set(mem.wr_en, 0)

        async def run_wlm(false_lit, max_cycles=50):
            ctx.set(wlm.false_lit, false_lit)
            ctx.set(wlm.start, 1)
            await ctx.tick()
            ctx.set(wlm.start, 0)
            await ctx.tick()

            ctx.set(wlm.clause_id_ready, 1)
            results = []
            for _ in range(max_cycles):
                if ctx.get(wlm.clause_id_valid):
                    results.append(ctx.get(wlm.clause_id))
                if ctx.get(wlm.done):
                    break
                await ctx.tick()
            ctx.set(wlm.clause_id_ready, 0)
            await ctx.tick()
            return results

        await write_watch_list(3, [5, 17, 42])
        await write_watch_list(10, [])
        await write_watch_list(5, [7])
        await write_watch_list(2, [10, 20, 30, 40, 50, 60, 70, 80])
        await write_watch_list(6, [100, 200])

        results = await run_wlm(3)
        assert results == [5, 17, 42], f"Test 1 FAIL: expected [5, 17, 42], got {results}"
        print("Test 1 PASSED: Spec example (3-entry watch list).")

        results = await run_wlm(10)
        assert results == [], f"Test 2 FAIL: expected [], got {results}"
        print("Test 2 PASSED: Empty watch list.")

        results = await run_wlm(5)
        assert results == [7], f"Test 3 FAIL: expected [7], got {results}"
        print("Test 3 PASSED: Single-entry watch list.")

        expected = [10, 20, 30, 40, 50, 60, 70, 80]
        results = await run_wlm(2)
        assert results == expected, f"Test 4 FAIL: expected {expected}, got {results}"
        print("Test 4 PASSED: 8-entry watch list.")

        r1 = await run_wlm(3)
        r2 = await run_wlm(6)
        r3 = await run_wlm(5)
        assert r1 == [5, 17, 42], f"Test 5a FAIL: got {r1}"
        assert r2 == [100, 200], f"Test 5b FAIL: got {r2}"
        assert r3 == [7], f"Test 5c FAIL: got {r3}"
        print("Test 5 PASSED: Back-to-back invocations.")

        print("\nAll tests PASSED.")

    sim.add_testbench(testbench)
    vcd_path = os.path.join(REPO_ROOT, "test", "logs", "watch_list_manager.vcd")
    with sim.write_vcd(vcd_path):
        sim.run()


if __name__ == "__main__":
    test_watch_list_manager()
