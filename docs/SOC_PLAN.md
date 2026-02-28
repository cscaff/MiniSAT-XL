# MiniSAT-XL SoC Plan

## Overview

This document describes the Amaranth-based SoC skeleton that integrates a
PicoRV32 RISC-V softcore with the BCP hardware accelerator via a simple
Wishbone interconnect.

---

## Memory Map

| Base         | Size   | Peripheral                        |
|--------------|--------|-----------------------------------|
| `0x00000000` | 64 KB  | Firmware RAM                      |
| `0x10000000` | 128 KB | Clause Memory write window        |
| `0x20000000` | 2 KB   | Assignment Memory write window    |
| `0x30000000` | 4 KB   | Occurrence List length table      |
| `0x30010000` | ~400KB | Occurrence List clause-ID table   |
| `0x40000000` | 32 B   | BCP CSRs                          |

### Firmware RAM (`0x00000000`)

64 KB of read/write synchronous SRAM.  The PicoRV32 fetches instructions and
data from here.  The simulation testbench pre-loads firmware words at
elaboration time.

### Clause Memory Write Window (`0x10000000`)

Each clause occupies 4 consecutive 32-bit words (16 bytes) at offset
`clause_id * 16`:

| Word | Bits        | Contents                                 |
|------|-------------|------------------------------------------|
| 0    | `[15:0]`    | `lit0` (16-bit literal encoding)         |
| 0    | `[16]`      | `sat_bit`                                |
| 0    | `[19:17]`   | `size` (number of valid literals, 1–5)   |
| 0    | `[31:20]`   | reserved (write 0)                       |
| 1    | `[15:0]`    | `lit1`                                   |
| 1    | `[31:16]`   | `lit2`                                   |
| 2    | `[15:0]`    | `lit3`                                   |
| 2    | `[31:16]`   | `lit4`                                   |
| 3    | any         | **trigger write enable** (commit)        |

### Assignment Memory Write Window (`0x20000000`)

One 32-bit word per variable at byte offset `var_id * 4`.  Only bits `[1:0]`
are used:

| Value | Meaning    |
|-------|------------|
| `0`   | UNASSIGNED |
| `1`   | FALSE      |
| `2`   | TRUE       |

### Occurrence List Window (`0x30000000`)

The WatchListMemory is repurposed as an occurrence list (each literal maps to
the set of clauses it appears in, used to trigger BCP when a literal becomes
false).

**Length table** (`0x30000000 + lit * 4`):  bits `[6:0]` = list length.

**Clause-ID table** (`0x30010000 + (lit * MAX_WATCH_LEN + idx) * 4`):
bits `[12:0]` = clause ID at position `idx`.

### BCP CSRs (`0x40000000`)

| Offset | Access | Register    | Description                                       |
|--------|--------|-------------|---------------------------------------------------|
| `+0x00`| W      | `control`   | bit 0 = `start`, bit 1 = `conflict_ack`          |
| `+0x04`| W      | `false_lit` | literal that became false                         |
| `+0x08`| R      | `status`    | bit 0=`busy`, bit 1=`done`, bit 2=`conflict`     |
| `+0x0C`| R      | `cc_id`     | conflict clause ID (valid when `conflict`=1)      |
| `+0x10`| R      | `impl`      | pop-on-read: `[12:0]`=var, `[13]`=value, `[26:14]`=reason, `[31]`=valid |
| `+0x14`| RW     | `result`    | firmware writes `1`=SAT, `2`=UNSAT               |

---

## Literal Encoding

Literals are 16-bit values encoded as:

```
lit = 2 * var_id + polarity
```

- `polarity = 0`: positive literal (+x)
- `polarity = 1`: negative literal (¬x)
- `var_id = lit >> 1`

The BCP accelerator processes clauses that watch a given literal and emits
implications when a clause becomes unit.

---

## Epoch Rules (CPU ↔ Accelerator Mutual Exclusion)

The CPU and the BCP accelerator share assignment memory and must not access
it simultaneously.  The protocol is:

1. **CPU mutates** clause DB, occurrence lists, or assignments only when
   `status.busy == 0` (accelerator is IDLE).
2. **CPU starts** BCP by writing `false_lit`, then writing `control.start = 1`.
3. **Accelerator runs** (`busy=1`): CPU must not write to shared memories.
4. **Accelerator finishes** (`done=1`):
   - If `conflict=0`: hardware writeback has already committed all implications
     to assignment memory.  CPU drains the implication stream (reads `impl`
     until `valid=0`) to update its trail.
   - If `conflict=1`: CPU reads `cc_id`, performs conflict analysis /
     backtracking, updates assignment memory, then writes `control.conflict_ack=1`.
5. Hardware returns to IDLE after ACK (or immediately after `done` if no conflict).

---

## Module Structure

```
soc/
  __init__.py          Package marker
  wishbone.py          WishboneBus and WishboneDecoder
  firmware_ram.py      Wishbone-connected synchronous RAM
  bcp_csr.py           BCP CSR block (Wishbone ↔ BCPAccelerator)
  mem_windows.py       Write windows for clause/assign/watchlist memories
  picorv32_bridge.py   PicoRV32 native interface → Wishbone bridge
  sim_harness.py       Simulation harness (no PicoRV32) + Python helpers
  soc.py               Full SoC top level (with PicoRV32 Instance)

rtl/
  picorv32.v           Vendored PicoRV32 stub (replace with real source)

firmware/
  start.S              Minimal startup (sp init, BSS clear, call main)
  main.c               CDCL firmware using BCP accelerator via MMIO
  link.ld              Linker script (64 KB at 0x00000000)
  Makefile             Build rules (riscv64-unknown-elf-gcc)
  bin2hex.py           Convert firmware.bin → firmware.hex

test/
  test_soc.py          Amaranth simulation test (Python firmware model)

docs/
  SOC_PLAN.md          This file
```

---

## How to Build and Run

### Prerequisites

- Python 3.10+ with `amaranth` installed (`pip install amaranth`)
- RISC-V toolchain for firmware compilation (optional, needed for real HW):
  `riscv64-unknown-elf-gcc` (GCC 12+ recommended)

### Run the SoC simulation (Python firmware model)

```bash
cd /path/to/MiniSAT-XL
# Run the SoC integration test (no RISC-V toolchain needed)
python test/test_soc.py
```

Expected output:
```
CDCL result: SAT
Final assignment: [2, 1, 2]   # x0=TRUE, x1=FALSE, x2=TRUE
test_soc_cdcl PASSED: SAT result verified.
```

### Compile firmware (for FPGA synthesis)

```bash
cd firmware
make
# Produces: firmware.elf, firmware.bin, firmware.hex
```

### Synthesise the full SoC

```python
from soc.soc import MiniSATXLSoC
import struct

# Load compiled firmware
with open("firmware/firmware.bin", "rb") as f:
    data = f.read()
words = list(struct.unpack(f"<{len(data)//4}I", data[:len(data)//4*4]))

soc = MiniSATXLSoC(firmware_init=words)
# Elaborate with your platform...
```

---

## Notes

- The PicoRV32 Verilog stub in `rtl/picorv32.v` is for interface documentation
  only.  Download the real source from https://github.com/YosysHQ/picorv32 for
  synthesis.
- The simulation test (`test/test_soc.py`) does **not** require the RISC-V
  toolchain; it implements the firmware algorithm directly in Python.
- Phase 1 uses software-committed implications (no hardware writeback to
  assignment memory from the accelerator unless the WRITEBACK FSM state is
  entered); the firmware drains the implication stream and records the trail.
