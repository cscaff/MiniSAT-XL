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
