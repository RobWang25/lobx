// A vector of reusable slots, addressed by index.
#pragma once

#include <cassert>
#include <cstddef>
#include <stdexcept>
#include <vector>

#include "lobx/types.hpp"

namespace lobx {

// A template is a recipe the compiler fills in for each type, so Pool<Level> and
// Pool<OrderNode> become two separate classes. T must have an Index member called
// `next`, which links free slots together while they're unused.
template <typename T>
class Pool {
public:
    void reserve(std::size_t count) { slots_.reserve(count); }

    // Returns a free slot. Its contents are left over from earlier use, so the
    // caller must set every field. Growing moves all the slots, so don't hold a
    // T& across a call to acquire().
    Index acquire() {
        if (free_head_ != kNone) {
            const Index index = free_head_;
            free_head_ = slots_[index].next;
            return index;
        }
        if (slots_.size() >= kNone) {
            throw std::length_error("lobx::Pool is full");
        }
        slots_.emplace_back();
        return static_cast<Index>(slots_.size() - 1);
    }

    void release(Index index) {
        slots_[index].next = free_head_;
        free_head_ = index;
    }

    // Two versions: the const one lets read-only code look at slots too.
    T& operator[](Index index) {
        assert(index < slots_.size());
        return slots_[index];
    }
    const T& operator[](Index index) const {
        assert(index < slots_.size());
        return slots_[index];
    }

private:
    std::vector<T> slots_;
    Index free_head_ = kNone;
};

}  // namespace lobx
