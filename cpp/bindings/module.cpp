// Python bindings for the C++ order book, built as lobx._core.
//
// This layer only converts between C++ and Python types. Everything here works in
// integers: the Python side turns string IDs and Decimal prices into integers
// before calling in (see lobx/_native.py).
//
// Each call holds the GIL from start to finish, so only one Python thread can be
// inside a book at a time.
#include <cstdint>
#include <cstddef>
#include <vector>

#include <nanobind/nanobind.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/vector.h>

#include "lobx/order_book.hpp"

namespace nb = nanobind;
using namespace nb::literals;  // Lets us write "name"_a for a named argument

namespace {

using namespace lobx;

// Collects what one submit() call produces. It lives as long as its book and is
// cleared before each call, so its vectors keep their memory between calls.
struct CollectingSink {
    std::vector<Trade> trades;
    std::vector<OrderId> self_trade_cancels;

    void on_trade(const Trade& trade) { trades.push_back(trade); }
    void on_self_trade_cancel(OrderId id) { self_trade_cancels.push_back(id); }
};

// What Python sees as lobx._core.OrderBook: a book plus its sink.
class PyOrderBook {
public:
    explicit PyOrderBook(bool self_trade_prevention)
        : book_(BookOptions{.self_trade_prevention = self_trade_prevention}) {}

    // Returns (status, remaining, trades, self_trade_cancels).
    nb::tuple submit(OrderId id, UserId user, Side side, Price price, Quantity quantity,
                     Timestamp timestamp) {
        const SubmitResult result = collect(NewOrder{id, user, side, price, quantity, timestamp});
        // nb::cast converts a C++ value into a new Python object. For a vector, that
        // means a new Python list.
        return nb::make_tuple(result.status, result.remaining, nb::cast(sink_.trades),
                              nb::cast(sink_.self_trade_cancels));
    }

    // Returns (status, remaining, trade tuples, IDs of removed resting orders).
    // Each trade tuple contains the IDs, users, price and quantity used by the wrapper.
    nb::tuple submit_compact(OrderId id, UserId user, Side side, Price price, Quantity quantity,
                             Timestamp timestamp) {
        const SubmitResult result = collect(NewOrder{id, user, side, price, quantity, timestamp});
        nb::list trades;
        nb::list removed;
        for (OrderId cancelled : sink_.self_trade_cancels) {
            removed.append(cancelled);
        }
        for (std::size_t i = 0; i < sink_.trades.size(); ++i) {
            const Trade& trade = sink_.trades[i];
            trades.append(nb::make_tuple(trade.trade_id, trade.buy_order_id, trade.sell_order_id,
                                         trade.buyer, trade.seller, trade.price, trade.quantity));

            // Only the final fill can leave part of a resting order in the book.
            const OrderId resting = side == Side::Buy ? trade.sell_order_id : trade.buy_order_id;
            if (i + 1 < sink_.trades.size() || !book_.contains(resting)) {
                removed.append(resting);
            }
        }
        return nb::make_tuple(result.status, result.remaining, trades, removed);
    }

    // Exposes the wrapped book for the read-only methods.
    const OrderBook& book() const { return book_; }
    OrderBook& book() { return book_; }

private:
    SubmitResult collect(const NewOrder& order) {
        sink_.trades.clear();
        sink_.self_trade_cancels.clear();
        return book_.submit(order, sink_);
    }

    OrderBook book_;
    CollectingSink sink_;
};

}  // namespace

