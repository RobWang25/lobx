// A limit order book for one symbol, with price-time priority matching.
//
// Orders live in a pool and form a doubly linked list at each price. A sorted
// "ladder" for each side finds the best price, and a hash map finds any order by
// ID. Everything refers to everything else by pool index.
//
// The ladder type is a template argument (see ladder.hpp). OrderBook uses the
// sorted vector, and MapOrderBook uses std::map, for comparison.
//
// Not thread-safe: only one thread may call a book at a time.
#pragma once

#include <algorithm>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

#include <ankerl/unordered_dense.h>

#include "lobx/ladder.hpp"
#include "lobx/pool.hpp"
#include "lobx/types.hpp"

namespace lobx {

// A concept names the requirements for a template argument. Here, a sink is any
// type with these two functions. Results go through a sink, rather than a returned
// vector or a std::function, so the hot path doesn't have to allocate and the
// compiler can inline the calls.
template <typename S>
concept EventSink = requires(S& sink, const Trade& trade, OrderId id) {
    sink.on_trade(trade);
    sink.on_self_trade_cancel(id);
};

struct NullSink {
    void on_trade(const Trade&) {}
    void on_self_trade_cancel(OrderId) {}
};

struct BookOptions {
    bool self_trade_prevention = true;
    std::size_t expected_orders = 0;  // Room to reserve up front, to avoid growing later
    std::size_t expected_levels = 0;
};

template <typename Ladder>
class BasicOrderBook {
public:
    // `explicit` stops a BookOptions from silently converting into a book.
    explicit BasicOrderBook(BookOptions options = {})
        : self_trade_prevention_(options.self_trade_prevention) {
        orders_.reserve(options.expected_orders);
        index_.reserve(options.expected_orders);
        levels_.reserve(options.expected_levels);
        bids_.reserve(options.expected_levels);
        asks_.reserve(options.expected_levels);
    }

    // Matches an order against the book, then rests whatever is left. Trades and
    // self-trade cancels go to the sink as they happen. The sink must not call back
    // into this book. If a callback throws, changes already reported stay applied.
    //
    // This is a template, so its full definition has to stay in the header: the
    // compiler needs it to generate a version for each sink type.
    template <EventSink Sink>
    SubmitResult submit(const NewOrder& order, Sink& sink) {
        if ((order.side != Side::Buy && order.side != Side::Sell) ||
            order.price <= 0 || order.quantity <= 0 || order.quantity > kMaxOrderQuantity) {
            return {SubmitStatus::RejectedInvalid, 0};
        }
        if (index_.contains(order.id)) {
            return {SubmitStatus::RejectedDuplicate, 0};
        }

        Quantity remaining = order.quantity;
        const Ladder& opposing = ladder(opposite(order.side));

        while (remaining > 0 && !opposing.empty()) {
            const Index level_index = opposing.best();
            Level& level = levels_[level_index];
            if (!crosses(order, level.price)) {
                break;
            }

            const Index resting_index = level.head;
            OrderNode& resting = orders_[resting_index];

            if (self_trade_prevention_ && resting.user == order.user) {
                const OrderId cancelled = resting.id;
                remove_order(resting_index);
                ++self_trade_cancels_;
                sink.on_self_trade_cancel(cancelled);
                continue;
            }

            const Quantity traded = std::min(remaining, resting.quantity);
            const bool incoming_buys = order.side == Side::Buy;
            const Trade trade{
                ++trades_,
                incoming_buys ? order.id : resting.id,
                incoming_buys ? resting.id : order.id,
                incoming_buys ? order.user : resting.user,
                incoming_buys ? resting.user : order.user,
                level.price,
                traded,
                order.timestamp,
            };
            remaining -= traded;

            // A partially filled order stays where it is, keeping its time priority.
            if (traded == resting.quantity) {
                remove_order(resting_index);
            } else {
                resting.quantity -= traded;
                resting.partially_filled = true;
                level.total_quantity -= traded;
            }
            sink.on_trade(trade);
        }

        if (remaining == 0) {
            return {SubmitStatus::Filled, 0};
        }
        const bool any_traded = remaining < order.quantity;
        rest_order(order, remaining, any_traded);
        return {any_traded ? SubmitStatus::Partial : SubmitStatus::Open, remaining};
    }

