// Copies vs references, using the partial fill from lobx as the example.
//
// In Python, `order = queue[0]` gives another name for the same object. In C++,
// plain assignment makes a separate copy, and you ask for a reference with `&`.

#include <cstdint>
#include <deque>
#include <iostream>

// A struct stores its fields directly, with no per-object header or dictionary.
struct Order {
    std::uint64_t id;
    std::int64_t quantity;
};

// `const std::deque<Order>&` means: use the caller's queue without copying it,
// and promise not to change it.
void print_queue(const char* label, const std::deque<Order>& queue) {
    std::cout << label << ':';
    for (const Order& order : queue) {
        std::cout << " (id=" << order.id << " qty=" << order.quantity << ')';
    }
    std::cout << '\n';
}

int main() {
    std::deque<Order> level{{1, 10}, {2, 10}};
    print_queue("start                 ", level);

    Order copy = level.front();  // A separate Order; the queue can't see changes to it.
    copy.quantity -= 4;
    print_queue("after changing a copy ", level);

    Order& front = level.front();  // Another name for the Order inside the queue.
    front.quantity -= 4;
    print_queue("after changing a ref  ", level);

    std::cout << "sizeof(Order) = " << sizeof(Order) << " bytes\n";
    return 0;
}
