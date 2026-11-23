"""
Integration tests for TradingEngine.
"""
import pytest
from decimal import Decimal
from datetime import datetime

from lobx.models import Order, Side, generate_order_id
from lobx.engine import TradingEngine


@pytest.fixture
def engine():
    """Create fresh trading engine."""
    return TradingEngine(enable_logging=False)


class TestEngineBasics:
    """Test basic engine operations."""
    
    def test_submit_order_creates_book(self, engine):
        """Test that submitting order creates book for new symbol."""
        order = Order(
            order_id=generate_order_id(),
            user_id="user1",
            symbol="AAPL",
            side=Side.BUY,
            price=Decimal("150.00"),
            quantity=100,
            timestamp=datetime.now()
        )
        
        trades = engine.submit_order(order)
        
        assert "AAPL" in engine.books
        assert len(trades) == 0  # No match on empty book
    
    def test_submit_matching_orders(self, engine):
        """Test that matching orders execute trades."""
        # Submit sell order
        sell_order = Order(
            order_id=generate_order_id(),
            user_id="seller",
            symbol="AAPL",
            side=Side.SELL,
            price=Decimal("150.00"),
            quantity=50,
            timestamp=datetime.now()
        )
        engine.submit_order(sell_order)
        
        # Submit matching buy order
        buy_order = Order(
            order_id=generate_order_id(),
            user_id="buyer",
            symbol="AAPL",
            side=Side.BUY,
            price=Decimal("150.00"),
            quantity=50,
            timestamp=datetime.now()
        )
        trades = engine.submit_order(buy_order)
        
        assert len(trades) == 1
        assert trades[0].quantity == 50
        assert engine.total_trades_executed == 1
    
    def test_cancel_order(self, engine):
        """Test order cancellation."""
        order = Order(
            order_id="TEST123",
            user_id="user1",
            symbol="AAPL",
            side=Side.BUY,
            price=Decimal("150.00"),
            quantity=100,
            timestamp=datetime.now()
        )
        engine.submit_order(order)
        
        # Cancel the order
        success = engine.cancel_order("TEST123", "AAPL")
        
        assert success
        assert engine.total_orders_cancelled == 1
        assert engine.get_order("TEST123", "AAPL") is None
    
    def test_cancel_nonexistent_order(self, engine):
        """Test cancelling order that doesn't exist."""
        success = engine.cancel_order("FAKE123", "AAPL")
        assert not success
    
    def test_cancel_wrong_symbol(self, engine):
        """Test cancelling with wrong symbol."""
        order = Order(
            order_id="TEST123",
            user_id="user1",
            symbol="AAPL",
            side=Side.BUY,
            price=Decimal("150.00"),
            quantity=100,
            timestamp=datetime.now()
        )
        engine.submit_order(order)
        
        # Try to cancel with wrong symbol
        success = engine.cancel_order("TEST123", "MSFT")
        assert not success


class TestMultipleSymbols:
    """Test handling multiple symbols."""
    
    def test_separate_books(self, engine):
        """Test that symbols have separate books."""
        # Add orders for different symbols
        aapl_order = Order(
            generate_order_id(), "u1", "AAPL", Side.BUY,
            Decimal("150.00"), 100, datetime.now()
        )
        msft_order = Order(
            generate_order_id(), "u2", "MSFT", Side.BUY,
            Decimal("380.00"), 50, datetime.now()
        )
        
        engine.submit_order(aapl_order)
        engine.submit_order(msft_order)
        
        assert len(engine.books) == 2
        assert "AAPL" in engine.books
        assert "MSFT" in engine.books
    
    def test_orders_dont_cross_symbols(self, engine):
        """Test that AAPL orders don't match with MSFT orders."""
        # Sell AAPL at $150
        aapl_sell = Order(
            generate_order_id(), "seller", "AAPL", Side.SELL,
            Decimal("150.00"), 100, datetime.now()
        )
        engine.submit_order(aapl_sell)
        
        # Buy MSFT at $150 (different symbol!)
        msft_buy = Order(
            generate_order_id(), "buyer", "MSFT", Side.BUY,
            Decimal("150.00"), 100, datetime.now()
        )
        trades = engine.submit_order(msft_buy)
        
        # Should not match across symbols
        assert len(trades) == 0


