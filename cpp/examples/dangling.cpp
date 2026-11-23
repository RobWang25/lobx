// A dangling reference: this program is wrong on purpose, and AddressSanitizer
// stops it with a heap-use-after-free report.
//
// A std::vector keeps its elements in one block of memory. When it runs out of
// room it allocates a bigger block, moves the elements and frees the old block,
// so any reference into the old block now points at freed memory.
//
// This is why the port keeps price levels in a separate pool. The sorted price
// ladder holds level indexes, so orders can refer to a level while the ladder's
// own entries move around.

#include <cstdint>
#include <iostream>
#include <vector>

struct Level {
    std::int64_t price;
    std::int64_t total_quantity;
};

int main() {
    std::vector<Level> ladder{{10000, 5}};  // Room for exactly one element.
    Level& best = ladder[0];

    ladder.push_back({10001, 7});  // No room left, so the elements move.

    std::cout << best.total_quantity << '\n';  // Reads freed memory.
    return 0;
}
