"""
Wishbone-connected firmware RAM.

Single-port synchronous SRAM mapped on a Wishbone slave port.
Byte enables (sel) are respected for writes.

Parameters
----------
depth_words : int
    Number of 32-bit words (default 16384 = 64 KB).
init : list of int
    Optional initial word values.
"""

from amaranth import *
from amaranth.lib.memory import Memory

from soc.wishbone import WishboneBus

DEFAULT_DEPTH = 16384  # 64 KB


class FirmwareRAM(Elaboratable):
    """
    Wishbone slave firmware RAM.

    Memory map: slave is addressed in words via adr[0 .. depth-1].
    Writes respect byte-enables (sel[3:0]).
    Reads return data the same cycle ACK is asserted (registered output
    = 1-cycle read latency, ACK issued next cycle after STB).
    """

    def __init__(self, depth_words=DEFAULT_DEPTH, init=None):
        self.depth_words = depth_words
        self.init = init or []

        self.bus = WishboneBus(name="fw_ram")

    def elaborate(self, platform):
        m = Module()

        # 32-bit wide, depth_words deep
        m.submodules.mem = mem = Memory(
            shape=32, depth=self.depth_words, init=self.init
        )

        # Local word address (strip upper bits from decoded adr)
        addr_bits = (self.depth_words - 1).bit_length()
        local_addr = Signal(addr_bits)
        m.d.comb += local_addr.eq(self.bus.adr[:addr_bits])

        # Write port (byte enables)
        wr_port = mem.write_port(granularity=8)
        m.d.comb += [
            wr_port.addr.eq(local_addr),
            wr_port.data.eq(self.bus.dat_w),
            wr_port.en.eq(
                Repl(self.bus.stb & self.bus.cyc & self.bus.we, 4) & self.bus.sel
            ),
        ]

        # Read port (synchronous 1-cycle)
        rd_port = mem.read_port(domain="sync")
        m.d.comb += [
            rd_port.addr.eq(local_addr),
            rd_port.en.eq(self.bus.stb & self.bus.cyc & ~self.bus.we),
        ]

        # Pipeline ACK one cycle after STB for reads; same-cycle for writes
        ack_r = Signal()
        m.d.sync += ack_r.eq(
            self.bus.stb & self.bus.cyc & ~self.bus.we & ~ack_r
        )

        m.d.comb += [
            self.bus.dat_r.eq(rd_port.data),
            # Writes ACK immediately; reads ACK after 1 cycle
            self.bus.ack.eq(
                (self.bus.stb & self.bus.cyc & self.bus.we) | ack_r
            ),
        ]

        return m
