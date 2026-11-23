#!/usr/bin/env python3
"""
Measure throughput at each layer, from the bare C++ core up to HTTP.

    .venv/bin/python bench/bench_layers.py --label my-run

Layers, each on the same seeded workloads:
  core          C++ only, through Google Benchmark (build/cpp-release/lobx_bench)
  binding       lobx._core called from Python with integers prepared in advance
  engine cpp    TradingEngine(backend="cpp"), with Order objects built in advance
  engine python TradingEngine(backend="python"), the same way
  http          POST /orders and DELETE /orders through uvicorn, one client,
                one request at a time, on each backend

Throughput only, measured without per-operation timers, except HTTP, which
reports latency too. Event logging is off in the engine layers and on in the
API, as it runs by default. Layers alternate within each round, and the median
of the rounds is reported, so background load affects every layer alike.
"""
import argparse
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

import run_baseline  # noqa: E402
from lobx._native import AVAILABLE, IdMap, _core, price_to_units  # noqa: E402
from lobx.engine import TradingEngine  # noqa: E402
from lobx.models import Side  # noqa: E402

WORKLOADS = ["deep_book", "mixed", "cancel_heavy"]
SYMBOL = run_baseline.SYMBOL


def core_rates(bench_binary, repetitions):
    """Median ops/sec for each workload from Google Benchmark, vector and map ladders."""
    result = subprocess.run(
        [bench_binary, "--benchmark_filter=/workload/", "--benchmark_format=json",
         f"--benchmark_repetitions={repetitions}", "--benchmark_report_aggregates_only=true"],
        capture_output=True, text=True, check=True)
    rates = {}
    for entry in json.loads(result.stdout)["benchmarks"]:
        # With one repetition there's no median aggregate, just the single run.
        if entry.get("aggregate_name", "median") == "median":
            ladder, _, workload = entry["run_name"].split("/")
            rates[(ladder, workload)] = entry["items_per_second"]
    return rates


def binding_ops(ops):
    """Convert prepared Order objects into the integers lobx._core takes."""
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


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Server:
    """uvicorn running the API on one backend, without access logs."""

    def __init__(self, backend):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning", "--no-access-log"],
            cwd=REPO_ROOT, env={**os.environ, "LOBX_BACKEND": backend},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def __enter__(self):
        import httpx
        for _ in range(100):
            try:
                httpx.get(self.url + "/", timeout=0.5)
                return self
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("uvicorn didn't start")

    def __exit__(self, *_):
        self.process.terminate()
        self.process.wait(timeout=10)


def time_http(server, ops, symbol):
    """Send ops one request at a time. Returns ops/sec and latency percentiles in µs."""
    import httpx
    server_ids = {}  # The API makes its own order IDs, so cancels need mapping
    latencies = []
    with httpx.Client(base_url=server.url) as client:
        started = time.perf_counter()
        for op in ops:
            before = time.perf_counter()
            if isinstance(op, str):
                if op in server_ids:
                    client.delete(f"/orders/{symbol}/{server_ids[op]}")
            else:
                response = client.post("/orders", json={
                    "symbol": symbol, "user_id": op.user_id, "side": op.side.value,
                    "price": str(op.price), "quantity": str(op.quantity)})
                response.raise_for_status()
                server_ids[op.order_id] = response.json()["order_id"]
            latencies.append(time.perf_counter() - before)
        elapsed = time.perf_counter() - started
    latencies.sort()
    pick = lambda q: round(latencies[int(len(latencies) * q)] * 1e6, 1)
    return {"ops_per_sec": len(ops) / elapsed, "p50_us": pick(0.5), "p99_us": pick(0.99)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--label", required=True, help="results file name, without extension")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--bench-binary", default=str(REPO_ROOT / "build/cpp-release/lobx_bench"))
    parser.add_argument("--http-ops", type=int, default=3000,
                        help="operations per HTTP run, from the start of the mixed workload")
    args = parser.parse_args()
    if not AVAILABLE:
        sys.exit("lobx._core isn't built. Run: .venv/bin/python -m pip install --no-build-isolation -e .")

    manifest = json.loads((HERE / "workload_manifest.json").read_text())
    ops = {}
    for name in WORKLOADS:
        path = HERE / "workloads" / f"{name}.txt"
        if not path.exists():
            sys.exit(f"{path} is missing. Run bench/generate_workloads.py first.")
        ops[name] = run_baseline.load_ops(path)
    converted = {name: binding_ops(ops[name]) for name in WORKLOADS}
    http_ops = ops["mixed"][:args.http_ops]

    samples = {}

    def record(key, value):
        samples.setdefault(key, []).append(value)

    servers = {backend: Server(backend) for backend in ("python", "cpp")}
    for server in servers.values():
        server.__enter__()
    try:
        for round_number in range(args.rounds):
            for name in WORKLOADS:
                record(("binding", name), time_binding(converted[name]))
                record(("engine cpp", name), time_engine(ops[name], "cpp"))
                record(("engine python", name), time_engine(ops[name], "python"))
            for backend, server in servers.items():
                record((f"http {backend}", "mixed"), time_http(server, http_ops, f"R{round_number}"))
            print(f"round {round_number + 1} of {args.rounds} done", flush=True)
    finally:
        for server in servers.values():
            server.__exit__()

    core = core_rates(args.bench_binary, args.rounds)
    results = {
        "python": platform.python_version(),
        "machine": run_baseline.cpu_name(),
        "lobx_source_sha256": run_baseline.lobx_source_hash(),
        "workload_sha256": {name: manifest[name]["sha256"] for name in WORKLOADS},
        "rounds": args.rounds,
        "http_ops": args.http_ops,
        "ops_per_sec": {},
        "http": {},
    }
    for ladder in ("vector", "map"):
        results["ops_per_sec"][f"core {ladder}"] = {name: round(core[(ladder, name)]) for name in WORKLOADS}
    for (layer, name), values in samples.items():
        if layer.startswith("http"):
            median_run = sorted(values, key=lambda run: run["ops_per_sec"])[len(values) // 2]
            results["http"][layer] = {k: round(v, 1) for k, v in median_run.items()}
        else:
            results["ops_per_sec"].setdefault(layer, {})[name] = round(statistics.median(values))

    print(f"\n{'layer':<15}" + "".join(f"{name:>15}" for name in WORKLOADS))
    for layer, rates in results["ops_per_sec"].items():
        print(f"{layer:<15}" + "".join(f"{rates[name]:>15,}" for name in WORKLOADS))
    for layer, run in results["http"].items():
        print(f"{layer:<15}{run['ops_per_sec']:>15,.0f} ops/sec on mixed, "
              f"p50 {run['p50_us']:.0f} µs, p99 {run['p99_us']:.0f} µs")

    output = HERE / "results" / f"{args.label}.json"
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
