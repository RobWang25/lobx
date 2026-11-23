"""
Matching engine with price-time priority.
Implements FIFO matching within price levels.
"""
from typing import List, Tuple
from datetime import datetime

from .models import Order, Trade, Side, OrderStatus, generate_trade_id
from .book import OrderBook


class MatchingEngine:
    """
    Matches incoming orders against the order book.
    
    Algorithm:
    1. Check if order crosses the spread
    2. Match against best opposing price level (FIFO)
    3. Generate trades for matches
    4. Update order quantities
    5. Continue until order filled or no more matches
    """
    
    def __init__(self, enable_self_trade_prevention: bool = True):
        """
        Initialize matching engine.
        
        Args:
            enable_self_trade_prevention: Prevent users from trading with themselves
        """
        self.enable_self_trade_prevention = enable_self_trade_prevention
        self.total_trades = 0
    
    def match_order(self, order: Order, book: OrderBook) -> Tuple[List[Trade], Order]:
        """
        Match incoming order against order book.
        
        Args:
            order: Incoming order to match
            book: Order book to match against
            
        Returns:
            Tuple of (list of trades, remaining order or None)
            
        The order parameter is not modified; a new order with updated
        quantity/status is returned if partially filled.
        """
        trades = []
        remaining_qty = order.quantity
        
        while remaining_qty > 0:
            if not self._can_match(order, book):
                break
            
            # Get best opposing order
            opposing_side = Side.SELL if order.side == Side.BUY else Side.BUY
            opposing_order = book.peek_best_order(opposing_side)
            
            if not opposing_order:
                break
            
            # Self-trade prevention
            if self.enable_self_trade_prevention:
                if order.user_id == opposing_order.user_id:
                    # Cancel the resting order to prevent self-trade
                    book.cancel_order(opposing_order.order_id)
                    continue
            
            # Execute trade
            match_qty = min(remaining_qty, opposing_order.quantity)
            match_price = opposing_order.price
            
            trade = self._create_trade(
                order, opposing_order, match_price, match_qty
            )
            trades.append(trade)
            
            # Update quantities
            remaining_qty -= match_qty

            # A fully filled order leaves the book. A partially filled one stays
            # where it is, so it keeps its time priority.
            if match_qty == opposing_order.quantity:
                book.pop_best_order(opposing_side)
            else:
                book.reduce_best_order(opposing_side, match_qty)

            self.total_trades += 1
        
        # Create remaining order object
        if remaining_qty == 0:
            remaining_order = order.with_status(OrderStatus.FILLED)
        elif remaining_qty < order.quantity:
            remaining_order = order.with_quantity(remaining_qty).with_status(
                OrderStatus.PARTIAL
            )
        else:
            remaining_order = order
        
        return trades, remaining_order
    
    def _can_match(self, order: Order, book: OrderBook) -> bool:
        """
        Check if order can match against book.
        
        Args:
            order: Order to check
            book: Order book
            
        Returns:
            True if order crosses the spread
        """
        if order.side == Side.BUY:
            best_ask = book.get_best_ask()
            return best_ask is not None and order.price >= best_ask
        else:
            best_bid = book.get_best_bid()
            return best_bid is not None and order.price <= best_bid
    
    def _create_trade(
        self, 
        incoming_order: Order,
        resting_order: Order,
        price: float,
        quantity: int
    ) -> Trade:
        """
        Create trade record.
        
        Args:
            incoming_order: Newly arrived order (taker)
            resting_order: Order already in book (maker)
            price: Execution price
            quantity: Trade quantity
            
        Returns:
            Trade object
        """
        # Determine buy/sell sides
        if incoming_order.side == Side.BUY:
            buy_order_id = incoming_order.order_id
            sell_order_id = resting_order.order_id
            buyer_user_id = incoming_order.user_id
            seller_user_id = resting_order.user_id
        else:
            buy_order_id = resting_order.order_id
            sell_order_id = incoming_order.order_id
            buyer_user_id = resting_order.user_id
            seller_user_id = incoming_order.user_id
        
        return Trade(
            trade_id=generate_trade_id(),
            symbol=incoming_order.symbol,
            buy_order_id=buy_order_id,
            sell_order_id=sell_order_id,
            price=price,
            quantity=quantity,
            timestamp=datetime.now(),
            buyer_user_id=buyer_user_id,
            seller_user_id=seller_user_id
        )
    
    def get_statistics(self) -> dict:
        """Get matching engine statistics."""
        return {
            "total_trades": self.total_trades,
            "self_trade_prevention": self.enable_self_trade_prevention
        }