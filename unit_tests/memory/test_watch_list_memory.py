"""
Testbench for the Watch List Memory module.

Verifies:
  1. Default reads return 0 (length=0, clause_id=0).
  2. Write a length and clause IDs for one literal, read back after 2 cycles.
  3. Write watch lists for multiple literals with distinct data, read each back.
  4. Overwrite a watch list entry and verify update.
  5. Verify the spec example content (literal encodings and their watch lists).
"""

import os
import sys

# Add src/ to the path so we can import the module
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from amaranth.sim import Simulator

from memory.watch_list_memory import WatchListMemory


def test_watch_list_memory():
    dut = WatchListMemory(num_literals=1024, max_watch_len=100)
    sim = Simulator(dut)
    sim.add_clock(1e-8)  # 100 MHz

    async def testbench(ctx):
        async def read_watch(lit, idx):
            ctx.set(dut.rd_lit, lit)
            ctx.set(dut.rd_idx, idx)
            ctx.set(dut.rd_en, 1)
            await ctx.tick()
            ctx.set(dut.rd_en, 0)
            await ctx.tick()
            valid = ctx.get(dut.rd_valid)
            assert valid == 1, "rd_valid not asserted after 2-cycle read"
            return {
                "len": ctx.get(dut.rd_len),
                "data": ctx.get(dut.rd_data),
            }

        async def write_clause_id(lit, idx, clause_id):
            ctx.set(dut.wr_lit, lit)
            ctx.set(dut.wr_idx, idx)
            ctx.set(dut.wr_data, clause_id)
            ctx.set(dut.wr_en, 1)
            await ctx.tick()
            ctx.set(dut.wr_en, 0)

        async def write_length(lit, length):
            ctx.set(dut.wr_lit, lit)
            ctx.set(dut.wr_len, length)
            ctx.set(dut.wr_len_en, 1)
            await ctx.tick()
            ctx.set(dut.wr_len_en, 0)

        # ---- Test 1: Default reads return 0 ----
        for lit in [0, 1, 100, 1023]:
            d = await read_watch(lit, 0)
            assert d["len"] == 0, f"Test 1 FAIL: lit {lit} len != 0"
            assert d["data"] == 0, f"Test 1 FAIL: lit {lit} data != 0"
        print("Test 1 PASSED: Default reads return all zeros.")

        # ---- Test 2: Write a length and clause IDs for one literal ----
        await write_length(2, 3)
        await write_clause_id(2, 0, 0)
        await write_clause_id(2, 1, 2)
        await write_clause_id(2, 2, 4)

        d = await read_watch(2, 0)
        assert d["len"] == 3, f"Test 2 FAIL: len expected 3, got {d['len']}"
        assert d["data"] == 0, f"Test 2 FAIL: clause_id[0] expected 0, got {d['data']}"

        d = await read_watch(2, 1)
        assert d["data"] == 2, f"Test 2 FAIL: clause_id[1] expected 2, got {d['data']}"

        d = await read_watch(2, 2)
        assert d["data"] == 4, f"Test 2 FAIL: clause_id[2] expected 4, got {d['data']}"
        print("Test 2 PASSED: Write and read back a single literal's watch list.")

        # ---- Test 3: Write watch lists for multiple literals ----
        watch_lists = {
            3:  (1, [1]),
            4:  (1, [0]),
            5:  (1, [2]),
            6:  (2, [0, 3]),
            8:  (1, [1]),
            9:  (1, [2]),
            10: (1, [2]),
            11: (1, [3]),
        }

        for lit, (length, cids) in watch_lists.items():
            await write_length(lit, length)
            for idx, cid in enumerate(cids):
                await write_clause_id(lit, idx, cid)

        for lit, (length, cids) in watch_lists.items():
            d = await read_watch(lit, 0)
            assert d["len"] == length, (
                f"Test 3 FAIL: lit {lit} len expected {length}, got {d['len']}"
            )
            for idx, expected_cid in enumerate(cids):
                d = await read_watch(lit, idx)
                assert d["data"] == expected_cid, (
                    f"Test 3 FAIL: lit {lit} clause_id[{idx}] expected {expected_cid}, got {d['data']}"
                )
        print("Test 3 PASSED: Multiple literals with distinct watch lists.")

        # ---- Test 4: Overwrite a watch list entry and verify ----
        await write_clause_id(2, 1, 99)
        d = await read_watch(2, 1)
        assert d["data"] == 99, f"Test 4 FAIL: expected 99, got {d['data']}"

        await write_length(2, 5)
        d = await read_watch(2, 0)
        assert d["len"] == 5, f"Test 4 FAIL: len expected 5, got {d['len']}"
        print("Test 4 PASSED: Overwrite updates correctly.")

        # ---- Test 5: Verify spec example content ----
        spec_examples = [
            (3,  1, [1]),
            (4,  1, [0]),
            (5,  1, [2]),
            (6,  2, [0, 3]),
            (8,  1, [1]),
            (9,  1, [2]),
            (10, 1, [2]),
            (11, 1, [3]),
        ]
        for lit, length, cids in spec_examples:
            d = await read_watch(lit, 0)
            assert d["len"] == length, (
                f"Test 5 FAIL: lit {lit} len expected {length}, got {d['len']}"
            )
            for idx, expected_cid in enumerate(cids):
                d = await read_watch(lit, idx)
                assert d["data"] == expected_cid, (
                    f"Test 5 FAIL: lit {lit} clause_id[{idx}] expected {expected_cid}, got {d['data']}"
                )
        print("Test 5 PASSED: Spec example watch lists verified.")
        print("\nAll tests PASSED.")

    sim.add_testbench(testbench)
    vcd_path = os.path.join(REPO_ROOT, "unit_tests", "logs", "watch_list_memory.vcd")
    with sim.write_vcd(vcd_path):
        sim.run()


if __name__ == "__main__":
    test_watch_list_memory()
