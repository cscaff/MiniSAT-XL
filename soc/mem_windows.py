"""
Wishbone write windows for the three shared on-chip memories.

ClauseMemoryWindow
    Base + clause_id * 16 (4 x 32-bit words per clause):
      word 0 (+0):  { 12'b0, size[2:0], sat_bit, lit0[15:0] }
                    bits [31:20]=0, bits [19:17]=size, bit [16]=sat_bit,
                    bits [15:0]=lit0
      word 1 (+4):  { lit2[15:0], lit1[15:0] }
      word 2 (+8):  { lit4[15:0], lit3[15:0] }
      word 3 (+12): write any value  ->  triggers wr_en pulse

AssignmentMemoryWindow
    Base + var_id * 4:
      data[1:0] = assignment value (0=UNASSIGNED, 1=FALSE, 2=TRUE)

OccurrenceListWindow  (alias for WatchListMemory)
    Base+0x00000 + lit * 4:          write list length (7 bits)
    Base+0x10000 + (lit*MAX_WL+idx)*4: write clause_id (13 bits)

All windows ACK immediately (zero wait states, write-only).
Reads return 0.
"""

from amaranth import *

from soc.wishbone import WishboneBus
from memory.clause_memory import LIT_WIDTH
from memory.watch_list_memory import MAX_WATCH_LEN, NUM_LITERALS


class ClauseMemoryWindow(Elaboratable):
    """
    Wishbone write window for ClauseMemory.

    The firmware writes 3 data words to offsets 0, 4, 8 within a clause
    slot (clause_id * 16), then writes word 3 to commit.

    Ports
    -----
    bus          : WishboneBus
    clause_wr_*  : connect to ClauseMemory / BCPAccelerator write port
    """

    def __init__(self, max_clauses):
        self.bus = WishboneBus(name="clause_win")

        self.clause_wr_addr    = Signal(range(max_clauses))
        self.clause_wr_sat_bit = Signal()
        self.clause_wr_size    = Signal(3)
        self.clause_wr_lit0    = Signal(LIT_WIDTH)
        self.clause_wr_lit1    = Signal(LIT_WIDTH)
        self.clause_wr_lit2    = Signal(LIT_WIDTH)
        self.clause_wr_lit3    = Signal(LIT_WIDTH)
        self.clause_wr_lit4    = Signal(LIT_WIDTH)
        self.clause_wr_en      = Signal()

    def elaborate(self, platform):
        m = Module()

        bus = self.bus
        # Bits [15:2] of word-address give clause_id (each clause = 4 words)
        clause_id = bus.adr[2:2 + self.clause_wr_addr.shape().width]
        word_off  = bus.adr[0:2]  # 0,1,2,3 within clause slot

        # Stage registers
        w0 = Signal(32)
        w1 = Signal(32)
        w2 = Signal(32)

        with m.If(bus.stb & bus.cyc & bus.we):
            with m.Switch(word_off):
                with m.Case(0):
                    m.d.sync += w0.eq(bus.dat_w)
                with m.Case(1):
                    m.d.sync += w1.eq(bus.dat_w)
                with m.Case(2):
                    m.d.sync += w2.eq(bus.dat_w)

        # Commit on word 3 write
        commit = Signal()
        m.d.comb += commit.eq(
            bus.stb & bus.cyc & bus.we & (word_off == 3)
        )

        m.d.comb += [
            self.clause_wr_addr.eq(clause_id),
            self.clause_wr_sat_bit.eq(w0[16]),
            self.clause_wr_size.eq(w0[17:20]),
            self.clause_wr_lit0.eq(w0[0:LIT_WIDTH]),
            self.clause_wr_lit1.eq(w1[0:LIT_WIDTH]),
            self.clause_wr_lit2.eq(w1[LIT_WIDTH:2 * LIT_WIDTH]),
            self.clause_wr_lit3.eq(w2[0:LIT_WIDTH]),
            self.clause_wr_lit4.eq(w2[LIT_WIDTH:2 * LIT_WIDTH]),
            self.clause_wr_en.eq(commit),
            bus.dat_r.eq(0),
            bus.ack.eq(bus.stb & bus.cyc),
        ]

        return m


