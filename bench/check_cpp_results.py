#!/usr/bin/env python3
"""
Check that the C++ book reproduces the Python engine's results on every workload.

Each workload's output from cpp/tools/replay.cpp must hash to the result_sha256
recorded by bench/run_baseline.py. Build the C++ tools first, then run:

    python bench/check_cpp_results.py build/cpp-release/lobx_replay
    python bench/check_cpp_results.py build/cpp-release/lobx_replay --ladder map
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON_RESULTS = HERE / "results" / "cancel-o1-py3.14.json"


def load_workload_inputs():
    """Get the paths and manifest entries for the verified benchmark inputs."""
    manifest = json.loads((HERE / "workload_manifest.json").read_text())
    workloads = []
    for name, entry in manifest.items():
        workload = HERE / "workloads" / f"{name}.txt"
        if not workload.is_file() or hashlib.sha256(workload.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"{workload} is missing or stale. Run bench/generate_workloads.py first.")
        workloads.append((name, workload, entry))
    return workloads


def load_expected_workloads(python_results_path):
    """Load reference hashes for the verified benchmark inputs."""
    if not python_results_path.is_file():
        raise ValueError(f"{python_results_path} is missing. Run bench/run_baseline.py and pass its JSON with --python-results.")
    baseline = json.loads(python_results_path.read_text())
    if baseline.get("backend", "python") != "python":
        raise ValueError("Use a baseline measured on the Python backend")
    python_results = baseline["workloads"]
    workloads = []
    for name, workload, _ in load_workload_inputs():
        expected = python_results.get(name, {}).get("logging_off", {}).get("result_sha256")
        if not expected:
            raise ValueError(f"The Python baseline has no logging-off result hash for {name}.")
        workloads.append((name, workload, expected))
    return workloads


def main():
    parser = argparse.ArgumentParser(description="Compare C++ replay hashes with the Python baseline.")
    parser.add_argument("replay", help="path to the lobx_replay executable")
    parser.add_argument("--ladder", choices=("vector", "map"), default="vector")
    parser.add_argument("--python-results", type=Path, default=PYTHON_RESULTS,
                        help="baseline JSON from bench/run_baseline.py with logging off")
    args = parser.parse_args()
    try:
        workloads = load_expected_workloads(args.python_results)
    except (KeyError, OSError, ValueError) as error:
        parser.error(str(error))

    all_match = True
    for name, workload, expected in workloads:
        run = subprocess.run(
            [args.replay, "--ladder", args.ladder, str(workload)],
            capture_output=True,
            check=True,
        )
        actual = hashlib.sha256(run.stdout).hexdigest()
        match = actual == expected
        all_match = all_match and match
        print(f"{name:<13} {'match' if match else 'DIFFERENT'}  {actual[:12]}  {run.stderr.decode().strip()}")

    sys.exit(0 if all_match else 1)


if __name__ == "__main__":
    main()
