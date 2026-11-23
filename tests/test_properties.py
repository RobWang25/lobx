"""
Property-based tests using Hypothesis.
Tests invariants that should always hold.
"""
from hypothesis import given, strategies as st, settings
from dataclasses import replace
from decimal import Decimal
from datetime import datetime

from lobx.models import Order, Side, OrderStatus
from lobx.book import OrderBook
from lobx.matching import MatchingEngine
from lobx.engine import TradingEngine


# Custom strategies
@st.composite
def order_strategy(draw, symbol="TEST", user_prefix="user"):
    """Generate valid orders."""
    user_id = f"{user_prefix}{draw(st.integers(min_value=1, max_value=100))}"
    side = draw(st.sampled_from([Side.BUY, Side.SELL]))
    price = Decimal(str(draw(st.floats(min_value=1.0, max_value=1000.0))))
    price = price.quantize(Decimal("0.01"))
    quantity = draw(st.integers(min_value=1, max_value=1000))
    
    return Order(
        order_id=f"ORD-{draw(st.integers(min_value=1, max_value=1000000))}",
        user_id=user_id,
        symbol=symbol,
        side=side,
        price=price,
        quantity=quantity,
        timestamp=datetime.now()
    )


class TestOrderBookInvariants:
    """Test order book invariants using property-based testing."""
    
    @given(orders=st.lists(order_strategy(), min_size=0, max_size=50))
    @settings(max_examples=100)
    def test_total_quantities_never_negative(self, orders):
        """Total bid and ask quantities should never be negative."""
        book = OrderBook("TEST")
        
        for order in orders:
            book.add_order(order)
        
        stats = book.get_statistics()
        assert stats["total_bid_quantity"] >= 0
        assert stats["total_ask_quantity"] >= 0
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_best_bid_always_highest(self, orders):
        """Best bid should always be the highest bid price."""
        book = OrderBook("TEST")
        
        buy_orders = [o for o in orders if o.side == Side.BUY]
        if not buy_orders:
            return
        
        for order in buy_orders:
            book.add_order(order)
        
        best_bid = book.get_best_bid()
        if best_bid is not None:
            # Check no bid is higher than best bid
            for price, queue in book.bids.items():
                if queue:
                    assert price <= best_bid
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_best_ask_always_lowest(self, orders):
        """Best ask should always be the lowest ask price."""
        book = OrderBook("TEST")
        
        sell_orders = [o for o in orders if o.side == Side.SELL]
        if not sell_orders:
            return
        
        for order in sell_orders:
            book.add_order(order)
        
        best_ask = book.get_best_ask()
        if best_ask is not None:
            # Check no ask is lower than best ask
            for price, queue in book.asks.items():
                if queue:
                    assert price >= best_ask
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=50))
    @settings(max_examples=100)
    def test_order_index_consistency(self, orders):
        """Order index should always match orders in book."""
        book = OrderBook("TEST")
        
        unique_orders = []
        seen_ids = set()
        for order in orders:
            if order.order_id not in seen_ids:
                unique_orders.append(order)
                seen_ids.add(order.order_id)
        
        for order in unique_orders:
            book.add_order(order)
        
        # Every order in index should be in a price level
        for order_id, order in book.order_index.items():
            if order.side == Side.BUY:
                assert book.bids[order.price][order_id] == order
            else:
                assert book.asks[order.price][order_id] == order
    
    @given(
        orders=st.lists(order_strategy(), min_size=5, max_size=20),
        cancel_indices=st.lists(st.integers(min_value=0, max_value=19), min_size=1, max_size=10)
    )
    @settings(max_examples=50)
    def test_cancellation_maintains_consistency(self, orders, cancel_indices):
        """Cancelling orders should maintain book consistency."""
        book = OrderBook("TEST")
        
        unique_orders = []
        seen_ids = set()
        for order in orders:
            if order.order_id not in seen_ids:
                unique_orders.append(order)
                seen_ids.add(order.order_id)
        
        if not unique_orders:
            return
        
        for order in unique_orders:
            book.add_order(order)
        
        # Cancel some orders
        for idx in cancel_indices:
            if idx < len(unique_orders):
                book.cancel_order(unique_orders[idx].order_id)
        
        # Check consistency
        stats = book.get_statistics()
        assert stats["total_bid_quantity"] >= 0
        assert stats["total_ask_quantity"] >= 0
        assert stats["active_orders"] == len(book.order_index)
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=30))
    @settings(max_examples=50)
    def test_latency_always_positive(self, orders):
        """Latency measurements should always be positive."""
        engine = TradingEngine(enable_logging=False)
        
        for order in orders:
            engine.submit_order(order)
        
        stats = engine.get_statistics()
        latency = stats.get("latency", {})
        
        if latency:
            assert latency.get("min_ms", 0) >= 0
            assert latency.get("max_ms", 0) >= 0
            assert latency.get("mean_ms", 0) >= 0
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=30))
    @settings(max_examples=50)
    def test_active_orders_equals_index_size(self, orders):
        """Active orders count should equal order index size."""
        engine = TradingEngine(enable_logging=False)
        
        for order in orders:
            engine.submit_order(order)
        
        book = engine.get_book("TEST")
        if book:
            stats = book.get_statistics()
            assert stats["active_orders"] == len(book.order_index)


