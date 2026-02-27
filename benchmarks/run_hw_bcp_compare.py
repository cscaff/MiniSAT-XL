#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


def parse_dimacs(path):
    num_vars = None
    clauses = []
    current = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("%"):
                break
            if line.startswith("p"):
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "cnf":
                    num_vars = int(parts[2])
                continue
            for tok in line.split():
                if tok.startswith("%"):
                    break
                lit = int(tok)
                if lit == 0:
                    if current:
                        clauses.append(current)
                        current = []
                else:
                    current.append(lit)
    if current:
        clauses.append(current)
    if num_vars is None:
        raise ValueError(f"Missing DIMACS header in {path}")
    return num_vars, clauses


def parse_result_file(path, num_vars):
    tokens = Path(path).read_text().split()
    if not tokens:
        return "INDET", None
    status = tokens[0].upper()
    if status == "UNSAT":
        return "UNSAT", None
    if status != "SAT":
        return "INDET", None
    model = [None] * (num_vars + 1)
    for tok in tokens[1:]:
        lit = int(tok)
        if lit == 0:
            break
        var = abs(lit)
        if 1 <= var <= num_vars:
            model[var] = lit > 0
    return "SAT", model


def sanitize_dimacs(path):
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        out_path = tmp.name
        with open(path, "r") as f:
            for line in f:
                if line.lstrip().startswith("%"):
                    break
                tmp.write(line)
    return out_path


def satisfies(clauses, model):
    if model is None:
        return False
    for clause in clauses:
        clause_sat = False
        for lit in clause:
            var = abs(lit)
            val = model[var]
            if val is None:
                return False
            if (lit > 0 and val) or (lit < 0 and not val):
                clause_sat = True
                break
        if not clause_sat:
            return False
    return True


def run_minisat(exe, cnf_path, env, cwd):
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        res_path = tmp.name
    sanitized = sanitize_dimacs(cnf_path)
    cmd = [exe, "-verb=0", sanitized, res_path]
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    stdout = proc.stdout
    stderr = proc.stderr
    try:
        num_vars, clauses = parse_dimacs(sanitized)
        status, model = parse_result_file(res_path, num_vars)
    finally:
        try:
            os.remove(res_path)
        except OSError:
            pass
        try:
            os.remove(sanitized)
        except OSError:
            pass
    return status, model, num_vars, clauses, stdout, stderr


def build_minisat(minisat_dir, build_dir, hw, python_config):
    env = os.environ.copy()
    make_cmd = ["make", "d", f"BUILD_DIR={build_dir}"]
    if hw:
        make_cmd.append("HW_BCP_SIM=1")
        if python_config:
            make_cmd.append(f"PYTHON_CONFIG={python_config}")
    make_cmd.append("CXXFLAGS=-std=gnu++98")
    subprocess.check_call(make_cmd, cwd=minisat_dir, env=env)


def collect_instances(folder, limit):
    files = sorted(p for p in Path(folder).iterdir() if p.is_file())
    return files[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench-root", default="benchmarks")
    parser.add_argument("--per-family", type=int, default=20)
    parser.add_argument("--minisat-dir", default="simulation/minisat")
    parser.add_argument("--build-dir-sw", default="build-sw")
    parser.add_argument("--build-dir-hw", default="build-hw")
    parser.add_argument("--python-config", default=os.environ.get("PYTHON_CONFIG", "python3-config --embed"))
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    minisat_dir = repo_root / args.minisat_dir

    if not args.skip_build:
        build_minisat(minisat_dir, args.build_dir_sw, hw=False, python_config=None)
        build_minisat(minisat_dir, args.build_dir_hw, hw=True, python_config=args.python_config)

    sw_exe = minisat_dir / args.build_dir_sw / "debug" / "bin" / "minisat"
    hw_exe = minisat_dir / args.build_dir_hw / "debug" / "bin" / "minisat"

    if not sw_exe.exists() or not hw_exe.exists():
        raise RuntimeError("MiniSAT binaries not found; build may have failed.")

    env_hw = os.environ.copy()
    env_hw["MINISAT_ACCEL_ROOT"] = str(repo_root)

    families = ["uf50-218", "uuf50-218"]
    total = 0
    failures = 0
    bit_mismatches = 0

    for fam in families:
        folder = repo_root / args.bench_root / fam
        instances = collect_instances(folder, args.per_family)
        for cnf_path in instances:
            total += 1
            sw_status, sw_model, num_vars, clauses, sw_out, sw_err = run_minisat(
                str(sw_exe), cnf_path, env=os.environ.copy(), cwd=repo_root
            )
            hw_status, hw_model, _, _, hw_out, hw_err = run_minisat(
                str(hw_exe), cnf_path, env=env_hw, cwd=repo_root
            )

            if sw_status not in ("SAT", "UNSAT") or hw_status not in ("SAT", "UNSAT"):
                failures += 1
                print(f"[FAIL] {cnf_path.name}: indeterminate result SW={sw_status} HW={hw_status}")
                if sw_out or sw_err:
                    print(f"  SW output: {sw_out.strip()} {sw_err.strip()}")
                if hw_out or hw_err:
                    print(f"  HW output: {hw_out.strip()} {hw_err.strip()}")
                continue

            status_ok = (sw_status == hw_status)
            if not status_ok:
                failures += 1
                print(f"[FAIL] {cnf_path.name}: status mismatch SW={sw_status} HW={hw_status}")
                continue

            if sw_status == "SAT":
                sw_sat = satisfies(clauses, sw_model)
                hw_sat = satisfies(clauses, hw_model)
                if not sw_sat or not hw_sat:
                    failures += 1
                    print(f"[FAIL] {cnf_path.name}: model does not satisfy CNF (SW={sw_sat}, HW={hw_sat})")
                    continue
                if sw_model != hw_model:
                    bit_mismatches += 1

            print(f"[OK] {cnf_path.name}: {sw_status}")

    print("\n=== Summary ===")
    print(f"Total: {total}")
    print(f"Failures: {failures}")
    print(f"Bit-for-bit model mismatches (SAT only): {bit_mismatches}")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
