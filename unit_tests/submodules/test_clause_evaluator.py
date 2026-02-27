"""
Testbench for the Clause Evaluator module.

Verifies:
  1. Satisfied clause (sat_bit=1) → SATISFIED.
  2. Unit clause: one FALSE, one UNASSIGNED → UNIT.
  3. Conflict clause: all literals FALSE → CONFLICT.
  4. Unresolved clause: multiple UNASSIGNED literals → UNRESOLVED.
  5. Satisfied via assignment: one literal TRUE → SATISFIED.
  6. Spec example: (a ∨ b ∨ c) with a=FALSE, b=UNASSIGNED, c=FALSE → UNIT implying b.
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

from submodules.clause_evaluator import (
    ClauseEvaluator, SATISFIED, UNIT, CONFLICT, UNRESOLVED
)
from memory.assignment_memory import AssignmentMemory, UNASSIGNED, FALSE, TRUE


STATUS_NAMES = {
    SATISFIED: "SATISFIED",
    UNIT: "UNIT",
    CONFLICT: "CONFLICT",
    UNRESOLVED: "UNRESOLVED",
}


class EvalTestWrapper(Elaboratable):
    def __init__(self, max_clauses=8192, max_vars=512):
        self.ev = ClauseEvaluator(max_clauses=max_clauses, max_vars=max_vars)
        self.amem = AssignmentMemory(max_vars=max_vars)

    def elaborate(self, platform):
        m = Module()
        m.submodules.ev = self.ev
        m.submodules.amem = self.amem

        m.d.comb += [
            self.amem.rd_addr.eq(self.ev.assign_rd_addr),
            self.ev.assign_rd_data.eq(self.amem.rd_data),
        ]
        return m


def test_clause_evaluator():
    dut = EvalTestWrapper(max_clauses=8192, max_vars=512)
    ev = dut.ev
    amem = dut.amem
    sim = Simulator(dut)
    sim.add_clock(1e-8)

    async def testbench(ctx):
        async def write_assign(var_id, value):
            ctx.set(amem.wr_addr, var_id)
            ctx.set(amem.wr_data, value)
            ctx.set(amem.wr_en, 1)
            await ctx.tick()
            ctx.set(amem.wr_en, 0)

        async def clear_assignments(var_ids):
            for v in var_ids:
                await write_assign(v, UNASSIGNED)

        async def submit_clause(clause_id, sat_bit, size, lits):
            ctx.set(ev.clause_id_in, clause_id)
            ctx.set(ev.meta_valid, 1)
            ctx.set(ev.sat_bit, sat_bit)
            ctx.set(ev.size, size)
            ctx.set(ev.lit0, lits[0])
            ctx.set(ev.lit1, lits[1])
            ctx.set(ev.lit2, lits[2])
            ctx.set(ev.lit3, lits[3])
            ctx.set(ev.lit4, lits[4])
            await ctx.tick()
            ctx.set(ev.meta_valid, 0)

        async def wait_result(max_cycles=20):
            for _ in range(max_cycles):
                if ctx.get(ev.result_valid):
                    result = {
                        "status": ctx.get(ev.result_status),
                        "implied_var": ctx.get(ev.result_implied_var),
                        "implied_val": ctx.get(ev.result_implied_val),
                        "clause_id": ctx.get(ev.result_clause_id),
                    }
                    ctx.set(ev.result_ready, 1)
                    await ctx.tick()
                    ctx.set(ev.result_ready, 0)
                    return result
                await ctx.tick()
            raise AssertionError("Timed out waiting for result_valid")

        # ---- Test 1: Satisfied clause via sat_bit ----
        await submit_clause(42, sat_bit=1, size=3, lits=[2, 4, 6, 0, 0])
        r = await wait_result()
        assert r["status"] == SATISFIED, (
            f"Test 1 FAIL: expected SATISFIED, got {STATUS_NAMES[r['status']]}"
        )
        assert r["clause_id"] == 42, "Test 1 FAIL: clause_id"
        print("Test 1 PASSED: sat_bit=1 → SATISFIED")
        await ctx.tick()

        # ---- Test 2: Unit clause ----
        await write_assign(0, FALSE)
        await submit_clause(7, sat_bit=0, size=2, lits=[0, 3, 0, 0, 0])
        r = await wait_result()
        assert r["status"] == UNIT, (
            f"Test 2 FAIL: expected UNIT, got {STATUS_NAMES[r['status']]}"
        )
        assert r["implied_var"] == 1, (
            f"Test 2 FAIL: implied_var expected 1, got {r['implied_var']}"
        )
        assert r["implied_val"] == 0, (
            f"Test 2 FAIL: implied_val expected 0, got {r['implied_val']}"
        )
        print("Test 2 PASSED: Unit clause → UNIT with correct implication")
        await ctx.tick()
        await clear_assignments([0])

        # ---- Test 3: Conflict clause ----
        await write_assign(0, FALSE)
        await write_assign(1, FALSE)
        await write_assign(2, FALSE)
        await submit_clause(99, sat_bit=0, size=3, lits=[0, 2, 4, 0, 0])
        r = await wait_result()
        assert r["status"] == CONFLICT, (
            f"Test 3 FAIL: expected CONFLICT, got {STATUS_NAMES[r['status']]}"
        )
        assert r["clause_id"] == 99
        print("Test 3 PASSED: All literals FALSE → CONFLICT")
        await ctx.tick()
        await clear_assignments([0, 1, 2])

        # ---- Test 4: Unresolved clause ----
        await submit_clause(50, sat_bit=0, size=2, lits=[0, 2, 0, 0, 0])
        r = await wait_result()
        assert r["status"] == UNRESOLVED, (
            f"Test 4 FAIL: expected UNRESOLVED, got {STATUS_NAMES[r['status']]}"
        )
        print("Test 4 PASSED: Multiple UNASSIGNED → UNRESOLVED")
        await ctx.tick()

        # ---- Test 5: Satisfied via assignment ----
        await write_assign(0, FALSE)
        await write_assign(1, TRUE)
        await write_assign(2, FALSE)
        await submit_clause(10, sat_bit=0, size=3, lits=[0, 2, 4, 0, 0])
        r = await wait_result()
        assert r["status"] == SATISFIED, (
            f"Test 5 FAIL: expected SATISFIED, got {STATUS_NAMES[r['status']]}"
        )
        print("Test 5 PASSED: One literal TRUE → SATISFIED")
        await ctx.tick()
        await clear_assignments([0, 1, 2])

        # ---- Test 6: Spec example ----
        await write_assign(1, FALSE)
        await write_assign(3, FALSE)
        await submit_clause(0, sat_bit=0, size=3, lits=[2, 4, 6, 0, 0])
        r = await wait_result()
        assert r["status"] == UNIT, (
            f"Test 6 FAIL: expected UNIT, got {STATUS_NAMES[r['status']]}"
        )
        assert r["implied_var"] == 2, (
            f"Test 6 FAIL: implied_var expected 2, got {r['implied_var']}"
        )
        assert r["implied_val"] == 1, (
            f"Test 6 FAIL: implied_val expected 1, got {r['implied_val']}"
        )
        assert r["clause_id"] == 0
        print("Test 6 PASSED: Spec example (a∨b∨c) → UNIT implying b=TRUE")

        print("\nAll tests PASSED.")

    sim.add_testbench(testbench)
    vcd_path = os.path.join(REPO_ROOT, "unit_tests", "logs", "clause_evaluator.vcd")
    with sim.write_vcd(vcd_path):
        sim.run()


if __name__ == "__main__":
    test_clause_evaluator()