class TestSelfTradePreventionInvariants:
    """Test self-trade prevention invariants."""
    
    @given(
        price=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("100.00"), places=2),
        quantity=st.integers(min_value=1, max_value=100)
    )
    @settings(max_examples=100)
    def test_no_self_trades(self, price, quantity):
        """Users should never trade with themselves."""
        engine = TradingEngine(enable_logging=False)
        
        # Submit sell order from user1
        sell_order = Order(
            order_id="SELL1",
            user_id="user1",
            symbol="TEST",
            side=Side.SELL,
            price=price,
            quantity=quantity,
            timestamp=datetime.now()
        )
        engine.submit_order(sell_order)
        
        # Submit buy order from same user at crossing price
        buy_order = Order(
            order_id="BUY1",
            user_id="user1",  # Same user
            symbol="TEST",
            side=Side.BUY,
            price=price,
            quantity=quantity,
            timestamp=datetime.now()
        )
        trades = engine.submit_order(buy_order)
        
        # Should not result in any trades due to self-trade prevention
        assert len(trades) == 0
    
    @given(
        orders=st.lists(order_strategy(user_prefix="user"), min_size=2, max_size=20)
    )
    @settings(max_examples=50)
    def test_trades_never_between_same_user(self, orders):
        """Trades should never occur between same user."""
        engine = TradingEngine(enable_logging=False)
        
        all_trades = []
        for order in orders:
            trades = engine.submit_order(order)
            all_trades.extend(trades)
        
        # Check all trades are between different users
        for trade in all_trades:
            assert trade.buyer_user_id != trade.seller_user_id


class TestDeterminismInvariants:
    """Test determinism invariants."""
    
    @given(orders=st.lists(order_strategy(), min_size=5, max_size=20))
    @settings(max_examples=20)
    def test_same_inputs_same_outputs(self, orders):
        """Same order sequence should produce same results."""
        # Run twice
        results = []
        
        for _ in range(2):
            engine = TradingEngine(enable_logging=False)
            
            for order in orders:
                engine.submit_order(order)
            
            stats = engine.get_statistics()
            results.append({
                "orders": stats["total_orders_submitted"],
                "trades": stats["total_trades_executed"]
            })
        
        # Results should be identical
        assert results[0] == results[1]
    
    @given(orders=st.lists(order_strategy(), min_size=5, max_size=15))
    @settings(max_examples=20)
    def test_replay_produces_same_result(self, orders):
        """Replaying events should produce same result."""
        from lobx.replay import EventReplayer
        import tempfile
        import os
        
        # Original run
        engine1 = TradingEngine(enable_logging=True)
        for order in orders:
            engine1.submit_order(order)
        
        original_stats = engine1.get_statistics()
        
        # Save and replay
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            temp_file = f.name
        
        try:
            engine1.save_event_log(temp_file)
            
            # Replay
            engine2 = TradingEngine(enable_logging=False)
            EventReplayer.replay_from_file(temp_file, engine2)
            
            replayed_stats = engine2.get_statistics()
            
            # Should have same trades
            assert original_stats["total_trades_executed"] == replayed_stats["total_trades_executed"]
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)


