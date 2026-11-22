// Helpers shared by the test files.
#pragma once

#include <cstdint>
#include <vector>

#include "lobx/order_book.hpp"

namespace lobx::testing {

// Converts a price in cents to book units, so tests can write dollars(100'00).
constexpr Price dollars(std::int64_t cents) { return cents * kPriceScale / 100; }

inline NewOrder make_order(OrderId id, UserId user, Side side, Price price, Quantity quantity) {
    return NewOrder{id, user, side, price, quantity, static_cast<Timestamp>(id)};
}

// Records everything the book reports.
struct RecordingSink {
    std::vector<Trade> trades;
    std::vector<OrderId> self_trade_cancels;

    void on_trade(const Trade& trade) { trades.push_back(trade); }
    void on_self_trade_cancel(OrderId id) { self_trade_cancels.push_back(id); }
};

// Rests an order, for tests where the sink's output doesn't matter.
inline SubmitResult add(OrderBook& book, const NewOrder& order) {
    NullSink sink;
    return book.submit(order, sink);
}

inline std::vector<OrderId> ids_at(const OrderBook& book, Side side, Price price) {
    std::vector<OrderId> ids;
    for (const OrderView& order : book.orders_at(side, price)) {
        ids.push_back(order.id);
    }
    return ids;
}

}  // namespace lobx::testing
