"""
Main trading engine coordinating order books and matching.
"""
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
import time

from .models import Order, Trade, OrderStatus
from .book import OrderBook
from .matching import MatchingEngine
from .replay import EventLogger


class TradingEngine:
    """
    Central trading engine managing multiple symbols.
    
    Coordinates:
    - Order book management per symbol
    - Order matching
    - Event logging for replay
    - Statistics tracking
    """
    
    def __init__(self, enable_logging: bool = True, event_callback=None):
        """
        Initialize trading engine.
        
        Args:
            enable_logging: Enable event logging for replay
        """
        self.books: Dict[str, OrderBook] = {}
        self.matching_engine = MatchingEngine()
        self.event_logger = EventLogger() if enable_logging else None
        
        # Statistics
        self.total_orders_submitted = 0
        self.total_orders_cancelled = 0
        self.total_trades_executed = 0
        self.start_time = time.time()
        
        # Latency tracking
        self.latencies = []

        self.event_callback = event_callback
    
    def submit_order(self, order: Order) -> List[Trade]:
        """
        Submit order to the exchange.
        
        Args:
            order: Order to submit
            
        Returns:
            List of trades executed
            
        Process:
        1. Get or create order book for symbol
        2. Attempt to match order
        3. Add remaining order to book if not fully filled
        4. Log events
        5. Track statistics
        """
        start_time = time.perf_counter()
        
        # Get or create book
        if order.symbol not in self.books:
            self.books[order.symbol] = OrderBook(order.symbol)
        
        book = self.books[order.symbol]
        
        # Match order
        trades, remaining_order = self.matching_engine.match_order(order, book)
        
        # Add remaining order to book if not fully filled
        if remaining_order.status != OrderStatus.FILLED:
            book.add_order(remaining_order)
        
        # Log events
        if self.event_logger:
            self.event_logger.log_order(order)
            for trade in trades:
                self.event_logger.log_trade(trade)
        
        # Update statistics
        self.total_orders_submitted += 1
        self.total_trades_executed += len(trades)
        
        # Track latency
        latency = (time.perf_counter() - start_time) * 1000  # ms
        self.latencies.append(latency)

        if self.event_callback:
            asyncio.create_task(self.event_callback('order_submitted', order))
        for trade in trades:
            if self.event_callback:
                asyncio.create_task(self.event_callback('trade_executed', trade))
        
        return trades
    
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        Cancel order by ID.
        
        Args:
            order_id: Order to cancel
            symbol: Symbol of the order
            
        Returns:
            True if cancelled successfully
        """
        if symbol not in self.books:
            return False
        
        book = self.books[symbol]
        cancelled_order = book.cancel_order(order_id)
        
        if cancelled_order:
            if self.event_logger:
                self.event_logger.log_cancel(cancelled_order)
            self.total_orders_cancelled += 1
            return True
        
        return False
    
    def get_book(self, symbol: str) -> Optional[OrderBook]:
        """Get order book for symbol."""
        return self.books.get(symbol)
    
    def get_book_depth(self, symbol: str, levels: int = 5) -> Optional[dict]:
        """Get book depth for symbol."""
        book = self.get_book(symbol)
        return book.get_book_depth(levels) if book else None
    
    def get_order(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order by ID."""
        book = self.get_book(symbol)
        return book.get_order(order_id) if book else None
    
    def get_statistics(self) -> dict:
        """
        Get comprehensive engine statistics.
        
        Returns:
            Dictionary with performance metrics
        """
        uptime = time.time() - self.start_time
        
        # Calculate latency percentiles
        latency_stats = {}
        if self.latencies:
            sorted_lat = sorted(self.latencies)
            n = len(sorted_lat)
            latency_stats = {
                "min_ms": sorted_lat[0],
                "p50_ms": sorted_lat[n // 2],
                "p95_ms": sorted_lat[int(n * 0.95)],
                "p99_ms": sorted_lat[int(n * 0.99)],
                "max_ms": sorted_lat[-1],
                "mean_ms": sum(self.latencies) / n
            }
        
        # Calculate throughput
        orders_per_sec = self.total_orders_submitted / uptime if uptime > 0 else 0
        trades_per_sec = self.total_trades_executed / uptime if uptime > 0 else 0
        
        # Aggregate book statistics
        book_stats = {}
        for symbol, book in self.books.items():
            book_stats[symbol] = book.get_statistics()
        
        return {
            "uptime_seconds": uptime,
            "total_orders_submitted": self.total_orders_submitted,
            "total_orders_cancelled": self.total_orders_cancelled,
            "total_trades_executed": self.total_trades_executed,
            "orders_per_second": orders_per_sec,
            "trades_per_second": trades_per_sec,
            "latency": latency_stats,
            "active_symbols": len(self.books),
            "books": book_stats
        }
    
    def reset_statistics(self):
        """Reset statistics counters."""
        self.total_orders_submitted = 0
        self.total_orders_cancelled = 0
        self.total_trades_executed = 0
        self.start_time = time.time()
        self.latencies = []
    
    def get_event_log(self) -> Optional[List]:
        """Get event log for replay."""
        if self.event_logger:
            return self.event_logger.get_events()
        return None
    
    def save_event_log(self, filepath: str):
        """Save event log to file."""
        if self.event_logger:
            self.event_logger.save_to_file(filepath)