// Replays a bench/workloads file through the C++ book.
//
// Writes the results to stdout in the format hashed by bench/run_baseline.py, so
// bench/check_cpp_results.py can compare them with the Python engine. The speed goes
// to stderr. It's a rough figure: Phase 4 measures this properly.
//
//   lobx_replay bench/workloads/mixed.txt > results.txt
#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
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

template <typename Integer>
bool parse_integer(std::string_view text, Integer& value) {
    const char* end = text.data() + text.size();
    const auto result = std::from_chars(text.data(), end, value);
    return result.ec == std::errc{} && result.ptr == end;
}

bool parse_order_id(std::string_view text, OrderId& id) {
    if (text.size() < 2 || text.front() != 'O' || (text[1] == '0' && text.size() > 2)) {
        return false;
    }
    return parse_integer(text.substr(1), id);
}

std::vector<Operation> load(const char* path) {
    std::ifstream file(path);
    if (!file) {
        throw std::runtime_error(std::string("can't open ") + path);
    }

    std::vector<Operation> operations;
    ankerl::unordered_dense::map<std::string, UserId> user_ids;  // Each new name gets the next number
    std::string line;
    for (std::size_t number = 1; std::getline(file, line); ++number) {
        const auto invalid_line = [path, number] {
            return std::runtime_error(std::string(path) + ':' + std::to_string(number) +
                                      ": invalid workload operation");
        };
        std::istringstream row(line);
        std::string kind, order_id, extra;
        Operation operation{};
        if (!(row >> kind >> order_id) || !parse_order_id(order_id, operation.order.id)) {
            throw invalid_line();
        }
        if (kind == "C") {
            operation.is_cancel = true;
        } else if (kind == "N") {
            std::string user_id, side, price_text, quantity_text;
            Price cents;
            Quantity quantity;
            if (!(row >> user_id >> side >> price_text >> quantity_text) ||
                (side != "B" && side != "S") ||
                !parse_integer(price_text, cents) || !parse_integer(quantity_text, quantity) ||
                cents <= 0 ||
                cents > std::numeric_limits<Price>::max() / kUnitsPerCent ||
                quantity <= 0 || quantity > kMaxOrderQuantity) {
                throw invalid_line();
            }
            operation.order.user = user_ids.try_emplace(user_id, user_ids.size()).first->second;
            operation.order.side = side == "B" ? Side::Buy : Side::Sell;
            operation.order.price = cents * kUnitsPerCent;
            operation.order.quantity = quantity;
        } else {
            throw invalid_line();
        }
        if (row >> extra) {
            throw invalid_line();
        }
        operations.push_back(operation);
    }
    if (file.bad() || operations.empty()) {
        throw std::runtime_error(std::string("can't read workload operations from ") + path);
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
            const double seconds = replay(operations).seconds;
            rates.push_back(seconds > 0 ? static_cast<double>(operations.size()) / seconds : 0);
        }
        const Run last = replay(operations);
        rates.push_back(last.seconds > 0 ? static_cast<double>(operations.size()) / last.seconds : 0);

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
