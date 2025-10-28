"""
Utility functions for the trading exchange.
"""
from decimal import Decimal
from datetime import datetime
from typing import List
import random

from .models import Order, Side, generate_order_id


def generate_random_order(
    symbol: str = "TEST",
    user_id: str = None,
    price_range: tuple = (95.0, 105.0),
    quantity_range: tuple = (1, 100),
    side: Side = None
) -> Order:
    """
    Generate a random order for testing.
    
    Args:
        symbol: Trading symbol
        user_id: User ID (random if None)
        price_range: (min, max) price range
        quantity_range: (min, max) quantity range
        side: Order side (random if None)
        
    Returns:
        Random order
    """
    if user_id is None:
        user_id = f"user{random.randint(1, 100)}"
    
    if side is None:
        side = random.choice([Side.BUY, Side.SELL])
    
    price = Decimal(str(random.uniform(*price_range))).quantize(Decimal("0.01"))
    quantity = random.randint(*quantity_range)
    
    return Order(
        order_id=generate_order_id(),
        user_id=user_id,
        symbol=symbol,
        side=side,
        price=price,
        quantity=quantity,
        timestamp=datetime.now()
    )


def generate_order_flow(
    num_orders: int,
    symbol: str = "TEST",
    num_users: int = 10,
    seed: int = None
) -> List[Order]:
    """
    Generate a sequence of random orders.
    
    Args:
        num_orders: Number of orders to generate
        symbol: Trading symbol
        num_users: Number of unique users
        seed: Random seed for reproducibility
        
    Returns:
        List of orders
    """
    if seed is not None:
        random.seed(seed)
    
    orders = []
    for i in range(num_orders):
        user_id = f"user{i % num_users}"
        order = generate_random_order(symbol=symbol, user_id=user_id)
        orders.append(order)
    
    return orders


def create_market_maker_orders(
    symbol: str,
    midprice: Decimal,
    spread: Decimal = Decimal("0.10"),
    depth_levels: int = 5,
    quantity_per_level: int = 100,
    user_id: str = "market_maker"
) -> List[Order]:
    """
    Create market maker orders (bids and asks) around a midprice.
    
    Args:
        symbol: Trading symbol
        midprice: Center price
        spread: Half-spread (distance from mid to best bid/ask)
        depth_levels: Number of price levels per side
        quantity_per_level: Order size at each level
        user_id: Market maker user ID
        
    Returns:
        List of orders (bids and asks)
    """
    orders = []
    
    # Create bid ladder
    for i in range(depth_levels):
        price = (midprice - spread - Decimal(i) * Decimal("0.01")).quantize(Decimal("0.01"))
        order = Order(
            order_id=generate_order_id(),
            user_id=user_id,
            symbol=symbol,
            side=Side.BUY,
            price=price,
            quantity=quantity_per_level,
            timestamp=datetime.now()
        )
        orders.append(order)
    
    # Create ask ladder
    for i in range(depth_levels):
        price = (midprice + spread + Decimal(i) * Decimal("0.01")).quantize(Decimal("0.01"))
        order = Order(
            order_id=generate_order_id(),
            user_id=user_id,
            symbol=symbol,
            side=Side.SELL,
            price=price,
            quantity=quantity_per_level,
            timestamp=datetime.now()
        )
        orders.append(order)
    
    return orders


def calculate_vwap(trades: List) -> Decimal:
    """
    Calculate volume-weighted average price.
    
    Args:
        trades: List of Trade objects
        
    Returns:
        VWAP or None if no trades
    """
    if not trades:
        return None
    
    total_value = sum(Decimal(str(t.price)) * t.quantity for t in trades)
    total_volume = sum(t.quantity for t in trades)
    
    if total_volume == 0:
        return None
    
    return (total_value / total_volume).quantize(Decimal("0.01"))


def format_order_book(depth_data: dict, max_levels: int = 10) -> str:
    """
    Format order book depth as a readable string.
    
    Args:
        depth_data: Book depth dictionary
        max_levels: Maximum levels to display
        
    Returns:
        Formatted string
    """
    lines = []
    lines.append(f"Symbol: {depth_data['symbol']}")
    lines.append(f"Spread: ${depth_data.get('spread', 0):.2f}")
    lines.append(f"Midprice: ${depth_data.get('midprice', 0):.2f}")
    lines.append("")
    
    # Header
    lines.append(f"{'Price':>10} | {'Bid Qty':>8} | {'Orders':>6} || {'Ask Qty':>8} | {'Orders':>6}")
    lines.append("-" * 60)
    
    # Get bids and asks
    bids = depth_data.get('bids', [])[:max_levels]
    asks = depth_data.get('asks', [])[:max_levels]
    
    # Reverse asks so best ask is closest to midprice
    asks_reversed = list(reversed(asks))
    
    # Display asks first (higher prices at top)
    for ask in asks_reversed:
        lines.append(f"${ask['price']:>9.2f} | {'':>8} | {'':>6} || {ask['quantity']:>8} | {ask['orders']:>6}")
    
    lines.append("-" * 60)
    
    # Display bids
    for bid in bids:
        lines.append(f"${bid['price']:>9.2f} | {bid['quantity']:>8} | {bid['orders']:>6} || {'':>8} | {'':>6}")
    
    return "\n".join(lines)


def simulate_random_walk(
    start_price: Decimal,
    num_steps: int,
    volatility: float = 0.01,
    seed: int = None
) -> List[Decimal]:
    """
    Simulate a random walk price path.
    
    Args:
        start_price: Initial price
        num_steps: Number of steps
        volatility: Price volatility (std dev of returns)
        seed: Random seed
        
    Returns:
        List of prices
    """
    if seed is not None:
        random.seed(seed)
    
    prices = [start_price]
    current_price = start_price
    
    for _ in range(num_steps - 1):
        # Geometric Brownian motion step
        return_pct = random.gauss(0, volatility)
        current_price = current_price * (1 + Decimal(str(return_pct)))
        current_price = current_price.quantize(Decimal("0.01"))
        prices.append(current_price)
    
    return prices