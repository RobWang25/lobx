"""
Tests for the C++ core (lobx._core) and its Python conversions.

The core is optional, so its tests are skipped unless the package has been built:
    .venv/bin/python -m pip install --no-build-isolation -e .
"""
import random
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from lobx._native import AVAILABLE, IdMap, _core, price_to_units, units_to_price
from lobx.models import Side

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench"))
import differential  # noqa: E402

needs_core = pytest.mark.skipif(not AVAILABLE, reason="lobx._core isn't built")


class TestPriceConversion:
    def test_round_trip(self):
        assert price_to_units(Decimal("100.25")) == 1_002_500
        assert price_to_units(Decimal("0.0001")) == 1
        assert units_to_price(1_002_500) == Decimal("100.25")

    @pytest.mark.parametrize("price", ["100.00001", "0.00005"])
    def test_rejects_more_than_four_decimals(self, price):
        with pytest.raises(ValueError, match="decimal places"):
            price_to_units(Decimal(price))

    @pytest.mark.parametrize("price", ["0", "-1", "1e20"])
    def test_rejects_out_of_range(self, price):
        with pytest.raises(ValueError, match="out of range"):
            price_to_units(Decimal(price))


class TestIdMap:
    def test_assigns_stable_numbers_in_first_seen_order(self):
        ids = IdMap()
        assert [ids.number(name) for name in ("a", "b", "a", "c")] == [0, 1, 0, 2]
        assert ids.name(1) == "b"
        assert len(ids) == 3

    def test_lookup_doesnt_assign(self):
        ids = IdMap()
        assert ids.lookup("missing") is None
        assert len(ids) == 0


@pytest.fixture
def core():
    return _core


# A fixture rather than an attribute on self: pytest keeps test objects alive until
# it exits, and nanobind reports any C++ objects still alive at exit as leaks.
@pytest.fixture
def book(core):
    return core.OrderBook()


@needs_core
class TestBindings:
    def test_trade_fields_come_through(self, core, book):
        assert book.submit(1, 10, core.Side.SELL, 1_000_000, 10)[0] == core.SubmitStatus.OPEN

        status, remaining, trades, cancels = book.submit(
            2, 20, core.Side.BUY, 1_000_000, 4, timestamp=99)

        assert status == core.SubmitStatus.FILLED
        assert remaining == 0
        assert cancels == []
        [trade] = trades
        assert (trade.trade_id, trade.buy_order_id, trade.sell_order_id) == (1, 2, 1)
        assert (trade.buyer, trade.seller, trade.price, trade.quantity) == (20, 10, 1_000_000, 4)
        assert trade.timestamp == 99

    def test_queries(self, core, book):
        assert book.best_bid() is None
        book.submit(1, 10, core.Side.BUY, 990_000, 5)
        book.submit(2, 11, core.Side.SELL, 1_010_000, 7)

        assert book.best_bid() == 990_000
        assert book.spread() == 20_000
        assert book.find(2).quantity == 7
        assert book.find(3) is None
        assert book.peek_best(core.Side.BUY).id == 1
        assert [level.price for level in book.depth(core.Side.SELL, 5)] == [1_010_000]
        assert book.stats().active_orders == 2
        assert book.cancel(1) is True
        assert book.cancel(1) is False

    def test_self_trade_cancels_are_reported(self, core, book):
        book.submit(1, 10, core.Side.SELL, 1_000_000, 5)
        status, _, trades, cancels = book.submit(2, 10, core.Side.BUY, 1_000_000, 5)
        assert (status, trades, cancels) == (core.SubmitStatus.OPEN, [], [1])

    def test_submit_compact_reports_orders_that_left_the_book(self, core, book):
        book.submit(1, 10, core.Side.SELL, 1_000_000, 3)
        book.submit(2, 11, core.Side.SELL, 1_000_000, 5)
        book.submit(3, 20, core.Side.SELL, 1_000_000, 5)  # Same user as the buyer below
        book.submit(4, 12, core.Side.SELL, 1_000_000, 5)

        # Buys 3 from order 1 and 5 from order 2, cancels order 3 as a self-trade,
        # then buys the last 1 from order 4.
        status, remaining, trades, removed = book.submit_compact(
            5, 20, core.Side.BUY, 1_000_000, 9)

        assert (status, remaining) == (core.SubmitStatus.FILLED, 0)
        # (trade_id, buy_order_id, sell_order_id, buyer, seller, price, quantity)
        assert trades == [(1, 5, 1, 20, 10, 1_000_000, 3), (2, 5, 2, 20, 11, 1_000_000, 5),
                          (3, 5, 4, 20, 12, 1_000_000, 1)]
        # 1 and 2 were used up and 3 was a self-trade. 4 still rests with 4 left.
        assert sorted(removed) == [1, 2, 3]
        assert book.contains(4) and not book.contains(3)
        assert book.find(4).quantity == 4

    def test_rejections(self, core, book):
        too_big = core.MAX_ORDER_QUANTITY + 1
        assert book.submit(1, 1, core.Side.BUY, 100, too_big)[0] == core.SubmitStatus.REJECTED_INVALID
        book.submit(2, 1, core.Side.BUY, 100, 1)
        assert book.submit(2, 1, core.Side.BUY, 100, 1)[0] == core.SubmitStatus.REJECTED_DUPLICATE

    def test_negative_ids_are_refused_by_the_binding(self, core, book):
        with pytest.raises(TypeError):
            book.submit(-1, 1, core.Side.BUY, 100, 1)

    def test_constants_match_python(self, core, book):
        from lobx import _native
        assert core.PRICE_SCALE == _native.PRICE_SCALE
        assert core.MAX_ORDER_QUANTITY == _native.MAX_ORDER_QUANTITY


