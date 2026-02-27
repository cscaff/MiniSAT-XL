# HW BCP API integration changes

## Overview
I added a Python bridge that runs the Amaranth `BCPAccelerator` in a persistent simulator and exposed a small API for MiniSAT to call. MiniSAT now has an optional `HW_BCP_SIM` compile-time path that replaces `Solver::propagate()` with a call into that Python bridge, while keeping the original software propagation intact when the macro is off.

## New/updated files
### Added
- `simulation/bcp_hw_bridge.py`
  - Hosts a background Amaranth `Simulator` with a command queue.
  - Exposes Python functions callable from C++:
    - `init(num_vars)`
    - `add_clause(clause_id, lits)`
    - `set_assignment(var, val)`
    - `run_bcp(false_lit) -> {conflict, implications}`
    - `disable_clause(clause_id)`
    - `shutdown()`

- `simulation/minisat/minisat/utils/HWBCPSim.h`
- `simulation/minisat/minisat/utils/HWBCPSim.cc`
  - C++ shim that embeds CPython, imports `bcp_hw_bridge`, and calls its API.

### Updated
- `src/top.py`
  - Fixed imports to `submodules.*` so the simulator can import the top-level module from `src/` directly.

- `simulation/minisat/minisat/core/Solver.h`
  - Added HW state to map clauses to HW clause IDs and declarations for HW helpers.

- `simulation/minisat/minisat/core/Solver.cc`
  - Added HW initialization and clause registration.
  - Added HW-aware clause removal via `disableClause()`.
  - Updated `uncheckedEnqueue()` and `cancelUntil()` to sync assignments to HW.
  - Replaced `propagate()` under `#ifdef HW_BCP_SIM` to call HW BCP and enqueue implications.

- `simulation/minisat/Makefile`
  - Added `HW_BCP_SIM` build toggle and Python include/link flags.

- `README.md`
  - Added build/run instructions for the HW BCP simulation mode.

## Python API behavior
### `init(num_vars)`
Initializes the simulator and validates `num_vars <= MAX_VARS`.

### `add_clause(clause_id, lits)`
- Writes clause into clause memory.
- Updates occurrence lists (watch lists) for each literal.
- Enforces `MAX_K=5` and `MAX_WATCH_LEN=100`.

### `set_assignment(var, val)`
Writes variable assignment into assignment memory. Encoding:
- `0` = UNASSIGNED
- `1` = FALSE
- `2` = TRUE

### `run_bcp(false_lit)`
- Pulses `start` with `false_lit` and waits for `done`.
- Returns:
  ```json
  {"conflict": <clause_id or -1>, "implications": [(var, value, reason), ...]}
  ```
- Each implication is `(var, value, reason)` where `value` is 0/1 for FALSE/TRUE.

### `disable_clause(clause_id)`
- Marks the clause’s `sat_bit=1` (kept in memory but ignored by evaluator).
- Avoids breaking the watch/occurrence lists which still reference the clause ID.

## C++ bridge API (HWBCPSim)
Header: `minisat/utils/HWBCPSim.h`
```cpp
struct HWImplication { Var var; bool value; int reason_id; };
class HWBCPSim {
public:
  static void init(int num_vars);
  static void addClause(int clause_id, const vec<Lit>& lits);
  static void disableClause(int clause_id);
  static void setAssignment(Var v, lbool val);
  static void runBCP(int false_lit, vec<HWImplication>& out_impls, int& out_conflict_id);
  static void shutdown();
};
```

## MiniSAT integration details
- `Solver::propagate()` is replaced under `#ifdef HW_BCP_SIM`:
  - For each pending trail literal `p`, compute `false_lit = toInt(p) ^ 1`.
  - Call `HWBCPSim::runBCP(false_lit, impls, conflict_id)`.
  - Enqueue each implication as a standard MiniSAT assignment (with reason clause).
  - Report conflict if either:
    - HW returns `conflict_id`, or
    - A returned implication contradicts an existing assignment.
- Clause IDs are assigned once and stored in a map (`CRef -> clause_id`).
- When a clause is deleted in MiniSAT, `disableClause()` is called to set `sat_bit=1` in HW memory.

## Build/run (HW mode)
```
export MINISAT_ACCEL_ROOT=/path/to/MiniSAT-Accel
cd simulation/minisat
make config
make r HW_BCP_SIM=1
./build/release/bin/minisat <cnf>
```
If Python link flags fail on your system:
```
make r HW_BCP_SIM=1 PYTHON_CONFIG="python3-config --embed"
```

## Current limitations
- Hardware model supports `MAX_K=5`, `MAX_CLAUSES=8192`, `MAX_VARS=512`.
- Clause removal is modeled via `sat_bit` instead of watch list compaction.
- Watch lists are built as occurrence lists (each clause is in all literals’ lists).
- If you want true removal, you’ll need a compaction step to rewrite the watch lists.
