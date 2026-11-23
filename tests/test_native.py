"""
Tests for the C++ core (lobx._core) and its Python conversions.

The core is optional, so its tests are skipped unless the package has been built:
    .venv/bin/python -m pip install --no-build-isolation -e .
"""
import random
from dataclasses import FrozenInstanceError, fields
from datetime import datetime
from decimal import Decimal, Inexact, localcontext
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from bench import differential
from lobx._native import AVAILABLE, IdMap, _core, price_to_units, units_to_price
from lobx.models import Order, Side, Trade, _build_trusted

needs_core = pytest.mark.skipif(not AVAILABLE, reason="lobx._core isn't built")


def test_trusted_models_match_normal_construction():
    price = Decimal("100.00")
    timestamp = datetime(2026, 1, 1)
    for normal in (
        Order("O1", "u1", "BENCH", Side.BUY, price, 5, timestamp),
        Trade("T1", "BENCH", "O1", "O2", price, 5, timestamp, "u1", "u2"),
    ):
        cls = type(normal)
        values = dict(vars(normal))
        assert values.keys() == {field.name for field in fields(cls)}
        trusted = _build_trusted(cls, values)
        assert trusted == normal
        assert repr(trusted) == repr(normal)
        assert hash(trusted) == hash(normal)
        assert trusted.to_dict() == normal.to_dict()
        with pytest.raises(FrozenInstanceError):
            trusted.quantity = 4


class TestPriceConversion:
    def test_round_trip(self):
        assert price_to_units(Decimal("100.25")) == 1_002_500
        assert price_to_units(Decimal("0.0001")) == 1
        assert price_to_units(Decimal("1.25000")) == 12_500
        assert units_to_price(1_002_500) == Decimal("100.25")

    def test_conversion_is_exact_under_a_low_precision_context(self):
        highest = Decimal("922337203685477.5807")
        with localcontext() as context:
            context.prec = 3
            context.traps[Inexact] = True
            assert price_to_units(highest) == 2**63 - 1
            assert units_to_price(2**63 - 1) == highest
            with pytest.raises(ValueError, match="decimal places"):
                price_to_units(Decimal("922337203685477.58069"))

    @pytest.mark.parametrize("price", ["100.00001", "0.00005", "1e-999999"])
    def test_rejects_more_than_four_decimals(self, price):
        with pytest.raises(ValueError, match="decimal places"):
            price_to_units(Decimal(price))

    @pytest.mark.parametrize("price", [
        "0", "-1", "922337203685477.5808", "1e999999", "NaN", "sNaN", "Infinity", "-Infinity",
    ])
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
        with pytest.raises(AttributeError):
            trade.quantity = 0

        book.submit(3, 30, core.Side.BUY, 1_000_000, 6)
        assert trades == [trade]
        assert trade.quantity == 4

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

    @pytest.mark.parametrize("last_fill", [1, 5])
    def test_compact_submit_reports_removed_resting_ids(self, core, book, last_fill):
        book.submit(1, 10, core.Side.SELL, 1_000_000, 3)
        book.submit(2, 11, core.Side.SELL, 1_000_000, 5)
        book.submit(3, 20, core.Side.SELL, 1_000_000, 5)
        book.submit(4, 12, core.Side.SELL, 1_000_000, 5)

        status, remaining, trades, removed = book.submit_compact(
            5, 20, core.Side.BUY, 1_000_000, 8 + last_fill,
        )

        assert (status, remaining) == (core.SubmitStatus.FILLED, 0)
        assert trades == [
            (1, 5, 1, 20, 10, 1_000_000, 3),
            (2, 5, 2, 20, 11, 1_000_000, 5),
            (3, 5, 4, 20, 12, 1_000_000, last_fill),
        ]
        if last_fill == 5:
            assert sorted(removed) == [1, 2, 3, 4]
            assert not book.contains(4)
        else:
            assert sorted(removed) == [1, 2, 3]
            assert book.find(4).quantity == 4

    def test_rejections(self, core, book):
        too_big = core.MAX_ORDER_QUANTITY + 1
        assert book.submit(1, 1, core.Side.BUY, 100, too_big)[0] == core.SubmitStatus.REJECTED_INVALID
        book.submit(2, 1, core.Side.BUY, 100, 1)
        assert book.submit(2, 1, core.Side.BUY, 100, 1)[0] == core.SubmitStatus.REJECTED_DUPLICATE

    @pytest.mark.parametrize("order_id", [-1, 2**64])
    def test_out_of_range_ids_are_refused_by_the_binding(self, core, book, order_id):
        with pytest.raises(TypeError):
            book.submit(order_id, 1, core.Side.BUY, 100, 1)

    def test_constants_match_python(self, core, book):
        from lobx import _native
        assert core.PRICE_SCALE == _native.PRICE_SCALE
        assert core.MAX_ORDER_QUANTITY == _native.MAX_ORDER_QUANTITY


@needs_core
class TestDifferential:
    """The C++ core must make exactly the same decisions as the Python engine."""

    def test_the_comparison_notices_a_difference(self, monkeypatch):
        ops = [("new", "A", "u1", Side.SELL, Decimal("100"), 5),
               ("new", "B", "u1", Side.BUY, Decimal("100"), 5)]
        cpp_side = differential.CppSide
        monkeypatch.setattr(differential, "CppSide", lambda _: cpp_side(self_trade_prevention=False))

        with pytest.raises(differential.Divergence, match=r"op 1 .*python=.* cpp="):
            differential.compare(ops)

    def test_random_run_counts_every_requested_operation(self, capsys):
        differential.run_random(7, seed=1)

        assert "7 ops, no differences" in capsys.readouterr().out

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
                numbered.append(("new", f"O{index % 12}", user, side, Decimal(cents).scaleb(-2), quantity))
            else:
                numbered.append(("cancel", f"O{op[1]}"))
        differential.compare(numbered, self_trade_prevention=stp, snapshot_every=1)

    def test_example_session(self):
        count, replayed, logged = differential.replay_session(
            Path(__file__).resolve().parent.parent / "example_session.jsonl")
        assert count == 13
        assert replayed == logged
