"""
BCP hardware simulation bridge for MiniSAT.

Embeds an Amaranth simulation of the BCPAccelerator and exposes a
synchronous Python API callable from C++ via the CPython API.
"""

import os
import sys
import queue
import threading

from amaranth.sim import Simulator

# Ensure hardware sources are importable
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from top import BCPAccelerator  # noqa: E402
from memory.assignment_memory import UNASSIGNED, FALSE, TRUE, MAX_VARS  # noqa: E402
from memory.watch_list_memory import NUM_LITERALS, MAX_WATCH_LEN  # noqa: E402
from memory.clause_memory import MAX_CLAUSES  # noqa: E402


class _BCPSim:
    def __init__(self):
        self._cmd_q = queue.Queue()
        self._resp_q = queue.Queue()
        self._dut = BCPAccelerator()
        self._sim = Simulator(self._dut)
        self._sim.add_clock(1e-8)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        self._initialized = False
        self._num_vars = 0
        self._occurrence = {lit: [] for lit in range(NUM_LITERALS)}
        self._clauses = {}

    def _run(self):
        dut = self._dut

        async def testbench(ctx):
            while True:
                cmd = self._cmd_q.get()
                cmd_type = cmd["type"]
                if cmd_type == "shutdown":
                    self._resp_q.put(True)
                    return
                if cmd_type == "write_clause":
                    await self._write_clause(ctx, dut, cmd["clause_id"], cmd["size"],
                                             cmd["sat_bit"], cmd["lits"])
                    self._resp_q.put(True)
                elif cmd_type == "write_watch_list":
                    await self._write_watch_list(ctx, dut, cmd["lit"], cmd["clause_ids"])
                    self._resp_q.put(True)
                elif cmd_type == "write_assign":
                    await self._write_assign(ctx, dut, cmd["var"], cmd["val"])
                    self._resp_q.put(True)
                elif cmd_type == "run_bcp":
                    result = await self._run_bcp(ctx, dut, cmd["false_lit"])
                    self._resp_q.put(result)
                else:
                    raise ValueError(f"Unknown command: {cmd_type}")

        self._sim.add_testbench(testbench)
        self._sim.run()

    def _exec(self, cmd):
        self._cmd_q.put(cmd)
        return self._resp_q.get()

    @staticmethod
    async def _write_clause(ctx, dut, clause_id, size, sat_bit, lits):
        ctx.set(dut.clause_wr_addr, clause_id)
        ctx.set(dut.clause_wr_sat_bit, sat_bit)
        ctx.set(dut.clause_wr_size, size)
        ctx.set(dut.clause_wr_lit0, lits[0] if len(lits) > 0 else 0)
        ctx.set(dut.clause_wr_lit1, lits[1] if len(lits) > 1 else 0)
        ctx.set(dut.clause_wr_lit2, lits[2] if len(lits) > 2 else 0)
        ctx.set(dut.clause_wr_lit3, lits[3] if len(lits) > 3 else 0)
        ctx.set(dut.clause_wr_lit4, lits[4] if len(lits) > 4 else 0)
        ctx.set(dut.clause_wr_en, 1)
        await ctx.tick()
        ctx.set(dut.clause_wr_en, 0)

    @staticmethod
    async def _write_watch_list(ctx, dut, lit_code, clause_ids):
        ctx.set(dut.wl_wr_lit, lit_code)
        ctx.set(dut.wl_wr_len, len(clause_ids))
        ctx.set(dut.wl_wr_len_en, 1)
        await ctx.tick()
        ctx.set(dut.wl_wr_len_en, 0)
        for idx, cid in enumerate(clause_ids):
            ctx.set(dut.wl_wr_lit, lit_code)
            ctx.set(dut.wl_wr_idx, idx)
            ctx.set(dut.wl_wr_data, cid)
            ctx.set(dut.wl_wr_en, 1)
            await ctx.tick()
            ctx.set(dut.wl_wr_en, 0)

    @staticmethod
    async def _write_assign(ctx, dut, var, hw_val):
        ctx.set(dut.assign_wr_addr, var)
        ctx.set(dut.assign_wr_data, hw_val)
        ctx.set(dut.assign_wr_en, 1)
        await ctx.tick()
        ctx.set(dut.assign_wr_en, 0)

    @staticmethod
    async def _start_bcp(ctx, dut, false_lit):
        ctx.set(dut.false_lit, false_lit)
        ctx.set(dut.start, 1)
        await ctx.tick()
        ctx.set(dut.start, 0)

    @staticmethod
    async def _wait_done(ctx, dut, max_cycles=10000):
        for _ in range(max_cycles):
            if ctx.get(dut.done):
                return
            await ctx.tick()
        raise RuntimeError(f"BCP timed out after {max_cycles} cycles")

    @staticmethod
    async def _pop_implication(ctx, dut):
        var = ctx.get(dut.impl_var)
        value = ctx.get(dut.impl_value)
        reason = ctx.get(dut.impl_reason)
        ctx.set(dut.impl_ready, 1)
        await ctx.tick()
        ctx.set(dut.impl_ready, 0)
        return var, value, reason

    async def _run_bcp(self, ctx, dut, false_lit):
        await self._start_bcp(ctx, dut, false_lit)
        await self._wait_done(ctx, dut)

        conflict_cid = -1
        if ctx.get(dut.conflict):
            conflict_cid = ctx.get(dut.conflict_clause_id)
            ctx.set(dut.conflict_ack, 1)
            await ctx.tick()
            ctx.set(dut.conflict_ack, 0)
            await ctx.tick()  # DONE -> IDLE

        # Drain implications
        implications = []
        while ctx.get(dut.impl_valid):
            var, value, reason = await self._pop_implication(ctx, dut)
            implications.append((var, value, reason))

        if conflict_cid < 0:
            await ctx.tick()  # DONE -> IDLE

        return {"conflict": conflict_cid, "implications": implications}

    def init(self, num_vars):
        if self._initialized:
            raise RuntimeError("BCP simulation already initialized")
        if num_vars > MAX_VARS:
            raise ValueError(f"num_vars {num_vars} exceeds MAX_VARS {MAX_VARS}")
        self._num_vars = num_vars
        self._initialized = True

    def add_clause(self, clause_id, lits):
        if not self._initialized:
            raise RuntimeError("BCP simulation not initialized")
        if clause_id >= MAX_CLAUSES:
            raise ValueError(f"clause_id {clause_id} exceeds MAX_CLAUSES {MAX_CLAUSES}")
        if len(lits) > 5:
            raise ValueError("Clause size exceeds MAX_K=5")
        for lit in lits:
            if not (0 <= lit < NUM_LITERALS):
                raise ValueError(f"Literal {lit} out of range")

        size = len(lits)
        self._clauses[clause_id] = list(lits)
        self._exec({
            "type": "write_clause",
            "clause_id": clause_id,
            "size": size,
            "sat_bit": 0,
            "lits": lits,
        })

        for lit in lits:
            occ = self._occurrence[lit]
            occ.append(clause_id)
            if len(occ) > MAX_WATCH_LEN:
                raise ValueError(
                    f"Watch list for literal {lit} exceeds MAX_WATCH_LEN {MAX_WATCH_LEN}"
                )
            self._exec({
                "type": "write_watch_list",
                "lit": lit,
                "clause_ids": list(occ),
            })

    def disable_clause(self, clause_id):
        if not self._initialized:
            raise RuntimeError("BCP simulation not initialized")
        if clause_id not in self._clauses:
            raise ValueError(f"Unknown clause_id {clause_id}")
        lits = self._clauses[clause_id]
        self._exec({
            "type": "write_clause",
            "clause_id": clause_id,
            "size": len(lits),
            "sat_bit": 1,
            "lits": lits,
        })

    def set_assignment(self, var, val):
        if not self._initialized:
            raise RuntimeError("BCP simulation not initialized")
        if not (0 <= var < MAX_VARS):
            raise ValueError(f"var {var} out of range")
        if val not in (UNASSIGNED, FALSE, TRUE):
            raise ValueError(f"Invalid assignment value {val}")
        self._exec({"type": "write_assign", "var": var, "val": val})

    def run_bcp(self, false_lit):
        if not self._initialized:
            raise RuntimeError("BCP simulation not initialized")
        if not (0 <= false_lit < NUM_LITERALS):
            raise ValueError(f"false_lit {false_lit} out of range")
        return self._exec({"type": "run_bcp", "false_lit": false_lit})

    def shutdown(self):
        self._exec({"type": "shutdown"})


_bridge = _BCPSim()


def init(num_vars):
    _bridge.init(num_vars)


def add_clause(clause_id, lits):
    _bridge.add_clause(clause_id, lits)


def set_assignment(var, val):
    _bridge.set_assignment(var, val)


def run_bcp(false_lit):
    return _bridge.run_bcp(false_lit)


def disable_clause(clause_id):
    _bridge.disable_clause(clause_id)


def shutdown():
    _bridge.shutdown()
