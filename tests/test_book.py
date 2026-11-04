"""
Unit tests for OrderBook.
"""
import pytest
from decimal import Decimal
from datetime import datetime

from lobx.models import Order, Side, OrderStatus, generate_order_id
from lobx.book import OrderBook


@pytest.fixture
def book():
    """Create empty order book."""
    return OrderBook("AAPL")


@pytest.fixture
def sample_buy_order():
    """Create sample buy order."""
    return Order(
        order_id=generate_order_id(),
        user_id="user1",
        symbol="AAPL",
        side=Side.BUY,
        price=Decimal("100.00"),
        quantity=10,
        timestamp=datetime.now()
    )


@pytest.fixture
def sample_sell_order():
    """Create sample sell order."""
    return Order(
        order_id=generate_order_id(),
        user_id="user2",
        symbol="AAPL",
        side=Side.SELL,
        price=Decimal("101.00"),
        quantity=15,
        timestamp=datetime.now()
    )


class TestOrderBookBasics:
    """Test basic order book operations."""
    
    def test_add_buy_order(self, book, sample_buy_order):
        """Test adding a buy order."""
        assert book.add_order(sample_buy_order)
        assert sample_buy_order.order_id in book.order_index
        assert book.get_best_bid() == Decimal("100.00")
    
    def test_add_sell_order(self, book, sample_sell_order):
        """Test adding a sell order."""
        assert book.add_order(sample_sell_order)
        assert sample_sell_order.order_id in book.order_index
        assert book.get_best_ask() == Decimal("101.00")
    
    def test_cannot_add_duplicate_order_id(self, book, sample_buy_order):
        """Test that duplicate order IDs are rejected."""
        assert book.add_order(sample_buy_order)
        assert not book.add_order(sample_buy_order)
    
    def test_wrong_symbol_raises_error(self, book):
        """Test that wrong symbol raises error."""
        order = Order(
            order_id=generate_order_id(),
            user_id="user1",
            symbol="MSFT",  # Wrong symbol
            side=Side.BUY,
            price=Decimal("100.00"),
            quantity=10,
            timestamp=datetime.now()
        )
        with pytest.raises(ValueError):
            book.add_order(order)
    
    def test_order_added_to_correct_side(self, book, sample_buy_order, sample_sell_order):
        """Test that orders go to correct side of book."""
        book.add_order(sample_buy_order)
        book.add_order(sample_sell_order)
        
        assert sample_buy_order.price in book.bids
        assert sample_sell_order.price in book.asks
        assert sample_buy_order.price not in book.asks
        assert sample_sell_order.price not in book.bids


class TestBestPrices:
    """Test best bid/ask tracking."""
    
    def test_best_bid_with_multiple_levels(self, book):
        """Test best bid with multiple price levels."""
        orders = [
            Order(generate_order_id(), "u1", "AAPL", Side.BUY, Decimal("100.00"), 10, datetime.now()),
            Order(generate_order_id(), "u2", "AAPL", Side.BUY, Decimal("99.50"), 20, datetime.now()),
            Order(generate_order_id(), "u3", "AAPL", Side.BUY, Decimal("100.50"), 5, datetime.now()),
        ]
        
        for order in orders:
            book.add_order(order)
        
        assert book.get_best_bid() == Decimal("100.50")
    
    def test_best_ask_with_multiple_levels(self, book):
        """Test best ask with multiple price levels."""
        orders = [
            Order(generate_order_id(), "u1", "AAPL", Side.SELL, Decimal("102.00"), 10, datetime.now()),
            Order(generate_order_id(), "u2", "AAPL", Side.SELL, Decimal("101.50"), 20, datetime.now()),
            Order(generate_order_id(), "u3", "AAPL", Side.SELL, Decimal("103.00"), 5, datetime.now()),
        ]
        
        for order in orders:
            book.add_order(order)
        
        assert book.get_best_ask() == Decimal("101.50")
    
    def test_empty_book_returns_none(self, book):
        """Test that empty book returns None for best prices."""
        assert book.get_best_bid() is None
        assert book.get_best_ask() is None
    
    def test_best_bid_updates_after_removal(self, book):
        """Test that best bid updates when top order removed."""
        order1 = Order(generate_order_id(), "u1", "AAPL", Side.BUY, Decimal("100.00"), 10, datetime.now())
        order2 = Order(generate_order_id(), "u2", "AAPL", Side.BUY, Decimal("99.50"), 10, datetime.now())
        
        book.add_order(order1)
        book.add_order(order2)
        
        assert book.get_best_bid() == Decimal("100.00")
        
        book.cancel_order(order1.order_id)
        assert book.get_best_bid() == Decimal("99.50")


