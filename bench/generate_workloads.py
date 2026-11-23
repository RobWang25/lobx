#!/usr/bin/env python3
"""
Generate the seeded workloads shared by the Python and C++ engines.

Each workload is a text file with one operation per line, kept simple so the
C++ benchmark can read it without a JSON library:

    N <order_id> <user_id> <B|S> <price_in_cents> <quantity>
    C <order_id>

The files are large, so they are not committed. workload_manifest.json is, and
its hashes let both engines confirm they are replaying identical input.
"""
import hashlib
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKLOAD_DIR = HERE / "workloads"
MANIFEST_PATH = HERE / "workload_manifest.json"

TOTAL_OPS = 200_000


def new_order(order_id, user, side, cents, quantity):
    return f"N {order_id} {user} {side} {cents} {quantity}"


def cancel(order_id):
    return f"C {order_id}"


def deep_book(rng):
    """40,000 resting price levels, then activity close to the best prices."""
    mid = 100_000  # 1000.00, far enough from zero for 20,000 levels below it
    levels = [("B", mid - offset) for offset in range(1, 20_001)]
    levels += [("S", mid + offset) for offset in range(1, 20_001)]
    rng.shuffle(levels)

    ops = []
    order_count = 0

    def add(side, cents, quantity):
        nonlocal order_count
        ops.append(new_order(f"O{order_count}", f"u{order_count % 100}", side, cents, quantity))
        order_count += 1

    for side, cents in levels:
        add(side, cents, rng.randint(1, 100))

    while len(ops) < TOTAL_OPS:
        draw = rng.random()
        side = "B" if rng.random() < 0.5 else "S"
        if draw < 0.70:  # passive, within 50 ticks of the middle
            offset = rng.randint(1, 50)
            add(side, mid - offset if side == "B" else mid + offset, rng.randint(1, 100))
        elif draw < 0.85:  # crosses the middle by up to 5 ticks
            add(side, mid + 5 if side == "B" else mid - 5, rng.randint(1, 100))
        else:
            ops.append(cancel(f"O{rng.randrange(order_count)}"))
    return ops


def mixed(rng):
    """Random prices across 1,001 ticks, so most orders trade; 15% are cancels."""
    ops = []
    order_count = 0
    while len(ops) < TOTAL_OPS:
        if order_count and rng.random() < 0.15:
            ops.append(cancel(f"O{rng.randrange(order_count)}"))
        else:
            side = "B" if rng.random() < 0.5 else "S"
            cents = rng.randint(9_500, 10_500)
            ops.append(new_order(f"O{order_count}", f"u{order_count % 100}", side, cents, rng.randint(1, 100)))
            order_count += 1
    return ops


def cancel_heavy(rng):
    """Market-maker style: long queues on 20 prices, about half the ops are cancels."""
    mid = 10_000
    ops = []
    live = []
    order_count = 0

    def add_passive():
        nonlocal order_count
        side = "B" if rng.random() < 0.5 else "S"
        offset = rng.randint(1, 10)
        cents = mid - offset if side == "B" else mid + offset
        order_id = f"O{order_count}"
        ops.append(new_order(order_id, f"mm{order_count % 5}", side, cents, rng.randint(1, 100)))
        live.append(order_id)
        order_count += 1

    for _ in range(5_000):
        add_passive()

    while len(ops) < TOTAL_OPS:
        draw = rng.random()
        if draw < 0.48 or not live:
            add_passive()
        elif draw < 0.95:
            # Swap-remove keeps this O(1). A taker may already have filled the
            # chosen order, so some cancels miss, as they do on a real exchange.
            index = rng.randrange(len(live))
            live[index], live[-1] = live[-1], live[index]
            ops.append(cancel(live.pop()))
        else:
            side = "B" if rng.random() < 0.5 else "S"
            cents = mid + 10 if side == "B" else mid - 10
            ops.append(new_order(f"O{order_count}", f"taker{order_count}", side, cents, rng.randint(1, 50)))
            order_count += 1
    return ops


WORKLOADS = {
    "deep_book": (101, deep_book),
    "mixed": (202, mixed),
    "cancel_heavy": (303, cancel_heavy),
}


def main():
    WORKLOAD_DIR.mkdir(exist_ok=True)
    manifest = {}
    for name, (seed, generate) in WORKLOADS.items():
        ops = generate(random.Random(seed))
        data = ("\n".join(ops) + "\n").encode()
        (WORKLOAD_DIR / f"{name}.txt").write_bytes(data)
        manifest[name] = {
            "seed": seed,
            "ops": len(ops),
            "new_orders": sum(op.startswith("N") for op in ops),
            "cancels": sum(op.startswith("C") for op in ops),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        print(f"{name}: {len(ops):,} ops, {len(data) / 1e6:.1f} MB")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
