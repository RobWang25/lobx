# Performance Results

## C++ Port

Measured on an Apple M3 Pro with Python 3.14, with a load average of about 3 to 4. Each figure is the median of 3 runs over the same 200,000-operation workloads used below. Every engine run reproduced the recorded result hashes on both backends. Figures are from after the wrapper changes described below, except where a table says otherwise.

### Throughput by layer

Operations per second. Each layer adds one step on top of the one above it.

| Layer | `deep_book` | `mixed` | `cancel_heavy` |
|-------|------------:|--------:|---------------:|
| C++ core, sorted-vector ladder | 2,534,101 | 21,686,750 | 32,933,630 |
| C++ core, `std::map` ladder | 9,276,034 | 11,829,539 | 31,381,984 |
| Python calling `lobx._core` directly | 1,865,902 | 5,539,226 | 8,206,293 |
| `TradingEngine`, cpp backend | 430,403 | 557,414 | 687,297 |
| `TradingEngine`, python backend | 360,428 | 177,798 | 530,109 |

- **C++ core:** measured with Google Benchmark (`build/cpp-release/lobx_bench`), with no Python involved.
- **`lobx._core` directly:** IDs and prices are converted to integers before the clock starts, so this is the cost of crossing into C++ and building the returned Python objects.
- **`TradingEngine`:** `Order` objects are built before the clock starts and event logging is off, as in the baseline below. No per-operation timers.

The C++-backed engine is 1.2 to 3.1 times faster than the Python engine, even though the core alone is 7 to 122 times faster. On `mixed`, the C++ core takes about 0.05 µs per operation and the C++-backed engine about 1.8 µs. The rest is Python around the core: the engine's own bookkeeping and lock (about 0.5 µs, the same on both backends), converting each timestamp, crossing into C++, and building the returned `Trade` objects.

### Making the wrapper cheaper

Before these changes, the C++-backed engine took 2.8 µs per operation on `mixed` and was slower than the Python engine on `cancel_heavy`. Timing each step separately showed where the time went:

| Step | Before | After |
|------|-------:|------:|
| Convert a `Decimal` price to integer units | 277 ns | 16 ns, cached per price |
| Build a `Trade` (a frozen dataclass) | 590 ns | 295 ns |
| Read a core trade's 7 fields | 157 ns | Unpacked from a plain tuple |
| Work out which resting orders left the book | A Python loop and a `find` call | Returned by C++ |
| Build the cancelled `Order` | Twice, with validation | Once, without |

- **Price cache:** `NativeOrderBook` keeps each `Decimal` price's units in a dictionary, so only a price's first appearance pays for the conversion.
- **`build_trusted`** (`lobx/models.py`) creates a frozen `Order` or `Trade` without running `__init__` and `__post_init__`. It's only used for values the core already holds, which passed validation on the way in. A test checks that the result compares, hashes and refuses changes exactly like one built normally.
- **`submit_compact`** is a second binding method, shaped for the wrapper. It returns trades as plain tuples and lists the resting orders the call removed, either used up or cancelled as self-trades. The original `submit` is unchanged.

`TradingEngine` throughput on the cpp backend, operations per second:

| Workload | Before | After | Change |
|----------|-------:|------:|-------:|
| `deep_book` | 366,838 | 430,403 | +17% |
| `mixed` | 356,988 | 557,414 | +56% |
| `cancel_heavy` | 394,262 | 687,297 | +74% |

The engine's own bookkeeping now dominates: per operation, it takes a lock, reads the clock twice and appends to two latency lists. That code is shared with the Python backend, so it wasn't changed here.

### Latency through the engine

`bench/run_baseline.py` on each backend. Its per-operation timers add a little to every figure. The python rows are from the previous session, since the Python backend's code didn't change.

| Workload | Backend | Ops/sec, logging off | p50 | p99 | Ops/sec, logging on |
|----------|---------|---------------------:|----:|----:|--------------------:|
| `deep_book` | python | 327,466 | 1.67 µs | 20.12 µs | 187,021 |
| `deep_book` | cpp | 360,333 | 1.79 µs | 7.79 µs | 189,415 |
| `mixed` | python | 170,465 | 1.92 µs | 26.25 µs | 112,270 |
| `mixed` | cpp | 419,754 | 1.58 µs | 5.67 µs | 195,666 |
| `cancel_heavy` | python | 485,206 | 1.50 µs | 14.00 µs | 257,370 |
| `cancel_heavy` | cpp | 593,869 | 1.50 µs | 3.71 µs | 295,698 |

