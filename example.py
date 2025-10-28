"""
Quick start example demonstrating the trading exchange.
"""
from decimal import Decimal
from datetime import datetime
import random

from lobx.models import Order, Side, generate_order_id
from lobx.engine import TradingEngine


def main():
    print("="*60)
    print("LOBX Trading Exchange - Quick Start Example")
    print("="*60)
    
    engine = TradingEngine(enable_logging=True)
    
    # Example 1: Simple buy and sell
    print("\n[Example 1] Simple Buy and Sell")
    print("-" * 40)
    
    buy_order = Order(
        order_id=generate_order_id(),
        user_id="alice",
        symbol="AAPL",
        side=Side.BUY,
        price=Decimal("150.00"),
        quantity=100,
        timestamp=datetime.now()
    )
    
    print(f"Submitting buy order: {buy_order.quantity} @ ${buy_order.price}")
    trades = engine.submit_order(buy_order)
    print(f"Trades executed: {len(trades)}")
    
    sell_order = Order(
        order_id=generate_order_id(),
        user_id="bob",
        symbol="AAPL",
        side=Side.SELL,
        price=Decimal("150.00"),
        quantity=50,
        timestamp=datetime.now()
    )
    
    print(f"Submitting sell order: {sell_order.quantity} @ ${sell_order.price}")
    trades = engine.submit_order(sell_order)
    print(f"Trades executed: {len(trades)}")
    
    if trades:
        trade = trades[0]
        print(f"  Trade: {trade.quantity} shares @ ${trade.price}")
        print(f"  Buyer: {trade.buyer_user_id}")
        print(f"  Seller: {trade.seller_user_id}")
    
    # Example 2: Building order book depth
    print("\n[Example 2] Building Order Book")
    print("-" * 40)
    
    # Add multiple buy orders
    for i, price in enumerate([149.50, 149.00, 148.50]):
        order = Order(
            order_id=generate_order_id(),
            user_id=f"buyer{i}",
            symbol="AAPL",
            side=Side.BUY,
            price=Decimal(str(price)),
            quantity=random.randint(10, 50),
            timestamp=datetime.now()
        )
        engine.submit_order(order)
    
    # Add multiple sell orders
    for i, price in enumerate([151.00, 151.50, 152.00]):
        order = Order(
            order_id=generate_order_id(),
            user_id=f"seller{i}",
            symbol="AAPL",
            side=Side.SELL,
            price=Decimal(str(price)),
            quantity=random.randint(10, 50),
            timestamp=datetime.now()
        )
        engine.submit_order(order)
    
    # View order book
    depth = engine.get_book_depth("AAPL", levels=5)
    print("\nOrder Book Depth:")
    print(f"  Symbol: {depth['symbol']}")
    print(f"  Spread: ${depth['spread']:.2f}")
    print(f"  Midprice: ${depth['midprice']:.2f}")
    
    print("\n  Bids:")
    for level in depth['bids']:
        print(f"    ${level['price']:.2f} | {level['quantity']:3d} shares | {level['orders']} orders")
    
    print("\n  Asks:")
    for level in depth['asks']:
        print(f"    ${level['price']:.2f} | {level['quantity']:3d} shares | {level['orders']} orders")
    
    # Example 3: Market order crossing spread
    print("\n[Example 3] Market Order (Crossing Spread)")
    print("-" * 40)
    
    # Aggressive buy order that crosses spread
    aggressive_buy = Order(
        order_id=generate_order_id(),
        user_id="charlie",
        symbol="AAPL",
        side=Side.BUY,
        price=Decimal("152.00"),
        quantity=100,
        timestamp=datetime.now()
    )
    
    print(f"Submitting aggressive buy: {aggressive_buy.quantity} @ ${aggressive_buy.price}")
    trades = engine.submit_order(aggressive_buy)
    print(f"Trades executed: {len(trades)}")
    
    total_qty = sum(t.quantity for t in trades)
    avg_price = sum(t.price * t.quantity for t in trades) / total_qty if total_qty > 0 else 0
    print(f"  Total quantity: {total_qty}")
    print(f"  Average price: ${avg_price:.2f}")
    
    # Example 4: Order cancellation
    print("\n[Example 4] Order Cancellation")
    print("-" * 40)
    
    cancel_order = Order(
        order_id=generate_order_id(),
        user_id="dave",
        symbol="AAPL",
        side=Side.BUY,
        price=Decimal("145.00"),
        quantity=200,
        timestamp=datetime.now()
    )
    
    print(f"Submitting order: {cancel_order.order_id}")
    engine.submit_order(cancel_order)
    
    print(f"Cancelling order: {cancel_order.order_id}")
    success = engine.cancel_order(cancel_order.order_id, "AAPL")
    print(f"Cancellation {'successful' if success else 'failed'}")
    
    # Example 5: Self-trade prevention
    print("\n[Example 5] Self-Trade Prevention")
    print("-" * 40)
    
    # User submits both buy and sell
    order1 = Order(
        order_id=generate_order_id(),
        user_id="eve",
        symbol="AAPL",
        side=Side.SELL,
        price=Decimal("150.00"),
        quantity=50,
        timestamp=datetime.now()
    )
    engine.submit_order(order1)
    print(f"User 'eve' submits sell order")
    
    order2 = Order(
        order_id=generate_order_id(),
        user_id="eve",  # Same user
        symbol="AAPL",
        side=Side.BUY,
        price=Decimal("150.00"),
        quantity=50,
        timestamp=datetime.now()
    )
    trades = engine.submit_order(order2)
    print(f"User 'eve' submits buy order at same price")
    print(f"Self-trade prevented: {len(trades) == 0}")
    
    # Example 6: Statistics
    print("\n[Example 6] Engine Statistics")
    print("-" * 40)
    
    stats = engine.get_statistics()
    print(f"Uptime: {stats['uptime_seconds']:.2f} seconds")
    print(f"Total orders submitted: {stats['total_orders_submitted']}")
    print(f"Total trades executed: {stats['total_trades_executed']}")
    print(f"Orders per second: {stats['orders_per_second']:.2f}")
    print(f"Trades per second: {stats['trades_per_second']:.2f}")
    
    if stats['latency']:
        print("\nLatency (ms):")
        print(f"  Min: {stats['latency']['min_ms']:.4f}")
        print(f"  P50: {stats['latency']['p50_ms']:.4f}")
        print(f"  P95: {stats['latency']['p95_ms']:.4f}")
        print(f"  P99: {stats['latency']['p99_ms']:.4f}")
        print(f"  Max: {stats['latency']['max_ms']:.4f}")
    
    # Example 7: Event replay
    print("\n[Example 7] Event Logging and Replay")
    print("-" * 40)
    
    # Save event log
    log_file = "example_session.jsonl"
    engine.save_event_log(log_file)
    print(f"Event log saved to: {log_file}")
    
    # Replay events
    from lobx.replay import EventReplayer
    
    new_engine = TradingEngine(enable_logging=False)
    summary = EventReplayer.replay_from_file(log_file, new_engine)
    
    print(f"Replay summary:")
    print(f"  Orders replayed: {summary['orders_replayed']}")
    print(f"  Trades expected: {summary['trades_expected']}")
    print(f"  Trades actual: {summary['trades_actual']}")
    print(f"  Deterministic: {summary['deterministic']}")
    
    print("\n" + "="*60)
    print("Example complete!")
    print("="*60)


if __name__ == "__main__":
    main()