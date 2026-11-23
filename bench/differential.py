#!/usr/bin/env python3
"""
Compare TradingEngine on the C++ backend with the Python backend, operation by operation.

Both engines get the same operations. After each one, the trades, the submit
result and the cancel result must match, and every few operations the whole book
must match too, down to each resting Order object. Any difference stops the run
and prints the operation.

    .venv/bin/python bench/differential.py random --ops 1000000
    .venv/bin/python bench/differential.py workloads
    .venv/bin/python bench/differential.py session

Trade IDs and trade timestamps aren't compared, because the backends make them
differently. Self-trade cancels are compared through their effect on the book.
"""
import argparse
import hashlib
import json
import random
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT))

from lobx._native import AVAILABLE, price_to_units  # noqa: E402
from lobx.engine import TradingEngine  # noqa: E402
from lobx.models import Order, OrderStatus, Side  # noqa: E402

SYMBOL = "DIFF"
TIMESTAMP = datetime(2026, 1, 1)


class Divergence(AssertionError):
    pass


class EngineSide:
    """A TradingEngine on one backend, reporting results in a form both backends share."""

    def __init__(self, backend, self_trade_prevention=True):
        self.engine = TradingEngine(
            enable_logging=False, backend=backend, self_trade_prevention=self_trade_prevention)

    def new(self, order_id, user, side, price, quantity):
        order = Order(order_id, user, SYMBOL, side, price, quantity, TIMESTAMP)
        trades = self.engine.submit_order(order)
        resting = self.engine.get_book(SYMBOL).get_order(order_id)
        status = resting.status.value if resting else OrderStatus.FILLED.value
        remaining = resting.quantity if resting else 0
        return status, remaining, [
            (t.buy_order_id, t.sell_order_id, t.buyer_user_id, t.seller_user_id,
             t.price, t.quantity)
            for t in trades
        ]

    def cancel(self, order_id):
        return self.engine.cancel_order(order_id, SYMBOL)

    def snapshot(self):
        """Every resting Order, by side and price, best price first."""
        book = self.engine.get_book(SYMBOL)
        if book is None:
            return {Side.BUY: [], Side.SELL: []}
        return {
            side: [(price, book.get_orders_at_price(side, price))
                   for price, _, _ in book.get_levels(side)]
            for side in (Side.BUY, Side.SELL)
        }

    @property
    def self_trade_cancels(self):
        book = self.engine.get_book(SYMBOL)
        return book.get_statistics().get("self_trade_cancels", 0) if book else 0


def PythonSide(self_trade_prevention=True):
    return EngineSide("python", self_trade_prevention)


def CppSide(self_trade_prevention=True):
    return EngineSide("cpp", self_trade_prevention)


def compare(ops, self_trade_prevention=True, snapshot_every=1):
    """Run ops through both engines, raising Divergence at the first difference."""
    python = PythonSide(self_trade_prevention)
    cpp = CppSide(self_trade_prevention)
    trades = 0
    for index, op in enumerate(ops):
        if op[0] == "new":
            expected, actual = python.new(*op[1:]), cpp.new(*op[1:])
            trades += len(expected[2])
        else:
            expected, actual = python.cancel(op[1]), cpp.cancel(op[1])
        if expected != actual:
            raise Divergence(f"op {index} {op}: python={expected} cpp={actual}")
        if (index + 1) % snapshot_every == 0 and python.snapshot() != cpp.snapshot():
            raise Divergence(f"books differ after op {index} {op}")
    if python.snapshot() != cpp.snapshot():
        raise Divergence("books differ at the end")
    return {"ops": len(ops), "trades": trades, "self_trade_cancels": cpp.self_trade_cancels}


# Each regime stresses something different. Prices are (lowest, highest, decimals).
REGIMES = {
    "tight": dict(prices=(9998, 10002, 2), users=3, max_qty=20, cancel=0.3),
    "wide": dict(prices=(9800, 10200, 2), users=50, max_qty=100, cancel=0.2),
    "fine_ticks": dict(prices=(1_000_000, 1_000_020, 4), users=10, max_qty=50, cancel=0.25),
    "large_qty": dict(prices=(9990, 10010, 2), users=20, max_qty=1_000_000_000, cancel=0.2),
    "no_stp": dict(prices=(9998, 10002, 2), users=4, max_qty=20, cancel=0.3, stp=False),
}


def random_ops(rng, count, prices, users, max_qty, cancel, stp=True):
    """Generate operations with fresh order IDs and cancels of recent, old or unknown IDs."""
    low, high, decimals = prices
    ops = []
    issued = 0
    for _ in range(count):
        if issued and rng.random() < cancel:
            roll = rng.random()
            if roll < 0.7:  # Recent orders, which are often still resting
                target = f"O{rng.randrange(max(0, issued - 50), issued)}"
            elif roll < 0.95:
                target = f"O{rng.randrange(issued)}"
            else:
                target = f"X{rng.randrange(1000)}"  # Never used
            ops.append(("cancel", target))
        else:
            ops.append((
                "new", f"O{issued}", f"u{rng.randrange(users)}",
                rng.choice((Side.BUY, Side.SELL)),
                Decimal(rng.randint(low, high)).scaleb(-decimals),
                rng.randint(1, max_qty),
            ))
            issued += 1
    return ops


