// Plain data types shared by the order book and its callers.
#pragma once

#include <cstdint>
#include <limits>

namespace lobx {

// `using` gives a type a second name. These are all still plain integers, but the
// names show what each value means.
using OrderId = std::uint64_t;  // String IDs get converted to integers in the Python layer
using UserId = std::uint64_t;
using Price = std::int64_t;     // Whole units of 0.0001, so 100.25 is 1'002'500
using Quantity = std::int64_t;
using Timestamp = std::int64_t;  // Supplied by the caller, so replays give identical results

inline constexpr Price kPriceScale = 10'000;

// A position in a Pool. Unlike a pointer or reference, it stays correct when the
// pool's storage moves.
using Index = std::uint32_t;
inline constexpr Index kNone = std::numeric_limits<Index>::max();  // "No element"

// With this cap, a level's total can't overflow even if every possible order
// index sat at one price. static_assert checks this at compile time.
inline constexpr Quantity kMaxOrderQuantity = 1'000'000'000;
static_assert(kMaxOrderQuantity <=
              std::numeric_limits<Quantity>::max() / std::numeric_limits<Index>::max());

// `enum class` values must be written as Side::Buy and don't convert to integers
// by accident.
enum class Side : std::uint8_t { Buy, Sell };

constexpr Side opposite(Side side) { return side == Side::Buy ? Side::Sell : Side::Buy; }

struct NewOrder {
    OrderId id;
    UserId user;
    Side side;
    Price price;
    Quantity quantity;
    Timestamp timestamp;
};

struct Trade {
    std::uint64_t trade_id;  // Counts up from 1 in each book
    OrderId buy_order_id;
    OrderId sell_order_id;
    UserId buyer;
    UserId seller;
    Price price;
    Quantity quantity;
    Timestamp timestamp;  // The incoming order's timestamp
};

enum class SubmitStatus : std::uint8_t {
    Open,              // Nothing traded, all of it is resting
    Partial,           // Some traded, the rest is resting
    Filled,            // All of it traded
    RejectedInvalid,   // Unknown side or price or quantity out of range
    RejectedDuplicate  // This ID is already resting
};

struct SubmitResult {
    SubmitStatus status;
    Quantity remaining;  // Amount left resting in the book
};

// Read-only copies returned by queries. They stay valid after the book changes.
struct OrderView {
    OrderId id;
    UserId user;
    Side side;
    Price price;
    Quantity quantity;
    Timestamp timestamp;
    bool partially_filled;
};

struct LevelView {
    Price price;
    Quantity quantity;
    std::uint32_t order_count;
};

struct BookStats {
    std::uint64_t orders_rested = 0;  // Every order that ever rested, including ones now gone
    std::uint64_t trades = 0;
    std::uint64_t self_trade_cancels = 0;
    std::uint64_t active_orders = 0;
    std::uint64_t bid_levels = 0;
    std::uint64_t ask_levels = 0;
    Quantity total_bid_quantity = 0;
    Quantity total_ask_quantity = 0;
};

}  // namespace lobx
