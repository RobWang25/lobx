// Book behaviour, based on tests/test_book.py.
//
// Not carried over: the wrong-symbol check and update_order, because a C++ book has
// no symbol or index-only update. The pop_best tests are covered through matching.
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "support.hpp"

using namespace lobx;
using lobx::testing::add;
using lobx::testing::dollars;
using lobx::testing::ids_at;
using lobx::testing::make_order;
using Ids = std::vector<OrderId>;

TEST_CASE("adding orders", "[book]") {
    OrderBook book;

    SECTION("a buy order sets the best bid") {
        const auto result = add(book, make_order(1, 1, Side::Buy, dollars(100'00), 10));
        CHECK(result.status == SubmitStatus::Open);
        CHECK(result.remaining == 10);
        CHECK(book.find(1).has_value());
        CHECK(book.best_bid() == dollars(100'00));
        CHECK_FALSE(book.best_ask().has_value());
    }

    SECTION("a sell order sets the best ask") {
        add(book, make_order(1, 1, Side::Sell, dollars(101'00), 15));
        CHECK(book.best_ask() == dollars(101'00));
        CHECK_FALSE(book.best_bid().has_value());
    }

    SECTION("a duplicate ID is rejected and changes nothing") {
        add(book, make_order(1, 1, Side::Buy, dollars(100'00), 10));
        const auto result = add(book, make_order(1, 2, Side::Sell, dollars(100'00), 10));
        CHECK(result.status == SubmitStatus::RejectedDuplicate);
        CHECK(book.stats().trades == 0);
        CHECK(book.stats().active_orders == 1);
    }

    SECTION("out-of-range prices and quantities are rejected") {
        const auto rejected = SubmitStatus::RejectedInvalid;
        CHECK(add(book, make_order(1, 1, Side::Buy, 0, 10)).status == rejected);
        CHECK(add(book, make_order(2, 1, Side::Buy, -1, 10)).status == rejected);
        CHECK(add(book, make_order(3, 1, Side::Buy, 100, 0)).status == rejected);
        CHECK(add(book, make_order(4, 1, Side::Buy, 100, -5)).status == rejected);
        CHECK(add(book, make_order(5, 1, Side::Buy, 100, kMaxOrderQuantity + 1)).status == rejected);
        CHECK(add(book, make_order(6, 1, Side::Buy, 100, kMaxOrderQuantity)).status ==
              SubmitStatus::Open);
        CHECK(book.stats().active_orders == 1);
    }
}

TEST_CASE("best prices", "[book]") {
    OrderBook book;

    SECTION("an empty book has none") {
        CHECK_FALSE(book.best_bid().has_value());
        CHECK_FALSE(book.best_ask().has_value());
        CHECK_FALSE(book.peek_best(Side::Buy).has_value());
        CHECK_FALSE(book.peek_best(Side::Sell).has_value());
    }

    SECTION("the best bid is the highest") {
        add(book, make_order(1, 1, Side::Buy, dollars(100'00), 10));
        add(book, make_order(2, 2, Side::Buy, dollars(99'50), 20));
        add(book, make_order(3, 3, Side::Buy, dollars(100'50), 5));
        CHECK(book.best_bid() == dollars(100'50));
    }

    SECTION("the best ask is the lowest") {
        add(book, make_order(1, 1, Side::Sell, dollars(102'00), 10));
        add(book, make_order(2, 2, Side::Sell, dollars(101'50), 20));
        add(book, make_order(3, 3, Side::Sell, dollars(103'00), 5));
        CHECK(book.best_ask() == dollars(101'50));
    }

    SECTION("the best bid moves when the top order leaves") {
        add(book, make_order(1, 1, Side::Buy, dollars(100'00), 10));
        add(book, make_order(2, 2, Side::Buy, dollars(99'50), 10));
        REQUIRE(book.cancel(1));
        CHECK(book.best_bid() == dollars(99'50));
    }
}

TEST_CASE("cancelling", "[book]") {
    OrderBook book;
    const Price price = dollars(100'00);

    SECTION("an unknown ID returns false") {
        CHECK_FALSE(book.cancel(999));
    }

    SECTION("a cancelled order is gone, and can't be cancelled twice") {
        add(book, make_order(1, 1, Side::Buy, price, 10));
        CHECK(book.cancel(1));
        CHECK_FALSE(book.find(1).has_value());
        CHECK_FALSE(book.cancel(1));
    }

    SECTION("cancelling the last order at a price removes the level") {
        add(book, make_order(1, 1, Side::Buy, price, 10));
        book.cancel(1);
        CHECK(book.stats().bid_levels == 0);
        CHECK(book.orders_at(Side::Buy, price).empty());
    }

    SECTION("an order can be cancelled from any position in the queue") {
        for (OrderId id = 1; id <= 4; ++id) {
            add(book, make_order(id, id, Side::Buy, price, 10));
        }

        book.cancel(2);  // Middle
        CHECK(ids_at(book, Side::Buy, price) == Ids{1, 3, 4});
        book.cancel(1);  // Front
        CHECK(ids_at(book, Side::Buy, price) == Ids{3, 4});
        book.cancel(4);  // Back
        CHECK(ids_at(book, Side::Buy, price) == Ids{3});

        const auto level = book.depth(Side::Buy, 1).at(0);
        CHECK(level.quantity == 10);
        CHECK(level.order_count == 1);
    }

    SECTION("a level far from the best price can be removed") {
        for (int i = 0; i < 5; ++i) {
            add(book, make_order(static_cast<OrderId>(i + 1), 1, Side::Sell, dollars(100'00 + i * 100), 10));
        }
        book.cancel(3);  // 102.00, the middle of the ladder

        const auto levels = book.depth(Side::Sell, 10);
        REQUIRE(levels.size() == 4);
        CHECK(levels[0].price == dollars(100'00));
        CHECK(levels[1].price == dollars(101'00));
        CHECK(levels[2].price == dollars(103'00));
        CHECK(levels[3].price == dollars(104'00));
    }

    SECTION("slots freed by cancels are safely reused") {
        for (OrderId id = 1; id <= 3; ++id) {
            add(book, make_order(id, id, Side::Buy, price, 10));
        }
        book.cancel(2);
        add(book, make_order(4, 4, Side::Buy, price, 7));  // Reuses order 2's slot

        CHECK(ids_at(book, Side::Buy, price) == Ids{1, 3, 4});
        CHECK(book.find(4)->quantity == 7);
    }
}

TEST_CASE("orders at a price stay in arrival order", "[book]") {
    OrderBook book;
    const Price price = dollars(100'00);
    for (OrderId id = 1; id <= 5; ++id) {
        add(book, make_order(id, id, Side::Buy, price, 10));
    }

    CHECK(ids_at(book, Side::Buy, price) == Ids{1, 2, 3, 4, 5});

    const auto first = book.peek_best(Side::Buy);
    const auto again = book.peek_best(Side::Buy);
    REQUIRE(first.has_value());
    CHECK(first->id == 1);
    CHECK(again->id == 1);  // Peeking doesn't remove anything
    CHECK(book.stats().active_orders == 5);
}

TEST_CASE("depth", "[book]") {
    OrderBook book;

    SECTION("reports levels best-first on both sides") {
        OrderId id = 1;
        for (const Price price : {dollars(100'00), dollars(99'50), dollars(99'00)}) {
            add(book, make_order(id++, 1, Side::Buy, price, 10));
        }
        for (const Price price : {dollars(101'00), dollars(101'50), dollars(102'00)}) {
            add(book, make_order(id++, 2, Side::Sell, price, 15));
        }

        const auto bids = book.depth(Side::Buy, 3);
        const auto asks = book.depth(Side::Sell, 3);
        REQUIRE(bids.size() == 3);
        REQUIRE(asks.size() == 3);
        CHECK(bids[0].price == dollars(100'00));
        CHECK(asks[0].price == dollars(101'00));
        CHECK(book.spread() == dollars(1'00));
    }

    SECTION("adds up the orders at each price") {
        for (OrderId id = 1; id <= 3; ++id) {
            add(book, make_order(id, id, Side::Buy, dollars(100'00), 10));
        }
        const auto levels = book.depth(Side::Buy, 5);
        REQUIRE(levels.size() == 1);
        CHECK(levels[0].quantity == 30);
        CHECK(levels[0].order_count == 3);
    }

    SECTION("stops at the requested number of levels") {
        for (int i = 0; i < 10; ++i) {
            add(book, make_order(static_cast<OrderId>(i + 1), 1, Side::Buy, dollars(100'00 - i * 100), 10));
        }
        const auto levels = book.depth(Side::Buy, 3);
        REQUIRE(levels.size() == 3);
        CHECK(levels[0].price == dollars(100'00));
        CHECK(levels[1].price == dollars(99'00));
        CHECK(levels[2].price == dollars(98'00));
    }
}

TEST_CASE("spread needs both sides", "[book]") {
    OrderBook book;
    CHECK_FALSE(book.spread().has_value());

    add(book, make_order(1, 1, Side::Buy, dollars(100'00), 10));
    CHECK_FALSE(book.spread().has_value());

    add(book, make_order(2, 2, Side::Sell, dollars(101'50), 10));
    CHECK(book.spread() == dollars(1'50));
}

TEST_CASE("statistics", "[book]") {
    OrderBook book;
    for (OrderId id = 1; id <= 5; ++id) {
        add(book, make_order(id, id, Side::Buy, dollars(100'00), 10));
    }

    SECTION("count resting orders and quantity") {
        const BookStats stats = book.stats();
        CHECK(stats.orders_rested == 5);
        CHECK(stats.active_orders == 5);
        CHECK(stats.total_bid_quantity == 50);
        CHECK(stats.bid_levels == 1);
    }

    SECTION("update after cancels") {
        book.cancel(1);
        book.cancel(2);
        const BookStats stats = book.stats();
        CHECK(stats.orders_rested == 5);  // Doesn't go down
        CHECK(stats.active_orders == 3);
        CHECK(stats.total_bid_quantity == 30);
    }
}

TEST_CASE("a copied book is independent of the original", "[book]") {
    // The book holds indexes rather than pointers, so the compiler-generated copy
    // is correct: the copy's indexes refer to the copy's own pools.
    OrderBook original;
    add(original, make_order(1, 1, Side::Buy, dollars(100'00), 10));
    add(original, make_order(2, 2, Side::Buy, dollars(100'00), 10));

    OrderBook copy = original;
    copy.cancel(1);

    CHECK(ids_at(original, Side::Buy, dollars(100'00)) == Ids{1, 2});
    CHECK(ids_at(copy, Side::Buy, dollars(100'00)) == Ids{2});
}
