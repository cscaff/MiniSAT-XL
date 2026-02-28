"""
PicoRV32 Verilog Instance wrapper and native-to-Wishbone bridge.

PicoRV32 native memory interface:
  mem_valid  : CPU asserts to request a transaction
  mem_ready  : peripheral asserts to acknowledge
  mem_addr   : 32-bit byte address
  mem_wdata  : 32-bit write data
  mem_wstrb  : 4-bit byte write strobes (0 = read)
  mem_rdata  : 32-bit read data

This bridge converts the native interface to a Wishbone master.
The PicoRV32 Verilog is expected in rtl/picorv32.v.
"""

from amaranth import *

from soc.wishbone import WishboneBus


class PicoRV32Bridge(Elaboratable):
    """
    Wraps PicoRV32 and bridges its native memory port to a Wishbone master.

    Parameters
    ----------
    firmware_init : list of int
        Initial memory words for the firmware RAM (passed through to FirmwareRAM).
    reset_vector : int
        Reset vector address (default 0x00000000).
    """

    def __init__(self, reset_vector=0x0000_0000):
        self.reset_vector = reset_vector
        self.wb = WishboneBus(name="cpu")

    def elaborate(self, platform):
        m = Module()

        # PicoRV32 native interface signals
        mem_valid = Signal()
        mem_ready = Signal()
        mem_addr  = Signal(32)
        mem_wdata = Signal(32)
        mem_wstrb = Signal(4)
        mem_rdata = Signal(32)

        # Instantiate PicoRV32 (Verilog under rtl/picorv32.v)
        m.submodules.picorv32 = Instance(
            "picorv32",
            p_ENABLE_REGS_16_31  = 1,
            p_ENABLE_MUL         = 0,
            p_ENABLE_DIV         = 0,
            p_ENABLE_IRQ         = 0,
            p_ENABLE_TRACE       = 0,
            p_PROGADDR_RESET     = self.reset_vector,
            i_clk    = ClockSignal(),
            i_resetn = ~ResetSignal(),
            o_mem_valid = mem_valid,
            i_mem_ready = mem_ready,
            o_mem_addr  = mem_addr,
            o_mem_wdata = mem_wdata,
            o_mem_wstrb = mem_wstrb,
            i_mem_rdata = mem_rdata,
        )

        wb = self.wb

        # Transaction in flight
        txn_active = Signal()

        # Write-enable: any non-zero byte strobe means write
        is_write = Signal()
        m.d.comb += is_write.eq(mem_wstrb != 0)

        with m.If(~txn_active):
            with m.If(mem_valid):
                m.d.comb += [
                    wb.adr.eq(mem_addr[2:]),
                    wb.dat_w.eq(mem_wdata),
                    wb.we.eq(is_write),
                    wb.sel.eq(Mux(is_write, mem_wstrb, 0xF)),
                    wb.stb.eq(1),
                    wb.cyc.eq(1),
                ]
                with m.If(wb.ack):
                    m.d.comb += mem_ready.eq(1)
                    m.d.comb += mem_rdata.eq(wb.dat_r)
                with m.Else():
                    m.d.sync += txn_active.eq(1)
        with m.Else():
            m.d.comb += [
                wb.adr.eq(mem_addr[2:]),
                wb.dat_w.eq(mem_wdata),
                wb.we.eq(is_write),
                wb.sel.eq(Mux(is_write, mem_wstrb, 0xF)),
                wb.stb.eq(1),
                wb.cyc.eq(1),
            ]
            with m.If(wb.ack):
                m.d.comb += [
                    mem_ready.eq(1),
                    mem_rdata.eq(wb.dat_r),
                ]
                m.d.sync += txn_active.eq(0)

        return m
