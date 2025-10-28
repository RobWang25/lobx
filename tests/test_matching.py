"""
Unit tests for MatchingEngine.
"""
import pytest
from decimal import Decimal
from datetime import datetime

from lobx.models import Order, Side, OrderStatus, generate_order_id
from lobx.book import OrderBook
from lobx.matching import MatchingEngine


@pytest.fixture
def book():
    """Create empty order book."""
    return OrderBook("TEST")


@pytest.fixture
def matcher():
    """Create matching engine."""
    return MatchingEngine()


class TestBasicMatching:
    """Test basic matching scenarios."""
    
    def test_no_match_price_too_low(self, book, matcher):
        """Test that buy order doesn't match when price too low."""
        # Add sell order at $101
        sell_order = Order(
            order_id=generate_order_id(),
            user_id="seller",
            symbol="TEST",
            side=Side.SELL,
            price=Decimal("101.00"),
            quantity=100,
            timestamp=datetime.now()
        )
        book.add_order(sell_order)
        
        # Try to buy at $100 (below ask)
        buy_order = Order(
            order_id=generate_order_id(),
            user_id="buyer",
            symbol="TEST",
            side=Side.BUY,
            price=Decimal("100.00"),
            quantity=50,
            timestamp=datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        assert len(trades) == 0
        assert remaining.quantity == 50
        assert remaining.status == OrderStatus.OPEN
    
    def test_exact_match(self, book, matcher):
        """Test exact price and quantity match."""
        # Add sell order
        sell_order = Order(
            order_id=generate_order_id(),
            user_id="seller",
            symbol="TEST",
            side=Side.SELL,
            price=Decimal("100.00"),
            quantity=50,
            timestamp=datetime.now()
        )
        book.add_order(sell_order)
        
        # Match with buy order
        buy_order = Order(
            order_id=generate_order_id(),
            user_id="buyer",
            symbol="TEST",
            side=Side.BUY,
            price=Decimal("100.00"),
            quantity=50,
            timestamp=datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        assert len(trades) == 1
        assert trades[0].quantity == 50
        assert trades[0].price == Decimal("100.00")
        assert remaining.status == OrderStatus.FILLED
        assert remaining.quantity == 50
    
    def test_partial_fill_buyer(self, book, matcher):
        """Test buyer partially filled."""
        # Add small sell order
        sell_order = Order(
            order_id=generate_order_id(),
            user_id="seller",
            symbol="TEST",
            side=Side.SELL,
            price=Decimal("100.00"),
            quantity=30,
            timestamp=datetime.now()
        )
        book.add_order(sell_order)
        
        # Try to buy more than available
        buy_order = Order(
            order_id=generate_order_id(),
            user_id="buyer",
            symbol="TEST",
            side=Side.BUY,
            price=Decimal("100.00"),
            quantity=100,
            timestamp=datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        assert len(trades) == 1
        assert trades[0].quantity == 30
        assert remaining.quantity == 70  # 100 - 30
        assert remaining.status == OrderStatus.PARTIAL
    
    def test_partial_fill_seller(self, book, matcher):
        """Test seller partially filled."""
        # Add large buy order
        buy_order = Order(
            order_id=generate_order_id(),
            user_id="buyer",
            symbol="TEST",
            side=Side.BUY,
            price=Decimal("100.00"),
            quantity=100,
            timestamp=datetime.now()
        )
        book.add_order(buy_order)
        
        # Sell less than available
        sell_order = Order(
            order_id=generate_order_id(),
            user_id="seller",
            symbol="TEST",
            side=Side.SELL,
            price=Decimal("100.00"),
            quantity=40,
            timestamp=datetime.now()
        )
        
        trades, remaining = matcher.match_order(sell_order, book)
        
        assert len(trades) == 1
        assert trades[0].quantity == 40
        assert remaining.status == OrderStatus.FILLED
        assert remaining.quantity == 40


class TestPriceTimePriority:
    """Test price-time priority matching."""
    
    def test_best_price_wins(self, book, matcher):
        """Test that best price gets filled first."""
        # Add sell orders at different prices
        sell1 = Order(
            generate_order_id(), "s1", "TEST", Side.SELL,
            Decimal("102.00"), 50, datetime.now()
        )
        sell2 = Order(
            generate_order_id(), "s2", "TEST", Side.SELL,
            Decimal("101.00"), 50, datetime.now()
        )
        sell3 = Order(
            generate_order_id(), "s3", "TEST", Side.SELL,
            Decimal("103.00"), 50, datetime.now()
        )
        
        book.add_order(sell1)
        book.add_order(sell2)
        book.add_order(sell3)
        
        # Buy at high price
        buy_order = Order(
            generate_order_id(), "buyer", "TEST", Side.BUY,
            Decimal("105.00"), 50, datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        # Should match with cheapest seller (sell2 at $101)
        assert len(trades) == 1
        assert trades[0].price == Decimal("101.00")
    
    def test_time_priority_at_same_price(self, book, matcher):
        """Test FIFO at same price level."""
        # Add multiple sell orders at same price
        sell1 = Order(
            "SELL1", "s1", "TEST", Side.SELL,
            Decimal("100.00"), 20, datetime.now()
        )
        sell2 = Order(
            "SELL2", "s2", "TEST", Side.SELL,
            Decimal("100.00"), 30, datetime.now()
        )
        sell3 = Order(
            "SELL3", "s3", "TEST", Side.SELL,
            Decimal("100.00"), 40, datetime.now()
        )
        
        book.add_order(sell1)
        book.add_order(sell2)
        book.add_order(sell3)
        
        # Buy enough to match first two
        buy_order = Order(
            generate_order_id(), "buyer", "TEST", Side.BUY,
            Decimal("100.00"), 45, datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        # Should match SELL1 first (FIFO), then partial SELL2
        assert len(trades) == 2
        assert trades[0].sell_order_id == "SELL1"
        assert trades[0].quantity == 20
        assert trades[1].sell_order_id == "SELL2"
        assert trades[1].quantity == 25  # Partial fill


class TestMultipleLevels:
    """Test matching across multiple price levels."""
    
    def test_walk_the_book(self, book, matcher):
        """Test order matching across multiple price levels."""
        # Add sells at increasing prices
        for i, price in enumerate([100, 101, 102]):
            sell = Order(
                generate_order_id(), f"s{i}", "TEST", Side.SELL,
                Decimal(str(price)), 50, datetime.now()
            )
            book.add_order(sell)
        
        # Large buy order that crosses multiple levels
        buy_order = Order(
            generate_order_id(), "buyer", "TEST", Side.BUY,
            Decimal("102.00"), 120, datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        # Should generate 3 trades
        assert len(trades) == 3
        assert trades[0].price == Decimal("100.00")
        assert trades[1].price == Decimal("101.00")
        assert trades[2].price == Decimal("102.00")
        
        # Total matched
        total_matched = sum(t.quantity for t in trades)
        assert total_matched == 120
        assert remaining.status == OrderStatus.FILLED


class TestSelfTradePrevention:
    """Test self-trade prevention."""
    
    def test_self_trade_prevented(self, matcher):
        """Test that user cannot trade with themselves."""
        book = OrderBook("TEST")
        
        # User places sell order
        sell_order = Order(
            generate_order_id(), "alice", "TEST", Side.SELL,
            Decimal("100.00"), 50, datetime.now()
        )
        book.add_order(sell_order)
        
        # Same user tries to buy
        buy_order = Order(
            generate_order_id(), "alice", "TEST", Side.BUY,
            Decimal("100.00"), 50, datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        # Should not match with own order
        assert len(trades) == 0
    
    def test_self_trade_prevention_disabled(self):
        """Test matching when self-trade prevention disabled."""
        matcher = MatchingEngine(enable_self_trade_prevention=False)
        book = OrderBook("TEST")
        
        # User places sell order
        sell_order = Order(
            generate_order_id(), "alice", "TEST", Side.SELL,
            Decimal("100.00"), 50, datetime.now()
        )
        book.add_order(sell_order)
        
        # Same user tries to buy
        buy_order = Order(
            generate_order_id(), "alice", "TEST", Side.BUY,
            Decimal("100.00"), 50, datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        # Should match with own order
        assert len(trades) == 1


class TestEdgeCases:
    """Test edge cases."""
    
    def test_empty_book(self, book, matcher):
        """Test matching against empty book."""
        buy_order = Order(
            generate_order_id(), "buyer", "TEST", Side.BUY,
            Decimal("100.00"), 50, datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        assert len(trades) == 0
        assert remaining.quantity == 50
    
    def test_aggressive_market_taker(self, book, matcher):
        """Test aggressive order that crosses spread significantly."""
        # Add sell at $100
        sell = Order(
            generate_order_id(), "seller", "TEST", Side.SELL,
            Decimal("100.00"), 50, datetime.now()
        )
        book.add_order(sell)
        
        # Aggressive buy at $110
        buy_order = Order(
            generate_order_id(), "buyer", "TEST", Side.BUY,
            Decimal("110.00"), 50, datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        # Should match at seller's price ($100), not buyer's
        assert len(trades) == 1
        assert trades[0].price == Decimal("100.00")
    
    def test_zero_quantity_after_match(self, book, matcher):
        """Test order with exact match results in zero remaining."""
        sell = Order(
            generate_order_id(), "seller", "TEST", Side.SELL,
            Decimal("100.00"), 100, datetime.now()
        )
        book.add_order(sell)
        
        buy_order = Order(
            generate_order_id(), "buyer", "TEST", Side.BUY,
            Decimal("100.00"), 100, datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        assert remaining.quantity == 100  # Original quantity
        assert remaining.status == OrderStatus.FILLED