def run_random(total_ops, seed):
    per_regime = total_ops // len(REGIMES)
    grand_total = 0
    for offset, (name, regime) in enumerate(REGIMES.items()):
        settings = dict(regime)
        stp = settings.pop("stp", True)
        ops = random_ops(random.Random(seed + offset), per_regime, **settings)
        started = time.perf_counter()
        result = compare(ops, self_trade_prevention=stp, snapshot_every=1000)
        elapsed = time.perf_counter() - started
        grand_total += result["ops"]
        print(f"{name:<11} {result['ops']:>9,} ops  {result['trades']:>8,} trades  "
              f"{result['self_trade_cancels']:>7,} self-trade cancels  match  ({elapsed:.1f}s)",
              flush=True)
    print(f"total       {grand_total:>9,} ops, no differences")


def workload_hash(path):
    """Hash a workload's results from the C++ backend, in bench/run_baseline.py's format."""
    cpp = CppSide()
    digest = hashlib.sha256()

    def write(line):
        digest.update(line.encode() + b"\n")

    with open(path) as workload:
        for line in workload:
            fields = line.split()
            if fields[0] == "N":
                _, order_id, user, side, cents, quantity = fields
                _, _, trades = cpp.new(order_id, user, Side.BUY if side == "B" else Side.SELL,
                                       Decimal(int(cents)).scaleb(-2), int(quantity))
                for buy, sell, _, _, price, traded in trades:
                    write(f"T {buy} {sell} {price_to_units(price) // 100} {traded}")
            else:
                write(f"C {fields[1]} {int(cpp.cancel(fields[1]))}")

    for tag, side in (("B", Side.BUY), ("S", Side.SELL)):
        for price, orders in cpp.snapshot()[side]:
            resting = " ".join(f"{order.order_id}:{order.quantity}" for order in orders)
            write(f"L {tag} {price_to_units(price) // 100} {resting}")
    return digest.hexdigest()


def run_workloads():
    recorded = json.loads((HERE / "results" / "cancel-o1-py3.14.json").read_text())["workloads"]
    all_match = True
    for name, modes in recorded.items():
        actual = workload_hash(HERE / "workloads" / f"{name}.txt")
        match = actual == modes["logging_off"]["result_sha256"]
        all_match = all_match and match
        print(f"{name:<13} {'match' if match else 'DIFFERENT'}  {actual[:12]}")
    return all_match


def session_ops(path):
    """Turn an EventLogger file into operations. TRADE events are returned separately."""
    ops, trades = [], []
    for line in Path(path).read_text().splitlines():
        event = json.loads(line)
        payload = event["payload"]
        if event["event_type"] == "NEW_ORDER":
            ops.append(("new", payload["order_id"], payload["user_id"], Side(payload["side"]),
                        Decimal(payload["price"]), payload["quantity"]))
        elif event["event_type"] == "CANCEL_ORDER":
            ops.append(("cancel", payload["order_id"]))
        elif event["event_type"] == "TRADE":
            trades.append((payload["buy_order_id"], payload["sell_order_id"],
                           price_to_units(Decimal(payload["price"])), payload["quantity"]))
    return ops, trades


def replay_session(path):
    """Replay a session through both engines, and check the C++ trades against the log."""
    ops, logged_trades = session_ops(path)
    compare(ops)
    cpp = CppSide()
    replayed = []
    for op in ops:
        if op[0] == "new":
            replayed += [(buy, sell, price_to_units(price), qty)
                         for buy, sell, _, _, price, qty in cpp.new(*op[1:])[2]]
        else:
            cpp.cancel(op[1])
    return len(ops), replayed, logged_trades


def main():
    if not AVAILABLE:
        sys.exit("lobx._core isn't built. Run: .venv/bin/python -m pip install --no-build-isolation -e .")

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    random_command = commands.add_parser("random", help="random operations in several regimes")
    random_command.add_argument("--ops", type=int, default=1_000_000)
    random_command.add_argument("--seed", type=int, default=1)
    commands.add_parser("workloads", help="reproduce the recorded result hashes")
    commands.add_parser("session", help="replay example_session.jsonl")
    args = parser.parse_args()

    if args.command == "random":
        run_random(args.ops, args.seed)
    elif args.command == "workloads":
        sys.exit(0 if run_workloads() else 1)
    else:
        count, replayed, logged = replay_session(REPO_ROOT / "example_session.jsonl")
        print(f"{count} operations: C++ matches the Python engine")
        print(f"{len(replayed)} trades replayed, {len(logged)} in the log: "
              f"{'identical' if replayed == logged else 'DIFFERENT'}")
        sys.exit(0 if replayed == logged else 1)


if __name__ == "__main__":
    main()
