# Performance Results

## Phase 5 wrapper overhead

Phase 4 measured about 0.045 µs per `mixed` operation in the vector core and 3.13 µs through the C++-backed `TradingEngine`. This phase caches successful Decimal conversions, constructs frozen models from validated native values, and returns trade tuples and removed resting IDs from a single binding call. Cancel calls construct one cancelled `Order` when they need a snapshot. The engine skips that construction when logging is off and only a boolean is needed.

### Isolated `timeit` measurements

Each figure is the median of five runs of 100,000 samples on Python 3.14.2. The inputs are prepared before timing each step.

| Step | Phase 4 path | Phase 5 path |
| --- | ---: | ---: |
| Convert price / look up cached units | 564 ns | 23 ns |
| Construct a `Trade` | 851 ns | 297 ns |
| Construct an `Order` | 846 ns | 260 ns |
| Read seven trade fields / unpack a tuple | 170 ns | 25 ns |
| Build an `OrderView` to check a resting ID / check membership | 61 ns | 29 ns |
| Reconstruct a cancelled `Order` | 2,445 ns | 881 ns |

The compact binding packs more data per submit. A resting-order and matching-order pair took 430 ns through the compact binding and 296 ns through the original binding in the after run. The compact result saves work on the Python side by carrying both the trade fields and the removed resting IDs. The raw binding benchmark measures the original `submit` interface.

## Phase 4 benchmarks

The release benchmark measures both C++ ladders, the nanobind calls with prepared integer arguments, and both `TradingEngine` backends with prepared orders and event logging disabled. Each in-process workload contains 200,000 operations. Google Benchmark measures elapsed time for the core workload runs. The Python runner rotates the order of the remaining layers between rounds.

The HTTP benchmark sends the first 3,000 operations of `mixed` through one persistent connection to a fresh loopback Uvicorn server per round and backend. API event logging is enabled. The runner checks every cancel response and compares the final submit and trade counts with a Python replay.

Both ladders reproduce the Python result hashes for all three workloads. The Catch2 comparison also checks trades, cancel results, queue order, per-level totals and final statistics across 120,000 seeded operations.

### Local results

Apple M3 Pro with Python 3.14.2. Each entry is the median of 3 rounds.

The recorded data is available in [layered throughput and HTTP](bench/results/phase4-local.json), [C++ microbenchmarks](bench/results/phase4-micro-local.json), and [engine latency](bench/results/phase4-engine-latency-local.json).

| Layer, ops/sec | `deep_book` | `mixed` | `cancel_heavy` |
| --- | ---: | ---: | ---: |
| C++ core, vector | 2,587,877 | 22,330,982 | 34,190,076 |
| C++ core, std::map | 9,798,840 | 12,032,378 | 32,035,587 |
| Raw nanobind binding | 1,928,457 | 5,698,939 | 8,399,156 |
| Engine, cpp | 325,339 | 319,414 | 370,050 |
| Engine, python | 338,237 | 183,173 | 541,009 |

| HTTP backend, `mixed` | Requests/sec | p50 | p99 |
| --- | ---: | ---: | ---: |
| `python` | 2,106 | 462 µs | 698 µs |
| `cpp` | 2,086 | 463 µs | 830 µs |

The vector was 1.86× faster on `mixed` and 1.07× faster on `cancel_heavy`. The map was 3.79× faster on `deep_book`, where inserting and removing levels moves many vector entries. The vector is the default ladder.

Through `TradingEngine`, C++ was 1.74× faster on `mixed`. Python had higher throughput on `deep_book` and `cancel_heavy` in this run. Both HTTP backends handled about 2,100 requests/sec with a median around 0.46 ms.

### Level mutations at 100,000 resting levels

The microbenchmarks measure CPU time. Each iteration adds an order at a new level and cancels it after the book has warmed up.

| New level location | Vector, ns/op | Map, ns/op |
| --- | ---: | ---: |
| Just above the best bid | 17.9 | 103.9 |
| Below the worst bid | 24,414 | 46.4 |

The vector shifts its entries on both operations in the far-level test. Those shifts help explain the map's lead on `deep_book`.

### Engine latency in a separate replay

Logging was off and each operation was timed individually. The table shows the median of three rounds with alternating backend order. Python p99 was much higher than the archived baseline in this session, so the tail figures describe this run.

| Workload | Python p50 | Python p99 | C++ p50 | C++ p99 |
| --- | ---: | ---: | ---: | ---: |
| `deep_book` | 1.79 µs | 377.92 µs | 2.50 µs | 8.62 µs |
| `mixed` | 2.29 µs | 545.75 µs | 2.42 µs | 9.12 µs |
| `cancel_heavy` | 1.58 µs | 259.17 µs | 2.62 µs | 5.88 µs |

### Reproduce the comparisons

Build the Python extension with the steps in the README, then run from the repository root.

```bash
cmake -S cpp -B build/cpp-release -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpp-release
ctest --test-dir build/cpp-release --output-on-failure
.venv/bin/python bench/generate_workloads.py
.venv/bin/python bench/check_cpp_results.py build/cpp-release/lobx_replay --ladder vector
.venv/bin/python bench/check_cpp_results.py build/cpp-release/lobx_replay --ladder map
.venv/bin/python bench/bench_layers.py --label phase4-local --rounds 3 --http-ops 3000
./build/cpp-release/lobx_bench --benchmark_filter='add_cancel_level|cancel_mid_queue|rest_and_fill' --benchmark_repetitions=3 --benchmark_enable_random_interleaving=true
```

The layered runner writes new measurements to `build/bench-results/phase4-local.json` for this label. The linked snapshots in `bench/results/` contain the measurements used in this report.

For per-operation engine latency, select a backend explicitly in the timed replay.

```bash
.venv/bin/python bench/run_baseline.py --backend python --label phase4-engine-python --logging-modes off
.venv/bin/python bench/run_baseline.py --backend cpp --label phase4-engine-cpp --logging-modes off
```

## Phase 0 Python baseline

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
.venv/bin/python bench/generate_workloads.py
```

```bash
.venv/bin/python bench/run_baseline.py --label my-run
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
