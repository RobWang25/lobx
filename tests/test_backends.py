"""
Tests for choosing a backend, and for behaviour specific to the C++ backend.

The rest of the suite runs on whichever backend LOBX_BACKEND picks, so running it
twice covers both:
    LOBX_BACKEND=python pytest tests
    LOBX_BACKEND=cpp pytest tests
"""
import warnings
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from lobx import _native, engine as engine_module
from lobx.engine import TradingEngine, resolve_backend
from lobx.models import Order, OrderStatus, Side

SYMBOL = "TEST"
NOW = datetime(2026, 3, 4, 5, 6, 7, 891011)

needs_core = pytest.mark.skipif(not _native.AVAILABLE, reason="lobx._core isn't built")
BACKENDS = ["python", pytest.param("cpp", marks=needs_core)]


def make_order(order_id, user, side, price, quantity, timestamp=NOW):
    return Order(order_id, user, SYMBOL, side, Decimal(price), quantity, timestamp)


class TestChoosingABackend:
    @needs_core
    def test_defaults_to_cpp_when_built(self, monkeypatch):
        monkeypatch.delenv("LOBX_BACKEND", raising=False)
        assert resolve_backend() == "cpp"
        assert TradingEngine(enable_logging=False).backend == "cpp"

    def test_falls_back_to_python_without_the_core(self, monkeypatch):
        monkeypatch.delenv("LOBX_BACKEND", raising=False)
        monkeypatch.setattr(engine_module._native, "AVAILABLE", False)
        monkeypatch.setattr(engine_module, "_warned_about_fallback", False)
        with pytest.warns(RuntimeWarning, match="isn't built"):
            assert resolve_backend() == "python"
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # A second warning would raise here
            assert resolve_backend() == "python"

    def test_async_without_a_choice_uses_python(self, monkeypatch):
        monkeypatch.delenv("LOBX_BACKEND", raising=False)
        assert TradingEngine(enable_logging=False, use_async=True).backend == "python"

    @needs_core
    def test_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("LOBX_BACKEND", "CPP")
        assert resolve_backend() == "cpp"
        assert TradingEngine(enable_logging=False).backend == "cpp"

    def test_argument_overrides_the_environment(self, monkeypatch):
        monkeypatch.setenv("LOBX_BACKEND", "cpp")
        assert resolve_backend("python") == "python"

    def test_unknown_name(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            resolve_backend("rust")

    def test_cpp_without_the_core(self, monkeypatch):
        monkeypatch.setattr(engine_module._native, "AVAILABLE", False)
        with pytest.raises(RuntimeError, match="isn't built"):
            resolve_backend("cpp")

    @needs_core
    def test_async_only_works_on_python(self):
        with pytest.raises(ValueError, match="async"):
            TradingEngine(backend="cpp", use_async=True)

    @pytest.mark.parametrize("backend", BACKENDS)
    def test_statistics_report_the_backend(self, backend):
        assert TradingEngine(enable_logging=False, backend=backend).get_statistics()["backend"] == backend


@pytest.mark.parametrize("backend", BACKENDS)
class TestBothBackends:
    def test_duplicate_resting_id_is_rejected_before_matching(self, backend):
        engine = TradingEngine(enable_logging=False, backend=backend)
        engine.submit_order(make_order("A", "u1", Side.SELL, "100", 10))
        engine.submit_order(make_order("B", "u2", Side.BUY, "99", 10))

        # Would cross order B if it were allowed to match.
        trades = engine.submit_order(make_order("B", "u3", Side.SELL, "99", 5))

        assert trades == []
        assert engine.total_orders_rejected == 1
        assert engine.get_statistics()["total_orders_rejected"] == 1
        assert engine.get_book(SYMBOL).get_order("B").quantity == 10

    def test_levels_are_best_first(self, backend):
        engine = TradingEngine(enable_logging=False, backend=backend)
        for index, price in enumerate(["99", "101", "100"]):
            engine.submit_order(make_order(f"B{index}", "u1", Side.BUY, price, 10))
        engine.submit_order(make_order("B3", "u2", Side.BUY, "101", 5))

        book = engine.get_book(SYMBOL)
        assert book.get_levels(Side.BUY) == [
            (Decimal("101"), 15, 2), (Decimal("100"), 10, 1), (Decimal("99"), 10, 1)]
        assert book.get_levels(Side.BUY, 1) == [(Decimal("101"), 15, 2)]
        assert book.get_levels(Side.SELL) == []

    def test_book_endpoint(self, backend, monkeypatch):
        monkeypatch.setenv("LOBX_BACKEND", backend)
        from api.main import app

        with TestClient(app) as client:
            assert client.get("/stats/detailed").json()["backend"] == backend
            for side, price in (("BUY", "149.50"), ("BUY", "149.50"), ("SELL", "150.25")):
                order = {"symbol": "ZZZ", "user_id": f"u-{side}", "side": side,
                         "price": price, "quantity": "10"}
                assert client.post("/orders", json=order).status_code == 200
            book = client.get("/book/ZZZ?depth=5").json()

        assert book["bids"] == [{"price": "149.50", "quantity": "20", "order_count": 2}]
        assert book["asks"] == [{"price": "150.25", "quantity": "10", "order_count": 1}]


@needs_core
class TestCppBackend:
    @pytest.fixture
    def engine(self):
        return TradingEngine(enable_logging=False, backend="cpp")

    def test_resting_orders_come_back_exactly(self, engine):
        order = make_order("A", "alice", Side.BUY, "150.00", 10)
        engine.submit_order(order)

        stored = engine.get_book(SYMBOL).get_order("A")

        assert stored == order
        assert str(stored.price) == "150.00"
        assert stored.timestamp == NOW  # Including the microseconds

    def test_partial_fills_report_partial_status(self, engine):
        engine.submit_order(make_order("A", "u1", Side.SELL, "100", 10))
        engine.submit_order(make_order("B", "u2", Side.BUY, "100", 4))
        assert engine.get_book(SYMBOL).get_order("A").status == OrderStatus.PARTIAL

    def test_trades_are_numbered_and_use_the_incoming_timestamp(self, engine):
        later = datetime(2026, 3, 4, 9, 0)
        engine.submit_order(make_order("A", "u1", Side.SELL, "100", 5))
        engine.submit_order(make_order("B", "u1x", Side.SELL, "100", 5))
        trades = engine.submit_order(make_order("C", "u2", Side.BUY, "100", 10, timestamp=later))

        assert [t.trade_id for t in trades] == ["TRD-TEST-1", "TRD-TEST-2"]
        assert all(t.timestamp == later for t in trades)
        assert [(t.buyer_user_id, t.seller_user_id) for t in trades] == [("u2", "u1"), ("u2", "u1x")]

    def test_cancel_returns_the_cancelled_order(self, engine):
        engine.submit_order(make_order("A", "u1", Side.BUY, "100", 10))
        assert engine.cancel_order("A", SYMBOL)
        assert not engine.cancel_order("A", SYMBOL)
        assert engine.get_book(SYMBOL).get_order("A") is None

    @pytest.mark.parametrize("price", ["100.00001", "0.00001"])
    def test_rejects_prices_finer_than_four_decimals(self, engine, price):
        with pytest.raises(ValueError, match="decimal places"):
            engine.submit_order(make_order("A", "u1", Side.BUY, price, 10))
        assert engine.get_book(SYMBOL).get_statistics()["active_orders"] == 0

    def test_rejects_quantities_above_the_cap(self, engine):
        with pytest.raises(ValueError, match="above"):
            engine.submit_order(make_order("A", "u1", Side.BUY, "100", _native.MAX_ORDER_QUANTITY + 1))

    def test_rejects_timezone_aware_timestamps(self, engine):
        aware = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="naive"):
            engine.submit_order(make_order("A", "u1", Side.BUY, "100", 10, timestamp=aware))

    def test_ids_are_forgotten_once_orders_leave(self, engine):
        book_orders = [
            make_order("A", "u1", Side.SELL, "100", 5),
            make_order("B", "u2", Side.SELL, "100", 5),
            make_order("C", "u3", Side.SELL, "101", 5),
            make_order("D", "u4", Side.SELL, "102", 5),
        ]
        for order in book_orders:
            engine.submit_order(order)
        engine.submit_order(make_order("X", "u9", Side.BUY, "100", 7))  # Fills A, part of B
        engine.submit_order(make_order("Y", "u3", Side.BUY, "101", 6))  # Fills B, self-trade cancels C, rests 3
        engine.cancel_order("D", SYMBOL)

        book = engine.get_book(SYMBOL)
        # Y's last 3 rest after C is cancelled, so it's the only ID still held.
        assert set(book._numbers) == {"Y"}
        assert set(book._names.values()) == {"Y"}

    def test_snapshots_are_copies(self, engine):
        engine.submit_order(make_order("A", "u1", Side.BUY, "100", 10))
        book = engine.get_book(SYMBOL)

        bids = book.bids
        assert isinstance(bids[Decimal("100")], OrderedDict)
        bids.clear()

        assert list(book.bids) == [Decimal("100")]
        assert list(book.order_index) == ["A"]

    def test_unrepresentable_price_has_no_orders(self, engine):
        engine.submit_order(make_order("A", "u1", Side.BUY, "100", 10))
        assert engine.get_book(SYMBOL).get_orders_at_price(Side.BUY, Decimal("100.00001")) == []
