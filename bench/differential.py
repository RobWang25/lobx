#!/usr/bin/env python3
"""
Compare the C++ core (lobx._core) with the Python engine, operation by operation.

Both engines get the same operations. After each one, the trades, the submit
result and the cancel result must match, and every few operations the whole book
must match too. Any difference stops the run and prints the operation.

    .venv/bin/python bench/differential.py random --ops 1000000
    .venv/bin/python bench/differential.py workloads
    .venv/bin/python bench/differential.py session

Expected differences, which the generated operations avoid: C++ rejects a
duplicate resting order ID before matching, and reports self-trade cancels.
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

from bench.check_cpp_results import PYTHON_RESULTS, load_expected_workloads  # noqa: E402
from lobx._native import AVAILABLE, IdMap, _core, price_to_units  # noqa: E402
from lobx.engine import TradingEngine  # noqa: E402
from lobx.matching import MatchingEngine  # noqa: E402
from lobx.models import Order, OrderStatus, Side  # noqa: E402

SYMBOL = "DIFF"
TIMESTAMP = datetime(2026, 1, 1)
NO_LIMIT = 2**62  # "All levels" for depth()


class Divergence(AssertionError):
    pass


class PythonSide:
    """The Python TradingEngine, reporting results in a form both sides share."""

    def __init__(self, self_trade_prevention=True):
        self.engine = TradingEngine(enable_logging=False)
        self.engine.matching_engine = MatchingEngine(self_trade_prevention)

    def new(self, order_id, user, side, price, quantity):
        order = Order(order_id, user, SYMBOL, side, price, quantity, TIMESTAMP)
        trades = self.engine.submit_order(order)
        resting = self.engine.get_book(SYMBOL).get_order(order_id)
        status = resting.status.value if resting else OrderStatus.FILLED.value
        remaining = resting.quantity if resting else 0
        return status, remaining, [
            (t.buy_order_id, t.sell_order_id, t.buyer_user_id, t.seller_user_id,
             price_to_units(t.price), t.quantity)
            for t in trades
        ]

    def cancel(self, order_id):
        return self.engine.cancel_order(order_id, SYMBOL)

    def snapshot(self):
        book = self.engine.get_book(SYMBOL)
        result = {}
        for side, levels, best_first in ((Side.BUY, book and book.bids, True),
                                         (Side.SELL, book and book.asks, False)):
            prices = sorted((p for p, q in (levels or {}).items() if q), reverse=best_first)
            result[side] = [
                (price_to_units(price), [
                    (o.order_id, o.user_id, o.quantity, o.status == OrderStatus.PARTIAL)
                    for o in book.get_orders_at_price(side, price)
                ])
                for price in prices
            ]
        return result


class CppSide:
    """The C++ book behind lobx._core, with string IDs and Decimal prices converted."""

    def __init__(self, self_trade_prevention=True):
        self.book = _core.OrderBook(self_trade_prevention)
        self.order_ids = IdMap()
        self.user_ids = IdMap()
        self.sides = {Side.BUY: _core.Side.BUY, Side.SELL: _core.Side.SELL}
        self.self_trade_cancels = 0

    def new(self, order_id, user, side, price, quantity):
        status, remaining, trades, cancels = self.book.submit(
            self.order_ids.number(order_id), self.user_ids.number(user),
            self.sides[side], price_to_units(price), quantity)
        self.self_trade_cancels += len(cancels)
        name = self.order_ids.name
        user_name = self.user_ids.name
        return status.name, remaining, [
            (name(t.buy_order_id), name(t.sell_order_id), user_name(t.buyer),
             user_name(t.seller), t.price, t.quantity)
            for t in trades
        ]

    def cancel(self, order_id):
        number = self.order_ids.lookup(order_id)
        return number is not None and self.book.cancel(number)

    def snapshot(self):
        result = {}
        for side, core_side in self.sides.items():
            result[side] = [
                (level.price, [
                    (self.order_ids.name(o.id), self.user_ids.name(o.user), o.quantity,
                     o.partially_filled)
                    for o in self.book.orders_at(core_side, level.price)
                ])
                for level in self.book.depth(core_side, NO_LIMIT)
            ]
        return result


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
    per_regime, extra = divmod(total_ops, len(REGIMES))
    grand_total = 0
    for offset, (name, regime) in enumerate(REGIMES.items()):
        settings = dict(regime)
        stp = settings.pop("stp", True)
        ops = random_ops(random.Random(seed + offset), per_regime + (offset < extra), **settings)
        started = time.perf_counter()
        result = compare(ops, self_trade_prevention=stp, snapshot_every=1000)
        elapsed = time.perf_counter() - started
        grand_total += result["ops"]
        print(f"{name:<11} {result['ops']:>9,} ops  {result['trades']:>8,} trades  "
              f"{result['self_trade_cancels']:>7,} self-trade cancels  match  ({elapsed:.1f}s)",
              flush=True)
    print(f"total       {grand_total:>9,} ops, no differences")


def workload_hash(path):
    """Hash a workload's results from the C++ core, in bench/run_baseline.py's format."""
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
                for buy, sell, _, _, units, traded in trades:
                    write(f"T {buy} {sell} {units // 100} {traded}")
            else:
                write(f"C {fields[1]} {int(cpp.cancel(fields[1]))}")

    snapshot = cpp.snapshot()
    for tag, side in (("B", Side.BUY), ("S", Side.SELL)):
        for units, orders in snapshot[side]:
            resting = " ".join(f"{order_id}:{quantity}" for order_id, _, quantity, _ in orders)
            write(f"L {tag} {units // 100} {resting}")
    return digest.hexdigest()


def run_workloads(workloads):
    all_match = True
    for name, workload, expected in workloads:
        actual = workload_hash(workload)
        match = actual == expected
        all_match = all_match and match
        print(f"{name:<13} {'match' if match else 'DIFFERENT'}  {actual[:12]}", flush=True)
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
            replayed += [(buy, sell, units, qty) for buy, sell, _, _, units, qty in cpp.new(*op[1:])[2]]
        else:
            cpp.cancel(op[1])
    return len(ops), replayed, logged_trades


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    random_command = commands.add_parser("random", help="random operations in several regimes")
    random_command.add_argument("--ops", type=int, default=1_000_000)
    random_command.add_argument("--seed", type=int, default=1)
    workloads_command = commands.add_parser("workloads", help="reproduce the recorded result hashes")
    workloads_command.add_argument("--python-results", type=Path, default=PYTHON_RESULTS,
                                   help="baseline JSON from bench/run_baseline.py with logging off")
    commands.add_parser("session", help="replay example_session.jsonl")
    args = parser.parse_args()

    if not AVAILABLE:
        parser.error("lobx._core isn't built. Run .venv/bin/python -m pip install --no-build-isolation -e .")

    if args.command == "random":
        if args.ops <= 0:
            parser.error("--ops must be positive")
        run_random(args.ops, args.seed)
    elif args.command == "workloads":
        try:
            workloads = load_expected_workloads(args.python_results)
        except (KeyError, OSError, ValueError) as error:
            parser.error(str(error))
        sys.exit(0 if run_workloads(workloads) else 1)
    else:
        count, replayed, logged = replay_session(REPO_ROOT / "example_session.jsonl")
        print(f"{count} operations: C++ matches the Python engine")
        print(f"{len(replayed)} trades replayed, {len(logged)} in the log: "
              f"{'identical' if replayed == logged else 'DIFFERENT'}")
        sys.exit(0 if replayed == logged else 1)


if __name__ == "__main__":
    main()
