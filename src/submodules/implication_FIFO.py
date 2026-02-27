"""
Implication FIFO Module for the BCP Accelerator.

Buffers unit clause implications (variable + value + reason clause ID)
produced by the Clause Evaluator before software consumes them.
Uses Amaranth's synchronous circular-buffer FIFO.

See: Hardware Description/BCP_Accelerator_System_Architecture.md, Memory Module 4

┌──────────────────────────────────────────────────────────────────────────┐
│                      IMPLICATION FIFO MODULE                             │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │              INPUT INTERFACE (Push Side)                           │ │
│  │              (from Clause Evaluator)                              │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  • push_valid (1 bit)                                              │ │
│  │    "Clause Evaluator has an implication to push"                  │ │
│  │                                                                    │ │
│  │  • push_var (9 bits)                                               │ │
│  │    Which variable is implied                                      │ │
│  │                                                                    │ │
│  │  • push_value (1 bit)                                              │ │
│  │    Assign TRUE or FALSE                                           │ │
│  │                                                                    │ │
│  │  • push_reason (13 bits)                                           │ │
│  │    Clause ID that caused this implication                         │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           │ (push_valid & ~fifo_full)                                   │
│           ▼                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                  ENTRY PACKING STAGE                               │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  Input signals                                                    │ │
│  │  push_var (9b) ──┐                                                │ │
│  │  push_value (1b) ├──→ [Packer]                                    │ │
│  │  push_reason (13b)──┘                                              │ │
│  │                                                                    │ │
│  │  Output: ImplicationEntry (23 bits)                               │ │
│  │  ┌──────────────────────────────────────────────┐                │ │
│  │  │ [8:0]        [9]         [22:10]             │                │ │
│  │  │ var_id    │ value      │ reason              │                │ │
│  │  │ (9 bits)  │ (1 bit)    │ (13 bits)           │                │ │
│  │  └──────────────────────────────────────────────┘                │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           │ fifo.w_payload = packed_entry                               │
│           │ fifo.w_valid = push_valid                                   │
│           ▼                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                     AMARANTH SYNCFIFO                              │ │
│  │              (Circular Buffer, 128 entries)                        │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │  WRITE PORT (Synchronous)                                   │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  fifo.w_valid ──────────→ "Entry arriving"                 │ │ │
│  │  │  fifo.w_payload (23b) ──→ "Entry data"                     │ │ │
│  │  │                                                              │ │ │
│  │  │  fifo.w_ready ←────────── "Can accept entry?"              │ │ │
���  │  │                           (0 if FIFO full)                  │ │ │
│  │  │                                                              │ │ │
│  │  │  Internal: wr_ptr advances on write                         │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │  FIFO MEMORY (128 entries × 23 bits)                        │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  Entry [0]:   [var_id] [val] [reason]                      │ │ │
│  │  │  Entry [1]:   [var_id] [val] [reason]                      │ │ │
│  │  │  ...                                                         │ │ │
│  │  │  Entry [127]: [var_id] [val] [reason]                      │ │ │
│  │  │                ▲                                             │ │ │
│  │  │                │ rd_ptr points here                          │ │ │
│  │  │                (head of queue)                               │ │ │
│  │  │                                                              │ │ │
│  │  │  wr_ptr: circular write pointer                             │ │ │
│  │  │  rd_ptr: circular read pointer                              │ │ │
│  │  │  count: how many entries currently stored                   │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  │  ┌──────────────────────────────────────────────────────────────┐ │ │
│  │  │  READ PORT (Combinational)                                  │ │ │
│  │  ├──────────────────────────────────────────────────────────────┤ │ │
│  │  │                                                              │ │ │
│  │  │  rd_ptr ──→ [Memory Array]                                  │ │ │
│  │  │                  │                                           │ │ │
│  │  │                  ▼                                           │ │ │
│  │  │  fifo.r_payload (23b) ← "Head entry data"                  │ │ │
│  │  │  fifo.r_valid ←─────── "Any data available?"               │ │ │
│  │  │                         (0 if FIFO empty)                   │ │ │
│  │  │                                                              │ │ │
│  │  │  fifo.r_ready (input) ← "Consumer acknowledges"            │ │ │
│  │  │                         (from pop_ready)                     │ │ │
│  │  │                                                              │ │ │
│  │  │  Internal: rd_ptr advances on read                          │ │ │
│  │  │                                                              │ │ │
│  │  └──────────────────────────────────────────────────────────────┘ │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           │ fifo.r_payload (23 bits)                                    │
│           ▼                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                  ENTRY UNPACKING STAGE                             │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  Input: ImplicationEntry (23 bits)                               │ │
│  │  ┌──────────────────────────────────────────────┐                │ │
│  │  │ [8:0]        [9]         [22:10]             │                │ │
│  │  │ var_id    │ value      │ reason              │                │ │
│  │  │ (9 bits)  │ (1 bit)    │ (13 bits)           │                │ │
│  │  └──────────────────────────────────────────────┘                │ │
│  │                      │                                             │ │
│  │                      ▼                                             │ │
│  │                 [Unpacker]                                         │ │
│  │                      │                                             │ │
│  │  Output signals:                                                  │ │
│  │  pop_var ←─────── extracted var_id                               │ │
│  │  pop_value ←────── extracted value                               │ │
│  │  pop_reason ←───── extracted reason                              │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           ▼                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │              OUTPUT INTERFACE (Pop Side)                           │ │
│  │              (to Software / BCP Controller)                        │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  • pop_valid (1 bit)                                               │ │
│  │    "FIFO has implication available" (fifo.r_valid)               │ │
│  │                                                                    │ │
│  │  • pop_var (9 bits)                                                │ │
│  │    Which variable should be assigned                              │ │
│  │                                                                    │ │
│  │  • pop_value (1 bit)                                               │ │
│  │    Value to assign (0=FALSE, 1=TRUE)                             │ │
│  │                                                                    │ │
│  │  • pop_reason (13 bits)                                            │ │
│  │    Clause ID that caused this implication                         │ │
│  │                                                                    │ │
│  │  ← pop_ready (1 bit)                                               │ │
│  │    "Consumer has processed this entry"                            │ │
│  │    (from downstream, triggers fifo.r_ready)                       │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│           │                                                              │
│           ▼                                                              │
│           (to software/BCP controller)                                  │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │              STATUS SIGNALS (Monitoring)                           │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  • fifo_empty ←─ ~fifo.r_valid                                    │ │
│  │    "No implications waiting"                                      │ │
│  │                                                                    │ │
│  │  • fifo_full ←─ ~fifo.w_ready                                     │ │
│  │    "FIFO cannot accept more implications"                         │ │
│  │    (backpressure signal to Clause Evaluator)                      │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘

"""

