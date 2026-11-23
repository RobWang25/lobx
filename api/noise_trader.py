import asyncio
import random
from decimal import Decimal
from datetime import datetime

from lobx.engine import TradingEngine
from lobx.models import Side, Order, generate_order_id


class NoiseTrader:
    """
    Simulates random order flow to create realistic market pressure.
    Generates orders with configurable arrival rate and size distribution.
    """
    
    def __init__(
        self,
        trading_engine: TradingEngine,
        symbols: list[str],
        user_id: str,
        order_rate: float = 1.0,  # orders per second
        quantity_range: tuple = (1, 50),
        price_deviation: Decimal = Decimal("0.50")  # max deviation from mid
    ):
        self.trading_engine = trading_engine
        self.symbols = symbols
        self.user_id = user_id
        self.order_rate = order_rate
        self.quantity_range = quantity_range
        self.price_deviation = price_deviation
        self.running = False
    
    def get_mid_price(self, symbol: str) -> Decimal:
        """Get current mid price or fallback"""
        book = self.trading_engine.get_book(symbol)
        if not book:
            # Fallback prices
            fallbacks = {
                "AAPL": Decimal("150.00"),
                "GOOGL": Decimal("140.00"),
                "MSFT": Decimal("350.00")
            }
            return fallbacks.get(symbol, Decimal("100.00"))
        
        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        
        if best_bid and best_ask:
            return (best_bid + best_ask) / 2
        elif best_bid:
            return best_bid
        elif best_ask:
            return best_ask
        
        # Fallback prices
        fallbacks = {
            "AAPL": Decimal("150.00"),
            "GOOGL": Decimal("140.00"),
            "MSFT": Decimal("350.00")
        }
        return fallbacks.get(symbol, Decimal("100.00"))
    
    async def generate_order(self):
        """Generate a random order"""
        symbol = random.choice(self.symbols)
        side = random.choice([Side.BUY, Side.SELL])
        
        mid_price = self.get_mid_price(symbol)
        
        # Generate price near mid with some randomness
        deviation = Decimal(random.uniform(
            float(-self.price_deviation),
            float(self.price_deviation)
        ))
        price = (mid_price + deviation).quantize(Decimal("0.01"))
        
        # Ensure price is positive
        if price <= 0:
            price = Decimal("0.01")
        
        quantity = random.randint(*self.quantity_range)
        
        try:
            # Create Order object
            order = Order(
                order_id=generate_order_id(),
                user_id=self.user_id,
                symbol=symbol,
                side=side,
                price=price,
                quantity=quantity,
                timestamp=datetime.now()
            )
            
            # Submit order
            self.trading_engine.submit_order(order)
        except Exception as e:
            # Silently ignore errors (e.g., self-trade prevention)
            pass
    
    async def run(self):
        """Main noise trader loop"""
        self.running = True
        interval = 1.0 / self.order_rate if self.order_rate > 0 else 1.0
        
        while self.running:
            await self.generate_order()
            
            # Add some randomness to arrival times (Poisson-like)
            wait_time = random.expovariate(1.0 / interval) if interval > 0 else interval
            await asyncio.sleep(wait_time)
    
    def stop(self):
        """Stop noise trader"""
        self.running = False
    
    def set_order_rate(self, rate: float):
        """Adjust order arrival rate"""
        self.order_rate = rate