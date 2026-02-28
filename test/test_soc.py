"""
SoC Integration Test -- Amaranth simulation.

Exercises the BCPAccelerator hardware through the same CSR/memory-window
interface used by the real firmware running on PicoRV32, but driven by a
Python co-routine that implements the firmware CDCL algorithm.

Tiny CNF instance (3 variables, 3 clauses):
  Clause 0: (x0 ∨ x1)    lits [pos(0), pos(1)] = [0, 2]
  Clause 1: (¬x0 ∨ x2)   lits [neg(0), pos(2)] = [1, 4]
  Clause 2: (¬x1 ∨ ¬x2)  lits [neg(1), neg(2)] = [3, 5]

Expected result: SAT  (e.g. x0=TRUE, x1=FALSE, x2=TRUE)

Run:
  python -m test.test_soc
  # or
  python test/test_soc.py
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR   = os.path.join(REPO_ROOT, "src")
for p in (REPO_ROOT, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from amaranth.sim import Simulator

from memory.assignment_memory import UNASSIGNED, FALSE, TRUE
from soc.sim_harness import (
    SoCSimHarness,
    hw_write_clause,
    hw_write_occurrence_list,
    hw_write_assignment,
    hw_run_bcp,
    hw_drain_implications,
)

# Tiny instance constants
NUM_VARS = 3

def pos_lit(var): return 2 * var
def neg_lit(var): return 2 * var + 1


def test_soc_cdcl():
    """
    Run the CDCL firmware algorithm in Python, exercising hardware BCP.

    The testbench mirrors what firmware/main.c does on real silicon:
      1. Load clauses, occurrence lists, and initial assignments.
      2. Pick an unassigned variable, decide a value.
      3. Run BCP via the accelerator; drain implication stream.
      4. Handle conflicts with chronological backtracking.
      5. Repeat until SAT or UNSAT.
    Assert that the final answer is SAT.
    """
    harness = SoCSimHarness()
    accel   = harness.accel
    sim = Simulator(harness)
    sim.add_clock(1e-8)

    result_holder = {"result": None}

    async def firmware(ctx):
        # ---- 1. Initialise clause memory ----
        # Clause 0: (x0 ∨ x1)
        await hw_write_clause(ctx, accel, 0, sat_bit=0, size=2,
                               lits=[pos_lit(0), pos_lit(1)])
        # Clause 1: (¬x0 ∨ x2)
        await hw_write_clause(ctx, accel, 1, sat_bit=0, size=2,
                               lits=[neg_lit(0), pos_lit(2)])
        # Clause 2: (¬x1 ∨ ¬x2)
        await hw_write_clause(ctx, accel, 2, sat_bit=0, size=2,
                               lits=[neg_lit(1), neg_lit(2)])

        # ---- 2. Build occurrence lists ----
        # Each literal → list of clauses it appears in
        await hw_write_occurrence_list(ctx, accel, pos_lit(0), [0])   # x0  → c0
        await hw_write_occurrence_list(ctx, accel, neg_lit(0), [1])   # ¬x0 → c1
        await hw_write_occurrence_list(ctx, accel, pos_lit(1), [0])   # x1  → c0
        await hw_write_occurrence_list(ctx, accel, neg_lit(1), [2])   # ¬x1 → c2
        await hw_write_occurrence_list(ctx, accel, pos_lit(2), [1])   # x2  → c1
        await hw_write_occurrence_list(ctx, accel, neg_lit(2), [2])   # ¬x2 → c2

        # ---- 3. CDCL loop ----
        assignment = [UNASSIGNED] * NUM_VARS
        trail = []  # list of (var, val, is_decision)

        def pick_unassigned():
            for v in range(NUM_VARS):
                if assignment[v] == UNASSIGNED:
                    return v
            return -1

        async def propagate(false_lit):
            """
            BCP propagation queue: runs BCP for one false_lit at a time,
            draining implications and queuing new false lits.
            Returns (conflict_cid, new_implications) where conflict_cid=-1
            if no conflict.
            """
            queue = [false_lit]
            all_impl = []
            while queue:
                fl = queue.pop(0)
                res = await hw_run_bcp(ctx, accel, fl)
                if res["conflict"] >= 0:
                    return res["conflict"], all_impl
                for (iv, ival, ireason) in res["implications"]:
                    if assignment[iv] == UNASSIGNED:
                        # ival is 1-bit from impl_value (1=TRUE, 0=FALSE);
                        # map to assignment_memory constants TRUE=2, FALSE=1.
                        assignment[iv] = TRUE if ival else FALSE
                        await hw_write_assignment(ctx, accel, iv, assignment[iv])
                        all_impl.append((iv, assignment[iv], ireason))
                        # Queue BCP for the new false literal
                        new_fl = neg_lit(iv) if assignment[iv] == TRUE else pos_lit(iv)
                        queue.append(new_fl)
            return -1, all_impl

        sat_result = None

        for _iteration in range(100):
            var = pick_unassigned()
            if var < 0:
                sat_result = "SAT"
                break

            # Decide: assign var = TRUE
            decision_val = TRUE
            assignment[var] = decision_val
            await hw_write_assignment(ctx, accel, var, decision_val)
            trail.append((var, decision_val, True))

            # BCP for the decided assignment
            false_lit_for_decision = neg_lit(var) if decision_val == TRUE else pos_lit(var)
            conflict_cid, impl = await propagate(false_lit_for_decision)

            if conflict_cid >= 0:
                # Chronological backtrack: undo last decision and try opposite
                # Undo all implied assignments back to last decision
                while trail and not trail[-1][2]:
                    uvar, uval, _ = trail.pop()
                    assignment[uvar] = UNASSIGNED
                    await hw_write_assignment(ctx, accel, uvar, UNASSIGNED)

                if not trail:
                    sat_result = "UNSAT"
                    break

                # Undo decision
                dvar, dval, _ = trail.pop()
                assignment[dvar] = UNASSIGNED
                await hw_write_assignment(ctx, accel, dvar, UNASSIGNED)

                # Try opposite value
                flip_val = FALSE if dval == TRUE else TRUE
                assignment[dvar] = flip_val
                await hw_write_assignment(ctx, accel, dvar, flip_val)
                trail.append((dvar, flip_val, True))  # keep as decision

                # BCP for flipped decision
                fl2 = neg_lit(dvar) if flip_val == TRUE else pos_lit(dvar)
                c2, impl2 = await propagate(fl2)
                if c2 >= 0:
                    sat_result = "UNSAT"
                    break
            # Continue to next iteration with updated assignments
        else:
            sat_result = "UNSAT"  # loop limit exceeded

        result_holder["result"] = sat_result
        print(f"CDCL result: {sat_result}")
        print(f"Final assignment: {assignment}")
        assert sat_result == "SAT", f"Expected SAT, got {sat_result}"
        print("test_soc_cdcl PASSED: SAT result verified.")

    sim.add_testbench(firmware)

    vcd_path = os.path.join(REPO_ROOT, "test", "logs", "soc_cdcl.vcd")
    os.makedirs(os.path.dirname(vcd_path), exist_ok=True)
    with sim.write_vcd(vcd_path):
        sim.run()

    assert result_holder["result"] == "SAT", (
        f"Simulation did not reach SAT; got {result_holder['result']}"
    )


if __name__ == "__main__":
    test_soc_cdcl()