class TestOrderCancellation:
    """Test order cancellation."""
    
    def test_cancel_existing_order(self, book, sample_buy_order):
        """Test cancelling an existing order."""
        book.add_order(sample_buy_order)
        cancelled = book.cancel_order(sample_buy_order.order_id)
        
        assert cancelled is not None
        assert cancelled.status == OrderStatus.CANCELLED
        assert sample_buy_order.order_id not in book.order_index
    
    def test_cancel_nonexistent_order(self, book):
        """Test cancelling a nonexistent order."""
        cancelled = book.cancel_order("FAKE_ID")
        assert cancelled is None
    
    def test_cancel_cleans_up_empty_price_level(self, book):
        """Test that cancelling last order at price removes price level."""
        order = Order(
            generate_order_id(), "u1", "AAPL", Side.BUY, 
            Decimal("100.00"), 10, datetime.now()
        )
        book.add_order(order)
        book.cancel_order(order.order_id)
        
        assert Decimal("100.00") not in book.bids
    
    def test_cancel_one_of_many_at_price(self, book):
        """Test cancelling one order when multiple at same price."""
        order1 = Order(generate_order_id(), "u1", "AAPL", Side.BUY, Decimal("100.00"), 10, datetime.now())
        order2 = Order(generate_order_id(), "u2", "AAPL", Side.BUY, Decimal("100.00"), 20, datetime.now())
        
        book.add_order(order1)
        book.add_order(order2)
        
        book.cancel_order(order1.order_id)
        
        # Price level should still exist
        assert Decimal("100.00") in book.bids
        # Only order2 should remain
        assert len(book.bids[Decimal("100.00")]) == 1
        assert book.get_orders_at_price(Side.BUY, Decimal("100.00")) == [order2]


class TestFIFOOrdering:
    """Test FIFO ordering within price levels."""
    
    def test_fifo_order_at_same_price(self, book):
        """Test that orders at same price are FIFO."""
        orders = [
            Order(generate_order_id(), f"u{i}", "AAPL", Side.BUY, 
                  Decimal("100.00"), 10, datetime.now())
            for i in range(5)
        ]
        
        for order in orders:
            book.add_order(order)
        
        # First order should be at front of queue
        first_order = book.peek_best_order(Side.BUY)
        assert first_order.order_id == orders[0].order_id
        
        # Pop and check FIFO
        for expected_order in orders:
            popped = book.pop_best_order(Side.BUY)
            assert popped.order_id == expected_order.order_id
    
    def test_peek_does_not_remove(self, book, sample_buy_order):
        """Test that peek doesn't remove order."""
        book.add_order(sample_buy_order)
        
        peeked1 = book.peek_best_order(Side.BUY)
        peeked2 = book.peek_best_order(Side.BUY)
        
        assert peeked1.order_id == peeked2.order_id
        assert sample_buy_order.order_id in book.order_index
    
    def test_pop_removes_order(self, book, sample_buy_order):
        """Test that pop removes order from book."""
        book.add_order(sample_buy_order)
        
        popped = book.pop_best_order(Side.BUY)
        
        assert popped.order_id == sample_buy_order.order_id
        assert sample_buy_order.order_id not in book.order_index
        assert book.peek_best_order(Side.BUY) is None


class TestBookDepth:
    """Test book depth queries."""
    
    def test_book_depth_with_orders(self, book):
        """Test book depth with multiple levels."""
        # Add buy orders
        for price in [Decimal("100.00"), Decimal("99.50"), Decimal("99.00")]:
            order = Order(
                generate_order_id(), "u1", "AAPL", Side.BUY,
                price, 10, datetime.now()
            )
            book.add_order(order)
        
        # Add sell orders
        for price in [Decimal("101.00"), Decimal("101.50"), Decimal("102.00")]:
            order = Order(
                generate_order_id(), "u2", "AAPL", Side.SELL,
                price, 15, datetime.now()
            )
            book.add_order(order)
        
        depth = book.get_book_depth(levels=3)
        
        assert len(depth["bids"]) == 3
        assert len(depth["asks"]) == 3
        assert depth["bids"][0]["price"] == 100.00
        assert depth["asks"][0]["price"] == 101.00
        assert depth["spread"] == 1.00
    
    def test_spread_calculation(self, book):
        """Test spread calculation."""
        buy_order = Order(
            generate_order_id(), "u1", "AAPL", Side.BUY,
            Decimal("100.00"), 10, datetime.now()
        )
        sell_order = Order(
            generate_order_id(), "u2", "AAPL", Side.SELL,
            Decimal("101.50"), 10, datetime.now()
        )
        
        book.add_order(buy_order)
        book.add_order(sell_order)
        
        assert book.get_spread() == Decimal("1.50")
        assert book.get_midprice() == Decimal("100.75")
    
    def test_depth_aggregates_quantities(self, book):
        """Test that depth aggregates quantities at same price."""
        # Add 3 orders at same price
        for i in range(3):
            order = Order(
                generate_order_id(), f"u{i}", "AAPL", Side.BUY,
                Decimal("100.00"), 10, datetime.now()
            )
            book.add_order(order)
        
        depth = book.get_book_depth(levels=5)
        
        assert len(depth["bids"]) == 1
        assert depth["bids"][0]["quantity"] == 30
        assert depth["bids"][0]["orders"] == 3
    
    def test_depth_limits_levels(self, book):
        """Test that depth respects levels parameter."""
        # Add 10 price levels
        for i in range(10):
            order = Order(
                generate_order_id(), f"u{i}", "AAPL", Side.BUY,
                Decimal(str(100 - i)), 10, datetime.now()
            )
            book.add_order(order)
        
        depth = book.get_book_depth(levels=3)
        
        # Should only return top 3
        assert len(depth["bids"]) == 3
        assert depth["bids"][0]["price"] == 100.00
        assert depth["bids"][1]["price"] == 99.00
        assert depth["bids"][2]["price"] == 98.00