from amaranth import *
from amaranth.lib.fifo import SyncFIFO

from memory.assignment_memory import MAX_VARS
from memory.clause_memory import MAX_CLAUSES


# Entry layout: var_id + value + reason
VAR_ID_WIDTH = (MAX_VARS - 1).bit_length()
REASON_WIDTH = (MAX_CLAUSES - 1).bit_length()
ENTRY_WIDTH = VAR_ID_WIDTH + 1 + REASON_WIDTH

DEFAULT_FIFO_DEPTH = 128

#   How we arrived at 128

#   The bound comes entirely from MAX_WATCH_LEN = 100 in 
#   watch_list_memory.py — the physical capacity of the watch list
#   (occurrence list) memory, which allocates exactly 100 clause-ID
#   slots per literal:

#    clause_id_depth = num_literals * max_watch_len  (1024 × 100
#   entries)

#   In a single BCP round, the WLM reads at most watch_len entries for
#   the current false_lit, where watch_len ≤ MAX_WATCH_LEN = 100. Each
#   of those 100 clauses can produce at most 1 UNIT result. So 100 is
#   the hard ceiling on FIFO entries per round. 128 is just the next
#   power of 2 above that — clean alignment plus 28 slots of headroom.

#   There's also a subtlety: LENGTH_WIDTH = 7 means the length field is
#   7 bits (max 127 representable), but the memory only backs 100 slots.
#   So 128 covers even the length field's representable range.


class ImplicationFIFO(Elaboratable):
    """
    Implication FIFO.

    Buffers unit clause implications from the Clause Evaluator.
    Uses Amaranth's SyncFIFO for clean, minimal implementation.

    Parameters
    ----------
    fifo_depth : int
        Number of entries the FIFO can hold (default 128).

    Ports
    -----
    push_valid : Signal(), in
        Asserted by the Clause Evaluator to push an implication.
    push_var : Signal(range(MAX_VARS)), in
        Variable ID of the implied literal.
    push_value : Signal(), in
        Assigned value (0=FALSE, 1=TRUE).
    push_reason : Signal(range(MAX_CLAUSES)), in
        Clause ID that caused the implication.

    pop_valid : Signal(), out
        Asserted when the FIFO has data available to pop.
    pop_var : Signal(range(MAX_VARS)), out
        Variable ID at the head of the FIFO.
    pop_value : Signal(), out
        Value at the head of the FIFO.
    pop_reason : Signal(range(MAX_CLAUSES)), out
        Reason clause ID at the head of the FIFO.
    pop_ready : Signal(), in
        Asserted by the consumer to acknowledge and pop the head entry.

    fifo_empty : Signal(), out
        High when the FIFO contains no entries.
    fifo_full : Signal(), out
        High when the FIFO cannot accept more entries.
    """

    def __init__(self, fifo_depth=DEFAULT_FIFO_DEPTH):
        self.fifo_depth = fifo_depth

        # Push side (from Clause Evaluator)
        self.push_valid = Signal()
        self.push_var = Signal(range(MAX_VARS))
        self.push_value = Signal()
        self.push_reason = Signal(range(MAX_CLAUSES))

        # Pop side (to software)
        self.pop_valid = Signal()
        self.pop_var = Signal(range(MAX_VARS))
        self.pop_value = Signal()
        self.pop_reason = Signal(range(MAX_CLAUSES))
        self.pop_ready = Signal()

        # Status
        self.fifo_empty = Signal()
        self.fifo_full = Signal()

    def elaborate(self, platform):
        m = Module()

        # Instantiate SyncFIFO with packed entry width
        m.submodules.fifo = fifo = SyncFIFO(
            width=ENTRY_WIDTH,
            depth=self.fifo_depth,
        )

        # --- Push side (from Clause Evaluator) ---
        # Pack input signals into entry word
        push_entry = Cat(self.push_var, self.push_value, self.push_reason)

        m.d.comb += [
            # Drive FIFO write interface
            fifo.w_data.eq(push_entry),
            fifo.w_en.eq(self.push_valid),
        ]

        # --- Pop side (to software) ---
        # Unpack entry word to output signals
        m.d.comb += [
            self.pop_var.eq(fifo.r_data[0:VAR_ID_WIDTH]),
            self.pop_value.eq(fifo.r_data[VAR_ID_WIDTH]),
            self.pop_reason.eq(fifo.r_data[VAR_ID_WIDTH + 1:ENTRY_WIDTH]),
            # Drive FIFO read interface
            fifo.r_en.eq(self.pop_ready),
        ]

        # --- Status signals ---
        m.d.comb += [
            self.pop_valid.eq(fifo.r_rdy),
            self.fifo_empty.eq(~fifo.r_rdy),
            self.fifo_full.eq(~fifo.w_rdy),
        ]

        return m