    // Returns false if no resting order has this ID.
    bool cancel(OrderId id) {
        const auto found = index_.find(id);
        if (found == index_.end()) {
            return false;
        }
        remove_order(found->second);
        return true;
    }

    std::optional<Price> best_price(Side side) const {
        const Ladder& entries = ladder(side);
        if (entries.empty()) {
            return std::nullopt;
        }
        return levels_[entries.best()].price;
    }
    std::optional<Price> best_bid() const { return best_price(Side::Buy); }
    std::optional<Price> best_ask() const { return best_price(Side::Sell); }

    std::optional<Price> spread() const {
        const auto bid = best_bid();
        const auto ask = best_ask();
        if (!bid || !ask) {
            return std::nullopt;
        }
        return *ask - *bid;
    }

    // The order next in line to trade on this side.
    std::optional<OrderView> peek_best(Side side) const {
        const Ladder& entries = ladder(side);
        if (entries.empty()) {
            return std::nullopt;
        }
        return view(levels_[entries.best()].head);
    }

    std::optional<OrderView> find(OrderId id) const {
        const auto found = index_.find(id);
        if (found == index_.end()) {
            return std::nullopt;
        }
        return view(found->second);
    }

    // Queries below return new vectors, so they allocate. They aren't for the hot path.

    // Orders at one price, front of the queue first.
    std::vector<OrderView> orders_at(Side side, Price price) const {
        std::vector<OrderView> result;
        if (price <= 0) {
            return result;
        }
        const Index level_index = ladder(side).find(sort_key(side, price));
        if (level_index == kNone) {
            return result;
        }
        const Level& level = levels_[level_index];
        result.reserve(level.count);
        for (Index i = level.head; i != kNone; i = orders_[i].next) {
            result.push_back(view(i));
        }
        return result;
    }

    // Price levels, best price first.
    std::vector<LevelView> depth(Side side, std::size_t max_levels) const {
        const Ladder& entries = ladder(side);
        std::vector<LevelView> result;
        if (max_levels == 0) {
            return result;
        }
        result.reserve(std::min(max_levels, entries.size()));
        // The lambda captures result, max_levels and this by reference ([&]), and
        // returns false to stop once there are enough levels.
        entries.for_each_best_first([&](Index level_index) {
            const Level& level = levels_[level_index];
            result.push_back({level.price, level.total_quantity, level.count});
            return result.size() < max_levels;
        });
        return result;
    }

    BookStats stats() const {
        BookStats result;
        result.orders_rested = orders_rested_;
        result.trades = trades_;
        result.self_trade_cancels = self_trade_cancels_;
        result.active_orders = index_.size();
        result.bid_levels = bids_.size();
        result.ask_levels = asks_.size();
        bids_.for_each_best_first([&](Index level_index) {
            result.total_bid_quantity += levels_[level_index].total_quantity;
            return true;
        });
        asks_.for_each_best_first([&](Index level_index) {
            result.total_ask_quantity += levels_[level_index].total_quantity;
            return true;
        });
        return result;
    }

private:
    // One resting order. The prev and next links live inside it, which makes this
    // an "intrusive" linked list.
    struct OrderNode {
        OrderId id = 0;
        UserId user = 0;
        Quantity quantity = 0;
        Timestamp timestamp = 0;
        Index prev = kNone;   // The order ahead in the queue
        Index next = kNone;   // The order behind in the queue, or the next free slot
        Index level = kNone;  // The price level this order belongs to
        bool partially_filled = false;
    };

    // One price. Levels stay in their pool while the ladder's entries move around,
    // so an order's `level` index always stays correct.
    struct Level {
        Price price = 0;
        Quantity total_quantity = 0;
        Index head = kNone;  // Next order to trade
        Index tail = kNone;  // Most recent arrival
        Index next = kNone;  // Next free slot, used only by the pool
        std::uint32_t count = 0;
        Side side = Side::Buy;
    };