class TestStatistics:
    """Test statistics tracking."""
    
    def test_order_counting(self, engine):
        """Test that orders are counted correctly."""
        for i in range(10):
            order = Order(
                generate_order_id(), f"u{i}", "TEST", Side.BUY,
                Decimal("100.00"), 10, datetime.now()
            )
            engine.submit_order(order)
        
        stats = engine.get_statistics()
        assert stats["total_orders_submitted"] == 10
    
    def test_trade_counting(self, engine):
        """Test that trades are counted correctly."""
        # Add 5 sell orders
        for i in range(5):
            sell = Order(
                generate_order_id(), f"s{i}", "TEST", Side.SELL,
                Decimal("100.00"), 10, datetime.now()
            )
            engine.submit_order(sell)
        
        # One buy order that matches all
        buy = Order(
            generate_order_id(), "buyer", "TEST", Side.BUY,
            Decimal("100.00"), 50, datetime.now()
        )
        trades = engine.submit_order(buy)
        
        stats = engine.get_statistics()
        assert stats["total_trades_executed"] == 5
        assert len(trades) == 5
    
    def test_latency_tracking(self, engine):
        """Test that latency is tracked."""
        order = Order(
            generate_order_id(), "u1", "TEST", Side.BUY,
            Decimal("100.00"), 10, datetime.now()
        )
        engine.submit_order(order)
        
        stats = engine.get_statistics()
        assert "latency" in stats
        assert len(engine.latencies) == 1
        assert engine.latencies[0] >= 0  # Positive latency

    def test_latency_window_retains_the_latest_samples_and_resets(self):
        engine = TradingEngine(enable_logging=False, latency_window=3)
        latencies = engine.latencies
        samples = []
        for i in range(5):
            engine.submit_order(Order(str(i), "u1", "TEST", Side.BUY, Decimal("100.00"), 1, datetime.now()))
            samples.append(latencies[-1])

        stats = engine.get_statistics()
        assert list(latencies) == samples[-3:]
        assert stats["total_orders_submitted"] == 5
        assert stats["operation_latencies"]["submit_order"]["count"] == 3
        assert stats["latency"]["p99_ms"] == max(samples[-3:])

        engine.reset_statistics()
        assert not latencies
        assert engine.get_statistics()["operation_latencies"] == {}
        engine.submit_order(Order("new", "u1", "TEST", Side.BUY, Decimal("100.00"), 1, datetime.now()))
        assert len(latencies) == 1
        assert engine.latency_tracker.get_stats("submit_order")["count"] == 1

    def test_latency_window_must_be_positive(self):
        with pytest.raises(ValueError, match="latency window must be at least 1"):
            TradingEngine(backend="python", latency_window=0)
    
    def test_throughput_calculation(self, engine):
        """Test throughput calculation."""
        import time
        
        # Submit some orders
        for i in range(10):
            order = Order(
                generate_order_id(), f"u{i}", "TEST", Side.BUY,
                Decimal("100.00"), 10, datetime.now()
            )
            engine.submit_order(order)
        
        time.sleep(0.1)  # Wait a bit
        
        stats = engine.get_statistics()
        assert stats["orders_per_second"] > 0
        assert stats["uptime_seconds"] > 0
    
    def test_reset_statistics(self, engine):
        """Test statistics reset."""
        # Submit some orders
        for i in range(5):
            order = Order(
                generate_order_id(), f"u{i}", "TEST", Side.BUY,
                Decimal("100.00"), 10, datetime.now()
            )
            engine.submit_order(order)
        
        engine.reset_statistics()
        
        stats = engine.get_statistics()
        assert stats["total_orders_submitted"] == 0
        assert len(engine.latencies) == 0


