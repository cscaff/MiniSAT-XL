"""
Variable Assignment Memory Module for the BCP Accelerator.

Stores the current assignment state (UNASSIGNED, FALSE, TRUE) for each variable.
Used by the Clause Evaluator to determine literal truth values during BCP.

See: Hardware Description/BCP_Accelerator_System_Architecture.md, Memory Module 3

┌──────────────────────────────────────────────────────────────────────┐
│              VARIABLE ASSIGNMENT MEMORY MODULE                       │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    MEMORY CONFIGURATION                        │ │
│  ├────────────────────────────────────────────────────────────────┤ │
│  │  • Depth: max_vars (default 512)                              │ │
│  │  • Width: 2 bits per entry                                    │ │
│  │  • Init: All entries start as UNASSIGNED (0)                  │ │
│  │                                                               │ │
│  │  Entry Values:                                                │ │
│  │  ┌─────────────────────────────────────┐                     │ │
│  │  │ 00 (0) = UNASSIGNED                 │                     │ │
│  │  │ 01 (1) = FALSE                      │                     │ │
│  │  │ 10 (2) = TRUE                       │                     │ │
│  │  │ 11 (3) = [unused]                   │                     │ │
│  │  └─────────────────────────────────────┘                     │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────┐   ┌──────────────────────────────┐    │
│  │   READ PORT (comb)       │   │   WRITE PORT (sync)          │    │
│  │   (Clause Evaluator)     │   │   (Software / BCP Engine)    │    │
│  ├──────────────────────────┤   ├──────────────────────────────┤    │
│  │ Input:                   │   │ Inputs:                      │    │
│  │ • rd_addr (var ID)       │   │ • wr_addr (var ID)           │    │
│  │                          │   │ • wr_data (0/1/2)           │    │
│  │ Output:                  │   │ • wr_en (write enable)       │    │
│  │ • rd_data (assignment)   │   │                              │    │
│  │   [0=UNASSIGNED,         │   │ Behavior:                    │    │
│  │    1=FALSE,              │   │ • Updates on clock edge      │    │
│  │    2=TRUE]               │   │ • wr_en must be high         │    │
│  │                          │   │ • One cycle latency          │    │
│  │ Latency: Combinational   │   │                              │    │
│  │ (single-cycle reads)     │   │                              │    │
│  └──────────────────────────┘   └──────────────────────────────┘    │
│         │                                  │                        │
│         │                                  │                        │
│         ▼                                  ▼                        │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                   DUAL-PORT MEMORY (2 bits × 512)             │  │
│  │                                                               │  │
│  │  Address Range: [0 ... max_vars-1]                            │  │
│  │                                                               │  │
│  │  ┌─────────────────────────────────────────────┐              │  │
│  │  │ VAR_0:  [0]  UNASSIGNED / FALSE / TRUE      │              │  │
│  │  │ VAR_1:  [0]  UNASSIGNED / FALSE / TRUE      │              │  │
│  │  │ VAR_2:  [0]  UNASSIGNED / FALSE / TRUE      │              │  │
│  │  │ ...                                         │              │  │
│  │  │ VAR_511:[0]  UNASSIGNED / FALSE / TRUE      │              │  │
│  │  └─────────────────────────────────────────────┘              │  │
│  │                                                               │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │                                  │
         │ rd_data (2-bit)                  │ wr_addr, wr_data, wr_en
         ▼                                  ▼
    ┌─────────────┐                  ┌──────────────────┐
    │   CLAUSE    │                  │  BCP / SOFTWARE  │
    │ EVALUATOR   │                  │  CONTROLLER      │
    │  (Reader)   │                  │  (Writer)        │
    └─────────────┘                  └──────────────────┘

"""

from amaranth import *
from amaranth.lib.memory import Memory


# Assignment encoding constants
UNASSIGNED = 0
FALSE = 1
TRUE = 2

# Default configuration
MAX_VARS = 512


class AssignmentMemory(Elaboratable):
    """
    Variable Assignment Memory.

    Parameters
    ----------
    max_vars : int
        Maximum number of variables (default 512).

    Ports
    -----
    rd_addr : Signal(range(max_vars)), in
        Variable ID to read.
    rd_data : Signal(2), out
        Assignment value for the addressed variable (0=UNASSIGNED, 1=FALSE, 2=TRUE).
    wr_addr : Signal(range(max_vars)), in
        Variable ID to write.
    wr_data : Signal(2), in
        Assignment value to write.
    wr_en : Signal(), in
        Write enable.
    """

    def __init__(self, max_vars=MAX_VARS):
        self.max_vars = max_vars

        # Read port (to Clause Evaluator)
        self.rd_addr = Signal(range(max_vars))
        self.rd_data = Signal(2)

        # Write port (from software when variables are assigned)
        self.wr_addr = Signal(range(max_vars))
        self.wr_data = Signal(2)
        self.wr_en = Signal()

    def elaborate(self, platform):
        m = Module()

        # Instantiate the memory: 2-bit entries, one per variable
        m.submodules.mem = mem = Memory(
            shape=2, depth=self.max_vars, init=[]
        )

        # Read port - combinational (transparent) for single-cycle reads
        rd_port = mem.read_port(domain="comb")
        m.d.comb += [
            rd_port.addr.eq(self.rd_addr),
            self.rd_data.eq(rd_port.data),
        ]

        # Write port - synchronous
        wr_port = mem.write_port()
        m.d.comb += [
            wr_port.addr.eq(self.wr_addr),
            wr_port.data.eq(self.wr_data),
            wr_port.en.eq(self.wr_en),
        ]

        return m