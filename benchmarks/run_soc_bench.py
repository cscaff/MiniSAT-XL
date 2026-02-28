#!/usr/bin/env python3
"""
SoC benchmark runner.

Runs each CNF instance through soc_cdcl_solver.py (full SoC simulation path)
and checks the result against the expected SAT/UNSAT outcome for each family.

Usage:
    python benchmarks/run_soc_bench.py [--per-family N] [--families uf50-218,uuf50-218]
"""

import argparse
import subprocess
import sys
from pathlib import Path


def expected_status(family):
    if family.startswith("uuf"):
        return "UNSAT"
    if family.startswith("uf"):
        return "SAT"
    return None


def collect_instances(folder, limit):
    files = sorted(p for p in Path(folder).iterdir() if p.is_file())
    return files[:limit] if limit is not None else files


def run_solver(solver_path, cnf_path):
    proc = subprocess.run(
        [sys.executable, str(solver_path), str(cnf_path)],
        capture_output=True,
        text=True,
    )
    out    = (proc.stdout or "").strip()
    status = out.split()[0].upper() if out else "INDET"
    return proc.returncode, status, out, (proc.stderr or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-root",  default="benchmarks")
    ap.add_argument("--per-family",  type=int, default=None)
    ap.add_argument("--families",    default="uf50-218,uuf50-218")
    args = ap.parse_args()

    repo_root   = Path(__file__).resolve().parents[1]
    solver_path = repo_root / "simulation" / "soc_cdcl_solver.py"

    families   = [f.strip() for f in args.families.split(",") if f.strip()]
    total      = 0
    failures   = 0
    mismatches = 0

    for fam in families:
        folder   = repo_root / args.bench_root / fam
        expected = expected_status(fam)
        for cnf_path in collect_instances(folder, args.per_family):
            total += 1
            code, status, out, err = run_solver(solver_path, cnf_path)
            if code != 0 or status not in ("SAT", "UNSAT"):
                failures += 1
                print(f"[FAIL] {cnf_path.name}: {status} (exit={code})")
                if out:
                    print(f"  out: {out}")
                if err:
                    print(f"  err: {err}")
                continue
            if expected and status != expected:
                mismatches += 1
                print(f"[MISMATCH] {cnf_path.name}: expected {expected}, got {status}")
                continue
            print(f"[OK] {cnf_path.name}: {status}")

    print("\n=== Summary ===")
    print(f"Total:      {total}")
    print(f"Failures:   {failures}")
    print(f"Mismatches: {mismatches}")
    return 1 if failures or mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
