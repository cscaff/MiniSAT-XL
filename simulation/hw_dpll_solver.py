#!/usr/bin/env python3
import argparse
from pathlib import Path

from bcp_hw_bridge import init as hw_init, add_clause as hw_add_clause, run_bcp as hw_run_bcp
from bcp_hw_bridge import set_assignment as hw_set_assignment, shutdown as hw_shutdown
from memory.assignment_memory import UNASSIGNED, FALSE, TRUE


def parse_dimacs(path: Path):
    num_vars = None
    clauses = []
    with path.open() as f:
        current = []
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("%"):
                break
            if line.startswith("p"):
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "cnf":
                    num_vars = int(parts[2])
                continue
            for tok in line.split():
                if tok.startswith("%"):
                    break
                lit = int(tok)
                if lit == 0:
                    if current:
                        clauses.append(current)
                        current = []
                else:
                    current.append(lit)
        if current:
            clauses.append(current)
    if num_vars is None:
        raise ValueError("Missing DIMACS header")
    return num_vars, clauses


def lit_to_hw(lit: int) -> int:
    var = abs(lit) - 1
    sign = 1 if lit < 0 else 0
    return (var << 1) | sign


def assign_to_hw(val: bool) -> int:
    return TRUE if val else FALSE


def dpll(num_vars, clauses):
    assigns = [UNASSIGNED] * num_vars
    trail = []
    trail_lim = []

    def push_assign(var, val):
        assigns[var] = TRUE if val else FALSE
        hw_set_assignment(var, assigns[var])
        trail.append(var)

    def pop_to(level):
        while len(trail) > level:
            v = trail.pop()
            assigns[v] = UNASSIGNED
            hw_set_assignment(v, UNASSIGNED)

    def propagate(var, val):
        false_lit = ((var << 1) | (0 if val else 1))  # literal that became false
        result = hw_run_bcp(false_lit)
        if result["conflict"] >= 0:
            return False
        for v, value, _reason in result["implications"]:
            if assigns[v] == UNASSIGNED:
                push_assign(v, bool(value))
            elif assigns[v] != (TRUE if value else FALSE):
                return False
        return True

    def choose_var():
        for i in range(num_vars):
            if assigns[i] == UNASSIGNED:
                return i
        return None

    def solve():
        v = choose_var()
        if v is None:
            return True
        level = len(trail)
        # try True then False
        for val in (True, False):
            push_assign(v, val)
            if propagate(v, val) and solve():
                return True
            pop_to(level)
        return False

    return solve(), assigns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cnf", type=Path)
    args = ap.parse_args()

    num_vars, clauses = parse_dimacs(args.cnf)
    if any(len(c) > 5 for c in clauses):
        raise SystemExit("CNF contains clauses >5 literals; hardware limited to 5-SAT")

    hw_init(num_vars)
    for cid, clause in enumerate(clauses):
        hw_add_clause(cid, [lit_to_hw(l) for l in clause])

    sat, assigns = dpll(num_vars, clauses)
    print("SAT" if sat else "UNSAT")
    if sat:
        model = []
        for i, val in enumerate(assigns, start=1):
            if val == TRUE:
                model.append(str(i))
            elif val == FALSE:
                model.append(str(-i))
        print("v", " ".join(model), "0")

    hw_shutdown()


if __name__ == "__main__":
    main()
