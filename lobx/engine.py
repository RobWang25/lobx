"""
Main trading engine coordinating order books and matching.
"""
import asyncio
import os
from typing import TYPE_CHECKING, Dict, List, Optional, Union
from datetime import datetime
from threading import Lock
import time

from .models import Order, Trade, OrderStatus
from .book import OrderBook
from .matching import MatchingEngine
from .async_matching import AsyncMatchingEngine
from .replay import EventLogger
from .profiler import PerformanceProfiler, LatencyTracker

if TYPE_CHECKING:
    from .native_book import NativeOrderBook


BACKENDS = ("python", "cpp")


def resolve_backend(backend: Optional[str] = None) -> str:
    """
    Pick the matching backend: the argument if given, else LOBX_BACKEND, else python.

    Raises ValueError for an unknown name, and RuntimeError if cpp is chosen but
    the C++ core isn't built.
    """
    if backend is None:
        backend = os.environ.get("LOBX_BACKEND") or "python"
    name = backend.strip().lower()
    if name not in BACKENDS:
        raise ValueError(f"Unknown backend {name!r}, expected one of {', '.join(BACKENDS)}")
    if name == "cpp":
        from . import _native

        if not _native.AVAILABLE:
            from .native_book import BUILD_HINT

            raise RuntimeError(BUILD_HINT)
    return name


class TradingEngine:
    """
    Central trading engine managing multiple symbols.
    
    Coordinates:
    - Order book management per symbol
    - Order matching
    - Event logging for replay
    - Statistics tracking
    - Performance profiling
    """
    
    def __init__(
        self, 
        enable_logging: bool = True, 
        event_callback=None,
        use_async: bool = False,
        enable_profiling: bool = False,
        backend: Optional[str] = None,
        self_trade_prevention: bool = True,
    ):
        """
        Initialize trading engine.
        
        Args:
            enable_logging: Enable event logging for replay
            event_callback: Callback for trading events
            use_async: Use async matching engine
            enable_profiling: Enable performance profiling
            backend: "python" or "cpp". Defaults to the LOBX_BACKEND environment
                variable, then "python".
            self_trade_prevention: Cancel a resting order instead of letting its
                user trade with themselves
        """
        self.backend = resolve_backend(backend)
        if self.backend == "cpp" and use_async:
            raise ValueError("The async matching engine only works with the python backend")
        self.self_trade_prevention = self_trade_prevention
        self.books: Dict[str, Union[OrderBook, "NativeOrderBook"]] = {}
        self.use_async = use_async

        # Submits and cancels run one at a time. Matching reads the best order and
        # then changes it, so another thread must not change the book in between.
        self._lock = Lock()

        # The cpp backend matches inside NativeOrderBook, so it has no matching engine.
        if self.backend == "cpp":
            self.matching_engine = None
        elif use_async:
            self.matching_engine = AsyncMatchingEngine()
        else:
            self.matching_engine = MatchingEngine(self_trade_prevention)
        
        self.event_logger = EventLogger() if enable_logging else None
        
        # Statistics
        self.total_orders_submitted = 0
        self.total_orders_cancelled = 0
        self.total_orders_rejected = 0
        self.total_trades_executed = 0
        self.start_time = time.time()
        
        # Latency tracking
        self.latencies = []
        
        # Performance profiling
        self.profiler = PerformanceProfiler() if enable_profiling else None
        self.latency_tracker = LatencyTracker()
        if enable_profiling and self.profiler:
            self.profiler.enable()

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

        with self._lock:
            # Profile if enabled
            if self.profiler:
                with self.profiler.measure_operation('submit_order'):
                    return self._submit_order_impl(order, start_time)
            else:
                return self._submit_order_impl(order, start_time)
    
    def _submit_order_impl(self, order: Order, start_time: float) -> List[Trade]:
        """Internal submit order implementation"""
        book = self.books.get(order.symbol)
        new_symbol = book is None
        if new_symbol:
            book = self._new_book(order.symbol)

        # An order whose ID is already resting is rejected before matching, so it
        # can't trade and then fail to rest.
        if book.has_order(order.order_id):
            self.total_orders_rejected += 1
            return []

        if self.backend == "cpp":
            if self.profiler:
                with self.profiler.measure_operation('match_order'):
                    trades = book.submit(order)
            else:
                trades = book.submit(order)
        else:
            # Match order
            if self.profiler:
                with self.profiler.measure_operation('match_order'):
                    trades, remaining_order = self.matching_engine.match_order(order, book)
            else:
                trades, remaining_order = self.matching_engine.match_order(order, book)

            # Add remaining order to book if not fully filled
            if remaining_order.status != OrderStatus.FILLED:
                if self.profiler:
                    with self.profiler.measure_operation('add_to_book'):
                        book.add_order(remaining_order)
                else:
                    book.add_order(remaining_order)

        if new_symbol:
            self.books[order.symbol] = book
        
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
        self.latency_tracker.record('submit_order', latency)

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
        with self._lock:
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
    
    def _new_book(self, symbol: str):
        if self.backend == "cpp":
            from .native_book import NativeOrderBook

            return NativeOrderBook(symbol, self.self_trade_prevention)
        return OrderBook(symbol)

    def get_book(self, symbol: str) -> Optional[Union[OrderBook, "NativeOrderBook"]]:
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
        
        stats = {
            "backend": self.backend,
            "uptime_seconds": uptime,
            "total_orders_submitted": self.total_orders_submitted,
            "total_orders_cancelled": self.total_orders_cancelled,
            "total_orders_rejected": self.total_orders_rejected,
            "total_trades_executed": self.total_trades_executed,
            "orders_per_second": orders_per_sec,
            "trades_per_second": trades_per_sec,
            "latency": latency_stats,
            "active_symbols": len(self.books),
            "books": book_stats
        }
        
        # Add profiling data if available
        if self.profiler:
            stats["profiler_metrics"] = self.profiler.get_custom_metrics()
        
        # Add detailed latency tracking
        stats["operation_latencies"] = self.latency_tracker.get_stats()
        
        return stats
    
    def get_profiling_report(self, sort_by='cumulative', top_n=20) -> str:
        """
        Get detailed profiling report.
        
        Args:
            sort_by: Sort order ('cumulative', 'time', 'calls')
            top_n: Number of top functions to return
            
        Returns:
            String with formatted profiling statistics
        """
        if not self.profiler:
            return "Profiling not enabled"
        
        return self.profiler.get_stats(sort_by, top_n)
    
    def reset_statistics(self):
        """Reset statistics counters."""
        self.total_orders_submitted = 0
        self.total_orders_cancelled = 0
        self.total_orders_rejected = 0
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
