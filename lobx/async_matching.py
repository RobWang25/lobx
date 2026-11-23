"""
Async matching engine with batch processing and optional thread safety.
"""
import asyncio
from datetime import datetime
from threading import Lock

from .models import Order, Trade, Side, OrderStatus, generate_trade_id
from .book import OrderBook


class AsyncMatchingEngine:
    """
    Async version of matching engine with batch processing support.
    
    Features:
    - Async/await throughout matching pipeline
    - Batch processing for high-volume scenarios
    - Optional thread-safe mode
    - Non-blocking I/O operations
    """
    
    def __init__(
        self, 
        enable_self_trade_prevention: bool = True,
        thread_safe: bool = False,
        batch_size: int = 100
    ):
        """
        Initialize async matching engine.
        
        Args:
            enable_self_trade_prevention: Prevent users from trading with themselves
            thread_safe: Enable thread-safe mode with locks
            batch_size: Maximum batch size for batch processing
        """
        self.enable_self_trade_prevention = enable_self_trade_prevention
        self.thread_safe = thread_safe
        self.batch_size = batch_size
        self.total_trades = 0
        
        # Thread safety
        self._lock = Lock() if thread_safe else None
        
        # Batch processing queue
        self._order_queue: asyncio.Queue = asyncio.Queue()
        self._batch_processor_task: asyncio.Task | None = None
    
    async def match_order(
        self, 
        order: Order, 
        book: OrderBook
    ) -> tuple[list[Trade], Order]:
        """
        Match incoming order against order book (async version).
        
        Args:
            order: Incoming order to match
            book: Order book to match against
            
        Returns:
            Tuple of (list of trades, remaining order)
        """
        if self.thread_safe and self._lock:
            with self._lock:
                return await self._match_order_impl(order, book)
        else:
            return await self._match_order_impl(order, book)
    
    async def _match_order_impl(
        self, 
        order: Order, 
        book: OrderBook
    ) -> tuple[list[Trade], Order]:
        """Internal match order implementation"""
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
            opposing_qty = opposing_order.quantity - match_qty
            
            # Remove opposing order from book
            book.pop_best_order(opposing_side)
            
            # Re-add opposing order if partially filled
            if opposing_qty > 0:
                updated_opposing = opposing_order.with_quantity(opposing_qty).with_status(
                    OrderStatus.PARTIAL
                )
                book.add_order(updated_opposing)
            
            self.total_trades += 1
            
            # Yield control for other async operations
            await asyncio.sleep(0)
        
        # Create remaining order object
        if remaining_qty == 0:
            remaining_order = order.with_status(OrderStatus.FILLED)
        elif remaining_qty < order.quantity:
            remaining_order = order.with_quantity(remaining_qty).with_status(
                OrderStatus.PARTIAL
            )
        else:
            remaining_order = order.with_status(OrderStatus.OPEN)
        
        return trades, remaining_order
    
    async def match_batch(
        self, 
        orders: list[Order], 
        book: OrderBook
    ) -> list[tuple[Order, list[Trade], Order]]:
        """
        Match a batch of orders for better throughput.
        
        Args:
            orders: List of orders to match
            book: Order book to match against
            
        Returns:
            List of (original_order, trades, remaining_order) tuples
        """
        results = []
        
        # Process orders in batches
        for i in range(0, len(orders), self.batch_size):
            batch = orders[i:i + self.batch_size]
            
            # Match each order in the batch
            batch_results = await asyncio.gather(
                *[self.match_order(order, book) for order in batch]
            )
            
            # Combine results
            for order, (trades, remaining) in zip(batch, batch_results):
                results.append((order, trades, remaining))
        
        return results
    
    def _can_match(self, order: Order, book: OrderBook) -> bool:
        """Check if order can match against book"""
        if order.side == Side.BUY:
            best_ask = book.get_best_ask()
            return best_ask is not None and order.price >= best_ask
        else:  # SELL
            best_bid = book.get_best_bid()
            return best_bid is not None and order.price <= best_bid
    
    def _create_trade(
        self,
        aggressive_order: Order,
        passive_order: Order,
        price,
        quantity: int
    ) -> Trade:
        """Create trade from matched orders"""
        buyer_id = (
            aggressive_order.user_id
            if aggressive_order.side == Side.BUY
            else passive_order.user_id
        )
        seller_id = (
            aggressive_order.user_id
            if aggressive_order.side == Side.SELL
            else passive_order.user_id
        )
        
        return Trade(
            trade_id=generate_trade_id(),
            symbol=aggressive_order.symbol,
            price=price,
            quantity=quantity,
            buyer_order_id=aggressive_order.order_id if aggressive_order.side == Side.BUY else passive_order.order_id,
            seller_order_id=aggressive_order.order_id if aggressive_order.side == Side.SELL else passive_order.order_id,
            buyer_user_id=buyer_id,
            seller_user_id=seller_id,
            timestamp=datetime.now(),
            aggressor_side=aggressive_order.side
        )
    
    async def start_batch_processor(self, book: OrderBook):
        """
        Start background batch processor.
        
        Orders are queued and processed in batches for higher throughput.
        """
        async def process_batches():
            while True:
                # Collect a batch
                batch = []
                try:
                    # Wait for first order
                    order = await asyncio.wait_for(
                        self._order_queue.get(), 
                        timeout=0.1
                    )
                    batch.append(order)
                    
                    # Collect more orders up to batch_size
                    while len(batch) < self.batch_size:
                        try:
                            order = self._order_queue.get_nowait()
                            batch.append(order)
                        except asyncio.QueueEmpty:
                            break
                    
                    # Process batch
                    if batch:
                        await self.match_batch(batch, book)
                
                except asyncio.TimeoutError:
                    # No orders in queue, continue
                    continue
                except asyncio.CancelledError:
                    break
        
        self._batch_processor_task = asyncio.create_task(process_batches())
    
    async def queue_order(self, order: Order):
        """
        Queue order for batch processing.
        
        Must call start_batch_processor first.
        """
        await self._order_queue.put(order)
    
    async def stop_batch_processor(self):
        """Stop background batch processor"""
        if self._batch_processor_task:
            self._batch_processor_task.cancel()
            try:
                await self._batch_processor_task
            except asyncio.CancelledError:
                pass
