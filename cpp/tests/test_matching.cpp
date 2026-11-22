// Matching behaviour, based on tests/test_matching.py and tests/test_fifo.py.
//
// One difference from Python: a filled order reports remaining == 0, where the
// Python order keeps its original quantity.
#include <vector>

#include <catch2/catch_test_macros.hpp>
#include <catch2/generators/catch_generators.hpp>

#include "support.hpp"

using namespace lobx;
using lobx::testing::add;
using lobx::testing::dollars;
using lobx::testing::ids_at;
using lobx::testing::make_order;
using lobx::testing::RecordingSink;
using Ids = std::vector<OrderId>;

TEST_CASE("basic matching", "[matching]") {
    OrderBook book;
    RecordingSink sink;

    SECTION("no trade when the buy price is below the ask") {
        add(book, make_order(1, 1, Side::Sell, dollars(101'00), 100));
        const auto result = book.submit(make_order(2, 2, Side::Buy, dollars(100'00), 50), sink);

        CHECK(sink.trades.empty());
        CHECK(result.status == SubmitStatus::Open);
        CHECK(result.remaining == 50);
        CHECK(book.best_bid() == dollars(100'00));
    }

    SECTION("an exact match fills both orders") {
        add(book, make_order(1, 1, Side::Sell, dollars(100'00), 50));
        const auto result = book.submit(make_order(2, 2, Side::Buy, dollars(100'00), 50), sink);

        REQUIRE(sink.trades.size() == 1);
        const Trade& trade = sink.trades[0];
        CHECK(trade.trade_id == 1);
        CHECK(trade.buy_order_id == 2);
        CHECK(trade.sell_order_id == 1);
        CHECK(trade.buyer == 2);
        CHECK(trade.seller == 1);
        CHECK(trade.price == dollars(100'00));
        CHECK(trade.quantity == 50);
        CHECK(trade.timestamp == 2);
        CHECK(result.status == SubmitStatus::Filled);
        CHECK(result.remaining == 0);
        CHECK(book.stats().active_orders == 0);
    }

    SECTION("a larger buyer fills what it can and rests the rest") {
        add(book, make_order(1, 1, Side::Sell, dollars(100'00), 30));
        const auto result = book.submit(make_order(2, 2, Side::Buy, dollars(100'00), 100), sink);

        REQUIRE(sink.trades.size() == 1);
        CHECK(sink.trades[0].quantity == 30);
        CHECK(result.status == SubmitStatus::Partial);
        CHECK(result.remaining == 70);

        const auto resting = book.find(2);
        REQUIRE(resting.has_value());
        CHECK(resting->quantity == 70);
        CHECK(resting->partially_filled);
    }

    SECTION("a smaller seller leaves the resting buyer partially filled") {
        add(book, make_order(1, 1, Side::Buy, dollars(100'00), 100));
        const auto result = book.submit(make_order(2, 2, Side::Sell, dollars(100'00), 40), sink);

        REQUIRE(sink.trades.size() == 1);
        CHECK(sink.trades[0].quantity == 40);
        CHECK(sink.trades[0].buy_order_id == 1);
        CHECK(result.status == SubmitStatus::Filled);

        const auto resting = book.find(1);
        REQUIRE(resting.has_value());
        CHECK(resting->quantity == 60);
        CHECK(resting->partially_filled);
        CHECK(book.depth(Side::Buy, 1).at(0).quantity == 60);
    }

    SECTION("an order against an empty book just rests") {
        const auto result = book.submit(make_order(1, 1, Side::Buy, dollars(100'00), 50), sink);
        CHECK(sink.trades.empty());
        CHECK(result.remaining == 50);
    }

    SECTION("trades happen at the resting order's price") {
        add(book, make_order(1, 1, Side::Sell, dollars(100'00), 50));
        book.submit(make_order(2, 2, Side::Buy, dollars(110'00), 50), sink);

        REQUIRE(sink.trades.size() == 1);
        CHECK(sink.trades[0].price == dollars(100'00));
    }

    SECTION("trade IDs count up") {
        add(book, make_order(1, 1, Side::Sell, dollars(100'00), 10));
        add(book, make_order(2, 2, Side::Sell, dollars(100'00), 10));
        book.submit(make_order(3, 3, Side::Buy, dollars(100'00), 20), sink);

        REQUIRE(sink.trades.size() == 2);
        CHECK(sink.trades[0].trade_id == 1);
        CHECK(sink.trades[1].trade_id == 2);
        CHECK(book.stats().trades == 2);
    }
}

TEST_CASE("price-time priority", "[matching]") {
    OrderBook book;
    RecordingSink sink;

    SECTION("the best price trades first") {
        add(book, make_order(1, 1, Side::Sell, dollars(102'00), 50));
        add(book, make_order(2, 2, Side::Sell, dollars(101'00), 50));
        add(book, make_order(3, 3, Side::Sell, dollars(103'00), 50));
        book.submit(make_order(4, 4, Side::Buy, dollars(105'00), 50), sink);

        REQUIRE(sink.trades.size() == 1);
        CHECK(sink.trades[0].price == dollars(101'00));
    }

    SECTION("the highest bid trades first") {
        add(book, make_order(1, 1, Side::Buy, dollars(100'00), 50));
        add(book, make_order(2, 2, Side::Buy, dollars(101'00), 50));
        book.submit(make_order(3, 3, Side::Sell, dollars(99'00), 50), sink);

        REQUIRE(sink.trades.size() == 1);
        CHECK(sink.trades[0].price == dollars(101'00));
    }

    SECTION("the earliest order at a price trades first") {
        add(book, make_order(1, 1, Side::Sell, dollars(100'00), 20));
        add(book, make_order(2, 2, Side::Sell, dollars(100'00), 30));
        add(book, make_order(3, 3, Side::Sell, dollars(100'00), 40));
        book.submit(make_order(4, 4, Side::Buy, dollars(100'00), 45), sink);

        REQUIRE(sink.trades.size() == 2);
        CHECK(sink.trades[0].sell_order_id == 1);
        CHECK(sink.trades[0].quantity == 20);
        CHECK(sink.trades[1].sell_order_id == 2);
        CHECK(sink.trades[1].quantity == 25);
    }

    SECTION("a large order walks up through several prices") {
        add(book, make_order(1, 1, Side::Sell, dollars(100'00), 50));
        add(book, make_order(2, 2, Side::Sell, dollars(101'00), 50));
        add(book, make_order(3, 3, Side::Sell, dollars(102'00), 50));
        const auto result = book.submit(make_order(4, 4, Side::Buy, dollars(102'00), 120), sink);

        REQUIRE(sink.trades.size() == 3);
        CHECK(sink.trades[0].price == dollars(100'00));
        CHECK(sink.trades[1].price == dollars(101'00));
        CHECK(sink.trades[2].price == dollars(102'00));
        CHECK(sink.trades[2].quantity == 20);
        CHECK(result.status == SubmitStatus::Filled);
        CHECK(book.best_ask() == dollars(102'00));
    }
}

TEST_CASE("a partially filled order keeps its place", "[matching]") {
    const Side side = GENERATE(Side::Buy, Side::Sell);  // Runs the test once for each
    OrderBook book;
    RecordingSink sink;
    const Price price = dollars(100'00);

    add(book, make_order(1, 1, side, price, 10));
    add(book, make_order(2, 2, side, price, 10));

    book.submit(make_order(3, 3, opposite(side), price, 4), sink);
    CHECK(ids_at(book, side, price) == Ids{1, 2});
    CHECK(book.find(1)->quantity == 6);

    // The next taker finishes the same order.
    sink.trades.clear();
    book.submit(make_order(4, 4, opposite(side), price, 6), sink);
    REQUIRE(sink.trades.size() == 1);
    const OrderId resting = side == Side::Sell ? sink.trades[0].sell_order_id
                                               : sink.trades[0].buy_order_id;
    CHECK(resting == 1);
    CHECK(ids_at(book, side, price) == Ids{2});

    // A partially filled order can still be cancelled, and the level total stays right.
    book.submit(make_order(5, 5, opposite(side), price, 3), sink);
    CHECK(book.cancel(2));
    CHECK(book.stats().active_orders == 0);
    CHECK(book.depth(side, 1).empty());
}

TEST_CASE("self-trade prevention", "[matching]") {
    const UserId alice = 1;
    const UserId bob = 2;
    const Price price = dollars(100'00);
    RecordingSink sink;

    SECTION("enabled: the resting order is cancelled and reported") {
        OrderBook book;
        add(book, make_order(1, alice, Side::Sell, price, 50));
        const auto result = book.submit(make_order(2, alice, Side::Buy, price, 50), sink);

        CHECK(sink.trades.empty());
        CHECK(sink.self_trade_cancels == Ids{1});
        CHECK(book.stats().self_trade_cancels == 1);
        CHECK_FALSE(book.find(1).has_value());
        CHECK(result.status == SubmitStatus::Open);
        CHECK(book.best_bid() == price);
    }

    SECTION("enabled: matching continues with the next order") {
        OrderBook book;
        add(book, make_order(1, alice, Side::Sell, price, 50));
        add(book, make_order(2, bob, Side::Sell, price, 50));
        const auto result = book.submit(make_order(3, alice, Side::Buy, price, 50), sink);

        CHECK(sink.self_trade_cancels == Ids{1});
        REQUIRE(sink.trades.size() == 1);
        CHECK(sink.trades[0].sell_order_id == 2);
        CHECK(result.status == SubmitStatus::Filled);
    }

    SECTION("disabled: a user can trade with themselves") {
        OrderBook book(BookOptions{.self_trade_prevention = false});
        add(book, make_order(1, alice, Side::Sell, price, 50));
        book.submit(make_order(2, alice, Side::Buy, price, 50), sink);

        CHECK(sink.trades.size() == 1);
        CHECK(sink.self_trade_cancels.empty());
    }
}

TEST_CASE("an ID can be used again once its order has left", "[matching]") {
    OrderBook book;
    add(book, make_order(1, 1, Side::Buy, dollars(100'00), 10));
    book.cancel(1);
    CHECK(add(book, make_order(1, 1, Side::Buy, dollars(100'00), 10)).status == SubmitStatus::Open);
}