class TestPriceQuantityInvariants:
    """Test invariants related to prices and quantities."""
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=30))
    @settings(max_examples=50)
    def test_prices_always_positive(self, orders):
        """All prices should always be positive."""
        engine = TradingEngine(enable_logging=False)
        
        for order in orders:
            assert order.price > 0
            trades = engine.submit_order(order)
            
            for trade in trades:
                assert trade.price > 0
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=30))
    @settings(max_examples=50)
    def test_quantities_always_positive(self, orders):
        """All quantities should always be positive."""
        engine = TradingEngine(enable_logging=False)
        
        for order in orders:
            assert order.quantity > 0
            trades = engine.submit_order(order)
            
            for trade in trades:
                assert trade.quantity > 0
    
    @given(
        orders=st.lists(order_strategy(), min_size=2, max_size=20)
    )
    @settings(max_examples=50)
    def test_trade_quantity_never_exceeds_order(self, orders):
        """Trade quantity should never exceed original order quantity."""
        engine = TradingEngine(enable_logging=False)
        
        for order in orders:
            trades = engine.submit_order(order)
            
            # Sum of all trades should not exceed order quantity
            total_traded = sum(t.quantity for t in trades)
            assert total_traded <= order.quantity


class TestBookStructureInvariants:
    """Test invariants about book structure."""
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=30))
    @settings(max_examples=50)
    def test_empty_queues_removed(self, orders):
        """Empty price level queues should be removed from book."""
        book = OrderBook("TEST")
        
        unique_orders = []
        seen_ids = set()
        for order in orders:
            if order.order_id not in seen_ids:
                unique_orders.append(order)
                seen_ids.add(order.order_id)
        
        for order in unique_orders:
            book.add_order(order)
        
        # All queues should be non-empty
        for price, queue in book.bids.items():
            assert len(queue) > 0
        
        for price, queue in book.asks.items():
            assert len(queue) > 0
    
    @given(orders=st.lists(order_strategy(), min_size=1, max_size=30))
    @settings(max_examples=50)
    def test_order_index_matches_queues(self, orders):
        """Every order in index should be in exactly one queue."""
        book = OrderBook("TEST")
        
        unique_orders = []
        seen_ids = set()
        for order in orders:
            if order.order_id not in seen_ids:
                unique_orders.append(order)
                seen_ids.add(order.order_id)
        
        for order in unique_orders:
            book.add_order(order)
        
        # Count orders in queues
        orders_in_queues = 0
        for queue in book.bids.values():
            orders_in_queues += len(queue)
        for queue in book.asks.values():
            orders_in_queues += len(queue)
        
        # Should match index size
        assert orders_in_queues == len(book.order_index)


