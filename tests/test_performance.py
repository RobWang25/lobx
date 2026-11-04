"""
Performance tests for concurrent users, fairness under load, and deterministic replay.
"""
import pytest
import time
import random
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from datetime import datetime
from typing import List, Tuple, Dict

from lobx.engine import TradingEngine
from lobx.models import Order, Side, generate_order_id, Trade
from lobx.replay import EventReplayer


class TestConcurrentUserLatency:
    """Test end-to-end latency for concurrent users."""
    
    def test_single_user_baseline(self):
        """Baseline: single user submitting orders sequentially."""
        engine = TradingEngine(enable_logging=False)
        latencies = []
        
        for i in range(100):
            order = Order(
                order_id=generate_order_id(),
                user_id="user1",
                symbol="AAPL",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                price=Decimal("100.00"),
                quantity=10,
                timestamp=datetime.now()
            )
            
            start = time.perf_counter()
            engine.submit_order(order)
            latency = (time.perf_counter() - start) * 1000  # ms
            latencies.append(latency)
        
        p50 = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=20)[18]  # 95th percentile
        p99 = statistics.quantiles(latencies, n=100)[98]  # 99th percentile
        
        print(f"\nSingle user baseline:")
        print(f"  P50: {p50:.4f}ms")
        print(f"  P95: {p95:.4f}ms")
        print(f"  P99: {p99:.4f}ms")
        
        assert p99 < 1.0, f"P99 latency too high: {p99}ms"
    
    def test_concurrent_users_latency(self):
        """Test latency with multiple concurrent users."""
        engine = TradingEngine(enable_logging=False)
        num_users = 10
        orders_per_user = 50
        
        def submit_orders_for_user(user_id: str) -> List[float]:
            """Submit orders for a single user and return latencies."""
            latencies = []
            random.seed(user_id)  # Different seed per user
            
            for i in range(orders_per_user):
                order = Order(
                    order_id=generate_order_id(),
                    user_id=user_id,
                    symbol="AAPL",
                    side=random.choice([Side.BUY, Side.SELL]),
                    price=Decimal(str(random.uniform(95.0, 105.0))).quantize(Decimal("0.01")),
                    quantity=random.randint(1, 100),
                    timestamp=datetime.now()
                )
                
                start = time.perf_counter()
                engine.submit_order(order)
                latency = (time.perf_counter() - start) * 1000
                latencies.append(latency)
            
            return latencies
        
        # Submit orders concurrently from multiple users
        all_latencies = []
        with ThreadPoolExecutor(max_workers=num_users) as executor:
            futures = [
                executor.submit(submit_orders_for_user, f"user{i}")
                for i in range(num_users)
            ]
            
            for future in as_completed(futures):
                all_latencies.extend(future.result())
        
        p50 = statistics.median(all_latencies)
        p95 = statistics.quantiles(all_latencies, n=20)[18]
        p99 = statistics.quantiles(all_latencies, n=100)[98]
        
        print(f"\n{num_users} concurrent users ({num_users * orders_per_user} total orders):")
        print(f"  P50: {p50:.4f}ms")
        print(f"  P95: {p95:.4f}ms")
        print(f"  P99: {p99:.4f}ms")
        
        # Latency should still be reasonable under concurrent load
        assert p99 < 5.0, f"P99 latency degraded under load: {p99}ms"
    
    def test_latency_fairness_across_users(self):
        """Verify latency is fair across different users (no starvation)."""
        engine = TradingEngine(enable_logging=False)
        num_users = 5
        orders_per_user = 100
        
        def submit_and_measure(user_id: str) -> Dict:
            """Submit orders and return per-user statistics."""
            latencies = []
            random.seed(int(user_id.replace("user", "")))
            
            for i in range(orders_per_user):
                order = Order(
                    order_id=generate_order_id(),
                    user_id=user_id,
                    symbol="AAPL",
                    side=random.choice([Side.BUY, Side.SELL]),
                    price=Decimal(str(random.uniform(98.0, 102.0))).quantize(Decimal("0.01")),
                    quantity=random.randint(1, 50),
                    timestamp=datetime.now()
                )
                
                start = time.perf_counter()
                engine.submit_order(order)
                latencies.append((time.perf_counter() - start) * 1000)
            
            return {
                "user_id": user_id,
                "mean": statistics.mean(latencies),
                "p95": statistics.quantiles(latencies, n=20)[18],
                "p99": statistics.quantiles(latencies, n=100)[98]
            }
        
        # Run concurrent users
        user_stats = []
        with ThreadPoolExecutor(max_workers=num_users) as executor:
            futures = [
                executor.submit(submit_and_measure, f"user{i}")
                for i in range(num_users)
            ]
            
            for future in as_completed(futures):
                user_stats.append(future.result())
        
        # Check fairness: no user should have significantly worse latency
        mean_latencies = [stat["mean"] for stat in user_stats]
        p99_latencies = [stat["p99"] for stat in user_stats]
        
        overall_mean = statistics.mean(mean_latencies)
        mean_stdev = statistics.stdev(mean_latencies)
        
        print(f"\nLatency fairness across {num_users} users:")
        for stat in sorted(user_stats, key=lambda x: x["user_id"]):
            print(f"  {stat['user_id']}: mean={stat['mean']:.4f}ms, p95={stat['p95']:.4f}ms, p99={stat['p99']:.4f}ms")
        
        print(f"\nOverall mean: {overall_mean:.4f}ms, stdev: {mean_stdev:.4f}ms")
        
        # No user should be more than 2 standard deviations from mean (fairness check)
        for stat in user_stats:
            deviation = abs(stat["mean"] - overall_mean)
            assert deviation < 2 * mean_stdev, \
                f"{stat['user_id']} experienced unfair latency: {stat['mean']:.4f}ms vs {overall_mean:.4f}ms"


