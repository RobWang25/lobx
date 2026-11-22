// Replays a bench/workloads file through the C++ book.
//
// Writes the results to stdout in the format hashed by bench/run_baseline.py, so
// bench/check_cpp_results.py can compare them with the Python engine. The speed goes
// to stderr. It's a rough figure: Phase 4 measures this properly.
//
//   lobx_replay bench/workloads/mixed.txt > results.txt
#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include <ankerl/unordered_dense.h>

#include "lobx/order_book.hpp"

namespace {

using namespace lobx;

constexpr std::int64_t kUnitsPerCent = kPriceScale / 100;
constexpr int kRuns = 5;

struct Operation {
    bool is_cancel;
    NewOrder order;  // For a cancel, only order.id is used
};

// Order IDs look like "O123", so skip the first character.
OrderId parse_order_id(const std::string& text) { return std::stoull(text.substr(1)); }

std::vector<Operation> load(const char* path) {
    std::ifstream file(path);
    if (!file) {
        throw std::runtime_error(std::string("can't open ") + path);
    }

    std::vector<Operation> operations;
    ankerl::unordered_dense::map<std::string, UserId> user_ids;  // Each new name gets the next number
    std::string kind, order_id, user_id, side;
    std::int64_t cents = 0;
    Quantity quantity = 0;
    while (file >> kind >> order_id) {
        if (kind == "N") {
            file >> user_id >> side >> cents >> quantity;
            const auto [entry, is_new] = user_ids.try_emplace(user_id, user_ids.size());
            operations.push_back({false,
                                  {parse_order_id(order_id), entry->second,
                                   side == "B" ? Side::Buy : Side::Sell, cents * kUnitsPerCent,
                                   quantity, 0}});
        } else {
            operations.push_back({true, {parse_order_id(order_id), 0, Side::Buy, 0, 0, 0}});
        }
    }
    return operations;
}

// Keeps trades in a vector, to be printed after the clock has stopped.
struct TradeLog {
    std::vector<Trade> trades;

    void on_trade(const Trade& trade) { trades.push_back(trade); }
    void on_self_trade_cancel(OrderId) {}
};

struct Run {
    OrderBook book;
    TradeLog log;
    std::vector<std::size_t> trades_after;  // Trade count after each operation
    std::vector<bool> cancel_results;
    double seconds;
};

Run replay(const std::vector<Operation>& operations) {
    Run run{OrderBook{}, {}, {}, {}, 0.0};
    run.log.trades.reserve(operations.size());
    run.trades_after.resize(operations.size());
    run.cancel_results.resize(operations.size());

    const auto started = std::chrono::steady_clock::now();
    for (std::size_t i = 0; i < operations.size(); ++i) {
        const Operation& operation = operations[i];
        if (operation.is_cancel) {
            run.cancel_results[i] = run.book.cancel(operation.order.id);
        } else {
            run.book.submit(operation.order, run.log);
        }
        run.trades_after[i] = run.log.trades.size();
    }
    const auto finished = std::chrono::steady_clock::now();

    run.seconds = std::chrono::duration<double>(finished - started).count();
    return run;
}

void print_side(const OrderBook& book, Side side, char tag, std::ostream& out) {
    for (const LevelView& level : book.depth(side, book.stats().active_orders)) {
        out << "L " << tag << ' ' << level.price / kUnitsPerCent;
        for (const OrderView& order : book.orders_at(side, level.price)) {
            out << " O" << order.id << ':' << order.quantity;
        }
        out << '\n';
    }
}

void print_results(const std::vector<Operation>& operations, const Run& run, std::ostream& out) {
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

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: lobx_replay <workload file>\n";
        return 2;
    }

    try {
        const std::vector<Operation> operations = load(argv[1]);

        std::vector<double> rates;
        for (int i = 0; i < kRuns - 1; ++i) {
            rates.push_back(static_cast<double>(operations.size()) / replay(operations).seconds);
        }
        const Run last = replay(operations);
        rates.push_back(static_cast<double>(operations.size()) / last.seconds);

        std::sort(rates.begin(), rates.end());
        std::cerr << static_cast<std::int64_t>(rates[rates.size() / 2]) << " ops/sec, "
                  << last.log.trades.size() << " trades\n";

        print_results(operations, last, std::cout);
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
