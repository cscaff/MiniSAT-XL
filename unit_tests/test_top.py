"""
Testbench for the BCP Accelerator top-level module.

Verifies end-to-end integration of all pipeline stages:
  Watch List Manager -> Clause Prefetcher -> Clause Evaluator -> Implication FIFO
backed by Clause Memory, Watch List Memory, and Assignment Memory.

Verifies:
  1. Empty watch list: done asserted quickly, no implications, no conflict.
  2. Single UNIT clause: implication appears in FIFO with correct fields.
  3. Conflict detection: conflict signal latched with correct clause ID.
  4. Satisfied clause (sat_bit): no implication, no conflict, done.
  5. Sequential BCP calls accumulate implications in the FIFO.
  6. Multi-clause watch list (3 clauses) with backpressure -> 3 implications.
"""

import os
import sys

# Add src/ to the path so we can import the module
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from amaranth.sim import Simulator

from memory.assignment_memory import UNASSIGNED, FALSE, TRUE
from top import BCPAccelerator


def test_bcp_accelerator():
    dut = BCPAccelerator()
    sim = Simulator(dut)
    sim.add_clock(1e-8)

    async def testbench(ctx):
        async def write_clause(addr, sat_bit, size, lits):
            ctx.set(dut.clause_wr_addr, addr)
            ctx.set(dut.clause_wr_sat_bit, sat_bit)
            ctx.set(dut.clause_wr_size, size)
            ctx.set(dut.clause_wr_lit0, lits[0])
            ctx.set(dut.clause_wr_lit1, lits[1])
            ctx.set(dut.clause_wr_lit2, lits[2])
            ctx.set(dut.clause_wr_lit3, lits[3])
            ctx.set(dut.clause_wr_lit4, lits[4])
            ctx.set(dut.clause_wr_en, 1)
            await ctx.tick()
            ctx.set(dut.clause_wr_en, 0)

        async def write_watch_list(lit, clause_ids):
            ctx.set(dut.wl_wr_lit, lit)
            ctx.set(dut.wl_wr_len, len(clause_ids))
            ctx.set(dut.wl_wr_len_en, 1)
            await ctx.tick()
            ctx.set(dut.wl_wr_len_en, 0)
            for idx, cid in enumerate(clause_ids):
                ctx.set(dut.wl_wr_lit, lit)
                ctx.set(dut.wl_wr_idx, idx)
                ctx.set(dut.wl_wr_data, cid)
                ctx.set(dut.wl_wr_en, 1)
                await ctx.tick()
                ctx.set(dut.wl_wr_en, 0)

        async def write_assign(var_id, value):
            ctx.set(dut.assign_wr_addr, var_id)
            ctx.set(dut.assign_wr_data, value)
            ctx.set(dut.assign_wr_en, 1)
            await ctx.tick()
            ctx.set(dut.assign_wr_en, 0)

        async def start_bcp(false_lit):
            ctx.set(dut.false_lit, false_lit)
            ctx.set(dut.start, 1)
            await ctx.tick()
            ctx.set(dut.start, 0)

        async def wait_done(max_cycles=300):
            for _ in range(max_cycles):
                if ctx.get(dut.done):
                    return
                await ctx.tick()
            raise AssertionError("Timed out waiting for done")

        async def ack_conflict():
            ctx.set(dut.conflict_ack, 1)
            await ctx.tick()
            ctx.set(dut.conflict_ack, 0)

        async def pop_implication():
            assert ctx.get(dut.impl_valid) == 1, "No implication to pop"
            result = {
                "var": ctx.get(dut.impl_var),
                "value": ctx.get(dut.impl_value),
                "reason": ctx.get(dut.impl_reason),
            }
            ctx.set(dut.impl_ready, 1)
            await ctx.tick()
            ctx.set(dut.impl_ready, 0)
            return result

        # Setup: populate memories
        await write_clause(0, sat_bit=0, size=2, lits=[1, 2, 0, 0, 0])
        await write_clause(1, sat_bit=0, size=2, lits=[1, 3, 0, 0, 0])
        await write_clause(2, sat_bit=0, size=2, lits=[1, 4, 0, 0, 0])
        await write_clause(3, sat_bit=1, size=2, lits=[0, 2, 0, 0, 0])

        await write_watch_list(1, [0])
        await write_watch_list(3, [1])
        await write_watch_list(5, [2])
        await write_watch_list(7, [])
        await write_watch_list(0, [3])

        # ---- Test 1: Empty watch list ----
        await start_bcp(false_lit=7)
        await wait_done()
        assert ctx.get(dut.conflict) == 0, "Test 1 FAIL: unexpected conflict"
        assert ctx.get(dut.impl_valid) == 0, "Test 1 FAIL: unexpected implication"
        print("Test 1 PASSED: Empty watch list -> done, no output.")
        await ctx.tick()

        # ---- Test 2: Single UNIT implication ----
        await write_assign(0, TRUE)
        await start_bcp(false_lit=1)
        await wait_done()
        assert ctx.get(dut.conflict) == 0, "Test 2 FAIL: unexpected conflict"
        for _ in range(5):
            if ctx.get(dut.impl_valid):
                break
            await ctx.tick()
        assert ctx.get(dut.impl_valid) == 1, "Test 2 FAIL: no implication"
        imp = await pop_implication()
        assert imp["var"] == 1, f"Test 2 FAIL: var expected 1 (b), got {imp['var']}"
        assert imp["value"] == 1, f"Test 2 FAIL: value expected 1 (TRUE), got {imp['value']}"
        assert imp["reason"] == 0, f"Test 2 FAIL: reason expected 0, got {imp['reason']}"
        print("Test 2 PASSED: UNIT clause -> implication b=TRUE, reason=clause 0.")
        await ctx.tick()

        # ---- Test 3: Conflict detection ----
        await write_assign(1, TRUE)
        await start_bcp(false_lit=3)
        await wait_done()
        assert ctx.get(dut.conflict) == 1, "Test 3 FAIL: conflict not detected"
        assert ctx.get(dut.conflict_clause_id) == 1, (
            f"Test 3 FAIL: conflict_clause_id expected 1, got {ctx.get(dut.conflict_clause_id)}"
        )
        print("Test 3 PASSED: CONFLICT detected, clause_id=1.")
        await ack_conflict()
        await ctx.tick()

        # ---- Test 4: Satisfied clause (sat_bit=1) ----
        await write_assign(1, UNASSIGNED)
        await start_bcp(false_lit=0)
        await wait_done()
        assert ctx.get(dut.conflict) == 0, "Test 4 FAIL: unexpected conflict"
        assert ctx.get(dut.impl_valid) == 0, "Test 4 FAIL: unexpected implication"
        print("Test 4 PASSED: Satisfied clause -> no output, done.")
        await ctx.tick()

        # ---- Test 5: Two sequential BCP calls -> two implications ----
        await write_assign(1, UNASSIGNED)
        await write_assign(2, UNASSIGNED)
        await start_bcp(false_lit=1)
        await wait_done()
        await ctx.tick()

        await start_bcp(false_lit=5)
        await wait_done()
        await ctx.tick()

        for _ in range(5):
            if ctx.get(dut.impl_valid):
                break
            await ctx.tick()
        assert ctx.get(dut.impl_valid) == 1, "Test 5 FAIL: FIFO empty"
        imp1 = await pop_implication()
        assert imp1["var"] == 1 and imp1["value"] == 1, (
            f"Test 5a FAIL: expected b=TRUE, got var={imp1['var']} val={imp1['value']}"
        )
        for _ in range(5):
            if ctx.get(dut.impl_valid):
                break
            await ctx.tick()
        assert ctx.get(dut.impl_valid) == 1, "Test 5 FAIL: second impl missing"
        imp2 = await pop_implication()
        assert imp2["var"] == 2 and imp2["value"] == 1, (
            f"Test 5b FAIL: expected c=TRUE, got var={imp2['var']} val={imp2['value']}"
        )
        assert ctx.get(dut.impl_valid) == 0, "Test 5 FAIL: FIFO should be empty"
        print("Test 5 PASSED: Two sequential BCP calls -> two implications.")

        # ---- Test 6: Multi-clause watch list (backpressure) ----
        await write_clause(10, sat_bit=0, size=2, lits=[6, 8, 0, 0, 0])
        await write_clause(11, sat_bit=0, size=2, lits=[6, 10, 0, 0, 0])
        await write_clause(12, sat_bit=0, size=2, lits=[6, 12, 0, 0, 0])
        await write_watch_list(6, [10, 11, 12])

        await write_assign(3, FALSE)
        await write_assign(4, UNASSIGNED)
        await write_assign(5, UNASSIGNED)
        await write_assign(6, UNASSIGNED)

        while ctx.get(dut.impl_valid):
            await pop_implication()

        await start_bcp(false_lit=6)
        await wait_done(max_cycles=400)

        assert ctx.get(dut.conflict) == 0, "Test 6 FAIL: unexpected conflict"

        implications = []
        for _ in range(10):
            if ctx.get(dut.impl_valid):
                break
            await ctx.tick()
        for i in range(3):
            for _ in range(10):
                if ctx.get(dut.impl_valid):
                    break
                await ctx.tick()
            assert ctx.get(dut.impl_valid) == 1, (
                f"Test 6 FAIL: expected 3 implications, only got {i}"
            )
            imp = await pop_implication()
            implications.append(imp)

        implied_vars = sorted([imp["var"] for imp in implications])
        assert implied_vars == [4, 5, 6], (
            f"Test 6 FAIL: expected vars [4,5,6], got {implied_vars}"
        )
        for imp in implications:
            assert imp["value"] == 1, (
                f"Test 6 FAIL: expected value=TRUE for var {imp['var']}"
            )

        assert ctx.get(dut.impl_valid) == 0, "Test 6 FAIL: FIFO should be empty"
        print("Test 6 PASSED: Multi-clause watch list (3 clauses) -> 3 implications.")

        print("\nAll tests PASSED.")

    sim.add_testbench(testbench)
    vcd_path = os.path.join(REPO_ROOT, "unit_tests", "logs", "bcp_accelerator.vcd")
    with sim.write_vcd(vcd_path):
        sim.run()


if __name__ == "__main__":
    test_bcp_accelerator()
