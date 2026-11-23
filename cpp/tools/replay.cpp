// Replays a bench/workloads file through the C++ book.
//
// Writes the results to stdout in the format hashed by bench/run_baseline.py, so
// bench/check_cpp_results.py can compare them with the Python engine. The speed goes
// to stderr. It's a rough figure: Phase 4 measures this properly.
//
//   lobx_replay bench/workloads/mixed.txt > results.txt
//   lobx_replay --ladder map bench/workloads/mixed.txt > results.txt
#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "lobx/order_book.hpp"
#include "workload.hpp"

namespace {

using namespace lobx;

using workload::kUnitsPerCent;
using workload::Operation;

constexpr int kRuns = 5;

// Keeps trades in a vector, to be printed after the clock has stopped.
struct TradeLog {
    std::vector<Trade> trades;

    void on_trade(const Trade& trade) { trades.push_back(trade); }
    void on_self_trade_cancel(OrderId) {}
};

template <typename Book>
struct Run {
    Book book;
    TradeLog log;
    std::vector<std::size_t> trades_after;  // Trade count after each operation
    std::vector<bool> cancel_results;
    double seconds;
};

template <typename Book>
Run<Book> replay(const std::vector<Operation>& operations) {
    Run<Book> run{Book{}, {}, {}, {}, 0.0};
    run.log.trades.reserve(operations.size());
    run.trades_after.resize(operations.size());
    run.cancel_results.resize(operations.size());

    const auto started = std::chrono::steady_clock::now();
    for (std::size_t i = 0; i < operations.size(); ++i) {
        const Operation& operation = operations[i];
        if (operation.is_cancel) {
            run.cancel_results[i] = run.book.cancel(operation.order.id);
        } else {
            const auto result = run.book.submit(operation.order, run.log);
            if (result.status == SubmitStatus::RejectedDuplicate) {
                throw std::runtime_error("duplicate resting ID on workload line " + std::to_string(i + 1));
            }
        }
        run.trades_after[i] = run.log.trades.size();
    }
    const auto finished = std::chrono::steady_clock::now();

    run.seconds = std::chrono::duration<double>(finished - started).count();
    return run;
}

template <typename Book>
void print_side(const Book& book, Side side, char tag, std::ostream& out) {
    for (const LevelView& level : book.depth(side, book.stats().active_orders)) {
        out << "L " << tag << ' ' << level.price / kUnitsPerCent;
        for (const OrderView& order : book.orders_at(side, level.price)) {
            out << " O" << order.id << ':' << order.quantity;
        }
        out << '\n';
    }
}

template <typename Book>
void print_results(const std::vector<Operation>& operations, const Run<Book>& run,
                   std::ostream& out) {
    std::size_t next_trade = 0;
    for (std::size_t i = 0; i < operations.size(); ++i) {
        if (operations[i].is_cancel) {
            out << "C O" << operations[i].order.id << ' ' << (run.cancel_results[i] ? 1 : 0) << '\n';
        }
        for (; next_trade < run.trades_after[i]; ++next_trade) {
            const Trade& trade = run.log.trades[next_trade];
            out << "T O" << trade.buy_order_id << " O" << trade.sell_order_id << ' '
                << trade.price / kUnitsPerCent << ' ' << trade.quantity << '\n';
        }
    }
    print_side(run.book, Side::Buy, 'B', out);
    print_side(run.book, Side::Sell, 'S', out);
}

template <typename Book>
void run_all(const std::vector<Operation>& operations) {
    auto rate = [&operations](double seconds) {
        return seconds > 0 ? static_cast<double>(operations.size()) / seconds : 0.0;
    };
    std::vector<double> rates;
    for (int i = 0; i < kRuns - 1; ++i) {
        rates.push_back(rate(replay<Book>(operations).seconds));
    }
    const Run<Book> last = replay<Book>(operations);
    rates.push_back(rate(last.seconds));

    std::sort(rates.begin(), rates.end());
    std::cerr << static_cast<std::int64_t>(rates[rates.size() / 2]) << " ops/sec, "
              << last.log.trades.size() << " trades\n";

    print_results(operations, last, std::cout);
}

}  // namespace

int main(int argc, char** argv) {
    const bool has_ladder = argc == 4 && std::string_view(argv[1]) == "--ladder";
    const std::string_view ladder = has_ladder ? argv[2] : "vector";
    if ((argc != 2 && !has_ladder) || (ladder != "vector" && ladder != "map")) {
        std::cerr << "usage: lobx_replay [--ladder vector|map] <workload file>\n";
        return 2;
    }
    try {
        const auto operations = workload::load(argv[argc - 1]);
        if (ladder == "map") {
            run_all<MapOrderBook>(operations);
        } else {
            run_all<OrderBook>(operations);
        }
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
