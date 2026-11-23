#!/usr/bin/env python3
"""
Replay the seeded workloads through TradingEngine and record a baseline.

The backend is the engine's default (cpp once built) unless --backend or
LOBX_BACKEND picks one. Each results file records which backend it measured.

This measures in-process TradingEngine calls only. Orders are built before the
clock starts, and HTTP, JSON and WebSockets are not involved.

Each workload also produces result_sha256, a hash of everything the engine
decided. The C++ engine must produce the same bytes for the same workload:

    T <buy_id> <sell_id> <price_in_cents> <quantity>    each trade, in order
    C <order_id> <1|0>                                  each cancel and its result
    L <B|S> <price_in_cents> <id>:<qty> <id>:<qty> ...  each resting price level,
                                                        bids high to low, then
                                                        asks low to high
"""
import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.append(str(REPO_ROOT))  # appended, so PYTHONPATH can select another lobx

import lobx  # noqa: E402
from lobx.engine import BACKENDS, TradingEngine, resolve_backend  # noqa: E402
from lobx.models import Order, Side  # noqa: E402

SYMBOL = "BENCH"
TIMESTAMP = datetime(2026, 1, 1)
PERCENTILES = {"p50": 0.50, "p90": 0.90, "p99": 0.99, "p999": 0.999}


def load_ops(path):
    """Parse a workload. New orders become Order objects, cancels stay as ID strings."""
    ops = []
    with open(path) as workload:
        for line in workload:
            fields = line.split()
            if fields[0] == "N":
                _, order_id, user_id, side, cents, quantity = fields
                ops.append(Order(
                    order_id,
                    user_id,
                    SYMBOL,
                    Side.BUY if side == "B" else Side.SELL,
                    Decimal(int(cents)).scaleb(-2),
                    int(quantity),
                    TIMESTAMP,
                ))
            else:
                ops.append(fields[1])
    return ops


def replay(ops, enable_logging, backend=None):
    """Run every operation once, returning the engine, outcomes and timings."""
    engine = TradingEngine(enable_logging=enable_logging, backend=backend)
    outcomes = [None] * len(ops)
    latencies = [0] * len(ops)
    clock = time.perf_counter_ns

    started = clock()
    for index, op in enumerate(ops):
        before = clock()
        if isinstance(op, str):
            outcomes[index] = engine.cancel_order(op, SYMBOL)
        else:
            outcomes[index] = engine.submit_order(op)
        latencies[index] = clock() - before
    elapsed = clock() - started

    return engine, outcomes, latencies, elapsed


def cents(price):
    return int(price.scaleb(2))


def result_hash(ops, outcomes, engine):
    """Hash the engine's decisions, using the format in the module docstring."""
    digest = hashlib.sha256()

    def write(line):
        digest.update(line.encode() + b"\n")

    for op, outcome in zip(ops, outcomes):
        if isinstance(op, str):
            write(f"C {op} {int(outcome)}")
        else:
            for trade in outcome:
                write(f"T {trade.buy_order_id} {trade.sell_order_id} {cents(trade.price)} {trade.quantity}")

    book = engine.get_book(SYMBOL)
    for tag, side, levels, descending in (
        ("B", Side.BUY, book.bids, True),
        ("S", Side.SELL, book.asks, False),
    ):
        for price in sorted((p for p, queue in levels.items() if queue), reverse=descending):
            resting = " ".join(
                f"{order.order_id}:{order.quantity}"
                for order in book.get_orders_at_price(side, price)
            )
            write(f"L {tag} {cents(price)} {resting}")

    return digest.hexdigest()


def summarize(ops, outcomes, engine, latencies, elapsed):
    ordered = sorted(latencies)
    trades = [trade for outcome in outcomes if isinstance(outcome, list) for trade in outcome]
    cancel_results = [outcome for outcome in outcomes if isinstance(outcome, bool)]
    book = engine.get_book(SYMBOL)
    return {
        "ops_per_sec": round(len(ops) / (elapsed / 1e9)),
        "seconds": round(elapsed / 1e9, 3),
        "latency_us": {
            **{name: round(ordered[int(len(ordered) * q)] / 1e3, 2) for name, q in PERCENTILES.items()},
            "max": round(ordered[-1] / 1e3, 2),
        },
        "trades": len(trades),
        "traded_quantity": sum(trade.quantity for trade in trades),
        "cancels": len(cancel_results),
        "cancel_hits": sum(cancel_results),
        "resting_orders": len(book.order_index),
        "resting_levels": sum(1 for levels in (book.bids, book.asks) for queue in levels.values() if queue),
        "result_sha256": result_hash(ops, outcomes, engine),
    }


def run_workload(name, expected_sha256, repeats, enable_logging, backend):
    """Run a workload repeatedly and return the run with the median throughput."""
    path = HERE / "workloads" / f"{name}.txt"
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        sys.exit(f"{path} is missing or stale. Run bench/generate_workloads.py first.")

    ops = load_ops(path)
    runs = []
    for _ in range(repeats):
        engine, outcomes, latencies, elapsed = replay(ops, enable_logging, backend)
        runs.append(summarize(ops, outcomes, engine, latencies, elapsed))
        del engine, outcomes, latencies

    hashes = {run["result_sha256"] for run in runs}
    if len(hashes) != 1:
        sys.exit(f"{name}: results differed between runs: {hashes}")

    median_rate = statistics.median_low(run["ops_per_sec"] for run in runs)
    median_run = next(run for run in runs if run["ops_per_sec"] == median_rate)
    return {**median_run, "all_ops_per_sec": [run["ops_per_sec"] for run in runs]}


def cpu_name():
    result = subprocess.run(
        ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True
    )
    return result.stdout.strip() or platform.machine()


def lobx_source_hash():
    """Identify the exact engine code that ran, whichever copy of lobx was imported."""
    digest = hashlib.sha256()
    for path in sorted(Path(lobx.__file__).parent.glob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--label", required=True, help="results file name, without extension")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--logging-modes", default="off,on", help="comma-separated: off, on")
    parser.add_argument("--backend", choices=BACKENDS, help="default: LOBX_BACKEND, then cpp if built")
    args = parser.parse_args()
    backend = resolve_backend(args.backend)
    print(f"backend: {backend}", flush=True)

    manifest = json.loads((HERE / "workload_manifest.json").read_text())
    results = {
        "python": platform.python_version(),
        "backend": backend,
        "machine": cpu_name(),
        "lobx_source_sha256": lobx_source_hash(),
        "repeats": args.repeats,
        "workloads": {},
    }

    for name, entry in manifest.items():
        for mode in args.logging_modes.split(","):
            summary = run_workload(name, entry["sha256"], args.repeats, mode == "on", backend)
            results["workloads"].setdefault(name, {})[f"logging_{mode}"] = summary
            latency = summary["latency_us"]
            print(
                f"{name:<13} logging={mode:<3} {summary['ops_per_sec']:>9,} ops/s  "
                f"p50={latency['p50']:>7.2f}us  p99={latency['p99']:>9.2f}us  "
                f"trades={summary['trades']:,}  {summary['result_sha256'][:12]}",
                flush=True,
            )

    output = HERE / "results" / f"{args.label}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
