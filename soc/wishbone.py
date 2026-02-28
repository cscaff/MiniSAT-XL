"""
Minimal Wishbone B4 bus definitions and simple address-decoder interconnect.

Supports a single 32-bit master connected to N slaves.
All slaves respond in zero wait states (ACK same cycle as STB/CYC).

Signal bundle (master perspective, 30-bit word address):
  adr   : 30-bit word address  (byte_addr >> 2)
  dat_w : 32-bit write data
  dat_r : 32-bit read data
  we    :  1-bit write enable
  sel   :  4-bit byte select
  stb   :  1-bit strobe
  cyc   :  1-bit cycle
  ack   :  1-bit acknowledge
"""

from amaranth import *


class WishboneBus:
    """Signal bundle for one Wishbone master or slave port."""

    def __init__(self, name="wb"):
        self.adr   = Signal(30, name=f"{name}_adr")
        self.dat_w = Signal(32, name=f"{name}_dat_w")
        self.dat_r = Signal(32, name=f"{name}_dat_r")
        self.we    = Signal(name=f"{name}_we")
        self.sel   = Signal(4,  name=f"{name}_sel")
        self.stb   = Signal(name=f"{name}_stb")
        self.cyc   = Signal(name=f"{name}_cyc")
        self.ack   = Signal(name=f"{name}_ack")


class WishboneDecoder(Elaboratable):
    """
    Simple Wishbone address decoder (1 master, N slaves).

    Each slave is described by a (base, size) pair where both are byte-aligned
    power-of-two values.  The decoder selects the slave whose window contains
    the current master address and forwards all bus signals.

    Parameters
    ----------
    master : WishboneBus
        The single master port.
    slaves : list of (WishboneBus, int base, int size)
        Each entry is a tuple of (slave_bus, byte_base, byte_size).
    """

    def __init__(self, master: WishboneBus, slaves):
        self.master = master
        self.slaves = slaves  # [(bus, base, size), ...]

    def elaborate(self, platform):
        m = Module()
        master = self.master

        # Default: master ack = OR of all slave acks; dat_r = mux of slave dat_r
        combined_ack  = Signal()
        combined_datr = Signal(32)

        # Build per-slave select and wiring
        sel_sigs = []
        for i, (sl_bus, base, size) in enumerate(self.slaves):
            # Word address comparison: upper bits decide the slave
            # byte_base >> 2 gives word base; mask = ~((size >> 2) - 1)
            word_base = base >> 2
            word_mask = ~((size >> 2) - 1) & 0x3FFF_FFFF

            sel = Signal(name=f"wb_sel_{i}")
            m.d.comb += sel.eq((master.adr & word_mask) == (word_base & word_mask))
            sel_sigs.append(sel)

            # Route master -> slave
            m.d.comb += [
                sl_bus.adr.eq(master.adr),
                sl_bus.dat_w.eq(master.dat_w),
                sl_bus.we.eq(master.we),
                sl_bus.sel.eq(master.sel),
                sl_bus.cyc.eq(master.cyc),
                sl_bus.stb.eq(master.stb & sel),
            ]

            # Accumulate ack and read-data
            with m.If(sel):
                m.d.comb += combined_datr.eq(sl_bus.dat_r)
                m.d.comb += combined_ack.eq(sl_bus.ack)

        m.d.comb += [
            master.dat_r.eq(combined_datr),
            master.ack.eq(combined_ack),
        ]

        return m
