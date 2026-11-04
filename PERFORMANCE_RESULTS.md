# Performance Results

## Current Baseline

These numbers are the comparison point for the C++ port. They measure in-process `TradingEngine` calls on an Apple M3 Pro. Orders are built before the clock starts, so HTTP, JSON and WebSockets are not included. Each figure is the median of 3 runs of 200,000 operations, and the runner's per-operation timers add a small overhead.

Logging is on by default in `TradingEngine`, and the API runs with it on.

### Python 3.14.2

| Workload | Ops/sec, logging off | p50 | p99 | Ops/sec, logging on | Trades |
|----------|---------------------:|----:|----:|--------------------:|-------:|
| `deep_book` | 211,605 | 2.42 µs | 28.96 µs | 123,051 | 34,564 |
| `mixed` | 119,625 | 2.71 µs | 37.62 µs | 76,811 | 131,841 |
| `cancel_heavy` | 344,606 | 2.08 µs | 19.88 µs | 174,392 | 14,565 |

### Python 3.9.6

| Workload | Ops/sec, logging off | p50 | p99 | Ops/sec, logging on | Trades |
|----------|---------------------:|----:|----:|--------------------:|-------:|
| `deep_book` | 129,423 | 3.67 µs | 44.83 µs | 68,072 | 34,564 |
| `mixed` | 72,725 | 4.12 µs | 55.54 µs | 45,195 | 131,841 |
| `cancel_heavy` | 203,174 | 3.50 µs | 30.38 µs | 93,878 | 14,565 |

The C++ port will be compared against Python 3.14, the faster of the two.

### Workloads

- **`deep_book`**: 40,000 resting price levels, then 160,000 operations close to the middle of the book.
- **`mixed`**: 170,205 new orders at random prices across 1,001 ticks, plus 29,795 cancels. About 43% of the new orders trade.
- **`cancel_heavy`**: long queues on 20 prices, with 91,719 cancels and about 5% aggressive orders.

### Where the time goes

Python 3.14, logging off, from a single run of each workload:

| Workload | Operation | Share of ops | Share of time | p50 | p99 |
|----------|-----------|-------------:|--------------:|----:|----:|
| `cancel_heavy` | Cancel | 46% | 35% | 2.25 µs | 4.00 µs |
| `cancel_heavy` | New order, no trade | 49% | 40% | 2.42 µs | 4.46 µs |
| `mixed` | New order that traded | 36% | 82% | 16.67 µs | 40.96 µs |
| `mixed` | New order, no trade | 49% | 17% | 2.79 µs | 7.42 µs |
| `deep_book` | Cancel | 12% | 8% | 3.54 µs | 6.38 µs |
| `deep_book` | New order, no trade | 79% | 54% | 2.67 µs | 4.83 µs |

### Effect of O(1) cancels

Price levels changed from a `deque` to an `OrderedDict` keyed by order ID. `deque.remove` scanned the queue, running a Python equality check on each order until it found a match, while an `OrderedDict` deletes by key.

Python 3.14, logging off, median of 3 alternating rounds in one session. Every result hash stayed the same, so only the speed changed.

| Workload | Ops/sec, `deque` | Ops/sec, `OrderedDict` | Change |
|----------|-----------------:|-----------------------:|-------:|
| `deep_book` | 148,812 | 209,761 | +41% |
| `mixed` | 121,619 | 119,487 | -2% |
| `cancel_heavy` | 114,655 | 341,215 | +198% |

`mixed` gets slightly slower because cancels were already a small share of its time, and the extra bookkeeping costs a little on other operations.

### Effect of the Phase 0 fixes

Python 3.14, logging off, with `deque` price levels. These come from an earlier session than the figures above, so don't compare the two. The "before" figures come from a single run, measured between two runs of the fixed engine that agreed within about 2.5%.

| Workload | Ops/sec before | Ops/sec after | Trades before | Trades after |
|----------|---------------:|--------------:|--------------:|-------------:|
| `deep_book` | 1,258 | 248,070 | 34,510 | 34,564 |
| `mixed` | 89,242 | 176,696 | 131,825 | 131,841 |
| `cancel_heavy` | 159,695 | 162,991 | 13,759 | 14,565 |

Three fixes went in:

- **Heap scan:** adding an order used to scan every price in the heap. Removing that scan accounts for the throughput gains. `cancel_heavy` has only 20 prices, so it barely changes.
- **Partial fills:** a partially filled order used to move to the back of its queue, and now it keeps its place. The same input therefore produces different trades, which is why the trade counts changed.
- **Thread safety:** `TradingEngine` now runs submits and cancels one at a time under a lock. The lock's cost was too small to measure: seven alternating `mixed` runs averaged 170,961 ops/sec with it and 171,474 without.

### Comparing runs

Only compare numbers measured in the same session. The same `deque` engine ran `mixed` at 176,696 ops/sec in the Phase 0 session and about 121,600 ops/sec in the session above, on the same machine. Alternate the engines being compared, as in the table above.

### Determinism

`bench/results/` records a `result_sha256` for each workload, a hash of every trade, every cancel result and the final book. It matched across repeated runs, with logging on and off, and on both Python versions. The C++ engine has to reproduce these hashes. `bench/run_baseline.py` documents the exact format.

### Reproducing

```bash
.venv2/bin/python bench/generate_workloads.py
```

```bash
.venv2/bin/python bench/run_baseline.py --label my-run
```

---

## Earlier Test-Suite Numbers

These come from `tests/test_performance.py`, measured before the Phase 0 fixes in short runs of 100 to 5,000 orders. The 84,836 orders/sec peak came from a single 500-order run, so the book stayed small and the baseline above is the better guide.

"Concurrent users" here means threads running under Python's GIL, so orders were not processed in parallel.

### Latency

| Scenario | P50 | P95 | P99 |
|----------|----:|----:|----:|
| Single user | 0.0042 ms | 0.0077 ms | 0.0206 ms |
| 10 threads, 500 orders | 0.0031 ms | 0.0192 ms | 0.0263 ms |

### Latency across 5 users (100 orders each)

| User | Mean (ms) | P95 (ms) | P99 (ms) |
|------|----------:|---------:|---------:|
| user0 | 0.0046 | 0.0143 | 0.0314 |
| user1 | 0.0059 | 0.0213 | 0.0310 |
| user2 | 0.0056 | 0.0192 | 0.0339 |
| user3 | 0.0061 | 0.0179 | 0.0470 |
| user4 | 0.0054 | 0.0186 | 0.0277 |

### Short load runs

| Load (orders) | P99 latency (ms) | Throughput (orders/sec) |
|--------------:|-----------------:|------------------------:|
| 100 | 0.0609 | 65,261 |
| 500 | 0.0328 | 84,836 |
| 1,000 | 0.0319 | 81,907 |
| 5,000 | 0.0323 | 69,476 |

### Corrections to earlier claims

- **FIFO:** earlier versions of this file reported 0 FIFO violations, but the tests only checked that trades existed, and partial fills were losing queue position. `tests/test_fifo.py` now compares every trade and queue against a separate reference model.
- **Replay:** the tests in `tests/test_performance.py` compare trade, order and cancel counts between runs, not the trades themselves. The `result_sha256` values above are the stronger check.
- **Thread safety:** the engine had a race between threads, because matching reads the best order and then changes it. With frequent thread switching, the old engine crashed in 6 of 6 runs. `TradingEngine` now serializes submits and cancels, and `test_threaded_submissions_do_not_corrupt_the_book` covers this. `OrderBook` and `MatchingEngine` are still not thread-safe when used directly.
