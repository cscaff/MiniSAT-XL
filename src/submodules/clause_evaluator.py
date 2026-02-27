"""
Clause Evaluator Module for the BCP Accelerator.

Receives a prefetched clause and evaluates it against current variable
assignments to determine clause status: SATISFIED, UNIT, CONFLICT, or
UNRESOLVED.  This is Module 3 in the BCP pipeline.

FSM: IDLE -> EVAL -> OUTPUT

Uses valid/ready handshaking:
  - Upstream:   meta_valid (in) / meta_ready (out)
  - Downstream: result_valid (out) / result_ready (in)

OUTPUT state holds the result stable until result_ready fires.

Latency: 1 cycle (latch) + size cycles (eval) + 1+ cycle (output).
Sat-bit early exit: 2+ cycles total.

See: Hardware Description/BCP_Accelerator_System_Architecture.md, Module 3
     Notes/bcp_elastic_pipeline_spec.md, Section 3

     
┌──────────────────────────────────────────────────────────────────────────┐
│                      CLAUSE EVALUATOR MODULE                             │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                    INPUT INTERFACE (IDLE state)                    │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  From Clause Prefetcher:                                          │ │
│  │  • meta_valid (new clause available)                              │ │
│  │  • clause_id_in (which clause)                                    │ │
│  │  • sat_bit (pre-satisfied in memory?)                             │ │
│  │  • size (1-5 literals)                                            │ │
│  │  • lit0, lit1, lit2, lit3, lit4 (the literals)                    │ │
│  │                                                                    │ │
│  │  Back to Prefetcher:                                              │ │
│  │  • meta_ready = 1 (only in IDLE state)                            │ │
│  │    "I can accept a new clause"                                    │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           │ (when meta_valid=1)                                         │
│           ▼                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │              STATE: IDLE (Latching Stage)                          │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  On input arrival, latch:                                         │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ clause_id_reg    ← clause_id_in                             │ │ │
│  │  │ size_reg         ← size                                     │ │ │
│  │  │ lit_regs[0:4]    ← lit0-lit4 (save all 5)                 │ │ │
│  │  │ unassigned_count ← 0 (reset)                               │ │ │
│  │  │ last_unassigned_lit ← 0 (reset)                            │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  │  Early exit check:                                                │ │
│  │  ├─ if sat_bit=1:                                                 │ │
│  │  │   satisfied ← 1                                               │ │
│  │  │   next = OUTPUT  (skip evaluation!)                           │ │
│  │  │   ✓ Fast path: 2 cycles total                                 │ │
│  │  │                                                               │ │
│  │  └�� else:                                                         │ │
│  │      satisfied ← 0                                               │ │
│  │      lit_idx ← 0 (start from literal 0)                          │ │
│  │      next = EVAL  (normal path)                                  │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           ▼                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │            STATE: EVAL (Evaluation Loop)                           │ │
│  │            (repeats size_reg times)                                │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  For each literal in the clause:                                  │ │
│  │                                                                    │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ STEP 1: Multiplex current literal                           │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  lit_idx (0,1,2,3,4) ──┐                                    │ │ │
│  │  │                         ▼                                    │ │ │
│  │  │                   ┌──────────┐                               │ │ │
│  │  │                   │ Mux[5:1] │                               │ │ │
│  │  │  lit_regs[0:4] ──→│          │                               │ │ │
│  │  │                   └──────────┘                               │ │ │
│  │  │                         │                                    │ │ │
│  │  │                         ▼                                    │ │ │
│  │  │                   current_lit                                │ │ │
│  │  │                (16 bits: var_id + polarity)                 │ │ │
│  │  │                                                              │ │ │
│  │  └───────────────────────────────���──────────────────────────────┘ │ │
│  │           │                                                         │ │
│  │           ▼                                                         │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ STEP 2: Decode literal                                      │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  current_lit [15:1] ──────┐  (variable ID)                  │ │ │
│  │  │                           ▼                                  │ │ │
│  │  │                    assign_rd_addr                            │ │ │
│  │  │                    (to Assignment Memory)                    │ │ │
│  │  │                                                              │ │ │
│  │  │  current_lit [0] ─→ lit_polarity                            │ │ │
│  │  │                    (0=positive, 1=negative)                 │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────��───────────────────────────────┘ │ │
│  │           │                                                         │ │
│  │           ▼                                                         │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ STEP 3: Memory lookup (COMBINATIONAL)                       │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  assign_rd_addr ──→ Assignment Memory                        │ │ │
│  │  │                                                              │ │ │
│  │  │  assign_rd_data ←── [0/1/2] = [UNASSIGNED/FALSE/TRUE]       │ │ │
│  │  │                   (combinational read, 0-cycle latency)     │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │           │                                                         │ │
│  │           ▼                                                         │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ STEP 4: Evaluate literal truth value                        │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  Literal encoding truth table:                              │ │ │
│  │  │  ┌────────────┬──────────┬──────────┐                       │ │ │
│  │  │  │ Literal    │ Variable │ lit_true?│                       │ │ │
│  │  │  ├────────────┼──────────┼──────────┤                       │ │ │
│  │  │  │ +x (pol=0) │ x=TRUE   │ YES ✓   │                       │ │ │
│  │  │  │ +x (pol=0) │ x=FALSE  │ NO      │                       │ │ │
│  │  │  │ +x (pol=0) │ UNASSIGN │ MAYBE   │                       │ │ │
│  │  │  │ -x (pol=1) │ x=FALSE  │ YES ✓   │                       │ │ │
│  │  │  │ -x (pol=1) │ x=TRUE   │ NO      │                       │ │ │
│  │  │  │ -x (pol=1) │ UNASSIGN │ MAYBE   │                       │ │ │
│  │  │  └────────────┴──────────┴──────────┘                       │ │ │
│  │  │                                                              │ │ │
│  │  │  lit_true = ((~pol & (val==TRUE)) | (pol & (val==FALSE)))   │ │ │
│  │  │  lit_unassigned = (val == UNASSIGNED)                       │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │           │                                                         │ │
│  │           ▼                                                         │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ STEP 5: Update accumulators                                 │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  if lit_true:                                               │ │ │
│  │  │    satisfied ← 1  (clause is satisfied!)                    │ │ │
│  │  │                                                              │ │ │
│  │  │  if lit_unassigned:                                         │ │ │
│  │  │    unassigned_count ← unassigned_count + 1                  │ │ │
│  │  │    last_unassigned_lit ← current_lit                        │ │ │
│  │  │    (remember this unassigned literal for UNIT clause)       │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │           │                                                         │ │
│  │           ▼                                                         │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ STEP 6: Loop control                                        │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  if lit_idx == (size_reg - 1):                              │ │ │
│  │  │    ✓ Evaluated all literals                                 │ │ │
│  │  │    next = OUTPUT                                            │ │ │
│  │  │                                                              │ │ ��
│  │  │  else:                                                       │ │ │
│  │  │    lit_idx ← lit_idx + 1                                    │ │ │
│  │  │    Loop back to STEP 1 next cycle                           │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           │ (after size cycles)                                         │
│           ▼                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │            STATE: OUTPUT (Present Result)                          │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  Decode accumulated state into result:                            │ │
│  │                                                                    │ │
│  │  ┌─────────────���────────────────────────────────────────────────┐ │ │
│  │  │ Status determination (combinational):                       │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │ if satisfied == 1:                                           │ │ │
│  │  │   result_status = SATISFIED (0)                             │ │ │
│  │  │   "Clause is true, no implications needed"                  │ │ │
│  │  │                                                              │ │ │
│  │  │ elif unassigned_count == 0:                                 │ │ │
│  │  │   result_status = CONFLICT (2)                              │ │ │
│  │  │   "All literals false, contradiction!"                      │ │ │
│  │  │                                                              │ │ │
│  │  │ elif unassigned_count == 1:                                 │ │ │
│  │  │   result_status = UNIT (1)                                  │ │ │
│  │  │   "Exactly one unassigned, must assign it true"             │ │ │
│  │  │   result_implied_var = last_unassigned_lit >> 1             │ │ │
│  │  │   result_implied_val = ~last_unassigned_lit[0]              │ │ │
│  │  │   (compute what value makes the literal true)               │ │ │
│  │  │                                                              │ │ │
│  │  │ else:  (unassigned_count > 1)                               │ │ │
│  │  │   result_status = UNRESOLVED (3)                            │ │ │
│  │  │   "Multiple unassigned, clause not yet determined"          │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │ Watcher replacement flag:                                   │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │ found_replacement = ~satisfied & (unassigned_count > 1)     │ │ │
│  │  │                                                              │ │ │
│  │  │ If true: "Can move watch pointer to another literal"        │ │ │
│  │  │ (for 2-watcher optimization)                                │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  │  ┌───────────────────────────��──────────────────────────────────┐ │ │
│  │  │ Output presentation:                                        │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │ result_valid ← 1        ✓ Data ready                        │ │ │
│  │  │ result_status ← (SATISFIED/UNIT/CONFLICT/UNRESOLVED)        │ │ │
│  │  │ result_clause_id ← clause_id_reg                            │ │ │
│  │  │ result_implied_var ← (var for UNIT)                         │ │ │
│  │  │ result_implied_val ← (val for UNIT)                         │ │ │
│  │  │ found_replacement ← (flag)                                  │ │ │
│  │  │                                                              │ │ │
│  │  │ Holds stable until result_ready=1                           │ │ │
│  │  │ (downstream accepted)                                       │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           │ (when result_ready=1 or flush=1)                           │
│           ▼                                                              │
│        return to IDLE                                                   │
│           │                                                              │
│           └─→ next = IDLE                                              │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
         │
         ├─→ result_valid + result_status + result_*
         │   (to downstream: FIFO, conflict handler)
         │
         └─→ assign_rd_addr (to Assignment Memory)
             assign_rd_data ← (from Assignment Memory)
"""

