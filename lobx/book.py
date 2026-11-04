"""
Limit Order Book implementation.
Uses price-level dictionaries with FIFO queues and heaps for best prices.

Each price level is an OrderedDict of order_id -> order. It keeps arrival order
like a queue, and it can also delete any order by ID without scanning.
"""
from collections import OrderedDict, defaultdict
from decimal import Decimal
from typing import Optional, Dict, List, Set
import heapq

from .models import Order, Side, OrderStatus


class OrderBook:
    """
    Limit order book for a single symbol.
    
    Data structures:
    - Bids: Dict[price -> FIFO queue of buy orders]
    - Asks: Dict[price -> FIFO queue of sell orders]
    - Order index: Dict[order_id -> order] for O(1) lookups
    - Best bid/ask heaps, cleaned up lazily, for top-of-book access
    """
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        
        # Price levels with FIFO queues
        self.bids: Dict[Decimal, "OrderedDict[str, Order]"] = defaultdict(OrderedDict)
        self.asks: Dict[Decimal, "OrderedDict[str, Order]"] = defaultdict(OrderedDict)
        
        # Order index for fast lookups
        self.order_index: Dict[str, Order] = {}
        
        # Best prices (max heap for bids, min heap for asks)
        self.bid_prices: List[Decimal] = []  # Use negative prices for max-heap
        self.ask_prices: List[Decimal] = []

        # Prices currently in each heap, so each price is pushed only once
        self._bid_prices_in_heap: Set[Decimal] = set()
        self._ask_prices_in_heap: Set[Decimal] = set()

        # Statistics
        self.total_orders = 0
        self.total_volume = 0
    
    def add_order(self, order: Order) -> bool:
        """
        Add order to book.
        
        Args:
            order: Order to add
            
        Returns:
            True if added successfully
            
        Time complexity: O(log n) for heap operations
        """
        if order.symbol != self.symbol:
            raise ValueError(f"Order symbol {order.symbol} doesn't match book {self.symbol}")
        
        if order.order_id in self.order_index:
            return False  # Duplicate order ID
        
        # Add to appropriate side
        if order.side == Side.BUY:
            self.bids[order.price][order.order_id] = order
            if order.price not in self._bid_prices_in_heap:
                self._bid_prices_in_heap.add(order.price)
                heapq.heappush(self.bid_prices, -order.price)
        else:
            self.asks[order.price][order.order_id] = order
            if order.price not in self._ask_prices_in_heap:
                self._ask_prices_in_heap.add(order.price)
                heapq.heappush(self.ask_prices, order.price)
        
        # Index the order
        self.order_index[order.order_id] = order
        self.total_orders += 1
        
        return True
    
    def cancel_order(self, order_id: str) -> Optional[Order]:
        """
        Cancel order by ID.
        
        Args:
            order_id: Order to cancel
            
        Returns:
            Cancelled order or None if not found
            
        Time complexity: O(1)
        """
        order = self.order_index.get(order_id)
        if not order:
            return None
        
        # Remove from price level queue
        queue = self.bids[order.price] if order.side == Side.BUY else self.asks[order.price]
        
        del queue[order_id]

        # Clean up empty price level
        if not queue:
            if order.side == Side.BUY:
                del self.bids[order.price]
            else:
                del self.asks[order.price]
        
        # Remove from index
        del self.order_index[order_id]
        
        return order.with_status(OrderStatus.CANCELLED)
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID. O(1) lookup."""
        return self.order_index.get(order_id)
    
    def get_best_bid(self) -> Optional[Decimal]:
        """
        Get best bid price.
        
        Returns:
            Highest bid price or None if no bids
            
        Time complexity: O(log n) worst case (heap cleanup)
        """
        while self.bid_prices:
            best = -self.bid_prices[0]
            if best in self.bids and self.bids[best]:
                return best
            heapq.heappop(self.bid_prices)
            self._bid_prices_in_heap.discard(best)
        return None
    
    def get_best_ask(self) -> Optional[Decimal]:
        """
        Get best ask price.
        
        Returns:
            Lowest ask price or None if no asks
            
        Time complexity: O(log n) worst case
        """
        while self.ask_prices:
            best = self.ask_prices[0]
            if best in self.asks and self.asks[best]:
                return best
            heapq.heappop(self.ask_prices)
            self._ask_prices_in_heap.discard(best)
        return None
    
    def get_spread(self) -> Optional[Decimal]:
        """Get bid-ask spread."""
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid is not None and ask is not None:
            return ask - bid
        return None
    
    def get_midprice(self) -> Optional[Decimal]:
        """Get mid price."""
        bid = self.get_best_bid()
        ask = self.get_best_ask()
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        return None
    
    def get_book_depth(self, levels: int = 5) -> dict:
        """
        Get book depth for top N levels.
        
        Args:
            levels: Number of price levels to include
            
        Returns:
            Dictionary with bids and asks
        """
        bids = []
        asks = []
        
        # Get top bid levels
        bid_prices_sorted = sorted(
            [p for p in self.bids.keys() if self.bids[p]],
            reverse=True
        )[:levels]
        
        for price in bid_prices_sorted:
            total_qty = sum(o.quantity for o in self.bids[price].values())
            num_orders = len(self.bids[price])
            bids.append({
                "price": float(price),
                "quantity": total_qty,
                "orders": num_orders
            })
        
        # Get top ask levels
        ask_prices_sorted = sorted(
            [p for p in self.asks.keys() if self.asks[p]]
        )[:levels]
        
        for price in ask_prices_sorted:
            total_qty = sum(o.quantity for o in self.asks[price].values())
            num_orders = len(self.asks[price])
            asks.append({
                "price": float(price),
                "quantity": total_qty,
                "orders": num_orders
            })
        
        return {
            "symbol": self.symbol,
            "bids": bids,
            "asks": asks,
            "spread": float(self.get_spread()) if self.get_spread() else None,
            "midprice": float(self.get_midprice()) if self.get_midprice() else None
        }
    
    def get_orders_at_price(self, side: Side, price: Decimal) -> List[Order]:
        """Get all orders at a specific price level."""
        queue = self.bids[price] if side == Side.BUY else self.asks[price]
        return list(queue.values())
    
    def peek_best_order(self, side: Side) -> Optional[Order]:
        """
        Peek at best order on given side without removing.
        
        Args:
            side: BUY or SELL
            
        Returns:
            Best order or None
        """
        if side == Side.BUY:
            price = self.get_best_bid()
            if price and self.bids[price]:
                return next(iter(self.bids[price].values()))
        else:
            price = self.get_best_ask()
            if price and self.asks[price]:
                return next(iter(self.asks[price].values()))
        return None
    
    def pop_best_order(self, side: Side) -> Optional[Order]:
        """
        Remove and return best order on given side.
        
        Args:
            side: BUY or SELL
            
        Returns:
            Best order or None
        """
        if side == Side.BUY:
            price = self.get_best_bid()
            if price and self.bids[price]:
                _, order = self.bids[price].popitem(last=False)
                if not self.bids[price]:
                    del self.bids[price]
                del self.order_index[order.order_id]
                return order
        else:
            price = self.get_best_ask()
            if price and self.asks[price]:
                _, order = self.asks[price].popitem(last=False)
                if not self.asks[price]:
                    del self.asks[price]
                del self.order_index[order.order_id]
                return order
        return None
    
    def reduce_best_order(self, side: Side, quantity: int) -> Optional[Order]:
        """
        Partially fill the best order on the given side, keeping its queue position.

        Args:
            side: BUY or SELL
            quantity: Amount filled, which must be less than the order's quantity

        Returns:
            Updated order or None if that side is empty

        Time complexity: O(1) after finding the best price
        """
        price = self.get_best_bid() if side == Side.BUY else self.get_best_ask()
        if price is None:
            return None

        queue = self.bids[price] if side == Side.BUY else self.asks[price]
        order = next(iter(queue.values()))
        if quantity >= order.quantity:
            raise ValueError("Partial fill must be less than the order's quantity")

        updated = order.with_quantity(order.quantity - quantity).with_status(
            OrderStatus.PARTIAL
        )
        queue[order.order_id] = updated  # Updating a key keeps its position
        self.order_index[order.order_id] = updated
        return updated

    def update_order(self, order: Order):
        """Update order in index only; its queue entry is unchanged."""
        self.order_index[order.order_id] = order
    
    def get_statistics(self) -> dict:
        """Get book statistics."""
        total_bid_qty = sum(
            sum(o.quantity for o in queue.values())
            for queue in self.bids.values()
        )
        total_ask_qty = sum(
            sum(o.quantity for o in queue.values())
            for queue in self.asks.values()
        )
        
        return {
            "symbol": self.symbol,
            "total_orders": self.total_orders,
            "active_orders": len(self.order_index),
            "bid_levels": len([p for p in self.bids if self.bids[p]]),
            "ask_levels": len([p for p in self.asks if self.asks[p]]),
            "total_bid_quantity": total_bid_qty,
            "total_ask_quantity": total_ask_qty,
            "best_bid": float(self.get_best_bid()) if self.get_best_bid() else None,
            "best_ask": float(self.get_best_ask()) if self.get_best_ask() else None,
        }