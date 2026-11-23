"""
Event logging and deterministic replay system.
"""
import json
from datetime import datetime

from .models import Event, EventType, Order, Trade


class EventLogger:
    """
    Logs all exchange events for deterministic replay.
    
    Uses append-only log with sequence numbers to ensure
    events can be replayed in exact order.
    """
    
    def __init__(self):
        self.events: list[Event] = []
        self.sequence = 0
    
    def _log_event(self, event_type: EventType, payload: dict):
        """
        Log an event.
        
        Args:
            event_type: Type of event
            payload: Event data
        """
        event = Event(
            sequence=self.sequence,
            event_type=event_type,
            timestamp=datetime.now(),
            payload=payload
        )
        self.events.append(event)
        self.sequence += 1
    
    def log_order(self, order: Order):
        """Log new order event."""
        self._log_event(
            EventType.NEW_ORDER,
            order.to_dict()
        )
    
    def log_cancel(self, order: Order):
        """Log order cancellation event."""
        self._log_event(
            EventType.CANCEL_ORDER,
            {
                "order_id": order.order_id,
                "symbol": order.symbol
            }
        )
    
    def log_trade(self, trade: Trade):
        """Log trade execution event."""
        self._log_event(
            EventType.TRADE,
            trade.to_dict()
        )
    
    def get_events(self) -> list[Event]:
        """Get all logged events."""
        return self.events.copy()
    
    def save_to_file(self, filepath: str):
        """
        Save events to JSON Lines file.
        
        Args:
            filepath: Path to output file
        """
        with open(filepath, 'w') as f:
            for event in self.events:
                f.write(json.dumps(event.to_dict()) + '\n')
    
    @staticmethod
    def load_from_file(filepath: str) -> list[Event]:
        """
        Load events from JSON Lines file.
        
        Args:
            filepath: Path to input file
            
        Returns:
            List of events
        """
        events = []
        with open(filepath, 'r') as f:
            for line in f:
                event_dict = json.loads(line.strip())
                events.append(Event.from_dict(event_dict))
        return events


class EventReplayer:
    """
    Replays logged events to reconstruct exchange state.
    
    Enables deterministic testing and debugging.
    """
    
    @staticmethod
    def replay_from_file(filepath: str, engine) -> dict:
        """
        Replay events from file into a trading engine.
        
        Args:
            filepath: Path to event log file
            engine: TradingEngine instance to replay into
            
        Returns:
            Summary statistics
        """
        events = EventLogger.load_from_file(filepath)
        return EventReplayer.replay_events(events, engine)
    
    @staticmethod
    def replay_events(events: list[Event], engine) -> dict:
        """
        Replay list of events.
        
        Args:
            events: Events to replay
            engine: TradingEngine instance
            
        Returns:
            Summary statistics
        """
        orders_replayed = 0
        cancels_replayed = 0
        trades_expected = 0
        
        for event in sorted(events, key=lambda e: e.sequence):
            if event.event_type == EventType.NEW_ORDER:
                order = Order.from_dict(event.payload)
                engine.submit_order(order)
                orders_replayed += 1
            
            elif event.event_type == EventType.CANCEL_ORDER:
                order_id = event.payload["order_id"]
                symbol = event.payload["symbol"]
                engine.cancel_order(order_id, symbol)
                cancels_replayed += 1
            
            elif event.event_type == EventType.TRADE:
                trades_expected += 1
        
        return {
            "orders_replayed": orders_replayed,
            "cancels_replayed": cancels_replayed,
            "trades_expected": trades_expected,
            "trades_actual": engine.total_trades_executed,
            "deterministic": trades_expected == engine.total_trades_executed
        }
    
    @staticmethod
    def verify_determinism(filepath: str, num_runs: int = 3) -> bool:
        """
        Verify that replay is deterministic by running multiple times.
        
        Args:
            filepath: Path to event log
            num_runs: Number of replay runs
            
        Returns:
            True if all runs produce identical results
        """
        from .engine import TradingEngine
        
        results = []
        for _ in range(num_runs):
            engine = TradingEngine(enable_logging=False)
            summary = EventReplayer.replay_from_file(filepath, engine)
            stats = engine.get_statistics()
            
            results.append({
                "trades": stats["total_trades_executed"],
                "orders": stats["total_orders_submitted"],
                "deterministic": summary["deterministic"]
            })
        
        # Check if all results are identical
        first = results[0]
        return all(r == first for r in results)