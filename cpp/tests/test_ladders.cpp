// The two ladders must give identical results. Only their speed may differ.
#include <cstdint>
#include <random>
#include <utility>
#include <vector>

#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_template_test_macros.hpp>
#include <catch2/generators/catch_generators.hpp>

#include "support.hpp"

using namespace lobx;
using lobx::testing::RecordingSink;

namespace {

// Everything a book can report about its current state.
template <typename Book>
std::vector<std::pair<LevelView, std::vector<OrderView>>> full_book(const Book& book) {
    std::vector<std::pair<LevelView, std::vector<OrderView>>> levels;
    for (const Side side : {Side::Buy, Side::Sell}) {
        for (const LevelView& level : book.depth(side, 1'000'000)) {
            levels.emplace_back(level, book.orders_at(side, level.price));
        }
    }
    return levels;
}

}  // namespace

TEMPLATE_TEST_CASE("erasing a missing level leaves the ladder intact", "[ladder]",
                   VectorLadder, MapLadder) {
    TestType ladder;
    ladder.erase(100);
    ladder.find_or_insert(100, [] { return Index{1}; });
    ladder.erase(99);
    ladder.erase(101);
    REQUIRE(ladder.size() == 1);
    CHECK(ladder.best() == 1);
}

TEST_CASE("the vector and map ladders make identical decisions", "[ladder]") {
    // Narrow prices make long queues and frequent crosses. Wide prices make many
    // levels, so levels get added and removed far from the best price.
    const std::int64_t price_range = GENERATE(5, 2'000);
    const std::uint64_t seed = GENERATE(1u, 2u, 3u);

    OrderBook vector_book;
    MapOrderBook map_book;
    RecordingSink vector_sink;
    RecordingSink map_sink;

    std::mt19937_64 random(seed);  // A seeded generator, so failures repeat
    auto pick = [&](std::int64_t low, std::int64_t high) {
        return std::uniform_int_distribution<std::int64_t>(low, high)(random);
    };

    OrderId next_id = 1;
    for (int step = 0; step < 20'000; ++step) {
        if (next_id > 1 && pick(0, 9) < 3) {
            const auto id = static_cast<OrderId>(pick(1, static_cast<std::int64_t>(next_id) - 1));
            REQUIRE(vector_book.cancel(id) == map_book.cancel(id));
        } else {
            const NewOrder order{next_id++, static_cast<UserId>(pick(1, 5)),
                                 pick(0, 1) == 0 ? Side::Buy : Side::Sell,
                                 1'000'000 + pick(0, price_range) * 100, pick(1, 50), step};
            vector_sink.trades.clear();
            map_sink.trades.clear();
            REQUIRE(vector_book.submit(order, vector_sink) == map_book.submit(order, map_sink));
            REQUIRE(vector_sink.trades == map_sink.trades);
        }
        if (step % 500 == 0) {
            REQUIRE(full_book(vector_book) == full_book(map_book));
        }
    }

    REQUIRE(full_book(vector_book) == full_book(map_book));
    REQUIRE(vector_book.stats() == map_book.stats());
    REQUIRE(vector_sink.self_trade_cancels == map_sink.self_trade_cancels);
}