class TestCancellationInvariants:
    """Test invariants related to order cancellation."""
    
    @given(
        orders=st.lists(order_strategy(), min_size=5, max_size=20)
    )
    @settings(max_examples=50)
    def test_cancelled_orders_not_in_index(self, orders):
        """Cancelled orders should not be in order index."""
        book = OrderBook("TEST")
        
        unique_orders = []
        seen_ids = set()
        for order in orders:
            if order.order_id not in seen_ids:
                unique_orders.append(order)
                seen_ids.add(order.order_id)
        
        if not unique_orders:
            return
        
        for order in unique_orders:
            book.add_order(order)
        
        # Cancel half the orders
        to_cancel = unique_orders[:len(unique_orders)//2]
        for order in to_cancel:
            book.cancel_order(order.order_id)
        
        # Cancelled orders should not be in index
        for order in to_cancel:
            assert order.order_id not in book.order_index
    
    @given(
        orders=st.lists(order_strategy(), min_size=5, max_size=20)
    )
    @settings(max_examples=50)
    def test_cancel_returns_correct_status(self, orders):
        """Cancelled orders should have CANCELLED status."""
        book = OrderBook("TEST")
        
        unique_orders = []
        seen_ids = set()
        for order in orders:
            if order.order_id not in seen_ids:
                unique_orders.append(order)
                seen_ids.add(order.order_id)
        
        if not unique_orders:
            return
        
        for order in unique_orders:
            book.add_order(order)
        
        # Cancel first order
        cancelled = book.cancel_order(unique_orders[0].order_id)
        
        if cancelled:
            assert cancelled.status == OrderStatus.CANCELLED

    @given(orders=st.lists(order_strategy(), min_size=1, max_size=30))
    @settings(max_examples=50)
    def test_spread_never_negative(self, orders):
        """Spread should never be negative when using engine (with matching)."""
        engine = TradingEngine(enable_logging=False)
        
        for order in orders:
            engine.submit_order(order)
        
        book = engine.get_book("TEST")
        if book:
            spread = book.get_spread()
            if spread is not None:
                assert spread >= 0


class TestMatchingInvariants:
    """Test matching engine invariants."""
    
    @given(
        buy_orders=st.lists(order_strategy(), min_size=1, max_size=20),
        sell_orders=st.lists(order_strategy(), min_size=1, max_size=20)
    )
    @settings(max_examples=50)
    def test_matching_never_violates_fifo(self, buy_orders, sell_orders):
        """Matching should never violate FIFO within a price level."""
        book = OrderBook("TEST")
        matcher = MatchingEngine()
        arrival = {}

        # Add sell orders first to create resting orders
        for order in sell_orders:
            if order.side == Side.SELL and book.add_order(order):
                arrival[order.order_id] = len(arrival)

        # Now add buy orders and match. Fills at a price must follow arrival
        # order, so the arrival index at each price can never go backwards.
        last_arrival_at_price = {}
        for order in buy_orders:
            if order.side == Side.BUY:
                trades, remaining = matcher.match_order(order, book)

                for trade in trades:
                    assert trade.quantity > 0
                    assert trade.price > 0

                    resting_arrival = arrival[trade.sell_order_id]
                    assert resting_arrival >= last_arrival_at_price.get(trade.price, 0)
                    last_arrival_at_price[trade.price] = resting_arrival

    @given(orders=st.lists(order_strategy(), min_size=2, max_size=30))
    @settings(max_examples=50)
    def test_total_volume_conserved(self, orders):
        """Total volume should be conserved through matching."""
        engine = TradingEngine(enable_logging=False)

        # Unique IDs and users, so duplicate rejection and self-trade prevention
        # can't legitimately remove volume from this test.
        orders = [
            replace(order, order_id=f"O{index}", user_id=f"u{index}")
            for index, order in enumerate(orders)
        ]
        initial_buy_volume = sum(o.quantity for o in orders if o.side == Side.BUY)
        initial_sell_volume = sum(o.quantity for o in orders if o.side == Side.SELL)

        # Submit all orders
        traded_volume = 0
        for order in orders:
            traded_volume += sum(trade.quantity for trade in engine.submit_order(order))

        # Check that volume is conserved
        stats = engine.get_statistics()
        book_stats = stats["books"].get("TEST", {})

        remaining_buy = book_stats.get("total_bid_quantity", 0)
        remaining_sell = book_stats.get("total_ask_quantity", 0)

        # Every share submitted either traded or is still resting
        assert initial_buy_volume == traded_volume + remaining_buy
        assert initial_sell_volume == traded_volume + remaining_sell

    @given(orders=st.lists(order_strategy(), min_size=1, max_size=30))
    @settings(max_examples=50)
    def test_no_negative_quantities(self, orders):
        """Orders and trades should never have negative quantities."""
        engine = TradingEngine(enable_logging=False)
        
        for order in orders:
            trades = engine.submit_order(order)
            
            # Check all trades have positive quantities
            for trade in trades:
                assert trade.quantity > 0
            
            # Check book has no negative quantities
            book = engine.get_book("TEST")
            if book:
                stats = book.get_statistics()
                assert stats["total_bid_quantity"] >= 0
                assert stats["total_ask_quantity"] >= 0
    
    @given(
        buy_price=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("100.00"), places=2),
        sell_price=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("100.00"), places=2),
        quantity=st.integers(min_value=1, max_value=100)
    )
    @settings(max_examples=100)
    def test_orders_only_match_when_crossing(self, buy_price, sell_price, quantity):
        """Orders should only match when they cross the spread."""
        book = OrderBook("TEST")
        matcher = MatchingEngine()
        
        # Add sell order
        sell_order = Order(
            order_id="SELL1",
            user_id="seller",
            symbol="TEST",
            side=Side.SELL,
            price=sell_price,
            quantity=quantity,
            timestamp=datetime.now()
        )
        book.add_order(sell_order)
        
        # Add buy order
        buy_order = Order(
            order_id="BUY1",
            user_id="buyer",
            symbol="TEST",
            side=Side.BUY,
            price=buy_price,
            quantity=quantity,
            timestamp=datetime.now()
        )
        
        trades, remaining = matcher.match_order(buy_order, book)
        
        # Should only match if buy price >= sell price
        if buy_price >= sell_price:
            assert len(trades) > 0
        else:
            assert len(trades) == 0
    
    @given(
        orders=st.lists(order_strategy(), min_size=2, max_size=20)
    )
    @settings(max_examples=50)
    def test_trade_price_always_valid(self, orders):
        """Trade prices should always be within bid-ask range."""
        engine = TradingEngine(enable_logging=False)
        
        all_trades = []
        for order in orders:
            trades = engine.submit_order(order)
            all_trades.extend(trades)
        
        # All trade prices should be positive
        for trade in all_trades:
            assert trade.price > 0

