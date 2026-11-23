"""
An order book backed by the C++ core, with the same queries as OrderBook.

TradingEngine uses this when LOBX_BACKEND=cpp. It matches and rests orders in
one call (submit), instead of going through MatchingEngine.

Differences from the Python backend:
- Prices must have at most 4 decimal places, and quantities at most 1,000,000,000.
  Anything else raises ValueError.
- Timestamps must be naive (no timezone), and a trade's timestamp is the incoming
  order's timestamp rather than the time it was matched.
- Trade IDs count up per book, as TRD-<symbol>-<n>, instead of being random.
- bids, asks and order_index are read-only snapshots, rebuilt on every access.
"""
from collections import OrderedDict
from decimal import Decimal
from operator import index
from typing import Dict, List, Optional, Tuple

from .book import BookQueries
from .models import Order, OrderStatus, Side, Trade, _build_trusted
from ._native import (
    AVAILABLE,
    MAX_ORDER_QUANTITY,
    IdMap,
    _core,
    micros_to_timestamp,
    price_to_units,
    timestamp_to_micros,
)

BUILD_HINT = (
    "The C++ backend isn't built. On Python 3.10 or newer, run: "
    "python -m pip install --no-build-isolation -e ."
)
_ALL_LEVELS = 2**32 - 1  # The native level pool uses 32-bit indices.
_REJECTED = (_core.SubmitStatus.REJECTED_INVALID, _core.SubmitStatus.REJECTED_DUPLICATE) if AVAILABLE else ()


