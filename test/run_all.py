#!/usr/bin/env python3
import os
import subprocess
import sys


def find_tests(root):
    tests = []
    for base, _, files in os.walk(root):
        for name in files:
            if name.startswith("test_") and name.endswith(".py"):
                tests.append(os.path.join(base, name))
    return sorted(tests)


def main():
    root = os.path.abspath(os.path.dirname(__file__))
    tests = find_tests(root)
    if not tests:
        print("No tests found.")
        return 1

    failures = 0
    for test in tests:
        rel = os.path.relpath(test, root)
        print(f"=== {rel} ===")
        result = subprocess.run([sys.executable, test])
        if result.returncode != 0:
            failures += 1
            print(f"[FAIL] {rel}")
        else:
            print(f"[OK] {rel}")

    print("\n=== Summary ===")
    print(f"Total: {len(tests)}")
    print(f"Failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
