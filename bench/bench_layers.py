#!/usr/bin/env python3
"""Measure throughput from the C++ core up to the HTTP API."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
from tempfile import TemporaryFile
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bench import run_baseline  # noqa: E402
from bench.check_cpp_results import load_workload_inputs  # noqa: E402
from lobx._native import AVAILABLE, IdMap, _core, price_to_units  # noqa: E402
from lobx.engine import TradingEngine  # noqa: E402
from lobx.models import Side  # noqa: E402

SYMBOL = run_baseline.SYMBOL
BACKENDS = ("python", "cpp")
LADDERS = ("vector", "map")


def core_rates(bench_binary, repetitions, names):
    """Read the median wall-clock throughput from Google Benchmark."""
    process = subprocess.run(
        [bench_binary, "--benchmark_filter=/workload/", "--benchmark_format=json",
         f"--benchmark_repetitions={repetitions}", "--benchmark_report_aggregates_only=true",
         "--benchmark_enable_random_interleaving=true"],
        capture_output=True, text=True,
    )
    if process.returncode:
        raise RuntimeError(f"Core benchmark failed: {process.stderr.strip()}")
    rates = {}
    for entry in json.loads(process.stdout)["benchmarks"]:
        if entry.get("error_occurred"):
            raise RuntimeError(f"{entry['name']}: {entry['error_message']}")
        if entry.get("aggregate_name", "median") == "median":
            ladder, _, name = entry["run_name"].split("/")[:3]
            rates[ladder, name] = entry["items_per_second"]
    if rates.keys() != {(ladder, name) for ladder in LADDERS for name in names} or any(
        not math.isfinite(rate) or rate <= 0 for rate in rates.values()
    ):
        raise RuntimeError("Google Benchmark did not report valid throughput for every workload and ladder")
    return rates


def binding_ops(ops):
    """Prepare the integer arguments before timing the binding calls."""
    order_ids, user_ids = IdMap(), IdMap()
    sides = {Side.BUY: _core.Side.BUY, Side.SELL: _core.Side.SELL}
    converted = []
    for op in ops:
        if isinstance(op, str):
            converted.append((True, order_ids.number(op), 0, None, 0, 0))
        else:
            converted.append((False, order_ids.number(op.order_id), user_ids.number(op.user_id),
                              sides[op.side], price_to_units(op.price), op.quantity))
    return converted


def time_binding(converted):
    book = _core.OrderBook()
    submit, cancel = book.submit, book.cancel
    started = time.perf_counter()
    for is_cancel, order_id, user, side, price, quantity in converted:
        if is_cancel:
            cancel(order_id)
        else:
            submit(order_id, user, side, price, quantity)
    return len(converted) / (time.perf_counter() - started)


def time_engine(ops, backend):
    engine = TradingEngine(enable_logging=False, backend=backend)
    submit, cancel = engine.submit_order, engine.cancel_order
    started = time.perf_counter()
    for op in ops:
        if isinstance(op, str):
            cancel(op, SYMBOL)
        else:
            submit(op)
    return len(ops) / (time.perf_counter() - started)


@contextmanager
def api_client(backend):
    """Start a fresh loopback server and always collect the process on exit."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with TemporaryFile(mode="w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1",
             "--port", str(port), "--log-level", "warning", "--no-access-log"],
            cwd=REPO_ROOT, env={**os.environ, "LOBX_BACKEND": backend},
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        response = client.get("/stats/detailed", timeout=0.5)
                    except httpx.HTTPError:
                        pass
                    else:
                        if response.status_code == 200 and response.json()["backend"] == backend:
                            break
                    time.sleep(0.05)
                else:
                    log.seek(0)
                    raise RuntimeError(f"Uvicorn failed to start on {backend}: {log.read().strip()}")
                yield client
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def time_http(client, ops, expected_outcomes):
    """Send one HTTP request per operation and verify every cancel and the final counts."""
    server_ids = {}
    latencies = []
    started = time.perf_counter()
    for op, expected in zip(ops, expected_outcomes, strict=True):
        before = time.perf_counter()
        if isinstance(op, str):
            order_id = server_ids.get(op, f"missing-{op}")
            response = client.delete(f"/orders/{SYMBOL}/{order_id}")
            status = 200 if expected else 404
            if response.status_code != status:
                raise RuntimeError(f"Cancel {op} returned {response.status_code}, expected {status}")
        else:
            response = client.post("/orders", json={
                "symbol": SYMBOL, "user_id": op.user_id, "side": op.side.value,
                "price": str(op.price), "quantity": str(op.quantity),
            })
            response.raise_for_status()
            server_ids[op.order_id] = response.json()["order_id"]
        latencies.append(time.perf_counter() - before)
    elapsed = time.perf_counter() - started

    stats = client.get("/stats/detailed")
    stats.raise_for_status()
    stats = stats.json()
    submits = [outcome for outcome in expected_outcomes if isinstance(outcome, list)]
    if (stats["total_orders_submitted"] != len(submits) or
            stats["total_trades_executed"] != sum(map(len, submits))):
        raise RuntimeError("HTTP submit and trade counts differed from the Python replay")
    latencies.sort()
    return {
        "ops_per_sec": len(ops) / elapsed,
        "p50_us": latencies[len(latencies) // 2] * 1e6,
        "p99_us": latencies[int(len(latencies) * 0.99)] * 1e6,
    }


def round_order(items, round_number):
    offset = round_number % len(items)
    return items[offset:] + items[:offset]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="results file name, without extension")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--bench-binary", type=Path, default=REPO_ROOT / "build/cpp-release/lobx_bench")
    parser.add_argument("--http-ops", type=int, default=3000,
                        help="requests per HTTP round, from the start of the mixed workload")
    args = parser.parse_args()
    if not AVAILABLE:
        parser.error("Build lobx._core with .venv/bin/python -m pip install --no-build-isolation -e .")
    if not args.label or Path(args.label).name != args.label:
        parser.error("--label must be a file name")
    if args.rounds <= 0 or args.http_ops <= 0:
        parser.error("--rounds and --http-ops must be positive")
    try:
        workloads = load_workload_inputs()
    except (KeyError, OSError, ValueError) as error:
        parser.error(str(error))
    entries = {name: entry for name, _, entry in workloads}
    if args.http_ops > entries["mixed"]["ops"]:
        parser.error("--http-ops exceeds the size of the mixed workload")
    names = list(entries)
    binary = args.bench_binary.resolve()
    core = core_rates(binary, args.rounds, names)
    print("Core workload benchmarks complete", flush=True)

    results = {
        "python": platform.python_version(),
        "machine": run_baseline.cpu_name(),
        "lobx_source_sha256": run_baseline.lobx_source_hash(),
        "core_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "binding_sha256": hashlib.sha256(Path(_core.__file__).read_bytes()).hexdigest(),
        "workload_sha256": {name: entry["sha256"] for name, entry in entries.items()},
        "rounds": args.rounds,
        "http_ops": args.http_ops,
        "ops_per_sec": {f"core {ladder}": {name: round(core[ladder, name]) for name in names}
                        for ladder in LADDERS},
        "http": {},
    }
    for name, path, _ in workloads:
        ops = run_baseline.load_ops(path)
        converted = binding_ops(ops)
        layers = {
            "binding": lambda: time_binding(converted),
            "engine cpp": lambda: time_engine(ops, "cpp"),
            "engine python": lambda: time_engine(ops, "python"),
        }
        samples = {layer: [] for layer in layers}
        if name == "mixed":
            http_ops = ops[:args.http_ops]
        for round_number in range(args.rounds):
            for layer in round_order(tuple(layers), round_number):
                samples[layer].append(layers[layer]())
        for layer, rates in samples.items():
            results["ops_per_sec"].setdefault(layer, {})[name] = round(statistics.median(rates))
        print(f"{name} in-process benchmarks complete", flush=True)
        del ops, converted

    _, expected, _, _ = run_baseline.replay(http_ops, enable_logging=False)
    http_samples = {backend: [] for backend in BACKENDS}
    for round_number in range(args.rounds):
        for backend in round_order(BACKENDS, round_number):
            with api_client(backend) as client:
                http_samples[backend].append(time_http(client, http_ops, expected))
        print(f"HTTP round {round_number + 1} of {args.rounds} complete", flush=True)
    for backend, runs in http_samples.items():
        results["http"][f"http {backend}"] = {
            key: round(statistics.median(run[key] for run in runs), 1) for key in runs[0]
        }

    print(f"\n{'layer':<15}" + "".join(f"{name:>15}" for name in names))
    for layer, rates in results["ops_per_sec"].items():
        print(f"{layer:<15}" + "".join(f"{rates[name]:>15,}" for name in names))
    for layer, run in results["http"].items():
        print(f"{layer:<15}{run['ops_per_sec']:>15,.0f} ops/sec on mixed, "
              f"p50 {run['p50_us']:.0f} µs, p99 {run['p99_us']:.0f} µs")

    output = REPO_ROOT / "build" / "bench-results" / f"{args.label}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