    // Each ladder is sorted so a bigger key means a better price. Bids use the price
    // and asks use its negative, so the same code handles both sides.
    static constexpr Price sort_key(Side side, Price price) {
        return side == Side::Buy ? price : -price;
    }

    static bool crosses(const NewOrder& order, Price resting_price) {
        return order.side == Side::Buy ? order.price >= resting_price
                                       : order.price <= resting_price;
    }

    Ladder& ladder(Side side) { return side == Side::Buy ? bids_ : asks_; }
    const Ladder& ladder(Side side) const { return side == Side::Buy ? bids_ : asks_; }

    OrderView view(Index index) const {
        const OrderNode& node = orders_[index];
        const Level& level = levels_[node.level];
        return {node.id, node.user, level.side, level.price,
                node.quantity, node.timestamp, node.partially_filled};
    }

    // Finds the level for a price, creating it if needed. The lambda only runs when
    // the price is new.
    Index find_or_create_level(Side side, Price price) {
        return ladder(side).find_or_insert(sort_key(side, price), [&] {
            const Index level_index = levels_.acquire();
            Level& level = levels_[level_index];
            level.price = price;
            level.total_quantity = 0;
            level.head = kNone;
            level.tail = kNone;
            level.count = 0;
            level.side = side;
            return level_index;
        });
    }

    void rest_order(const NewOrder& order, Quantity quantity, bool partially_filled) {
        // Get the level first. References are only taken after both pools have
        // finished growing, because growing moves their contents.
        const Index level_index = find_or_create_level(order.side, order.price);
        const Index order_index = orders_.acquire();

        Level& level = levels_[level_index];
        OrderNode& node = orders_[order_index];
        node.id = order.id;
        node.user = order.user;
        node.quantity = quantity;
        node.timestamp = order.timestamp;
        node.prev = level.tail;
        node.next = kNone;
        node.level = level_index;
        node.partially_filled = partially_filled;

        // Link it in at the back of the queue.
        if (level.tail != kNone) {
            orders_[level.tail].next = order_index;
        } else {
            level.head = order_index;
        }
        level.tail = order_index;
        level.total_quantity += quantity;
        ++level.count;

        index_.emplace(order.id, order_index);
        ++orders_rested_;
    }

    // Unlinks an order from anywhere in its queue by updating at most two neighbours.
    // Unlinking is O(1). Emptying a level also removes its ladder entry.
    void remove_order(Index order_index) {
        const OrderNode& node = orders_[order_index];
        const Index level_index = node.level;
        Level& level = levels_[level_index];

        if (node.prev != kNone) {
            orders_[node.prev].next = node.next;
        } else {
            level.head = node.next;
        }
        if (node.next != kNone) {
            orders_[node.next].prev = node.prev;
        } else {
            level.tail = node.prev;
        }
        level.total_quantity -= node.quantity;
        --level.count;

        index_.erase(node.id);
        orders_.release(order_index);  // `node` must not be used after this

        if (level.count == 0) {
            remove_level(level_index);
        }
    }

    void remove_level(Index level_index) {
        const Level& level = levels_[level_index];
        Ladder& entries = ladder(level.side);
        const Price key = sort_key(level.side, level.price);
        assert(entries.find(key) == level_index && "missing or incorrect ladder entry");
        entries.erase(key);
        levels_.release(level_index);
    }

    Pool<OrderNode> orders_;
    Pool<Level> levels_;
    Ladder bids_;
    Ladder asks_;
    ankerl::unordered_dense::map<OrderId, Index> index_;
    bool self_trade_prevention_;
    std::uint64_t trades_ = 0;
    std::uint64_t self_trade_cancels_ = 0;
    std::uint64_t orders_rested_ = 0;
};

using OrderBook = BasicOrderBook<VectorLadder>;
using MapOrderBook = BasicOrderBook<MapLadder>;

}  // namespace lobx