from amaranth import *
from amaranth.lib.data import ArrayLayout

from memory.clause_memory import MAX_CLAUSES, MAX_K, LIT_WIDTH
from memory.assignment_memory import MAX_VARS, UNASSIGNED, FALSE, TRUE


# Result status codes
SATISFIED  = 0
UNIT       = 1
CONFLICT   = 2
UNRESOLVED = 3


class ClauseEvaluator(Elaboratable):
    """
    Clause Evaluator.

    Ports -- inputs (from Clause Prefetcher)
    -----------------------------------------
    clause_id_in : Signal(range(max_clauses)), in
    meta_valid   : Signal(), in
    sat_bit      : Signal(), in
    size         : Signal(3), in
    lit0-lit4    : Signal(LIT_WIDTH), in

    Ports -- backpressure to Prefetcher
    ------------------------------------
    meta_ready   : Signal(), out  -- high only when state == IDLE

    Ports -- assignment memory interface
    -------------------------------------
    assign_rd_addr : Signal(range(max_vars)), out
    assign_rd_data : Signal(2), in

    Ports -- outputs (evaluation result)
    -------------------------------------
    result_status      : Signal(2), out
    result_implied_var : Signal(range(max_vars)), out
    result_implied_val : Signal(), out
    result_clause_id   : Signal(range(max_clauses)), out
    result_valid       : Signal(), out
    found_replacement  : Signal(), out

    Ports -- backpressure from downstream
    --------------------------------------
    result_ready : Signal(), in  -- from FIFO / conflict output mux

    Ports -- control
    -----------------
    flush : Signal(), in  -- force return to IDLE on new BCP start
    """

    def __init__(self, max_clauses=MAX_CLAUSES, max_vars=MAX_VARS):
        self.max_clauses = max_clauses
        self.max_vars = max_vars

        # Inputs from Clause Prefetcher
        self.clause_id_in = Signal(range(max_clauses))
        self.meta_valid = Signal()
        self.sat_bit = Signal()
        self.size = Signal(3)
        self.lit0 = Signal(LIT_WIDTH)
        self.lit1 = Signal(LIT_WIDTH)
        self.lit2 = Signal(LIT_WIDTH)
        self.lit3 = Signal(LIT_WIDTH)
        self.lit4 = Signal(LIT_WIDTH)

        # Backpressure to Prefetcher
        self.meta_ready = Signal()

        # Assignment memory read interface
        self.assign_rd_addr = Signal(range(max_vars))
        self.assign_rd_data = Signal(2)

        # Evaluation result outputs
        self.result_status = Signal(2)
        self.result_implied_var = Signal(range(max_vars))
        self.result_implied_val = Signal()
        self.result_clause_id = Signal(range(max_clauses))
        self.result_valid = Signal()
        # High when clause found a replacement literal (UNRESOLVED: moved to new watcher)
        # Equivalent to `found = true` in the C propagate() inner loop
        self.found_replacement = Signal()

        # Backpressure from downstream
        self.result_ready = Signal()

        # Control
        self.flush = Signal()

    def elaborate(self, platform):
        m = Module()

        # Internal registers
        clause_id_reg = Signal(range(self.max_clauses))
        size_reg = Signal(3)
        satisfied = Signal()
        unassigned_count = Signal(range(MAX_K + 1))
        last_unassigned_lit = Signal(LIT_WIDTH)
        lit_idx = Signal(range(MAX_K))

        # Literal register array for muxing
        lit_regs = Array([Signal(LIT_WIDTH, name=f"lit_reg{i}") for i in range(MAX_K)])
        current_lit = Signal(LIT_WIDTH)
        m.d.comb += current_lit.eq(lit_regs[lit_idx])

        # Drive assignment memory read address from current literal
        # Variable ID = literal >> 1 (strip polarity bit)
        m.d.comb += self.assign_rd_addr.eq(current_lit >> 1)

        with m.FSM(name="eval"):
            with m.State("IDLE"):
                m.d.comb += [
                    self.result_valid.eq(0),
                    self.meta_ready.eq(1),
                ]
                with m.If(self.flush):
                    pass  # stay in IDLE
                with m.Elif(self.meta_valid):
                    # Latch all clause fields
                    m.d.sync += [
                        clause_id_reg.eq(self.clause_id_in),
                        size_reg.eq(self.size),
                        lit_regs[0].eq(self.lit0),
                        lit_regs[1].eq(self.lit1),
                        lit_regs[2].eq(self.lit2),
                        lit_regs[3].eq(self.lit3),
                        lit_regs[4].eq(self.lit4),
                        # Reset accumulators
                        unassigned_count.eq(0),
                        last_unassigned_lit.eq(0),
                    ]
                    with m.If(self.sat_bit):
                        # Early exit: clause already satisfied
                        m.d.sync += satisfied.eq(1)
                        m.next = "OUTPUT"
                    with m.Else():
                        m.d.sync += [
                            satisfied.eq(0),
                            lit_idx.eq(0),
                        ]
                        m.next = "EVAL"

            with m.State("EVAL"):
                with m.If(self.flush):
                    m.next = "IDLE"
                with m.Else():
                    # current_lit is driven combinationally from lit_regs[lit_idx]
                    # assign_rd_addr is driven combinationally from current_lit >> 1
                    # assign_rd_data is available combinationally (comb read port)

                    lit_polarity = current_lit[0]
                    assign_val = self.assign_rd_data

                    # Check if literal is satisfied
                    lit_true = Signal()
                    m.d.comb += lit_true.eq(
                        ((~lit_polarity) & (assign_val == TRUE)) |
                        (lit_polarity & (assign_val == FALSE))
                    )

                    lit_unassigned = Signal()
                    m.d.comb += lit_unassigned.eq(assign_val == UNASSIGNED)

                    with m.If(lit_true):
                        m.d.sync += satisfied.eq(1)
                    with m.If(lit_unassigned):
                        m.d.sync += [
                            unassigned_count.eq(unassigned_count + 1),
                            last_unassigned_lit.eq(current_lit),
                        ]

                    # Advance or finish
                    with m.If(lit_idx == size_reg - 1):
                        m.next = "OUTPUT"
                    with m.Else():
                        m.d.sync += lit_idx.eq(lit_idx + 1)

            with m.State("OUTPUT"):
                # Hold result stable until result_ready fires
                m.d.comb += [
                    self.result_valid.eq(1),
                    self.result_clause_id.eq(clause_id_reg),
                    # Clause found a replacement watcher: ~satisfied & unassigned > 1
                    # (matches C code's `found = true` branch in propagate())
                    self.found_replacement.eq(~satisfied & (unassigned_count > 1)),
                ]

                with m.If(satisfied):
                    m.d.comb += self.result_status.eq(SATISFIED)
                with m.Elif(unassigned_count == 0):
                    m.d.comb += self.result_status.eq(CONFLICT)
                with m.Elif(unassigned_count == 1):
                    m.d.comb += [
                        self.result_status.eq(UNIT),
                        self.result_implied_var.eq(last_unassigned_lit >> 1),
                        # Positive literal (pol=0) -> assign TRUE (1)
                        # Negative literal (pol=1) -> assign FALSE (0)
                        self.result_implied_val.eq(~last_unassigned_lit[0]),
                    ]
                with m.Else():
                    m.d.comb += self.result_status.eq(UNRESOLVED)

                # Only return to IDLE when downstream accepts the result
                with m.If(self.flush | self.result_ready):
                    m.next = "IDLE"

        return m