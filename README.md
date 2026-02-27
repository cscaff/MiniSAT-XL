# MiniSAT Accelerator

## Hardware Limitations
Handles 5-SAT
Max Vars = 512
Max Clauses = 8192
Max Watch List Length = 100

## HW BCP simulation (MiniSAT)
Build MiniSAT with the hardware-BCP simulation bridge enabled:

```
export MINISAT_ACCEL_ROOT=/path/to/MiniSAT-Accel
cd simulation/minisat
make config
make r HW_BCP_SIM=1
```

Run:

```
./build/release/bin/minisat <cnf>
```

Notes:
- The embedded Python must have `amaranth` available.
- If Python link flags fail, try `PYTHON_CONFIG="python3-config --embed"`.
- HW propagation is gated by `HW_BCP_SIM_ENABLE=1` (defaults to software propagation).

## Benchmark comparison (software vs HW sim)
Run a small comparison suite on uf50-218 and uuf50-218:

```
python3 benchmarks/run_hw_bcp_compare.py --per-family 20
```

This will build two MiniSAT binaries (software + HW_BCP_SIM) and compare
SAT/UNSAT plus model satisfaction, while also reporting bit-for-bit model mismatches.
Set `HW_BCP_SIM_ENABLE=1` in the environment when running the HW binary to force HW propagation.