@needs_core
class TestDifferential:
    """The C++ core must make exactly the same decisions as the Python engine."""

    def test_the_comparison_notices_a_difference(self):
        ops = [("new", "A", "u1", Side.SELL, Decimal("100"), 5),
               ("new", "B", "u1", Side.BUY, Decimal("100"), 5)]
        python = differential.PythonSide(self_trade_prevention=True)
        cpp = differential.CppSide(self_trade_prevention=False)  # Deliberately different
        results = [(python.new(*op[1:]), cpp.new(*op[1:])) for op in ops]
        assert results[1][0] != results[1][1]

    @pytest.mark.parametrize("regime", sorted(differential.REGIMES))
    def test_seeded_random_operations(self, regime):
        settings_ = dict(differential.REGIMES[regime])
        stp = settings_.pop("stp", True)
        ops = differential.random_ops(random.Random(regime), 4_000, **settings_)
        result = differential.compare(ops, self_trade_prevention=stp, snapshot_every=50)
        assert result["trades"] > 0

    @settings(max_examples=300, deadline=None)
    @given(
        ops=st.lists(
            st.one_of(
                st.tuples(
                    st.just("new"),
                    st.sampled_from(["u0", "u1", "u2"]),
                    st.sampled_from([Side.BUY, Side.SELL]),
                    st.integers(min_value=9998, max_value=10002),
                    st.integers(min_value=1, max_value=20),
                ),
                st.tuples(st.just("cancel"), st.integers(min_value=0, max_value=60)),
            ),
            max_size=60,
        ),
        stp=st.booleans(),
    )
    def test_matches_python_after_every_operation(self, ops, stp):
        numbered = []
        for index, op in enumerate(ops):
            if op[0] == "new":
                _, user, side, cents, quantity = op
                numbered.append(("new", f"O{index}", user, side, Decimal(cents).scaleb(-2), quantity))
            else:
                numbered.append(("cancel", f"O{op[1]}"))
        differential.compare(numbered, self_trade_prevention=stp, snapshot_every=1)

    def test_example_session(self):
        count, replayed, logged = differential.replay_session(
            Path(__file__).resolve().parent.parent / "example_session.jsonl")
        assert count == 13
        assert replayed == logged


def test_build_trusted_matches_normal_construction():
    import dataclasses
    from datetime import datetime
    from decimal import Decimal

    from lobx.models import Order, OrderStatus, Side, Trade, build_trusted

    stamp = datetime(2024, 1, 2, 9, 30)
    for cls, values in [
        (Order, dict(order_id="O1", user_id="u", symbol="X", side=Side.BUY,
                     price=Decimal("1.50"), quantity=3, timestamp=stamp, status=OrderStatus.OPEN)),
        (Trade, dict(trade_id="T1", symbol="X", buy_order_id="O1", sell_order_id="O2",
                     price=Decimal("1.50"), quantity=3, timestamp=stamp,
                     buyer_user_id="a", seller_user_id="b")),
    ]:
        normal, trusted = cls(**values), build_trusted(cls, dict(values))
        assert trusted == normal and hash(trusted) == hash(normal)
        assert repr(trusted) == repr(normal)
        assert set(values) == {field.name for field in dataclasses.fields(cls)}
        with pytest.raises(dataclasses.FrozenInstanceError):
            trusted.quantity = 4