class TestBookQueries:
    """Test book query methods."""
    
    def test_get_book(self, engine):
        """Test getting order book."""
        order = Order(
            generate_order_id(), "u1", "AAPL", Side.BUY,
            Decimal("150.00"), 100, datetime.now()
        )
        engine.submit_order(order)
        
        book = engine.get_book("AAPL")
        assert book is not None
        assert book.symbol == "AAPL"
    
    def test_get_nonexistent_book(self, engine):
        """Test getting book that doesn't exist."""
        book = engine.get_book("FAKE")
        assert book is None
    
    def test_get_book_depth(self, engine):
        """Test getting book depth."""
        # Add some orders
        for i in range(3):
            buy = Order(
                generate_order_id(), f"b{i}", "AAPL", Side.BUY,
                Decimal(str(150 - i)), 100, datetime.now()
            )
            sell = Order(
                generate_order_id(), f"s{i}", "AAPL", Side.SELL,
                Decimal(str(151 + i)), 100, datetime.now()
            )
            engine.submit_order(buy)
            engine.submit_order(sell)
        
        depth = engine.get_book_depth("AAPL", levels=3)
        
        assert depth is not None
        assert len(depth["bids"]) == 3
        assert len(depth["asks"]) == 3
        assert depth["spread"] is not None


class TestEventLogging:
    """Test event logging functionality."""
    
    def test_logging_enabled(self):
        """Test that events are logged when enabled."""
        engine = TradingEngine(enable_logging=True)
        
        order = Order(
            generate_order_id(), "u1", "TEST", Side.BUY,
            Decimal("100.00"), 10, datetime.now()
        )
        engine.submit_order(order)
        
        events = engine.get_event_log()
        assert events is not None
        assert len(events) > 0
    
    def test_logging_disabled(self):
        """Test that no events logged when disabled."""
        engine = TradingEngine(enable_logging=False)
        
        order = Order(
            generate_order_id(), "u1", "TEST", Side.BUY,
            Decimal("100.00"), 10, datetime.now()
        )
        engine.submit_order(order)
        
        events = engine.get_event_log()
        assert events is None
    
    def test_save_event_log(self, tmp_path):
        """Test saving event log to file."""
        engine = TradingEngine(enable_logging=True)
        
        # Submit some orders
        for i in range(3):
            order = Order(
                generate_order_id(), f"u{i}", "TEST", Side.BUY,
                Decimal("100.00"), 10, datetime.now()
            )
            engine.submit_order(order)
        
        # Save log
        log_file = tmp_path / "events.jsonl"
        engine.save_event_log(str(log_file))
        
        assert log_file.exists()
        assert log_file.stat().st_size > 0


class TestComplexScenarios:
    """Test complex trading scenarios."""
    
    def test_many_orders_same_price(self, engine):
        """Test handling many orders at same price."""
        # Add 100 sell orders at $100
        for i in range(100):
            sell = Order(
                generate_order_id(), f"s{i}", "TEST", Side.SELL,
                Decimal("100.00"), 1, datetime.now()
            )
            engine.submit_order(sell)
        
        # One large buy order
        buy = Order(
            generate_order_id(), "buyer", "TEST", Side.BUY,
            Decimal("100.00"), 100, datetime.now()
        )
        trades = engine.submit_order(buy)
        
        # Should generate 100 trades (one per sell order)
        assert len(trades) == 100
    
    def test_alternating_buys_sells(self, engine):
        """Test alternating buy and sell orders."""
        for i in range(10):
            if i % 2 == 0:
                order = Order(
                    generate_order_id(), f"u{i}", "TEST", Side.BUY,
                    Decimal("100.00"), 10, datetime.now()
                )
            else:
                order = Order(
                    generate_order_id(), f"u{i}", "TEST", Side.SELL,
                    Decimal("100.00"), 10, datetime.now()
                )
            engine.submit_order(order)
        
        stats = engine.get_statistics()
        # Each sell should match with a previous buy
        assert stats["total_trades_executed"] == 5
