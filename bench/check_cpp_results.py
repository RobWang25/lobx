#!/usr/bin/env python3
"""
Check that the C++ book reproduces the Python engine's results on every workload.

Each workload's output from cpp/tools/replay.cpp must hash to the result_sha256
recorded by bench/run_baseline.py. Build the C++ tools first, then run:

    python bench/check_cpp_results.py build/cpp-release/lobx_replay
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON_RESULTS = HERE / "results" / "cancel-o1-py3.14.json"


def main():
    parser = argparse.ArgumentParser(description="Compare C++ replay hashes with the Python baseline.")
    parser.add_argument("replay", help="path to the lobx_replay executable")
    parser.add_argument("--python-results", type=Path, default=PYTHON_RESULTS,
                        help="baseline JSON from bench/run_baseline.py with logging off")
    args = parser.parse_args()
    if not args.python_results.is_file():
        parser.error(f"{args.python_results} is missing. Run bench/run_baseline.py and pass its JSON with --python-results.")

    manifest = json.loads((HERE / "workload_manifest.json").read_text())
    python_results = json.loads(args.python_results.read_text())["workloads"]
    if any("result_sha256" not in python_results.get(name, {}).get("logging_off", {}) for name in manifest):
        parser.error("The Python baseline must contain a logging-off result hash for each workload.")
    all_match = True
    for name, entry in manifest.items():
        workload = HERE / "workloads" / f"{name}.txt"
        if not workload.is_file() or hashlib.sha256(workload.read_bytes()).hexdigest() != entry["sha256"]:
            parser.error(f"{workload} is missing or stale. Run bench/generate_workloads.py first.")

        run = subprocess.run(
            [args.replay, str(workload)],
            capture_output=True,
            check=True,
        )
        actual = hashlib.sha256(run.stdout).hexdigest()
        expected = python_results[name]["logging_off"]["result_sha256"]
        match = actual == expected
        all_match = all_match and match
        print(f"{name:<13} {'match' if match else 'DIFFERENT'}  {actual[:12]}  {run.stderr.decode().strip()}")

    sys.exit(0 if all_match else 1)


if __name__ == "__main__":
    main()