class AssignmentMemoryWindow(Elaboratable):
    """
    Wishbone write window for AssignmentMemory.

    Address: word-offset = var_id  (bus.adr[0 .. max_vars-1])
    Data:    bits [1:0] = assignment value

    Ports
    -----
    bus           : WishboneBus
    assign_wr_*   : connect to AssignmentMemory / BCPAccelerator write port
    """

    def __init__(self, max_vars):
        self.bus = WishboneBus(name="assign_win")

        self.assign_wr_addr = Signal(range(max_vars))
        self.assign_wr_data = Signal(2)
        self.assign_wr_en   = Signal()

    def elaborate(self, platform):
        m = Module()

        bus = self.bus
        var_id = bus.adr[:self.assign_wr_addr.shape().width]

        m.d.comb += [
            self.assign_wr_addr.eq(var_id),
            self.assign_wr_data.eq(bus.dat_w[:2]),
            self.assign_wr_en.eq(bus.stb & bus.cyc & bus.we),
            bus.dat_r.eq(0),
            bus.ack.eq(bus.stb & bus.cyc),
        ]

        return m


class OccurrenceListWindow(Elaboratable):
    """
    Wishbone write window for WatchListMemory (repurposed as occurrence lists).

    Two sub-regions within the window (split by bit 16 of byte address):
      Lower half (bit16=0): length table
        word addr = lit  →  wr_len for that literal
      Upper half (bit16=1): clause-id table
        word addr = lit * MAX_WATCH_LEN + idx  →  wr_data for that entry

    Ports
    -----
    bus           : WishboneBus
    wl_wr_*       : connect to WatchListMemory / BCPAccelerator write port
    """

    def __init__(self, num_literals=NUM_LITERALS, max_watch_len=MAX_WATCH_LEN):
        self.num_literals  = num_literals
        self.max_watch_len = max_watch_len

        self.bus = WishboneBus(name="occ_win")

        self.wl_wr_lit    = Signal(range(num_literals))
        self.wl_wr_idx    = Signal(range(max_watch_len))
        self.wl_wr_data   = Signal(13)  # CLAUSE_ID_WIDTH
        self.wl_wr_len    = Signal(7)   # LENGTH_WIDTH
        self.wl_wr_en     = Signal()
        self.wl_wr_len_en = Signal()

    def elaborate(self, platform):
        m = Module()

        bus = self.bus

        # bit 14 of word address distinguishes the two sub-regions
        # (0x10000 bytes = 0x4000 words → bit14 of word addr)
        region = bus.adr[14]

        lit_bits = (self.num_literals - 1).bit_length()
        idx_bits = (self.max_watch_len - 1).bit_length()

        with m.If(~region):
            # Length table: word addr = lit
            m.d.comb += [
                self.wl_wr_lit.eq(bus.adr[:lit_bits]),
                self.wl_wr_len.eq(bus.dat_w[:7]),
                self.wl_wr_len_en.eq(bus.stb & bus.cyc & bus.we),
                self.wl_wr_en.eq(0),
                self.wl_wr_idx.eq(0),
                self.wl_wr_data.eq(0),
            ]
        with m.Else():
            # Clause-id table: word addr = lit * max_watch_len + idx
            flat = bus.adr[:lit_bits + idx_bits]
            m.d.comb += [
                self.wl_wr_lit.eq(flat[idx_bits:idx_bits + lit_bits]),
                self.wl_wr_idx.eq(flat[:idx_bits]),
                self.wl_wr_data.eq(bus.dat_w[:13]),
                self.wl_wr_en.eq(bus.stb & bus.cyc & bus.we),
                self.wl_wr_len_en.eq(0),
                self.wl_wr_len.eq(0),
            ]

        m.d.comb += [
            bus.dat_r.eq(0),
            bus.ack.eq(bus.stb & bus.cyc),
        ]

        return m
