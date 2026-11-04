"""
LOBX - Limit Order Book Exchange
In-memory trading engine with price-time priority.
"""

from .models import Order, Trade, Side, OrderStatus, generate_order_id, generate_trade_id
from .book import OrderBook
from .matching import MatchingEngine
from .engine import TradingEngine
from .replay import EventLogger, EventReplayer

__version__ = "1.0.0"

__all__ = [
    # Models
    "Order",
    "Trade",
    "Side",
    "OrderStatus",
    "generate_order_id",
    "generate_trade_id",
    
    # Core components
    "OrderBook",
    "MatchingEngine",
    "TradingEngine",
    
    # Replay system
    "EventLogger",
    "EventReplayer",
]
