"""
Price-time priority tests.

These check the order fills actually happen in, including after partial fills.
The property test compares the engine against ReferenceBook, a deliberately
naive model written separately from lobx, after every operation.
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

import pytest
from hypothesis import given, settings, strategies as st

from lobx.book import OrderBook
from lobx.engine import TradingEngine
from lobx.models import Order, OrderStatus, Side

SYMBOL = "TEST"
NOW = datetime(2026, 1, 1)
PRICE = Decimal("100.00")


def make_order(order_id, user_id, side, quantity, price=PRICE):
    return Order(order_id, user_id, SYMBOL, side, price, quantity, NOW)


def opposite(side):
    return Side.SELL if side == Side.BUY else Side.BUY


def queue_at(engine, side, price=PRICE):
    book = engine.get_book(SYMBOL)
    levels = book.bids if side == Side.BUY else book.asks
    resting = levels[price].values() if price in levels else []
    return [(order.order_id, order.quantity) for order in resting]


@pytest.fixture
def engine():
    return TradingEngine(enable_logging=False)


@pytest.mark.parametrize("resting_side", [Side.BUY, Side.SELL])
class TestPartialFillKeepsPriority:
    """A partially filled resting order must stay at the front of its queue."""

    def rest_two_orders(self, engine, side):
        engine.submit_order(make_order("A", "u1", side, 10))
        engine.submit_order(make_order("B", "u2", side, 10))

    def test_keeps_queue_position(self, engine, resting_side):
        self.rest_two_orders(engine, resting_side)

        engine.submit_order(make_order("X", "u3", opposite(resting_side), 4))

        assert queue_at(engine, resting_side) == [("A", 6), ("B", 10)]

    def test_next_taker_finishes_the_same_order(self, engine, resting_side):
        self.rest_two_orders(engine, resting_side)
        engine.submit_order(make_order("X", "u3", opposite(resting_side), 4))

        trades = engine.submit_order(make_order("Y", "u4", opposite(resting_side), 6))

        resting_ids = [
            trade.sell_order_id if resting_side == Side.SELL else trade.buy_order_id
            for trade in trades
        ]
        assert resting_ids == ["A"]
        assert queue_at(engine, resting_side) == [("B", 10)]

    def test_repeated_partial_fills_stay_at_the_front(self, engine, resting_side):
        self.rest_two_orders(engine, resting_side)

        for index in range(3):
            engine.submit_order(make_order(f"X{index}", "u3", opposite(resting_side), 2))

        assert queue_at(engine, resting_side) == [("A", 4), ("B", 10)]

    def test_order_lookup_shows_remaining_quantity(self, engine, resting_side):
        self.rest_two_orders(engine, resting_side)

        engine.submit_order(make_order("X", "u3", opposite(resting_side), 4))

        order = engine.get_order("A", SYMBOL)
        assert order.quantity == 6
        assert order.status == OrderStatus.PARTIAL

    def test_partial_fill_is_not_counted_as_a_new_order(self, engine, resting_side):
        self.rest_two_orders(engine, resting_side)

        engine.submit_order(make_order("X", "u3", opposite(resting_side), 4))

        assert engine.get_book(SYMBOL).total_orders == 2

    def test_partially_filled_order_can_be_cancelled(self, engine, resting_side):
        self.rest_two_orders(engine, resting_side)
        engine.submit_order(make_order("X", "u3", opposite(resting_side), 4))

        assert engine.cancel_order("A", SYMBOL) is True

        assert queue_at(engine, resting_side) == [("B", 10)]
        assert engine.get_order("A", SYMBOL) is None


def test_threaded_submissions_do_not_corrupt_the_book():
    """Submitting from many threads must conserve volume and never raise."""
    thread_count = 8
    orders_per_thread = 300

    def order_for(thread_id, index):
        side = Side.BUY if (thread_id + index) % 2 else Side.SELL
        return make_order(f"T{thread_id}-{index}", f"u{thread_id}-{index}", side, 7 + index % 5)

    engine = TradingEngine(enable_logging=False)

    def submit_batch(thread_id):
        traded = 0
        for index in range(orders_per_thread):
            for trade in engine.submit_order(order_for(thread_id, index)):
                traded += trade.quantity
        return traded

    # Switching threads as often as possible makes any race far more likely.
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        with ThreadPoolExecutor(max_workers=thread_count) as pool:
            traded = sum(pool.map(submit_batch, range(thread_count)))
    finally:
        sys.setswitchinterval(previous_interval)

    orders = [
        order_for(thread_id, index)
        for thread_id in range(thread_count)
        for index in range(orders_per_thread)
    ]
    book = engine.get_statistics()["books"][SYMBOL]
    bought = sum(order.quantity for order in orders if order.side == Side.BUY)
    sold = sum(order.quantity for order in orders if order.side == Side.SELL)
    assert bought == traded + book["total_bid_quantity"]
    assert sold == traded + book["total_ask_quantity"]


class TestPriceHeapBookkeeping:
    """Each price must appear in the heap once, and be usable again after cleanup."""

    def test_price_can_return_after_lazy_cleanup(self):
        book = OrderBook(SYMBOL)
        book.add_order(make_order("A", "u1", Side.BUY, 10))
        book.cancel_order("A")
        assert book.get_best_bid() is None  # removes the stale price from the heap

        book.add_order(make_order("B", "u2", Side.BUY, 10))

        assert book.get_best_bid() == PRICE

    def test_ask_price_can_return_after_lazy_cleanup(self):
        book = OrderBook(SYMBOL)
        book.add_order(make_order("A", "u1", Side.SELL, 10))
        book.cancel_order("A")
        assert book.get_best_ask() is None

        book.add_order(make_order("B", "u2", Side.SELL, 10))

        assert book.get_best_ask() == PRICE

    def test_level_churn_does_not_grow_the_heap(self):
        book = OrderBook(SYMBOL)
        book.add_order(make_order("TOP", "u1", Side.BUY, 10, Decimal("101.00")))

        # A level below the best is created and emptied repeatedly, so its stale
        # price never reaches the top of the heap to be cleaned up.
        for index in range(100):
            book.add_order(make_order(f"O{index}", "u2", Side.BUY, 1))
            book.cancel_order(f"O{index}")

        assert len(book.bid_prices) == 2


@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
class TestCancelFromAnywhere:
    def test_cancel_does_not_scan_the_queue(self, engine, side, monkeypatch):
        """Cancelling the last of many orders must not compare it with the others."""
        for index in range(100):
            engine.submit_order(make_order(f"o{index}", "u1", side, 1))

        def fail_on_compare(self, other):
            raise AssertionError("cancel compared orders, so it scanned the queue")

        monkeypatch.setattr(Order, "__eq__", fail_on_compare)

        assert engine.cancel_order("o99", SYMBOL)

    def test_cancel_keeps_the_others_in_order(self, engine, side):
        for order_id in "ABCD":
            engine.submit_order(make_order(order_id, "u1", side, 10))
        engine.submit_order(make_order("X", "u2", opposite(side), 4))  # A is now partial

        assert engine.cancel_order("C", SYMBOL)
        assert queue_at(engine, side) == [("A", 6), ("B", 10), ("D", 10)]

        assert engine.cancel_order("A", SYMBOL)  # The partially filled order
        assert queue_at(engine, side) == [("B", 10), ("D", 10)]


class ReferenceBook:
    """Naive price-time book: plain lists, full scans, no shared code with lobx."""

    def __init__(self):
        self.levels = {Side.BUY: {}, Side.SELL: {}}

    def submit(self, order):
        resting_side = opposite(order.side)
        prices = self.levels[resting_side]
        remaining = order.quantity
        fills = []

        while remaining and prices:
            if order.side == Side.BUY:
                best = min(prices)
                if order.price < best:
                    break
            else:
                best = max(prices)
                if order.price > best:
                    break

            queue = prices[best]
            resting_id, resting_qty = queue[0]
            quantity = min(remaining, resting_qty)
            if order.side == Side.BUY:
                fills.append((order.order_id, resting_id, best, quantity))
            else:
                fills.append((resting_id, order.order_id, best, quantity))

            remaining -= quantity
            if quantity == resting_qty:
                queue.pop(0)
                if not queue:
                    del prices[best]
            else:
                queue[0] = (resting_id, resting_qty - quantity)

        if remaining:
            self.levels[order.side].setdefault(order.price, []).append(
                (order.order_id, remaining)
            )
        return fills

    def cancel(self, order_id):
        for prices in self.levels.values():
            for price, queue in prices.items():
                for entry in queue:
                    if entry[0] == order_id:
                        queue.remove(entry)
                        if not queue:
                            del prices[price]
                        return True
        return False


def book_snapshot(engine):
    book = engine.get_book(SYMBOL)
    return {
        side: {
            price: [(order.order_id, order.quantity) for order in queue.values()]
            for price, queue in levels.items()
            if queue
        }
        for side, levels in ((Side.BUY, book.bids), (Side.SELL, book.asks))
    }


new_order_op = st.tuples(
    st.just("new"),
    st.sampled_from([Side.BUY, Side.SELL]),
    st.integers(min_value=9998, max_value=10002),  # few prices, so queues form
    st.integers(min_value=1, max_value=20),
)
cancel_op = st.tuples(st.just("cancel"), st.integers(min_value=0, max_value=1000))


@given(ops=st.lists(st.one_of(new_order_op, new_order_op, cancel_op), max_size=80))
@settings(max_examples=200, deadline=None)
def test_engine_matches_reference_model(ops):
    """Trades, cancels and every queue must match the model after each operation."""
    engine = TradingEngine(enable_logging=False)
    reference = ReferenceBook()
    order_ids = []

    for op in ops:
        if op[0] == "new":
            _, side, cents, quantity = op
            order_id = f"O{len(order_ids)}"
            order_ids.append(order_id)
            # A unique user per order keeps self-trade prevention out of this test.
            order = make_order(order_id, f"u{order_id}", side, quantity, Decimal(cents) / 100)

            trades = engine.submit_order(order)

            actual = [
                (trade.buy_order_id, trade.sell_order_id, trade.price, trade.quantity)
                for trade in trades
            ]
            assert actual == reference.submit(order)
        elif order_ids:
            order_id = order_ids[op[1] % len(order_ids)]
            assert engine.cancel_order(order_id, SYMBOL) == reference.cancel(order_id)
        else:
            continue

        assert book_snapshot(engine) == reference.levels
