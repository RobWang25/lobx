# tests/test_performance.py
"""Performance and load testing for the trading engine."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from lobx.engine import TradingEngine
from lobx.models import Order, Side, generate_order_id
from decimal import Decimal
from datetime import datetime

def test_concurrent_order_submission():
    """Test handling concurrent orders."""
    engine = TradingEngine(enable_logging=False)
    
    def submit_orders(user_id: str, count: int):
        for i in range(count):
            order = Order(
                order_id=generate_order_id(),
                user_id=user_id,
                symbol="TEST",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                price=Decimal("100.00"),
                quantity=10,
                timestamp=datetime.now()
            )
            engine.submit_order(order)
    
    # Simulate 10 concurrent users
    start = time.time()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(submit_orders, f"user{i}", 100)
            for i in range(10)
        ]
        for future in futures:
            future.result()
    
    elapsed = time.time() - start
    stats = engine.get_statistics()
    
    print(f"Submitted {stats['total_orders_submitted']} orders in {elapsed:.2f}s")
    print(f"Throughput: {stats['orders_per_second']:.2f} orders/sec")
    print(f"Latency p50: {stats['latency']['p50_ms']:.3f}ms")
    print(f"Latency p99: {stats['latency']['p99_ms']:.3f}ms")