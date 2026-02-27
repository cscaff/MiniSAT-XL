"""
End-to-end BCP hardware bridge test.

Exercises bcp_hw_bridge.run_bcp() through the full BCPAccelerator simulation
(the same code path used by hw_cdcl_solver.py).  Each test case builds a tiny
CNF scenario in the HW memories, fires one or more BCP rounds, and checks the
returned implications / conflict signal.

Variable allocation (non-overlapping so HW state from one test cannot bleed
into the next):
  Test 1 – vars  1, 2       (unit propagation)
  Test 2 – vars  3, 4       (conflict)
  Test 3 – vars  5, 6       (satisfied clause → no output)
  Test 4 – vars  7, 8, 9    (two independent implications in one BCP round)
  Test 5 – vars 10, 11, 12  (sequential BCP, second round uses WRITEBACK'd assign)

Hardware literal encoding (must match bcp_hw_bridge / hw_cdcl_solver):
  pos(v) = 2*v       # positive literal for variable v
  neg(v) = 2*v + 1   # negative literal for variable v

Assignment memory encoding (from memory/assignment_memory.py):
  UNASSIGNED = 0
  FALSE      = 1
  TRUE       = 2

impl_value returned by run_bcp():
  0 = var should be set FALSE
  1 = var should be set TRUE
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SIM_DIR   = os.path.join(REPO_ROOT, "simulation")
SRC_DIR   = os.path.join(REPO_ROOT, "src")
for d in (SRC_DIR, SIM_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

from bcp_hw_bridge import init, add_clause, set_assignment, run_bcp, shutdown
from memory.assignment_memory import (
    UNASSIGNED as HW_UNASSIGNED,
    FALSE      as HW_FALSE,
    TRUE       as HW_TRUE,
)


# ---------------------------------------------------------------------------
# Literal helpers
# ---------------------------------------------------------------------------

def pos(var: int) -> int:
    """Positive literal code for *var* (even)."""
    return 2 * var


def neg(var: int) -> int:
    """Negative literal code for *var* (odd)."""
    return 2 * var + 1


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_implication(impls, var, expected_value, *, test_name):
    """Assert that (var, expected_value) appears at least once in *impls*.

    Implications may be duplicated in the list because the WRITEBACK phase
    re-pushes each item to the FIFO before the software drain.  We tolerate
    duplicates here; the CDCL solver guards against them with its 'already
    assigned' check.
    """
    found = [(v, val, r) for v, val, r in impls if v == var and val == expected_value]
    assert found, (
        f"{test_name}: expected implication var={var} value={expected_value}, "
        f"but got implications={impls}"
    )


def assert_no_implication_for(impls, var, *, test_name):
    """Assert that *var* does NOT appear in *impls* (in any role)."""
    bad = [(v, val, r) for v, val, r in impls if v == var]
    assert not bad, (
        f"{test_name}: unexpected implication for var={var}: {bad}"
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_1_unit_propagation():
    """
    Clause 0: (x1 ∨ x2).
    x1 = FALSE  →  BCP on pos(x1) should imply x2 = TRUE.
    """
    name = "Test 1 [unit propagation]"

    add_clause(0, [pos(1), pos(2)])
    set_assignment(1, HW_FALSE)       # pos(1) is now FALSE

    result = run_bcp(pos(1))

    assert result["conflict"] == -1, (
        f"{name}: unexpected conflict clause {result['conflict']}"
    )
    assert_implication(result["implications"], var=2, expected_value=1, test_name=name)
    print(f"PASS  {name}")


def test_2_conflict():
    """
    Clause 1: (x3 ∨ x4).
    x3 = FALSE, x4 = FALSE  →  BCP on pos(x3) should detect a conflict on clause 1.
    """
    name = "Test 2 [conflict]"

    add_clause(1, [pos(3), pos(4)])
    set_assignment(3, HW_FALSE)
    set_assignment(4, HW_FALSE)

    result = run_bcp(pos(3))

    assert result["conflict"] == 1, (
        f"{name}: expected conflict on clause 1, got {result['conflict']}"
    )
    print(f"PASS  {name}")


def test_3_satisfied_clause():
    """
    Clause 2: (x5 ∨ x6).
    x5 = TRUE, x6 = FALSE  →  BCP on pos(x6) (the false literal) should produce
    no implication and no conflict because x5=TRUE already satisfies the clause.
    """
    name = "Test 3 [satisfied clause]"

    add_clause(2, [pos(5), pos(6)])
    set_assignment(5, HW_TRUE)
    set_assignment(6, HW_FALSE)       # pos(6) is now FALSE

    result = run_bcp(pos(6))

    assert result["conflict"] == -1, (
        f"{name}: unexpected conflict {result['conflict']}"
    )
    assert_no_implication_for(result["implications"], var=5, test_name=name)
    print(f"PASS  {name}")


def test_4_multiple_independent_implications():
    """
    Two clauses share the same false literal (pos(x7)) but each has a
    distinct unassigned second literal (x8 and x9 respectively).  Because
    x8 and x9 are independent, neither clause depends on the other's
    implication during the same BCP round — no HW timing hazard.

    Clause 3: (x7 ∨ x8)
    Clause 4: (x7 ∨ x9)
    x7 = FALSE  →  BCP on pos(x7) should imply x8=TRUE and x9=TRUE.
    """
    name = "Test 4 [multiple independent implications]"

    add_clause(3, [pos(7), pos(8)])
    add_clause(4, [pos(7), pos(9)])
    set_assignment(7, HW_FALSE)       # pos(7) is now FALSE
    # x8 and x9 remain UNASSIGNED (hardware default)

    result = run_bcp(pos(7))

    assert result["conflict"] == -1, (
        f"{name}: unexpected conflict {result['conflict']}"
    )
    assert_implication(result["implications"], var=8, expected_value=1, test_name=name)
    assert_implication(result["implications"], var=9, expected_value=1, test_name=name)
    print(f"PASS  {name}")


def test_5_sequential_bcp_writeback():
    """
    Two sequential BCP calls that rely on WRITEBACK to keep assign_mem current.

    The bridge no longer pops implications during ACTIVE, so impl_count > 0
    when ACTIVE completes and WRITEBACK always fires.  WRITEBACK writes every
    implication into assign_mem before run_bcp() returns, so the second BCP
    call sees x11=TRUE without any explicit set_assignment() between rounds.

    Clause 5: (¬x10 ∨ x11)  — neg(10)=21, pos(11)=22
    Clause 6: (¬x11 ∨ x12)  — neg(11)=23, pos(12)=24

    x10 = TRUE  →  neg(x10) = FALSE  →  BCP #1 implies x11=TRUE.
    WRITEBACK writes x11=TRUE to assign_mem before round 1 returns.
    neg(x11) = FALSE  →  BCP #2 implies x12=TRUE (no manual sync needed).
    """
    name = "Test 5 [sequential BCP via WRITEBACK]"

    add_clause(5, [neg(10), pos(11)])
    add_clause(6, [neg(11), pos(12)])
    set_assignment(10, HW_TRUE)       # neg(10) is now FALSE

    # --- BCP round 1 ---
    result1 = run_bcp(neg(10))
    assert result1["conflict"] == -1, (
        f"{name} round 1: unexpected conflict {result1['conflict']}"
    )
    assert_implication(result1["implications"], var=11, expected_value=1, test_name=name + " r1")
    print(f"PASS  {name} (round 1 → x11=TRUE)")

    # No set_assignment() needed: WRITEBACK already wrote x11=TRUE to assign_mem.

    # --- BCP round 2 ---
    result2 = run_bcp(neg(11))
    assert result2["conflict"] == -1, (
        f"{name} round 2: unexpected conflict {result2['conflict']}"
    )
    assert_implication(result2["implications"], var=12, expected_value=1, test_name=name + " r2")
    print(f"PASS  {name} (round 2 → x12=TRUE)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    init(num_vars=15)
    try:
        test_1_unit_propagation()
        test_2_conflict()
        test_3_satisfied_clause()
        test_4_multiple_independent_implications()
        test_5_sequential_bcp_writeback()
        print("\nAll BCP bridge tests PASSED.")
        return 0
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        return 1
    finally:
        shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