class TestStatistics:
    """Test statistics tracking."""
    
    def test_statistics_tracking(self, book):
        """Test that statistics are tracked correctly."""
        # Add some orders
        for i in range(5):
            order = Order(
                generate_order_id(), f"u{i}", "AAPL", Side.BUY,
                Decimal("100.00"), 10, datetime.now()
            )
            book.add_order(order)
        
        stats = book.get_statistics()
        assert stats["total_orders"] == 5
        assert stats["active_orders"] == 5
        assert stats["total_bid_quantity"] == 50
    
    def test_statistics_after_cancellation(self, book):
        """Test statistics update after cancellation."""
        orders = []
        for i in range(5):
            order = Order(
                generate_order_id(), f"u{i}", "AAPL", Side.BUY,
                Decimal("100.00"), 10, datetime.now()
            )
            book.add_order(order)
            orders.append(order)
        
        # Cancel 2 orders
        book.cancel_order(orders[0].order_id)
        book.cancel_order(orders[1].order_id)
        
        stats = book.get_statistics()
        assert stats["total_orders"] == 5  # Total submitted doesn't change
        assert stats["active_orders"] == 3  # Active decreases
        assert stats["total_bid_quantity"] == 30  # Quantity decreases
    
    def test_statistics_tracks_levels(self, book):
        """Test that statistics track price levels."""
        # Add orders at different prices
        for price in [Decimal("100.00"), Decimal("99.00"), Decimal("98.00")]:
            order = Order(
                generate_order_id(), "u1", "AAPL", Side.BUY,
                price, 10, datetime.now()
            )
            book.add_order(order)
        
        stats = book.get_statistics()
        assert stats["bid_levels"] == 3


class TestGetOrder:
    """Test order lookup functionality."""
    
    def test_get_existing_order(self, book, sample_buy_order):
        """Test getting an order that exists."""
        book.add_order(sample_buy_order)
        
        retrieved = book.get_order(sample_buy_order.order_id)
        
        assert retrieved is not None
        assert retrieved.order_id == sample_buy_order.order_id
    
    def test_get_nonexistent_order(self, book):
        """Test getting an order that doesn't exist."""
        retrieved = book.get_order("FAKE_ID")
        assert retrieved is None
    
    def test_get_orders_at_price(self, book):
        """Test getting all orders at a specific price."""
        price = Decimal("100.00")
        
        # Add 3 orders at same price
        orders = []
        for i in range(3):
            order = Order(
                generate_order_id(), f"u{i}", "AAPL", Side.BUY,
                price, 10, datetime.now()
            )
            book.add_order(order)
            orders.append(order)
        
        retrieved = book.get_orders_at_price(Side.BUY, price)
        
        assert len(retrieved) == 3
        assert all(o.price == price for o in retrieved)


class TestUpdateOrder:
    """Test order update functionality."""
    
    def test_update_order_in_index(self, book, sample_buy_order):
        """Test updating order in index."""
        book.add_order(sample_buy_order)
        
        # Create updated order with new quantity
        updated = sample_buy_order.with_quantity(5)
        book.update_order(updated)
        
        # Check it's updated in index
        retrieved = book.get_order(sample_buy_order.order_id)
        assert retrieved.quantity == 5


class TestEdgeCases:
    """Test edge cases."""
    
    def test_empty_book_spread_is_none(self, book):
        """Test that empty book has no spread."""
        assert book.get_spread() is None
        assert book.get_midprice() is None
    
    def test_only_bids_no_spread(self, book, sample_buy_order):
        """Test that book with only bids has no spread."""
        book.add_order(sample_buy_order)
        assert book.get_spread() is None
    
    def test_only_asks_no_spread(self, book, sample_sell_order):
        """Test that book with only asks has no spread."""
        book.add_order(sample_sell_order)
        assert book.get_spread() is None
    
    def test_pop_from_empty_book(self, book):
        """Test popping from empty book returns None."""
        assert book.pop_best_order(Side.BUY) is None
        assert book.pop_best_order(Side.SELL) is None
    
    def test_peek_from_empty_book(self, book):
        """Test peeking at empty book returns None."""
        assert book.peek_best_order(Side.BUY) is None
        assert book.peek_best_order(Side.SELL) is None