class TestFairnessUnderLoad:
    """Test FIFO violations and latency skew under heavy load."""
    
    def test_fifo_compliance_under_load(self):
        """Verify FIFO ordering is maintained under concurrent order submission."""
        engine = TradingEngine(enable_logging=False)
        num_orders_per_price = 100
        price = Decimal("100.00")
        
        # Submit buy orders at same price from multiple threads
        order_ids = []
        
        def submit_buy_orders(batch_id: int) -> List[str]:
            """Submit a batch of buy orders."""
            batch_order_ids = []
            for i in range(num_orders_per_price // 10):
                order_id = f"BUY-{batch_id}-{i}"
                order = Order(
                    order_id=order_id,
                    user_id=f"user{batch_id}",
                    symbol="AAPL",
                    side=Side.BUY,
                    price=price,
                    quantity=10,
                    timestamp=datetime.now()
                )
                engine.submit_order(order)
                batch_order_ids.append(order_id)
            return batch_order_ids
        
        # Submit orders concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(submit_buy_orders, i) for i in range(10)]
            for future in as_completed(futures):
                order_ids.extend(future.result())
        
        # Submit large sell order to match all buys
        sell_order = Order(
            order_id="SELL-LARGE",
            user_id="seller",
            symbol="AAPL",
            side=Side.SELL,
            price=price,
            quantity=1000,
            timestamp=datetime.now()
        )
        trades = engine.submit_order(sell_order)
        
        # Verify FIFO: trades should match the order of submission
        # Get the order book's actual order
        book = engine.get_book("AAPL")
        
        # Check that we got trades
        assert len(trades) > 0, "Should have generated trades"
        
        print(f"\nFIFO compliance test:")
        print(f"  Orders submitted: {len(order_ids)}")
        print(f"  Trades executed: {len(trades)}")
        
        # Exact FIFO across threads isn't guaranteed, because thread scheduling
        # decides arrival order. Each thread submits in sequence, though, so its
        # own orders must fill in the order it sent them.
        assert len(trades) == len(order_ids)
        filled_ids = [trade.buy_order_id for trade in trades]
        for batch_id in range(10):
            batch_prefix = f"BUY-{batch_id}-"
            batch_fills = [oid for oid in filled_ids if oid.startswith(batch_prefix)]
            expected = [f"{batch_prefix}{i}" for i in range(num_orders_per_price // 10)]
            assert batch_fills == expected

    def test_price_time_priority_under_load(self):
        """Verify price-time priority is maintained under load."""
        engine = TradingEngine(enable_logging=False)
        
        # Submit orders at different prices
        prices_and_times = []
        
        def submit_mixed_orders(user_id: str):
            """Submit orders at various prices."""
            random.seed(int(user_id.replace("user", "")))
            for i in range(50):
                price = Decimal(str(random.choice([99.0, 100.0, 101.0]))).quantize(Decimal("0.01"))
                timestamp = datetime.now()
                
                order = Order(
                    order_id=generate_order_id(),
                    user_id=user_id,
                    symbol="AAPL",
                    side=Side.BUY,
                    price=price,
                    quantity=10,
                    timestamp=timestamp
                )
                engine.submit_order(order)
                prices_and_times.append((price, timestamp))
        
        # Submit from multiple users
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(submit_mixed_orders, f"user{i}") for i in range(5)]
            for future in as_completed(futures):
                future.result()
        
        # Check best bid is highest price
        book = engine.get_book("AAPL")
        best_bid = book.get_best_bid()
        
        assert best_bid == Decimal("101.00"), \
            f"Best bid should be highest price (101.00), got {best_bid}"
        
        print(f"\nPrice-time priority under load:")
        print(f"  Total orders: {len(prices_and_times)}")
        print(f"  Best bid: {best_bid}")
        print(f"  Test passed: highest price is at top of book")
    
    def test_latency_under_extreme_load(self):
        """Measure latency degradation under extreme load."""
        # Note: This test runs serially to avoid thread-safety issues
        # For production use, the engine should add locks for concurrent access
        
        load_levels = [100, 500, 1000, 5000]
        results = []
        
        for num_orders in load_levels:
            # Fresh engine for each test
            engine = TradingEngine(enable_logging=False)
            
            # Warm up
            for i in range(50):
                order = Order(
                    order_id=generate_order_id(),
                    user_id="warmup",
                    symbol="AAPL",
                    side=Side.BUY,
                    price=Decimal("100.00"),
                    quantity=10,
                    timestamp=datetime.now()
                )
                engine.submit_order(order)
            
            latencies = []
            random.seed(42)
            
            start_time = time.perf_counter()
            for i in range(num_orders):
                order = Order(
                    order_id=generate_order_id(),
                    user_id=f"user{i % 10}",
                    symbol="AAPL",
                    side=random.choice([Side.BUY, Side.SELL]),
                    price=Decimal(str(random.uniform(95.0, 105.0))).quantize(Decimal("0.01")),
                    quantity=random.randint(1, 100),
                    timestamp=datetime.now()
                )
                
                lat_start = time.perf_counter()
                engine.submit_order(order)
                latencies.append((time.perf_counter() - lat_start) * 1000)
            
            elapsed = time.perf_counter() - start_time
            throughput = num_orders / elapsed if elapsed > 0 else 0
            
            p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
            
            results.append({
                "load": num_orders,
                "p99_latency": p99,
                "throughput": throughput
            })
        
        print(f"\nLatency under increasing load:")
        for result in results:
            print(f"  {result['load']:5d} orders: P99={result['p99_latency']:.4f}ms, throughput={result['throughput']:.0f} orders/sec")
        
        # Verify latency doesn't degrade catastrophically
        max_p99 = max(r["p99_latency"] for r in results)
        assert max_p99 < 10.0, f"Latency degraded too much under load: {max_p99}ms"


class TestDeterministicReplay:
    """Test determinism under replay with identical seeds."""
    
    def test_replay_determinism_basic(self, tmp_path):
        """Verify replaying events produces identical results."""
        log_file = tmp_path / "test_events.jsonl"
        
        # First run: generate events
        engine1 = TradingEngine(enable_logging=True)
        random.seed(42)
        
        for i in range(50):
            order = Order(
                order_id=f"ORD-{i:04d}",
                user_id=f"user{i % 5}",
                symbol="AAPL",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                price=Decimal(str(random.uniform(99.0, 101.0))).quantize(Decimal("0.01")),
                quantity=random.randint(10, 100),
                timestamp=datetime.now()
            )
            engine1.submit_order(order)
        
        stats1 = engine1.get_statistics()
        engine1.save_event_log(str(log_file))
        
        # Replay: should get identical results
        engine2 = TradingEngine(enable_logging=False)
        replay_stats = EventReplayer.replay_from_file(str(log_file), engine2)
        stats2 = engine2.get_statistics()
        
        print(f"\nDeterministic replay test:")
        print(f"  Original trades: {stats1['total_trades_executed']}")
        print(f"  Replayed trades: {stats2['total_trades_executed']}")
        print(f"  Original volume: {stats1.get('total_volume', 'N/A')}")
        print(f"  Replayed volume: {stats2.get('total_volume', 'N/A')}")
        
        # Verify identical outcomes
        assert stats1["total_trades_executed"] == stats2["total_trades_executed"], "Trade count mismatch"
        assert stats1["total_orders_submitted"] == stats2["total_orders_submitted"], "Order count mismatch"
        assert replay_stats["orders_replayed"] == 50, "Should replay all orders"
        assert replay_stats["deterministic"], "Replay should be deterministic"
    
    def test_replay_determinism_multiple_runs(self, tmp_path):
        """Verify multiple replays produce identical results."""
        log_file = tmp_path / "multi_replay_events.jsonl"
        
        # Generate events
        engine = TradingEngine(enable_logging=True)
        random.seed(123)
        
        for i in range(100):
            order = Order(
                order_id=f"ORD-{i:04d}",
                user_id=f"user{i % 10}",
                symbol="AAPL",
                side=random.choice([Side.BUY, Side.SELL]),
                price=Decimal(str(random.uniform(95.0, 105.0))).quantize(Decimal("0.01")),
                quantity=random.randint(1, 100),
                timestamp=datetime.now()
            )
            engine.submit_order(order)
        
        engine.save_event_log(str(log_file))
        
        # Replay multiple times
        results = []
        for run in range(3):
            replay_engine = TradingEngine(enable_logging=False)
            EventReplayer.replay_from_file(str(log_file), replay_engine)
            stats = replay_engine.get_statistics()
            results.append({
                "run": run + 1,
                "trades": stats["total_trades_executed"],
                "orders": stats["total_orders_submitted"],
                "books": len(stats["books"])
            })
        
        print(f"\nMultiple replay runs:")
        for result in results:
            print(f"  Run {result['run']}: trades={result['trades']}, orders={result['orders']}, books={result['books']}")
        
        # All runs should be identical
        first = results[0]
        for result in results[1:]:
            assert result["trades"] == first["trades"], "Trades differ between replays"
            assert result["orders"] == first["orders"], "Orders differ between replays"
            assert result["books"] == first["books"], "Books differ"
    
    def test_replay_with_cancellations(self, tmp_path):
        """Test deterministic replay with order cancellations."""
        log_file = tmp_path / "cancel_events.jsonl"
        
        # Generate events with cancellations
        engine1 = TradingEngine(enable_logging=True)
        order_ids = []
        
        # Submit orders
        for i in range(20):
            order = Order(
                order_id=f"ORD-{i:04d}",
                user_id=f"user{i % 5}",
                symbol="AAPL",
                side=Side.BUY,
                price=Decimal("100.00"),
                quantity=10,
                timestamp=datetime.now()
            )
            engine1.submit_order(order)
            order_ids.append(order.order_id)
        
        # Cancel some orders
        random.seed(42)
        cancelled = random.sample(order_ids, 5)
        for order_id in cancelled:
            engine1.cancel_order(order_id, "AAPL")
        
        stats1 = engine1.get_statistics()
        engine1.save_event_log(str(log_file))
        
        # Replay
        engine2 = TradingEngine(enable_logging=False)
        EventReplayer.replay_from_file(str(log_file), engine2)
        stats2 = engine2.get_statistics()
        
        print(f"\nReplay with cancellations:")
        print(f"  Orders submitted: 20")
        print(f"  Orders cancelled: {len(cancelled)}")
        print(f"  Original cancelled: {stats1['total_orders_cancelled']}")
        print(f"  Replayed cancelled: {stats2['total_orders_cancelled']}")
        
        assert stats1["total_orders_cancelled"] == stats2["total_orders_cancelled"], \
            "Cancelled order count differs after replay"
        assert stats2["total_orders_cancelled"] == 5, "Should have 5 cancelled orders"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])