The C++ backend's p99 is 2.6 to 4.6 times lower on every workload, because matching an order that trades against several levels no longer costs Python work per level. Its p50 is now level with or below the Python backend's. With event logging on, both backends spend most of their time in the event logger, which is shared Python code.

### Through HTTP

The first 3,000 operations of `mixed`, sent as `POST /orders` and `DELETE /orders/...` requests through uvicorn, one at a time from one client. Access logs were off, and event logging was on, as the API runs by default.

| Backend | Requests/sec | p50 | p99 |
|---------|-------------:|----:|----:|
| python | 1,987 | 471 µs | 886 µs |
| cpp | 2,120 | 467 µs | 581 µs |

Each request takes about 470 µs, and the engine accounts for a few microseconds of that, around 1%. FastAPI, request validation, JSON and the network stack account for nearly all of it, so the backend barely changes API throughput. The lower p99 on C++ is consistent with the engine results, but at this sample size it's a hint rather than a firm result.

### Sorted vector or `std::map` for the price ladder

The book keeps each side's prices in a ladder, chosen as a template argument (`cpp/include/lobx/ladder.hpp`). Both ladders produce identical results.

Google Benchmark, nanoseconds per operation, median of 3:

| Operation | Levels or orders | Vector | `std::map` |
|-----------|-----------------:|-------:|-----------:|
| Add and remove a level below the worst price | 10 | 14.6 | 19.9 |
| | 1,000 | 204.8 | 47.2 |
| | 100,000 | 24,633.3 | 85.6 |
| Add and remove a level above the best price | 10 | 8.5 | 20.2 |
| | 1,000 | 12.6 | 32.8 |
| | 100,000 | 19.8 | 56.3 |
| Cancel from the middle of one price's queue | 10 | 9.8 | 10.4 |
| | 10,000 | 11.4 | 11.0 |
| Rest an order, then fill it | 100,000 on the other side | 14.3 | 30.7 |

- **The vector** is 2 to 3 times faster near the best price, where most activity happens, because its entries are contiguous and removing the best level is a `pop_back`. A level far from the best costs O(L), since every later entry shifts: 25 µs at 100,000 levels.
- **`std::map`** costs O(log L) anywhere, but each new level allocates a tree node, and following pointers is slower than scanning memory.
- **Queue position doesn't matter** for either: cancelling from the middle of a 10,000-order queue costs the same as from a 10-order one, because of the linked list.

This explains `deep_book`. It starts by inserting 40,000 one-order levels in shuffled order, and 15% of the later operations cancel a random resting order, often emptying a level far from the best price. Timed separately, building those 40,000 levels took 47.7 ms with the vector and 6.3 ms with `std::map`. The remaining 160,000 operations took 28.2 ms and 12.3 ms.

The vector stays the default. Realistic books concentrate activity near the best price, where it's faster, and `mixed` runs 1.9 times faster with it. A book with many levels and frequent changes far from the best price would suit `std::map` better.

### Reproducing

```bash
cmake -S cpp -B build/cpp-release -G Ninja -DCMAKE_BUILD_TYPE=Release
```

```bash
cmake --build build/cpp-release
```

```bash
.venv2/bin/python bench/bench_layers.py --label my-run
```

```bash
LOBX_BACKEND=cpp .venv2/bin/python bench/run_baseline.py --label my-cpp-run
```

```bash
./build/cpp-release/lobx_bench
```

Results are in `bench/results/`: `phase4-*.json` from before the wrapper changes and `phase5-*.json` from after.

---

## Python Baseline

These numbers were the comparison point for the C++ port, from the session before it. They measure in-process `TradingEngine` calls on an Apple M3 Pro. Orders are built before the clock starts, so HTTP, JSON and WebSockets are not included. Each figure is the median of 3 runs of 200,000 operations, and the runner's per-operation timers add a small overhead.

Logging is on by default in `TradingEngine`, and the API runs with it on.

### Python 3.14.2, python backend

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
