#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
from pathlib import Path

from bcp_hw_bridge import init as hw_init, add_clause as hw_add_clause, run_bcp as hw_run_bcp
from bcp_hw_bridge import set_assignment as hw_set_assignment, shutdown as hw_shutdown
from memory.assignment_memory import UNASSIGNED as HW_UNASSIGNED, FALSE as HW_FALSE, TRUE as HW_TRUE

UNASSIGNED = -1
FALSE = 0
TRUE = 1
VSIDS_DECAY = 0.95


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


def lit_to_code(lit: int) -> int:
    if lit > 0:
        return 2 * lit
    return 2 * (-lit) + 1


def lit_var(code: int) -> int:
    return code >> 1


def lit_neg(code: int) -> int:
    return code ^ 1


def sw_to_hw(val: int) -> int:
    if val == UNASSIGNED:
        return HW_UNASSIGNED
    return HW_TRUE if val == TRUE else HW_FALSE


@dataclass
class SolverStats:
    decisions: int = 0
    conflicts: int = 0
    propagations: int = 0
    implications: int = 0
    learned_clauses: int = 0


@dataclass
class Clause:
    size: int
    learnt: bool
    lits: list


class CDCLSolver:
    def __init__(self, num_vars, clauses):
        self.num_vars = num_vars
        self.stats = SolverStats()

        self.assigns = [UNASSIGNED] * (num_vars + 1)
        self.levels = [0] * (num_vars + 1)
        self.reasons = [-1] * (num_vars + 1)
        self.activity = [0.0] * (num_vars + 1)
        self.var_inc = 1.0

        self.trail = []
        self.prop_head = 0
        self.trail_delimiters = []
        self.num_decisions = 0

        self.clauses = []

        for signed_lits in clauses:
            self._add_clause(signed_lits, learnt=False)

    def _add_clause(self, signed_lits, learnt=False):
        lits = [lit_to_code(l) for l in signed_lits]
        c = Clause(size=len(lits), learnt=learnt, lits=lits)
        ci = len(self.clauses)
        self.clauses.append(c)

        if len(lits) > 5:
            raise ValueError("Clause size exceeds MAX_K=5")

        hw_add_clause(ci, lits)
        return ci

    def _add_learnt_clause(self, lit_codes):
        c = Clause(size=len(lit_codes), learnt=True, lits=list(lit_codes))
        ci = len(self.clauses)
        self.clauses.append(c)
        self.stats.learned_clauses += 1
        if len(lit_codes) <= 5:
            hw_add_clause(ci, list(lit_codes))
        return ci

    def _lit_value(self, code):
        var = lit_var(code)
        a = self.assigns[var]
        if a == UNASSIGNED:
            return UNASSIGNED
        if code & 1:
            return a ^ 1
        return a

    def _enqueue(self, code, reason):
        var = lit_var(code)
        self.assigns[var] = 0 if (code & 1) else 1
        self.levels[var] = self.num_decisions
        self.reasons[var] = reason
        self.trail.append(code)
        self.stats.implications += 1
        hw_set_assignment(var, sw_to_hw(self.assigns[var]))

    def _var_bump_activity(self, var):
        self.activity[var] += self.var_inc
        if self.activity[var] > 1e100:
            for v in range(1, self.num_vars + 1):
                self.activity[v] *= 1e-100
            self.var_inc *= 1e-100

    def _var_decay_activity(self):
        self.var_inc *= 1.0 / VSIDS_DECAY

    def _analyze(self, conflict_ci):
        current_level = self.num_decisions
        seen = [False] * (self.num_vars + 1)
        processed = [False] * (self.num_vars + 1)

        learnt = []
        counter = 0

        c = self.clauses[conflict_ci]
        for lit in c.lits:
            var = lit_var(lit)
            if not seen[var] and self.assigns[var] != UNASSIGNED:
                seen[var] = True
                self._var_bump_activity(var)
                if self.levels[var] == current_level:
                    counter += 1
                elif self.levels[var] > 0:
                    learnt.append(lit)

        trail_idx = len(self.trail) - 1
        uip_lit = 0

        while counter > 0:
            while not seen[lit_var(self.trail[trail_idx])]:
                trail_idx -= 1
            p = self.trail[trail_idx]
            trail_idx -= 1
            var = lit_var(p)
            seen[var] = False
            processed[var] = True
            counter -= 1

            if counter == 0:
                uip_lit = lit_neg(p)
            else:
                reason_ci = self.reasons[var]
                if reason_ci < 0:
                    uip_lit = lit_neg(p)
                    counter = 0
                else:
                    rc = self.clauses[reason_ci]
                    for lit in rc.lits:
                        rvar = lit_var(lit)
                        if rvar == var:
                            continue
                        if self.assigns[rvar] == UNASSIGNED or processed[rvar]:
                            continue
                        if not seen[rvar]:
                            seen[rvar] = True
                            self._var_bump_activity(rvar)
                            if self.levels[rvar] == current_level:
                                counter += 1
                            elif self.levels[rvar] > 0:
                                learnt.append(lit)

        learnt.insert(0, uip_lit)

        bt_level = 0
        max_idx = 1
        for i in range(1, len(learnt)):
            lv = self.levels[lit_var(learnt[i])]
            if lv > bt_level:
                bt_level = lv
                max_idx = i

        if len(learnt) > 1:
            learnt[1], learnt[max_idx] = learnt[max_idx], learnt[1]

        self._var_decay_activity()
        return learnt, bt_level

    def _backtrack(self, level):
        while len(self.trail) > 0:
            if self.num_decisions <= level:
                break

            if (self.num_decisions > level and
                    len(self.trail) <= self.trail_delimiters[self.num_decisions - 1]):
                self.num_decisions -= 1
                continue

            code = self.trail.pop()
            var = lit_var(code)
            self.assigns[var] = UNASSIGNED
            self.levels[var] = 0
            self.reasons[var] = -1
            hw_set_assignment(var, HW_UNASSIGNED)

        while self.num_decisions > level:
            self.num_decisions -= 1

        del self.trail_delimiters[self.num_decisions:]
        self.prop_head = len(self.trail)
        self._sync_hw_assigns()

    def _sync_hw_assigns(self):
        for var in range(1, self.num_vars + 1):
            hw_set_assignment(var, sw_to_hw(self.assigns[var]))

    def _pick_decision_var(self):
        best_var = 0
        best_act = -1.0
        for v in range(1, self.num_vars + 1):
            if self.assigns[v] == UNASSIGNED and self.activity[v] > best_act:
                best_act = self.activity[v]
                best_var = v
        return best_var

    def _check_clause(self, clause):
        unassigned = None
        for lit in clause.lits:
            val = self._lit_value(lit)
            if val == TRUE:
                return "sat", None
            if val == UNASSIGNED:
                if unassigned is not None:
                    return "open", None
                unassigned = lit
        if unassigned is None:
            return "conflict", None
        return "unit", unassigned

    def _propagate_sw_long(self):
        return -1

    def _implication_valid(self, var, value, reason):
        """SW-verify a HW implication: reason clause must be genuinely unit.

        The BCPAccelerator pipeline reads assignment memory combinationally
        during EVAL state, but WRITEBACK (which commits implications to
        assign_mem) only runs after the ACTIVE state completes. Clauses
        evaluated in the same BCP round therefore see in-flight implications
        as UNASSIGNED, producing spurious unit propagations. This check
        re-evaluates the reason clause against the current SW state to
        discard those phantoms before they corrupt the trail.
        """
        if reason < 0:
            return True  # decision literal, no clause to verify
        if reason >= len(self.clauses):
            return False
        c = self.clauses[reason]
        unassigned_lit = None
        for lit in c.lits:
            v = self._lit_value(lit)
            if v == TRUE:
                return False  # clause already satisfied, not unit
            if v == UNASSIGNED:
                if unassigned_lit is not None:
                    return False  # multiple unassigned, not unit
                unassigned_lit = lit
        if unassigned_lit is None:
            return False  # all-false = conflict, not a unit implication
        if lit_var(unassigned_lit) != var:
            return False  # wrong variable
        # Polarity check: positive literal (even code) implies TRUE (value=1)
        expected_value = 0 if (unassigned_lit & 1) else 1
        return expected_value == value

    def _propagate_hw(self):
        while self.prop_head < len(self.trail):
            true_lit = self.trail[self.prop_head]
            false_lit = true_lit ^ 1
            self.prop_head += 1
            self.stats.propagations += 1

            result = hw_run_bcp(false_lit)
            conflict_cid = result["conflict"]

            # SW-verify the HW conflict: the clause must be genuinely all-false.
            # The BCPAccelerator can produce spurious conflict signals; discarding
            # them keeps the solver correct at the cost of a missed early termination.
            if conflict_cid >= 0:
                c = self.clauses[conflict_cid]
                if not all(self._lit_value(lit) == FALSE for lit in c.lits):
                    conflict_cid = -1

            if conflict_cid >= 0:
                for var, value, reason in result["implications"]:
                    if self.assigns[var] != UNASSIGNED:
                        continue
                    if not self._implication_valid(var, value, reason):
                        continue
                    code = (var << 1) | (0 if value == 1 else 1)
                    self._enqueue(code, reason)
                return conflict_cid

            sw_conflict = -1
            for var, value, reason in result["implications"]:
                if sw_conflict >= 0:
                    continue
                if self.assigns[var] != UNASSIGNED:
                    expected = TRUE if value == 1 else FALSE
                    if self.assigns[var] != expected:
                        sw_conflict = reason
                    continue
                if not self._implication_valid(var, value, reason):
                    continue
                code = (var << 1) | (0 if value == 1 else 1)
                self._enqueue(code, reason)

            if sw_conflict >= 0:
                return sw_conflict

        return -1

    def solve(self):
        for i, c in enumerate(self.clauses):
            if c.size == 0:
                return False
            if c.size == 1:
                if self._lit_value(c.lits[0]) == FALSE:
                    return False
                if self._lit_value(c.lits[0]) == UNASSIGNED:
                    self._enqueue(c.lits[0], i)

        while True:
            conflict = self._propagate_hw()
            if conflict >= 0:
                self.stats.conflicts += 1
                if self.num_decisions == 0:
                    return False

                learnt_lits, bt_level = self._analyze(conflict)
                self._backtrack(bt_level)

                if len(learnt_lits) == 1:
                    self._enqueue(learnt_lits[0], -1)
                else:
                    ci = self._add_learnt_clause(learnt_lits)
                    self._enqueue(learnt_lits[0], ci)
            else:
                dec_var = self._pick_decision_var()
                if dec_var == 0:
                    return True

                self.stats.decisions += 1
                self.trail_delimiters.append(len(self.trail))
                self.num_decisions += 1

                dec_lit = (dec_var << 1) | 1  # decide FALSE
                self._enqueue(dec_lit, -1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cnf", type=Path)
    args = ap.parse_args()

    num_vars, clauses = parse_dimacs(args.cnf)
    if any(len(c) > 5 for c in clauses):
        raise SystemExit("CNF contains clauses >5 literals; hardware limited to 5-SAT")

    hw_init(num_vars)
    try:
        solver = CDCLSolver(num_vars, clauses)
        sat = solver.solve()
        print("SAT" if sat else "UNSAT")
    finally:
        hw_shutdown()


if __name__ == "__main__":
    main()