class NativeOrderBook(BookQueries):
    """
    Limit order book for one symbol, stored in the C++ core.

    The core only knows integers, so this class keeps the mappings back to Python
    values: order IDs for resting orders, user IDs, and each price's Decimal.
    """

    def __init__(self, symbol: str, self_trade_prevention: bool = True):
        if not AVAILABLE:
            raise RuntimeError(BUILD_HINT)
        if not hasattr(_core.OrderBook, "submit_compact"):
            raise RuntimeError("Rebuild the C++ extension with python -m pip install --no-build-isolation -e .")
        self.symbol = symbol
        self._book = _core.OrderBook(self_trade_prevention)
        self._sides = {Side.BUY: _core.Side.BUY, Side.SELL: _core.Side.SELL}

        # Order IDs for resting orders only, so memory doesn't grow with every
        # order ever submitted. Numbers are never reused.
        self._numbers: Dict[str, int] = {}
        self._names: Dict[int, str] = {}
        self._next_number = 0

        self._users = IdMap()
        # The first Decimal seen for each price, so prices come back exactly as
        # they went in (Decimal("150.00"), not Decimal("150.0000")).
        self._prices: Dict[int, Decimal] = {}
        self._units: Dict[Decimal, int] = {}
        self._trade_prefix = f"TRD-{symbol}-"

    # ---- Matching ----

    def submit(self, order: Order) -> List[Trade]:
        """Match a new order against the book and rest whatever is left."""
        if order.symbol != self.symbol:
            raise ValueError(f"Order symbol {order.symbol} doesn't match book {self.symbol}")
        order_id = order.order_id
        numbers = self._numbers
        if order_id in numbers:
            raise ValueError(f"Order {order_id} is already resting")
        try:
            quantity = index(order.quantity)
        except TypeError:
            raise ValueError("Quantity must be an integer") from None
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if quantity > MAX_ORDER_QUANTITY:
            raise ValueError(f"Quantity {quantity} is above {MAX_ORDER_QUANTITY:,}")

        side = self._sides.get(order.side)
        if side is None:
            raise ValueError(f"Unknown order side {order.side!r}")
        price = order.price
        # Only Decimals use the cache, so other inputs still go through validation.
        cacheable = type(price) is Decimal
        cached_units = self._units.get(price) if cacheable else None
        units = cached_units if cached_units is not None else price_to_units(price)
        timestamp = order.timestamp
        micros = timestamp_to_micros(timestamp)

        number = self._next_number
        status, remaining, core_trades, removed = self._book.submit_compact(
            number, self._users.number(order.user_id), side, units, quantity, micros)

        if status in _REJECTED:
            raise ValueError(f"The C++ core rejected order {order_id}: {status.name}")

        self._next_number += 1
        names = self._names
        names[number] = order_id
        if cached_units is None:
            self._prices.setdefault(units, price)
            if cacheable:
                self._units[price] = units
        trades = []
        if core_trades:
            symbol, prefix, prices = self.symbol, self._trade_prefix, self._prices
            user_name = self._users.name
            for trade_id, buy, sell, buyer, seller, trade_price, traded in core_trades:
                trades.append(_build_trusted(Trade, {
                    "trade_id": prefix + str(trade_id),
                    "symbol": symbol,
                    "buy_order_id": names[buy],
                    "sell_order_id": names[sell],
                    "price": prices[trade_price],
                    "quantity": traded,
                    "timestamp": timestamp,
                    "buyer_user_id": user_name(buyer),
                    "seller_user_id": user_name(seller),
                }))

        # Resolve trade names before forgetting the resting orders that left.
        for gone in removed:
            del numbers[names.pop(gone)]

        if remaining > 0:
            numbers[order_id] = number
        else:
            del names[number]
        return trades

    def _forget(self, number: int):
        name = self._names.pop(number)
        del self._numbers[name]

    # ---- Orders ----

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """Cancel an order by ID. Returns it with status CANCELLED, or None if it isn't resting."""
        number = self._numbers.get(order_id)
        if number is None:
            return None
        order = self._order(self._book.find(number), OrderStatus.CANCELLED)
        self._book.cancel(number)
        self._forget(number)
        return order

    def cancel(self, order_id: str) -> bool:
        """Cancel an order when the caller only needs to know whether it existed."""
        number = self._numbers.get(order_id)
        if number is None or not self._book.cancel(number):
            return False
        self._forget(number)
        return True

    def has_order(self, order_id: str) -> bool:
        return order_id in self._numbers

    def get_order(self, order_id: str) -> Optional[Order]:
        number = self._numbers.get(order_id)
        return None if number is None else self._order(self._book.find(number))

    def get_orders_at_price(self, side: Side, price: Decimal) -> List[Order]:
        try:
            units = self._units.get(price) if type(price) is Decimal else None
            if units is None:
                units = price_to_units(price)
        except (TypeError, ValueError):
            return []  # No order can rest at a price the core can't represent
        return [self._order(view) for view in self._book.orders_at(self._sides[side], units)]

    def peek_best_order(self, side: Side) -> Optional[Order]:
        view = self._book.peek_best(self._sides[side])
        return None if view is None else self._order(view)

    def _order(self, view, status: Optional[OrderStatus] = None) -> Order:
        if status is None:
            status = OrderStatus.PARTIAL if view.partially_filled else OrderStatus.OPEN
        return _build_trusted(Order, {
            "order_id": self._names[view.id],
            "user_id": self._users.name(view.user),
            "symbol": self.symbol,
            "side": Side.BUY if view.side == _core.Side.BUY else Side.SELL,
            "price": self._prices[view.price],
            "quantity": view.quantity,
            "timestamp": micros_to_timestamp(view.timestamp),
            "status": status,
        })

    # ---- Prices and levels ----

    def get_best_bid(self) -> Optional[Decimal]:
        units = self._book.best_bid()
        return None if units is None else self._prices[units]

    def get_best_ask(self) -> Optional[Decimal]:
        units = self._book.best_ask()
        return None if units is None else self._prices[units]

    def get_levels(self, side: Side, depth: Optional[int] = None) -> List[Tuple[Decimal, int, int]]:
        """Get (price, total quantity, order count) for each price, best price first."""
        limit = _ALL_LEVELS
        if depth is not None:
            depth = index(depth)
            if depth >= 0:
                limit = min(depth, _ALL_LEVELS)
        levels = self._book.depth(self._sides[side], limit)
        if depth is not None and depth < 0:
            levels = levels[:depth]
        return [(self._prices[level.price], level.quantity, level.order_count) for level in levels]

    def get_statistics(self) -> dict:
        stats = self._book.stats()
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        return {
            "symbol": self.symbol,
            "total_orders": stats.orders_rested,
            "active_orders": stats.active_orders,
            "bid_levels": stats.bid_levels,
            "ask_levels": stats.ask_levels,
            "total_bid_quantity": stats.total_bid_quantity,
            "total_ask_quantity": stats.total_ask_quantity,
            "best_bid": float(best_bid) if best_bid else None,
            "best_ask": float(best_ask) if best_ask else None,
            "self_trade_cancels": stats.self_trade_cancels,
        }

    @property
    def total_orders(self) -> int:
        """Orders that have ever rested in the book, like OrderBook.total_orders."""
        return self._book.stats().orders_rested

    # ---- Read-only snapshots, shaped like OrderBook's attributes ----

    @property
    def bids(self) -> Dict[Decimal, "OrderedDict[str, Order]"]:
        """A copy of the bids: price -> OrderedDict of order_id -> Order, in queue order."""
        return self._snapshot(Side.BUY)

    @property
    def asks(self) -> Dict[Decimal, "OrderedDict[str, Order]"]:
        """A copy of the asks: price -> OrderedDict of order_id -> Order, in queue order."""
        return self._snapshot(Side.SELL)

    @property
    def order_index(self) -> Dict[str, Order]:
        """A copy of every resting order, by ID."""
        return {
            order.order_id: order
            for side in (Side.BUY, Side.SELL)
            for queue in self._snapshot(side).values()
            for order in queue.values()
        }

    def _snapshot(self, side: Side) -> Dict[Decimal, "OrderedDict[str, Order]"]:
        return {
            price: OrderedDict((o.order_id, o) for o in self.get_orders_at_price(side, price))
            for price, _, _ in self.get_levels(side)
        }
