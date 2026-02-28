"""
Wishbone-mapped Control/Status Registers for the BCP Accelerator.

Memory map (byte offsets, 4-byte registers):
  +0x00  control  (W)  bit[0]=start, bit[1]=conflict_ack
  +0x04  false_lit(W)  literal that became false
  +0x08  status   (R)  bit[0]=busy, bit[1]=done, bit[2]=conflict
  +0x0C  cc_id    (R)  conflict_clause_id
  +0x10  impl     (R)  pop on read: [12:0]=var, [13]=value,
                        [26:14]=reason, [31]=valid
  +0x14  result   (RW) firmware writes 1=SAT, 2=UNSAT; testbench reads

All registers ACK immediately (combinational).
"""

from amaranth import *

from soc.wishbone import WishboneBus

# Register word offsets
REG_CONTROL  = 0
REG_FALSE_LIT = 1
REG_STATUS   = 2
REG_CC_ID    = 3
REG_IMPL     = 4
REG_RESULT   = 5


class BcpCsrBlock(Elaboratable):
    """
    Wishbone CSR block bridging the Wishbone bus to BCPAccelerator ports.

    The caller (SoC) must connect the *_accel_* signals to the
    corresponding BCPAccelerator signals.

    Ports -- accelerator control (connect to BCPAccelerator)
    ---------------------------------------------------------
    accel_start          : Signal(), out
    accel_false_lit      : Signal(), out
    accel_busy           : Signal(), in
    accel_done           : Signal(), in
    accel_conflict       : Signal(), in
    accel_conflict_ack   : Signal(), out
    accel_conflict_cid   : Signal(), in
    accel_impl_valid     : Signal(), in
    accel_impl_var       : Signal(), in
    accel_impl_value     : Signal(), in
    accel_impl_reason    : Signal(), in
    accel_impl_ready     : Signal(), out

    Ports -- result register (readable by testbench)
    ------------------------------------------------
    result : Signal(2), out   -- 0=running, 1=SAT, 2=UNSAT
    """

    def __init__(self, lit_width, var_width, cid_width):
        """
        Parameters
        ----------
        lit_width : int   Bit width of false_lit / impl_reason signals.
        var_width : int   Bit width of impl_var.
        cid_width : int   Bit width of conflict_clause_id.
        """
        self.bus = WishboneBus(name="bcp_csr")

        # Accelerator control connections
        self.accel_start        = Signal()
        self.accel_false_lit    = Signal(lit_width)
        self.accel_busy         = Signal()
        self.accel_done         = Signal()
        self.accel_conflict     = Signal()
        self.accel_conflict_ack = Signal()
        self.accel_conflict_cid = Signal(cid_width)
        self.accel_impl_valid   = Signal()
        self.accel_impl_var     = Signal(var_width)
        self.accel_impl_value   = Signal()
        self.accel_impl_reason  = Signal(cid_width)
        self.accel_impl_ready   = Signal()

        # Readable result register
        self.result = Signal(2)

    def elaborate(self, platform):
        m = Module()

        bus = self.bus
        reg_sel = bus.adr[0:3]  # lower 3 bits = word offset within the 6-reg window

        # Registered false_lit (written by firmware)
        false_lit_reg = Signal.like(self.accel_false_lit)

        # Result register
        result_reg = Signal(2)
        m.d.comb += self.result.eq(result_reg)

        # Pulsed signals (combinational, high for one cycle)
        start_pulse    = Signal()
        conf_ack_pulse = Signal()
        impl_pop       = Signal()

        # Default combinational outputs
        m.d.comb += [
            self.accel_start.eq(start_pulse),
            self.accel_false_lit.eq(false_lit_reg),
            self.accel_conflict_ack.eq(conf_ack_pulse),
            self.accel_impl_ready.eq(impl_pop),
        ]

        # Write handling
        with m.If(bus.stb & bus.cyc & bus.we):
            with m.Switch(reg_sel):
                with m.Case(REG_CONTROL):
                    m.d.comb += [
                        start_pulse.eq(bus.dat_w[0]),
                        conf_ack_pulse.eq(bus.dat_w[1]),
                    ]
                with m.Case(REG_FALSE_LIT):
                    m.d.sync += false_lit_reg.eq(bus.dat_w[:false_lit_reg.shape().width])
                with m.Case(REG_RESULT):
                    m.d.sync += result_reg.eq(bus.dat_w[:2])

        # Read handling + impl pop
        impl_word = Signal(32)
        m.d.comb += impl_word.eq(Cat(
            self.accel_impl_var,
            self.accel_impl_value,
            self.accel_impl_reason,
            Repl(0, 32 - 1
                 - self.accel_impl_var.shape().width
                 - self.accel_impl_reason.shape().width),
            self.accel_impl_valid,
        ))

        status_word = Signal(32)
        m.d.comb += status_word.eq(Cat(
            self.accel_busy,
            self.accel_done,
            self.accel_conflict,
        ))

        dat_r = Signal(32)
        with m.Switch(reg_sel):
            with m.Case(REG_STATUS):
                m.d.comb += dat_r.eq(status_word)
            with m.Case(REG_CC_ID):
                m.d.comb += dat_r.eq(self.accel_conflict_cid)
            with m.Case(REG_IMPL):
                m.d.comb += dat_r.eq(impl_word)
                # Pop implication on read
                m.d.comb += impl_pop.eq(
                    bus.stb & bus.cyc & ~bus.we & self.accel_impl_valid
                )
            with m.Case(REG_RESULT):
                m.d.comb += dat_r.eq(result_reg)
            with m.Default():
                m.d.comb += dat_r.eq(0)

        m.d.comb += [
            bus.dat_r.eq(dat_r),
            bus.ack.eq(bus.stb & bus.cyc),  # zero wait states
        ]

        return m
