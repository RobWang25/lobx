// Checks that the hot path doesn't allocate once the book has warmed up.
#include <cstddef>
#include <cstdlib>
#include <new>

#include <catch2/catch_test_macros.hpp>

#include "support.hpp"

// Replacing the global operator new means every `new` in this test program, including
// those inside std::vector and the hash map, passes through this counter.
namespace {
std::size_t allocation_count = 0;
}

void* operator new(std::size_t size) {
    ++allocation_count;
    if (void* memory = std::malloc(size == 0 ? 1 : size)) {
        return memory;
    }
    throw std::bad_alloc{};
}

void operator delete(void* memory) noexcept { std::free(memory); }
void operator delete(void* memory, std::size_t) noexcept { std::free(memory); }

using namespace lobx;
using lobx::testing::dollars;
using lobx::testing::make_order;

namespace {

// Uses every path through the book, then leaves it empty.
void exercise(OrderBook& book) {
    NullSink sink;
    const Price base = dollars(100'00);

    // Build a book with 200 price levels and 2,000 orders.
    OrderId id = 1;
    for (int level = 1; level <= 100; ++level) {
        for (int i = 0; i < 10; ++i) {
            const UserId user = static_cast<UserId>(i + 1);
            book.submit(make_order(id++, user, Side::Buy, base - level * 100, 10), sink);
            book.submit(make_order(id++, user, Side::Sell, base + level * 100, 10), sink);
        }
    }

    // Cancel from the middle of queues, and empty a level far from the best price.
    for (OrderId cancelled = 1; cancelled <= 2000; cancelled += 7) {
        book.cancel(cancelled);
    }
    for (OrderId cancelled = 1981; cancelled <= 2000; ++cancelled) {
        book.cancel(cancelled);
    }

    // Partial fill, full fills across levels, a self-trade cancel and a resting remainder.
    book.submit(make_order(id++, 99, Side::Buy, base + 100, 3), sink);
    book.submit(make_order(id++, 1, Side::Buy, base + 300, 200), sink);
    book.submit(make_order(id++, 98, Side::Sell, base - 300, 500), sink);

    // Clear everything out, so the next run starts from an empty book.
    for (OrderId cancelled = 1; cancelled < id; ++cancelled) {
        book.cancel(cancelled);
    }
}

}  // namespace

TEST_CASE("the hot path doesn't allocate after warm-up", "[allocation]") {
    OrderBook book;

    SECTION("the counter sees allocations while the book is growing") {
        const std::size_t before = allocation_count;
        exercise(book);
        CHECK(allocation_count > before);
    }

    SECTION("a second identical run allocates nothing") {
        exercise(book);

        const std::size_t before = allocation_count;
        exercise(book);
        const std::size_t allocations = allocation_count - before;

        CHECK(allocations == 0);
        CHECK(book.stats().active_orders == 0);
    }
}

TEST_CASE("reserving up front avoids allocating at all", "[allocation]") {
    OrderBook book(BookOptions{.expected_orders = 4096, .expected_levels = 512});

    const std::size_t before = allocation_count;
    exercise(book);
    const std::size_t allocations = allocation_count - before;

    CHECK(allocations == 0);
}
