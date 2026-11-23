"""
Data models for the trading exchange.
Immutable dataclasses for orders, trades, and events.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from datetime import datetime
import uuid


class Side(Enum):
    """Order side - buy or sell."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order lifecycle status."""
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class EventType(Enum):
    """Event types for replay log."""
    NEW_ORDER = "NEW_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    MODIFY_ORDER = "MODIFY_ORDER"
    TRADE = "TRADE"


@dataclass(frozen=True)
class Order:
    """
    Immutable limit order.
    
    Attributes:
        order_id: Unique identifier
        user_id: User who placed the order
        symbol: Trading ticker (e.g., "AAPL")
        side: BUY or SELL
        price: Limit price
        quantity: Number of shares
        timestamp: When order was created
        status: Current order status
    """
    order_id: str
    user_id: str
    symbol: str
    side: Side
    price: Decimal
    quantity: int
    timestamp: datetime
    status: OrderStatus = OrderStatus.OPEN
    
    def __post_init__(self):
        """Validate order fields."""
        if self.quantity <= 0:
            raise ValueError("Quantity must be positive")
        if self.price <= 0:
            raise ValueError("Price must be positive")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "price": str(self.price),
            "quantity": self.quantity,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Order':
        """Create order from dictionary."""
        return cls(
            order_id=data["order_id"],
            user_id=data["user_id"],
            symbol=data["symbol"],
            side=Side(data["side"]),
            price=Decimal(data["price"]),
            quantity=data["quantity"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            status=OrderStatus(data["status"])
        )
    
    def with_status(self, status: OrderStatus) -> 'Order':
        """Create new order with updated status."""
        return Order(
            order_id=self.order_id,
            user_id=self.user_id,
            symbol=self.symbol,
            side=self.side,
            price=self.price,
            quantity=self.quantity,
            timestamp=self.timestamp,
            status=status
        )
    
    def with_quantity(self, quantity: int) -> 'Order':
        """Create new order with updated quantity."""
        return Order(
            order_id=self.order_id,
            user_id=self.user_id,
            symbol=self.symbol,
            side=self.side,
            price=self.price,
            quantity=quantity,
            timestamp=self.timestamp,
            status=self.status
        )


@dataclass(frozen=True)
class Trade:
    """
    Executed trade between two orders.
    
    Attributes:
        trade_id: Unique identifier
        symbol: Trading symbol
        buy_order_id: Buyer's order ID
        sell_order_id: Seller's order ID
        price: Execution price
        quantity: Number of shares traded
        timestamp: When trade executed
        buyer_user_id: Buyer's user ID
        seller_user_id: Seller's user ID
    """
    trade_id: str
    symbol: str
    buy_order_id: str
    sell_order_id: str
    price: Decimal
    quantity: int
    timestamp: datetime
    buyer_user_id: str
    seller_user_id: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "price": str(self.price),
            "quantity": self.quantity,
            "timestamp": self.timestamp.isoformat(),
            "buyer_user_id": self.buyer_user_id,
            "seller_user_id": self.seller_user_id
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Trade':
        """Create trade from dictionary."""
        return cls(
            trade_id=data["trade_id"],
            symbol=data["symbol"],
            buy_order_id=data["buy_order_id"],
            sell_order_id=data["sell_order_id"],
            price=Decimal(data["price"]),
            quantity=data["quantity"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            buyer_user_id=data["buyer_user_id"],
            seller_user_id=data["seller_user_id"]
        )


@dataclass(frozen=True)
class Event:
    """
    Event log entry for deterministic replay.
    
    Attributes:
        sequence: Monotonic sequence number
        event_type: Type of event
        timestamp: When event occurred
        payload: Event-specific data
    """
    sequence: int
    event_type: EventType
    timestamp: datetime
    payload: dict
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Event':
        """Create event from dictionary."""
        return cls(
            sequence=data["sequence"],
            event_type=EventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            payload=data["payload"]
        )


def generate_order_id() -> str:
    """Generate unique order ID."""
    return f"ORD-{uuid.uuid4().hex[:12].upper()}"


def generate_trade_id() -> str:
    """Generate unique trade ID."""
    return f"TRD-{uuid.uuid4().hex[:12].upper()}"


_new_instance = object.__new__
_set_attribute = object.__setattr__


def build_trusted(cls, fields: dict):
    """
    Build an Order or Trade from values that are already known to be valid.

    This skips __init__ and __post_init__, so it's about twice as fast as calling
    the class, which matters on the C++ backend's hot path. fields must name every
    field, defaults included. The result is an ordinary frozen instance: it compares,
    hashes and refuses changes like one built normally.
    """
    instance = _new_instance(cls)
    # A frozen dataclass blocks its own __setattr__, so go through object's.
    _set_attribute(instance, "__dict__", fields)
    return instance
