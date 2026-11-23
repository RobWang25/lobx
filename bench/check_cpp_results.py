#!/usr/bin/env python3
"""
Check that the C++ book reproduces the Python engine's results on every workload.

Each workload's output from cpp/tools/replay.cpp must hash to the result_sha256
recorded by bench/run_baseline.py. Build the C++ tools first, then run:

    python bench/check_cpp_results.py build/cpp-release/lobx_replay
    python bench/check_cpp_results.py build/cpp-release/lobx_replay --ladder map
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON_RESULTS = HERE / "results" / "cancel-o1-py3.14.json"


def main():
    if len(sys.argv) not in (2, 4):
        sys.exit(__doc__)
    replay = sys.argv[1]
    options = sys.argv[2:]  # Passed through, e.g. --ladder map

    python_results = json.loads(PYTHON_RESULTS.read_text())["workloads"]
    all_match = True
    for name, modes in python_results.items():
        run = subprocess.run(
            [replay, *options, str(HERE / "workloads" / f"{name}.txt")],
            capture_output=True,
            check=True,
        )
        actual = hashlib.sha256(run.stdout).hexdigest()
        expected = modes["logging_off"]["result_sha256"]
        match = actual == expected
        all_match = all_match and match
        print(f"{name:<13} {'match' if match else 'DIFFERENT'}  {actual[:12]}  {run.stderr.decode().strip()}")

    sys.exit(0 if all_match else 1)


if __name__ == "__main__":
    main()