// NB_MODULE defines the function Python calls when it first imports lobx._core.
// `m` is the new module object, and everything below adds things to it.
NB_MODULE(_core, m) {
    m.doc() = "C++ limit order book. Use it through lobx, not directly.";
    m.attr("PRICE_SCALE") = kPriceScale;
    m.attr("MAX_ORDER_QUANTITY") = kMaxOrderQuantity;

    nb::enum_<Side>(m, "Side")
        .value("BUY", Side::Buy)
        .value("SELL", Side::Sell);

    nb::enum_<SubmitStatus>(m, "SubmitStatus")
        .value("OPEN", SubmitStatus::Open)
        .value("PARTIAL", SubmitStatus::Partial)
        .value("FILLED", SubmitStatus::Filled)
        .value("REJECTED_INVALID", SubmitStatus::RejectedInvalid)
        .value("REJECTED_DUPLICATE", SubmitStatus::RejectedDuplicate);

    // def_ro exposes a field as a read-only Python attribute. Python gets its own
    // copy of each struct, so holding one can't affect the book.
    nb::class_<Trade>(m, "Trade")
        .def_ro("trade_id", &Trade::trade_id)
        .def_ro("buy_order_id", &Trade::buy_order_id)
        .def_ro("sell_order_id", &Trade::sell_order_id)
        .def_ro("buyer", &Trade::buyer)
        .def_ro("seller", &Trade::seller)
        .def_ro("price", &Trade::price)
        .def_ro("quantity", &Trade::quantity)
        .def_ro("timestamp", &Trade::timestamp);

    nb::class_<OrderView>(m, "OrderView")
        .def_ro("id", &OrderView::id)
        .def_ro("user", &OrderView::user)
        .def_ro("side", &OrderView::side)
        .def_ro("price", &OrderView::price)
        .def_ro("quantity", &OrderView::quantity)
        .def_ro("timestamp", &OrderView::timestamp)
        .def_ro("partially_filled", &OrderView::partially_filled);

    nb::class_<LevelView>(m, "LevelView")
        .def_ro("price", &LevelView::price)
        .def_ro("quantity", &LevelView::quantity)
        .def_ro("order_count", &LevelView::order_count);

    nb::class_<BookStats>(m, "BookStats")
        .def_ro("orders_rested", &BookStats::orders_rested)
        .def_ro("trades", &BookStats::trades)
        .def_ro("self_trade_cancels", &BookStats::self_trade_cancels)
        .def_ro("active_orders", &BookStats::active_orders)
        .def_ro("bid_levels", &BookStats::bid_levels)
        .def_ro("ask_levels", &BookStats::ask_levels)
        .def_ro("total_bid_quantity", &BookStats::total_bid_quantity)
        .def_ro("total_ask_quantity", &BookStats::total_ask_quantity);

    // Each .def connects a Python method name to C++ code. The lambdas adapt
    // PyOrderBook to the call each method needs.
    nb::class_<PyOrderBook>(m, "OrderBook")
        .def(nb::init<bool>(), "self_trade_prevention"_a = true)
        .def("submit", &PyOrderBook::submit, "order_id"_a, "user_id"_a, "side"_a, "price"_a,
             "quantity"_a, "timestamp"_a = 0)
        .def("submit_compact", &PyOrderBook::submit_compact, "order_id"_a, "user_id"_a, "side"_a,
             "price"_a, "quantity"_a, "timestamp"_a = 0)
        .def("cancel", [](PyOrderBook& self, OrderId id) { return self.book().cancel(id); },
             "order_id"_a)
        .def("best_bid", [](const PyOrderBook& self) { return self.book().best_bid(); })
        .def("best_ask", [](const PyOrderBook& self) { return self.book().best_ask(); })
        .def("spread", [](const PyOrderBook& self) { return self.book().spread(); })
        .def("peek_best",
             [](const PyOrderBook& self, Side side) { return self.book().peek_best(side); },
             "side"_a)
        .def("find", [](const PyOrderBook& self, OrderId id) { return self.book().find(id); },
             "order_id"_a)
        .def("contains", [](const PyOrderBook& self, OrderId id) { return self.book().contains(id); },
             "order_id"_a)
        .def("orders_at",
             [](const PyOrderBook& self, Side side, Price price) {
                 return self.book().orders_at(side, price);
             },
             "side"_a, "price"_a)
        .def("depth",
             [](const PyOrderBook& self, Side side, std::size_t max_levels) {
                 return self.book().depth(side, max_levels);
             },
             "side"_a, "max_levels"_a)
        .def("stats", [](const PyOrderBook& self) { return self.book().stats(); });
}
