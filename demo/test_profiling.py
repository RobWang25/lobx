"""
Performance profiling script for the trading engine.

This script demonstrates the profiling capabilities added to the system.
"""
import sys
from pathlib import Path

# Add parent directory to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import time
from decimal import Decimal
from lobx.engine import TradingEngine
from lobx.models import Order, Side, generate_order_id
from datetime import datetime


def test_basic_profiling():
    """Test basic profiling functionality"""
    print("=" * 60)
    print("Testing Basic Profiling")
    print("=" * 60)
    
    # Create engine with profiling enabled
    engine = TradingEngine(enable_profiling=True, enable_logging=False)
    
    # Submit orders
    for i in range(100):
        order = Order(
            order_id=generate_order_id(),
            user_id=f"user_{i % 10}",
            symbol="AAPL",
            side=Side.BUY if i % 2 == 0 else Side.SELL,
            price=Decimal("150.00") + Decimal(i % 10) * Decimal("0.10"),
            quantity=100,
            timestamp=datetime.now()
        )
        engine.submit_order(order)
    
    # Get statistics
    stats = engine.get_statistics()
    
    print(f"\nTotal Orders: {stats['total_orders_submitted']}")
    print(f"Total Trades: {stats['total_trades_executed']}")
    print(f"\nLatency Statistics:")
    for key, value in stats['latency'].items():
        print(f"  {key}: {value:.6f} ms")
    
    print(f"\nOperation Latencies:")
    for op, op_stats in stats['operation_latencies'].items():
        if op_stats:
            print(f"  {op}:")
            print(f"    Count: {op_stats['count']}")
            print(f"    Mean: {op_stats['mean']:.6f} ms")
            print(f"    P95: {op_stats['p95']:.6f} ms")
            print(f"    P99: {op_stats['p99']:.6f} ms")
    
    if stats.get('profiler_metrics'):
        print(f"\nProfiler Metrics:")
        for op, metrics in stats['profiler_metrics'].items():
            print(f"  {op}:")
            print(f"    Count: {metrics['count']}")
            print(f"    Avg Time: {metrics['avg_time_ms']:.6f} ms")
            print(f"    Total Time: {metrics['total_time_ms']:.6f} ms")
    
    # Get detailed profiling report
    print("\n" + "=" * 60)
    print("Detailed Profiling Report (Top 10 functions)")
    print("=" * 60)
    print(engine.get_profiling_report(top_n=10))


def test_high_volume():
    """Test profiling with high volume"""
    print("\n" + "=" * 60)
    print("Testing High Volume (1000 orders)")
    print("=" * 60)
    
    # Create new engine for this test
    engine = TradingEngine(enable_profiling=False, enable_logging=False)
    
    start_time = time.time()
    
    for i in range(1000):
        order = Order(
            order_id=generate_order_id(),
            user_id=f"user_{i % 20}",
            symbol="AAPL",
            side=Side.BUY if i % 2 == 0 else Side.SELL,
            price=Decimal("150.00") + Decimal((i % 50) - 25) * Decimal("0.01"),
            quantity=100,
            timestamp=datetime.now()
        )
        engine.submit_order(order)
    
    elapsed = time.time() - start_time
    
    stats = engine.get_statistics()
    
    print(f"\nProcessed 1000 orders in {elapsed:.3f} seconds")
    print(f"Throughput: {1000/elapsed:.0f} orders/sec")
    print(f"Total Trades: {stats['total_trades_executed']}")
    print(f"\nLatency Statistics:")
    print(f"  P50: {stats['latency']['p50_ms']:.6f} ms")
    print(f"  P95: {stats['latency']['p95_ms']:.6f} ms")
    print(f"  P99: {stats['latency']['p99_ms']:.6f} ms")


def test_concurrent_symbols():
    """Test profiling with multiple symbols"""
    print("\n" + "=" * 60)
    print("Testing Multiple Symbols")
    print("=" * 60)
    
    # Create new engine for this test
    engine = TradingEngine(enable_profiling=False, enable_logging=False)
    symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]
    
    for i in range(500):
        symbol = symbols[i % len(symbols)]
        order = Order(
            order_id=generate_order_id(),
            user_id=f"user_{i % 10}",
            symbol=symbol,
            side=Side.BUY if i % 2 == 0 else Side.SELL,
            price=Decimal("150.00") + Decimal(i % 20) * Decimal("0.10"),
            quantity=100,
            timestamp=datetime.now()
        )
        engine.submit_order(order)
    
    stats = engine.get_statistics()
    
    print(f"\nActive Symbols: {stats['active_symbols']}")
    print(f"Total Orders: {stats['total_orders_submitted']}")
    print(f"Total Trades: {stats['total_trades_executed']}")
    
    print(f"\nBook Statistics:")
    for symbol, book_stats in stats['books'].items():
        print(f"  {symbol}:")
        print(f"    Bid Levels: {book_stats['bid_levels']}")
        print(f"    Ask Levels: {book_stats['ask_levels']}")
        print(f"    Total Orders: {book_stats['total_orders']}")


if __name__ == "__main__":
    test_basic_profiling()
    test_high_volume()
    test_concurrent_symbols()
    
    print("\n" + "=" * 60)
    print("Profiling tests completed!")
    print("=" * 60)
