Here's a summary of the work from the previous session:                                                  
                                                                                                           
  What Was Found            
                                                                                                           
  The UNSAT false positive bug was rooted in the src/top.py hardware — specifically a WRITEBACK state that 
  had been added to automatically write implications back to assign_mem after BCP completed. This caused:
                                                                                                           
  1. Duplicate implications: The HW would pop implications from the FIFO, write them to assign_mem, then
  re-push them back into the FIFO — so SW saw each implication twice
  2. Stale assign_mem reads: Clauses evaluated in the same BCP round see in-flight implications as
  UNASSIGNED (since assign_mem is only updated via writeback after the round), causing spurious unit
  propagations

  What Was Changed

  src/top.py — removed the entire WRITEBACK mechanism:
  - Deleted the WRITEBACK FSM state
  - Deleted impl_count, wb_remaining, writeback_active, wb_load signals
  - Removed auto_assign_en logic that wrote FIFO pops back to assign_mem and re-pushed
  - Assignments to assign_mem are now purely host-controlled (SW is responsible via hw_write_assignment)

  Architecture migration (threading bridge → SoC simulation):
  - Deleted simulation/bcp_hw_bridge.py, simulation/hw_cdcl_solver.py, benchmarks/run_hw_cdcl_bench.py,
  test/test_bcp_bridge.py
  - Added simulation/soc_cdcl_solver.py (full CDCL + _implication_valid() SW-verification of HW
  implications)
  - Added benchmarks/run_soc_bench.py

  Current Status

  The bug is partially fixed — 2/3 UNSAT test instances pass, but uuf50-0100.cnf still returns SAT (false
  positive). The _implication_valid() guard in soc_cdcl_solver.py catches many spurious implications but
  doesn't catch all the cases causing incorrect SAT results on harder UNSAT instances.

    The Root Cause                                                                                           
                                                                                                         
  The ClauseEvaluator reads assign_mem combinationally during its EVAL state (line 363,                    
  clause_evaluator.py):                                                                                    
                                                                                                           
  m.d.comb += self.assign_rd_addr.eq(current_lit >> 1)                                                     
                                                                  
  The memory read is zero-latency — it sees whatever is currently in assign_mem. But assign_mem is only
  updated by synchronous host writes from SW. Within a single BCP round, the sequence is:

  Clause A evaluated → UNIT (implies var X = TRUE)
    → pushed to FIFO
    → assign_mem still shows var X = UNASSIGNED  ← problem
  Clause B evaluated → reads var X from assign_mem → sees UNASSIGNED
    → thinks it's a UNIT clause too → spurious implication

  SW only writes assign_mem between BCP rounds, so all clauses in the same round share the stale snapshot.

  Why the WRITEBACK Approach Failed

  The removed WRITEBACK state tried to fix this after the fact — pop implications from the FIFO, write to
  assign_mem, re-push to FIFO. This created two problems:
  1. Duplicate implications in the FIFO
  2. Still doesn't help clauses evaluated during the same BCP round (they've already been evaluated before
  WRITEBACK runs)

  The Correct Hardware Fix

  Auto-write the implication to assign_mem at the moment of FIFO push — not after. In src/top.py, where
  impl_fifo.push_valid fires:

  FIFO push: impl_push = result_valid & (status == UNIT) & result_ready
     → simultaneously write evaluator.result_implied_var/val to assign_mem

  Because the evaluator goes OUTPUT → IDLE → EVAL for each clause (it's sequential, not pipelined), the
  write lands in assign_mem before the next clause begins EVAL. So clause B would see var X = TRUE in
  assign_mem, correctly identify the clause as SATISFIED, and produce no implication.

  This requires a write-port mux in top.py:
  - Host writes (between BCP rounds) → use assign_wr_* ports
  - Auto-writes (on FIFO push) → use evaluator.result_implied_var/val

  Auto-write should take priority; host writes only happen outside of BCP, so there's no real conflict.

  In short: yes, the fix belongs in src/top.py — wire an automatic assign_mem write whenever the evaluator
  pushes a UNIT result to the FIFO. One mux, no new FSM states, no re-pushing to FIFO.