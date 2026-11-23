#!/usr/bin/env python3
"""Time individual C++ wrapper steps with prepared data."""
import json
import platform
import statistics
import sys
import timeit
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lobx import models  # noqa: E402
from lobx._native import _core, price_to_units, timestamp_to_micros  # noqa: E402
from lobx.models import Order, OrderStatus, Side, Trade  # noqa: E402
from lobx.native_book import NativeOrderBook  # noqa: E402


def main():
    if _core is None:
        sys.exit("Build lobx._core before timing the wrapper")

    timestamp = datetime(2026, 1, 1)
    price = Decimal("100.25")
    units = price_to_units(price)
    units_by_price = {price: units}
    order = Order("O1", "seller", "BENCH", Side.SELL, price, 5, timestamp)
    order_fields = order.__dict__
    trade_fields = Trade("T1", "BENCH", "O2", "O1", price, 5, timestamp, "buyer", "seller").__dict__
    core_book = _core.OrderBook()
    core_book.submit(1, 1, _core.Side.SELL, units, 5)
    trade = core_book.submit(2, 2, _core.Side.BUY, units, 5)[2][0]
    trade_tuple = (trade.trade_id, trade.buy_order_id, trade.sell_order_id, trade.buyer,
                   trade.seller, trade.price, trade.quantity)
    core_book.submit(1, 1, _core.Side.SELL, units, 5)
    reconstruction_book = NativeOrderBook("BENCH")
    reconstruction_book.submit(order)
    order_view = reconstruction_book._book.find(0)
    native = NativeOrderBook("BENCH")
    native.submit(order)

    def cross_pair(submit):
        submit(3, 1, _core.Side.SELL, units, 5)
        submit(4, 2, _core.Side.BUY, units, 5)

    def wrapper_pair():
        native.cancel_order("O1")
        native.submit(order)

    def wrapper_boolean_pair():
        native.cancel("O1")
        native.submit(order)

    cases = {
        "price_to_units": "price_to_units(price)",
        "price_cache_lookup": "units_by_price.get(price)",
        "timestamp_to_micros": "timestamp_to_micros(timestamp)",
        "trade_dataclass": "Trade(**trade_fields)",
        "order_dataclass": "Order(**order_fields)",
        "trade_field_reads": "a,b,c,d,e,f,g = trade.trade_id,trade.buy_order_id,trade.sell_order_id,trade.buyer,trade.seller,trade.price,trade.quantity",
        "trade_tuple_unpack": "a,b,c,d,e,f,g = trade_tuple",
        "find_resting_order": "core_book.find(1)",
        "raw_binding_submit_pair": "cross_pair(raw_submit)",
        "wrapper_submit_cancel_pair": "wrapper_pair()",
    }
    raw_submit = _core.OrderBook().submit
    if hasattr(native, "cancel"):
        cases["wrapper_submit_boolean_cancel_pair"] = "wrapper_boolean_pair()"
    if hasattr(core_book, "submit_compact"):
        compact_submit = _core.OrderBook().submit_compact
        cases["compact_binding_submit_pair"] = "cross_pair(compact_submit)"
        cases["contains_resting_order"] = "core_book.contains(1)"
    if hasattr(models, "_build_trusted"):
        trusted = models._build_trusted
        cases["trade_trusted"] = "trusted(Trade, dict(trade_fields))"
        cases["order_trusted"] = "trusted(Order, dict(order_fields))"
        cases["cancelled_order_construction"] = "reconstruction_book._order(order_view, OrderStatus.CANCELLED)"
    else:
        cases["cancelled_order_construction"] = "reconstruction_book._order(order_view).with_status(OrderStatus.CANCELLED)"

    repetitions, iterations = 5, 100_000
    scope = {**globals(), **locals()}
    results = {
        name: round(statistics.median(timeit.repeat(statement, globals=scope,
                                                  repeat=repetitions, number=iterations)) * 1e9 / iterations, 1)
        for name, statement in cases.items()
    }
    print(json.dumps({"python": platform.python_version(), "repetitions": repetitions,
                      "iterations": iterations, "ns_per_sample": results}, indent=2))


if __name__ == "__main__":
    main()
