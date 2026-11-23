import asyncio
import random
from decimal import Decimal
from datetime import datetime

from lobx.engine import TradingEngine
from lobx.models import Side, Order, generate_order_id


class MarketMaker:
    """
    Market maker that provides liquidity by posting competing bids and asks.
    Adjusts spread based on volatility and maintains minimum liquidity.
    """
    
    def __init__(
        self,
        trading_engine: TradingEngine,
        symbols: list[str],
        base_spread: Decimal = Decimal("0.10"),
        quantity_range: tuple[int, int] = (10, 100),
        update_interval: float = 1.0,
        min_orders_per_side: int = 3
    ):
        self.trading_engine = trading_engine
        self.symbols = symbols
        self.base_spread = base_spread
        self.quantity_range = quantity_range
        self.update_interval = update_interval
        self.min_orders_per_side = min_orders_per_side
        
        # Track base prices for each symbol
        self.base_prices = {
            "AAPL": Decimal("150.00"),
            "GOOGL": Decimal("140.00"),
            "MSFT": Decimal("350.00")
        }
        
        # Volatility multiplier (can be adjusted for stress testing)
        self.volatility_multiplier = Decimal("1.0")
        
        self.running = False
        self.user_id = "market_maker"
    
    def get_mid_price(self, symbol: str) -> Decimal:
        """Get current mid price or base price if no market"""
        book = self.trading_engine.get_book(symbol)
        if not book:
            return self.base_prices.get(symbol, Decimal("100.00"))
        
        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        
        if best_bid and best_ask:
            return (best_bid + best_ask) / 2
        elif best_bid:
            return best_bid
        elif best_ask:
            return best_ask
        else:
            return self.base_prices.get(symbol, Decimal("100.00"))
    
    def calculate_spread(self, symbol: str) -> Decimal:
        """Calculate spread based on volatility"""
        return self.base_spread * self.volatility_multiplier
    
    def generate_price_levels(self, mid_price: Decimal, spread: Decimal, count: int) -> list[Decimal]:
        """Generate price levels for bid or ask side"""
        levels = []
        for i in range(count):
            offset = spread * (i + 1) * Decimal("0.5")
            # Add small random variation
            jitter = Decimal(random.uniform(-0.02, 0.02))
            levels.append(offset + jitter)
        return levels
    
    async def update_quotes(self, symbol: str):
        """Update market maker quotes for a symbol"""
        mid_price = self.get_mid_price(symbol)
        spread = self.calculate_spread(symbol)
        
        # Generate bid levels
        bid_offsets = self.generate_price_levels(mid_price, spread, self.min_orders_per_side)
        for offset in bid_offsets:
            price = (mid_price - offset).quantize(Decimal("0.01"))
            quantity = random.randint(*self.quantity_range)
            
            try:
                # Create Order object
                order = Order(
                    order_id=generate_order_id(),
                    user_id=self.user_id,
                    symbol=symbol,
                    side=Side.BUY,
                    price=price,
                    quantity=quantity,
                    timestamp=datetime.now()
                )
                self.trading_engine.submit_order(order)
            except:
                pass  # Order might fail if market moved
        
        # Generate ask levels
        ask_offsets = self.generate_price_levels(mid_price, spread, self.min_orders_per_side)
        for offset in ask_offsets:
            price = (mid_price + offset).quantize(Decimal("0.01"))
            quantity = random.randint(*self.quantity_range)
            
            try:
                # Create Order object
                order = Order(
                    order_id=generate_order_id(),
                    user_id=self.user_id,
                    symbol=symbol,
                    side=Side.SELL,
                    price=price,
                    quantity=quantity,
                    timestamp=datetime.now()
                )
                self.trading_engine.submit_order(order)
            except:
                pass
    
    def set_volatility_mode(self, mode: str):
        """Set volatility mode for stress testing"""
        modes = {
            "low": Decimal("0.5"),
            "normal": Decimal("1.0"),
            "high": Decimal("2.0"),
            "extreme": Decimal("5.0")
        }
        self.volatility_multiplier = modes.get(mode, Decimal("1.0"))
    
    def price_shock(self, symbol: str, shock_percent: Decimal):
        """Simulate a price shock"""
        self.base_prices[symbol] *= (1 + shock_percent / 100)
    
    async def run(self):
        """Main market maker loop"""
        self.running = True
        while self.running:
            for symbol in self.symbols:
                await self.update_quotes(symbol)
            
            await asyncio.sleep(self.update_interval)
    
    def stop(self):
        """Stop market maker"""
        self.running = False