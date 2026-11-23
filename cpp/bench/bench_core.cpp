// Google Benchmark measurements of the C++ core on its own, with no Python involved.
//
//   cmake --build build/cpp-release
//   ./build/cpp-release/lobx_bench
//   ./build/cpp-release/lobx_bench --benchmark_filter=workload
//
// Each benchmark runs once with the sorted-vector ladder ("vector/...") and once
// with std::map ("map/..."). The workload benchmarks read bench/workloads, which
// bench/generate_workloads.py creates.
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <benchmark/benchmark.h>

#include "lobx/order_book.hpp"
#include "workload.hpp"

namespace {

using namespace lobx;

constexpr Price kBase = 1'000'000;  // $100.00
constexpr Price kTick = 1;          // $0.0001, so 100,000 levels below kBase stay positive

using workload::Operation;

// Loads a workload once and keeps it, so file reading is never timed. User names
// are mapped to integers in first-seen order, as the Python layer does.
const std::vector<Operation>& get_workload(const std::string& name) {
    static std::map<std::string, std::vector<Operation>> cache;
    if (const auto entry = cache.find(name); entry != cache.end()) {
        return entry->second;
    }
    auto operations = workload::load(std::string(LOBX_WORKLOAD_DIR) + "/" + name + ".txt");
    OrderBook book;
    NullSink sink;
    for (const Operation& operation : operations) {
        if (operation.is_cancel) {
            book.cancel(operation.order.id);
        } else {
            const auto status = book.submit(operation.order, sink).status;
            if (status == SubmitStatus::RejectedInvalid || status == SubmitStatus::RejectedDuplicate) {
                throw std::runtime_error("rejected order in workload " + name);
            }
        }
    }
    return cache.emplace(name, std::move(operations)).first->second;
}

// Replays a whole workload into a fresh book on every iteration.
template <typename Book>
void replay_workload(benchmark::State& state, const std::string& name) {
    const std::vector<Operation>* operations = nullptr;
    try {
        operations = &get_workload(name);
    } catch (const std::exception& error) {
        state.SkipWithError(error.what());
        return;
    }
    for (auto _ : state) {
        Book book;
        NullSink sink;
        for (const Operation& operation : *operations) {
            if (operation.is_cancel) {
                benchmark::DoNotOptimize(book.cancel(operation.order.id));
            } else {
                benchmark::DoNotOptimize(book.submit(operation.order, sink));
            }
        }
        benchmark::ClobberMemory();
    }
    // Makes Google Benchmark report operations per second as "items_per_second".
    state.SetItemsProcessed(state.iterations() * static_cast<std::int64_t>(operations->size()));
}

// A book with one resting bid at each of `levels` prices, best at kBase.
template <typename Book>
Book bid_ladder(std::int64_t levels) {
    Book book;
    NullSink sink;
    // Seed from worst to best so fixture construction doesn't shift the vector.
    for (std::int64_t i = levels; i > 0; --i) {
        book.submit(NewOrder{static_cast<OrderId>(i), 1, Side::Buy, kBase - (i - 1) * kTick, 1, 0}, sink);
    }
    return book;
}

// Adds a new price level and cancels it again. `far` puts it below the worst bid,
// at the front of the sorted vector, so every entry shifts twice. Otherwise it goes
// just above the best bid, at the back.
template <typename Book>
void add_cancel_level(benchmark::State& state, bool far) {
    const std::int64_t levels = state.range(0);
    Book book = bid_ladder<Book>(levels);
    NullSink sink;
    const Price price = far ? kBase - levels * kTick : kBase + kTick;
    // The new bid must not cross the asks, and there are none, so it always rests.
    const NewOrder order{static_cast<OrderId>(levels + 1), 2, Side::Buy, price, 1, 0};
    if (book.submit(order, sink).status != SubmitStatus::Open || !book.cancel(order.id)) {
        state.SkipWithError("the test order did not rest and cancel");
        return;
    }
    for (auto _ : state) {
        benchmark::DoNotOptimize(book.submit(order, sink));
        benchmark::DoNotOptimize(book.cancel(order.id));
    }
    state.SetItemsProcessed(state.iterations() * 2);
}

// Cancels the order in the middle of a queue of `orders` at one price, then adds it
// back at the end. The linked list makes this the same cost at any queue length.
template <typename Book>
void cancel_mid_queue(benchmark::State& state) {
    const std::int64_t orders = state.range(0);
    Book book;
    NullSink sink;
    for (std::int64_t i = 0; i < orders; ++i) {
        book.submit(NewOrder{static_cast<OrderId>(i + 1), 1, Side::Buy, kBase, 1, 0}, sink);
    }
    OrderId middle = static_cast<OrderId>(orders / 2 + 1);
    OrderId next_id = static_cast<OrderId>(orders + 1);
    for (auto _ : state) {
        benchmark::DoNotOptimize(book.cancel(middle));
        book.submit(NewOrder{next_id, 1, Side::Buy, kBase, 1, 0}, sink);
        // The re-added order goes to the back, so the next cancel targets whichever
        // order is now in the middle. IDs stay unique.
        ++middle;
        ++next_id;
    }
    state.SetItemsProcessed(state.iterations() * 2);
}

// Rests an order and fills it completely with an opposite order.
template <typename Book>
void rest_and_fill(benchmark::State& state) {
    Book book = bid_ladder<Book>(state.range(0));  // A deep book on the other side
    NullSink sink;
    OrderId next_id = 10'000'000;
    for (auto _ : state) {
        book.submit(NewOrder{next_id++, 2, Side::Sell, kBase + kTick, 5, 0}, sink);
        benchmark::DoNotOptimize(book.submit(NewOrder{next_id++, 3, Side::Buy, kBase + kTick, 5, 0}, sink));
    }
    state.SetItemsProcessed(state.iterations() * 2);
}

template <typename Book>
void register_all(const std::string& ladder) {
    for (const std::string name : {"deep_book", "mixed", "cancel_heavy"}) {
        benchmark::RegisterBenchmark(ladder + "/workload/" + name, replay_workload<Book>, name)
            ->UseRealTime()->Unit(benchmark::kMillisecond);
    }
    benchmark::RegisterBenchmark(ladder + "/add_cancel_level_far", add_cancel_level<Book>, true)
        ->Arg(10)->Arg(1'000)->Arg(100'000);
    benchmark::RegisterBenchmark(ladder + "/add_cancel_level_near_best", add_cancel_level<Book>, false)
        ->Arg(10)->Arg(1'000)->Arg(100'000);
    benchmark::RegisterBenchmark(ladder + "/cancel_mid_queue", cancel_mid_queue<Book>)
        ->Arg(10)->Arg(10'000);
    benchmark::RegisterBenchmark(ladder + "/rest_and_fill", rest_and_fill<Book>)
        ->Arg(10)->Arg(100'000);
}

}  // namespace

int main(int argc, char** argv) {
    register_all<OrderBook>("vector");
    register_all<MapOrderBook>("map");
    benchmark::Initialize(&argc, argv);
    if (benchmark::ReportUnrecognizedArguments(argc, argv)) {
        return 2;
    }
    benchmark::RunSpecifiedBenchmarks();
    benchmark::Shutdown();
    return 0;
}
