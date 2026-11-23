// The two ways the book can keep one side's prices in order.
//
// Each ladder maps a sort key to a level's pool index. A bigger key always means a
// better price (OrderBook uses -price for asks), so "best" is the biggest key.
// OrderBook takes the ladder as a template argument, so the benchmarks can compare
// both with everything else identical.
#pragma once

#include <algorithm>
#include <cstddef>
#include <iterator>
#include <map>
#include <vector>

#include "lobx/types.hpp"

namespace lobx {

// A sorted vector, best price at the back. Contiguous and cache-friendly, and the
// best level is removed with pop_back. Adding or removing a level far from the best
// price shifts every entry after it, which is O(L) for L levels.
class VectorLadder {
public:
    void reserve(std::size_t count) { entries_.reserve(count); }
    bool empty() const { return entries_.empty(); }
    std::size_t size() const { return entries_.size(); }
    Index best() const { return entries_.back().level; }

    // The level with this key, or kNone.
    Index find(Price key) const {
        const auto position = lower_bound(key);
        return position != entries_.end() && position->key == key ? position->level : kNone;
    }

    // Returns the level with this key. If there isn't one, calls make_level() to
    // create it and inserts that. One binary search either way.
    template <typename MakeLevel>
    Index find_or_insert(Price key, MakeLevel&& make_level) {
        const auto position = lower_bound(key);
        if (position != entries_.end() && position->key == key) {
            return position->level;
        }
        const Index level = make_level();
        entries_.insert(position, Entry{key, level});
        return level;
    }

    void erase(Price key) {
        if (entries_.back().key == key) {
            entries_.pop_back();  // The best level: nothing to shift
        } else {
            entries_.erase(lower_bound(key));
        }
    }

    // Calls visit(level) from the best price down, until it returns false.
    template <typename Visit>
    void for_each_best_first(Visit&& visit) const {
        for (auto entry = entries_.rbegin(); entry != entries_.rend(); ++entry) {
            if (!visit(entry->level)) {
                return;
            }
        }
    }

private:
    struct Entry {
        Price key;
        Index level;
    };

    std::vector<Entry>::const_iterator lower_bound(Price key) const {
        return std::lower_bound(entries_.begin(), entries_.end(), key,
                                [](const Entry& entry, Price wanted) { return entry.key < wanted; });
    }

    std::vector<Entry> entries_;
};

// A std::map: a balanced binary tree with one heap-allocated node per level.
// Adding and removing a level is O(log L) wherever it is, but each new level
// allocates, and following tree pointers is slower than walking a vector.
class MapLadder {
public:
    void reserve(std::size_t) {}  // A map can't reserve nodes in advance
    bool empty() const { return levels_.empty(); }
    std::size_t size() const { return levels_.size(); }
    Index best() const { return std::prev(levels_.end())->second; }

    Index find(Price key) const {
        const auto found = levels_.find(key);
        return found != levels_.end() ? found->second : kNone;
    }

    template <typename MakeLevel>
    Index find_or_insert(Price key, MakeLevel&& make_level) {
        const auto position = levels_.lower_bound(key);
        if (position != levels_.end() && position->first == key) {
            return position->second;
        }
        // The hint tells the map where the new node goes, saving a second search.
        return levels_.emplace_hint(position, key, make_level())->second;
    }

    void erase(Price key) { levels_.erase(key); }

    template <typename Visit>
    void for_each_best_first(Visit&& visit) const {
        for (auto entry = levels_.rbegin(); entry != levels_.rend(); ++entry) {
            if (!visit(entry->second)) {
                return;
            }
        }
    }

private:
    std::map<Price, Index> levels_;
};

}  // namespace lobx
