// Shared reader for the workloads used by the replay tool and core benchmarks.
#pragma once

#include <charconv>
#include <cstddef>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include <ankerl/unordered_dense.h>

#include "lobx/types.hpp"

namespace lobx::workload {

inline constexpr Price kUnitsPerCent = kPriceScale / 100;

struct Operation {
    bool is_cancel;
    NewOrder order;  // For a cancel, only order.id is used
};

template <typename Integer>
bool parse_integer(std::string_view text, Integer& value) {
    const char* end = text.data() + text.size();
    const auto result = std::from_chars(text.data(), end, value);
    return result.ec == std::errc{} && result.ptr == end;
}

inline bool parse_order_id(std::string_view text, OrderId& id) {
    if (text.size() < 2 || text.front() != 'O' || (text[1] == '0' && text.size() > 2)) {
        return false;
    }
    return parse_integer(text.substr(1), id);
}

inline std::vector<Operation> load(const std::string& path) {
    std::ifstream file(path);
    if (!file) {
        throw std::runtime_error("can't open " + path);
    }

    std::vector<Operation> operations;
    ankerl::unordered_dense::map<std::string, UserId> user_ids;  // Each new name gets the next number
    std::string line;
    for (std::size_t number = 1; std::getline(file, line); ++number) {
        const auto invalid_line = [&path, number] {
            return std::runtime_error(path + ':' + std::to_string(number) +
                                      ": invalid workload operation");
        };
        std::istringstream row(line);
        std::string kind, order_id, extra;
        Operation operation{};
        if (!(row >> kind >> order_id) || !parse_order_id(order_id, operation.order.id)) {
            throw invalid_line();
        }
        if (kind == "C") {
            operation.is_cancel = true;
        } else if (kind == "N") {
            std::string user_id, side, price_text, quantity_text;
            Price cents;
            Quantity quantity;
            if (!(row >> user_id >> side >> price_text >> quantity_text) ||
                (side != "B" && side != "S") ||
                !parse_integer(price_text, cents) || !parse_integer(quantity_text, quantity) ||
                cents <= 0 ||
                cents > std::numeric_limits<Price>::max() / kUnitsPerCent ||
                quantity <= 0 || quantity > kMaxOrderQuantity) {
                throw invalid_line();
            }
            operation.order.user = user_ids.try_emplace(user_id, user_ids.size()).first->second;
            operation.order.side = side == "B" ? Side::Buy : Side::Sell;
            operation.order.price = cents * kUnitsPerCent;
            operation.order.quantity = quantity;
        } else {
            throw invalid_line();
        }
        if (row >> extra) {
            throw invalid_line();
        }
        operations.push_back(operation);
    }
    if (file.bad() || operations.empty()) {
        throw std::runtime_error("can't read workload operations from " + path);
    }
    return operations;
}

}  // namespace lobx::workload
