from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_serializer
from typing import Optional, List
from decimal import Decimal
from datetime import datetime
import asyncio
from contextlib import asynccontextmanager

from lobx.engine import TradingEngine
from lobx.models import Order, Side, generate_order_id
from api.market_maker import MarketMaker
from api.noise_trader import NoiseTrader
from api.websocket_manager import ConnectionManager


class OrderRequest(BaseModel):
    symbol: str
    user_id: str
    side: str  # "BUY" or "SELL"
    price: Decimal
    quantity: Decimal
    
    @field_serializer('price', 'quantity')
    def serialize_decimal(self, value: Decimal) -> str:
        return str(value)


class OrderResponse(BaseModel):
    order_id: str
    symbol: str
    user_id: str
    side: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    
    @field_serializer('price', 'quantity')
    def serialize_decimal(self, value: Decimal) -> str:
        return str(value)


class BookLevel(BaseModel):
    price: Decimal
    quantity: Decimal
    order_count: int
    
    @field_serializer('price', 'quantity')
    def serialize_decimal(self, value: Decimal) -> str:
        return str(value)


class OrderBookResponse(BaseModel):
    symbol: str
    bids: List[BookLevel]
    asks: List[BookLevel]
    spread: Optional[Decimal]
    mid_price: Optional[Decimal]
    
    @field_serializer('spread', 'mid_price')
    def serialize_decimal(self, value: Optional[Decimal]) -> Optional[str]:
        return str(value) if value is not None else None


class StatsResponse(BaseModel):
    total_orders: int
    total_trades: int
    total_volume: Decimal
    symbols: List[str]
    uptime_seconds: float
    
    @field_serializer('total_volume')
    def serialize_decimal(self, value: Decimal) -> str:
        return str(value)


# Global state
trading_engine: Optional[TradingEngine] = None
market_maker: Optional[MarketMaker] = None
noise_traders: List[NoiseTrader] = []
connection_manager = ConnectionManager()
start_time: Optional[datetime] = None
background_tasks: List[asyncio.Task] = []

# Configuration - Set these to False to disable
ENABLE_MARKET_MAKER = False
ENABLE_NOISE_TRADERS = False
NUM_NOISE_TRADERS = 3


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global trading_engine, market_maker, noise_traders, start_time, background_tasks
    
    # Startup
    start_time = datetime.now()
    trading_engine = TradingEngine(event_callback=trading_event_callback)
    
    # Initialize symbols - TradingEngine creates books on-demand
    # No need to explicitly add symbols
    
    # Start market maker (optional)
    if ENABLE_MARKET_MAKER:
        market_maker = MarketMaker(
            trading_engine=trading_engine,
            symbols=["AAPL", "GOOGL", "MSFT"],
            base_spread=Decimal("0.10"),
            quantity_range=(10, 100)
        )
        market_maker_task = asyncio.create_task(market_maker.run())
        background_tasks.append(market_maker_task)
        print("Market Maker enabled")
    else:
        print("Market Maker disabled")
    
    # Start noise traders (optional)
    if ENABLE_NOISE_TRADERS:
        for i in range(NUM_NOISE_TRADERS):
            noise_trader = NoiseTrader(
                trading_engine=trading_engine,
                symbols=["AAPL", "GOOGL", "MSFT"],
                user_id=f"noise_trader_{i}",
                order_rate=2.0  # 2 orders per second
            )
            noise_trader_task = asyncio.create_task(noise_trader.run())
            background_tasks.append(noise_trader_task)
            noise_traders.append(noise_trader)
        print(f"{NUM_NOISE_TRADERS} Noise Traders enabled")
    else:
        print("Noise Traders disabled")
    
    # Start event broadcaster
    broadcaster_task = asyncio.create_task(broadcast_events())
    background_tasks.append(broadcaster_task)
    
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        try:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        finally:
            background_tasks.clear()
            noise_traders.clear()
            market_maker = None


app = FastAPI(
    title="Trading Exchange API",
    description="High-performance limit order book trading system",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def broadcast_events():
    """Background task to broadcast trading events"""
    while True:
        await asyncio.sleep(0.1)  # 100ms intervals
        
        if trading_engine:
            # Get recent events (trades, order updates)
            stats = trading_engine.get_statistics()
            await connection_manager.broadcast_market_data({
                "type": "stats_update",
                "timestamp": datetime.now().isoformat(),
                "stats": {
                    "total_trades": stats["total_trades_executed"],
                    "total_volume": str(stats.get("total_volume", 0))
                }
            })


@app.post("/orders", response_model=OrderResponse)
async def submit_order(order_req: OrderRequest):
    """Submit a new limit order"""
    try:
        side = Side(order_req.side.upper())
        if order_req.quantity != order_req.quantity.to_integral_value():
            raise ValueError("Quantity must be a whole number")
        
        # Create Order object
        order = Order(
            order_id=generate_order_id(),
            user_id=order_req.user_id,
            symbol=order_req.symbol,
            side=side,
            price=order_req.price,
            quantity=int(order_req.quantity),
            timestamp=datetime.now()
        )
        
        # Submit to engine (returns list of trades)
        trades = trading_engine.submit_order(order)
        
        # Broadcast order to WebSocket clients
        await connection_manager.broadcast_market_data({
            "type": "order_submitted",
            "order": {
                "order_id": order.order_id,
                "symbol": order.symbol,
                "user_id": order.user_id,
                "side": order.side.value,
                "price": str(order.price),
                "quantity": str(order.quantity),
                "timestamp": order.timestamp.isoformat()
            }
        })
        
        return OrderResponse(
            order_id=order.order_id,
            symbol=order.symbol,
            user_id=order.user_id,
            side=order.side.value,
            price=order.price,
            quantity=order.quantity,
            timestamp=order.timestamp
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/orders/{symbol}/{order_id}")
async def cancel_order(symbol: str, order_id: str):
    """Cancel an existing order"""
    try:
        success = trading_engine.cancel_order(order_id, symbol)
        
        if success:
            await connection_manager.broadcast_market_data({
                "type": "order_cancelled",
                "order_id": order_id,
                "timestamp": datetime.now().isoformat()
            })
            return {"status": "cancelled", "order_id": order_id}
        else:
            raise HTTPException(status_code=404, detail="Order not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/book/{symbol}", response_model=OrderBookResponse)
async def get_order_book(symbol: str, depth: int = 10):
    """Get order book depth for a symbol"""
    try:
        book = trading_engine.get_book(symbol)
        if not book:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
        # Best price first on each side, already limited to `depth` levels
        sorted_bids = [
            BookLevel(price=price, quantity=Decimal(quantity), order_count=count)
            for price, quantity, count in book.get_levels(Side.BUY, depth)
        ]
        sorted_asks = [
            BookLevel(price=price, quantity=Decimal(quantity), order_count=count)
            for price, quantity, count in book.get_levels(Side.SELL, depth)
        ]
        
        # Calculate spread and mid price
        spread = None
        mid_price = None
        best_bid = book.get_best_bid()
        best_ask = book.get_best_ask()
        
        if best_bid and best_ask:
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2
        
        return OrderBookResponse(
            symbol=symbol,
            bids=sorted_bids,
            asks=sorted_asks,
            spread=spread,
            mid_price=mid_price
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get system statistics"""
    stats = trading_engine.get_statistics()
    uptime = (datetime.now() - start_time).total_seconds()
    
    # Calculate total volume from book stats
    total_volume = Decimal(0)
    for book_stats in stats.get("books", {}).values():
        total_volume += Decimal(book_stats.get("total_bid_quantity", 0))
        total_volume += Decimal(book_stats.get("total_ask_quantity", 0))
    
    return StatsResponse(
        total_orders=stats["total_orders_submitted"],
        total_trades=stats["total_trades_executed"],
        total_volume=total_volume,
        symbols=list(trading_engine.books.keys()),
        uptime_seconds=uptime
    )


@app.get("/stats/detailed")
async def get_detailed_stats():
    """Get detailed statistics including profiling data"""
    return trading_engine.get_statistics()


@app.get("/stats/profiling")
async def get_profiling_stats(sort_by: str = "cumulative", top_n: int = 20):
    """Get detailed profiling report"""
    report = trading_engine.get_profiling_report(sort_by, top_n)
    return {"profiling_report": report}


@app.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """WebSocket endpoint for global market data"""
    await connection_manager.connect_market(websocket)
    try:
        while True:
            # Keep connection alive and receive any client messages
            data = await websocket.receive_text()
            # Echo back for heartbeat
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        connection_manager.disconnect_market(websocket)


@app.websocket("/ws/account/{user_id}")
async def websocket_account(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for per-user trade notifications"""
    await connection_manager.connect_user(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        connection_manager.disconnect_user(user_id, websocket)


@app.get("/")
async def root():
    """API information"""
    return {
        "name": "Trading Exchange API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "trading_ui": "/trading",
        "market_maker_enabled": ENABLE_MARKET_MAKER,
        "noise_traders_enabled": ENABLE_NOISE_TRADERS,
        "num_noise_traders": NUM_NOISE_TRADERS if ENABLE_NOISE_TRADERS else 0
    }


@app.get("/config")
async def get_config():
    """Get server configuration"""
    return {
        "market_maker": {
            "enabled": ENABLE_MARKET_MAKER,
            "symbols": ["AAPL", "GOOGL", "MSFT"] if ENABLE_MARKET_MAKER else [],
            "base_spread": "0.10" if ENABLE_MARKET_MAKER else None,
            "quantity_range": [10, 100] if ENABLE_MARKET_MAKER else None
        },
        "noise_traders": {
            "enabled": ENABLE_NOISE_TRADERS,
            "count": NUM_NOISE_TRADERS if ENABLE_NOISE_TRADERS else 0,
            "symbols": ["AAPL", "GOOGL", "MSFT"] if ENABLE_NOISE_TRADERS else [],
            "order_rate": 2.0 if ENABLE_NOISE_TRADERS else None
        }
    }


@app.post("/config/market-maker/{enabled}")
async def toggle_market_maker(enabled: bool):
    """Enable or disable market maker"""
    global ENABLE_MARKET_MAKER, market_maker, background_tasks
    
    if enabled and not ENABLE_MARKET_MAKER:
        # Start market maker
        ENABLE_MARKET_MAKER = True
        market_maker = MarketMaker(
            trading_engine=trading_engine,
            symbols=["AAPL", "GOOGL", "MSFT"],
            base_spread=Decimal("0.10"),
            quantity_range=(10, 100)
        )
        market_maker_task = asyncio.create_task(market_maker.run())
        background_tasks.append(market_maker_task)
        return {"status": "enabled", "message": "Market maker started"}
    
    elif not enabled and ENABLE_MARKET_MAKER:
        # Stop market maker
        ENABLE_MARKET_MAKER = False
        if market_maker:
            market_maker.stop()
            market_maker = None
        return {"status": "disabled", "message": "Market maker stopped"}
    
    return {"status": "no_change", "message": f"Market maker already {'enabled' if enabled else 'disabled'}"}


@app.post("/config/noise-traders/{enabled}")
async def toggle_noise_traders(enabled: bool):
    """Enable or disable noise traders"""
    global ENABLE_NOISE_TRADERS, noise_traders, background_tasks
    
    if enabled and not ENABLE_NOISE_TRADERS:
        # Start noise traders
        ENABLE_NOISE_TRADERS = True
        noise_traders = []
        for i in range(NUM_NOISE_TRADERS):
            noise_trader = NoiseTrader(
                trading_engine=trading_engine,
                symbols=["AAPL", "GOOGL", "MSFT"],
                user_id=f"noise_trader_{i}",
                order_rate=2.0
            )
            noise_trader_task = asyncio.create_task(noise_trader.run())
            background_tasks.append(noise_trader_task)
            noise_traders.append(noise_trader)
        return {"status": "enabled", "message": f"{NUM_NOISE_TRADERS} noise traders started"}
    
    elif not enabled and ENABLE_NOISE_TRADERS:
        # Stop noise traders
        ENABLE_NOISE_TRADERS = False
        for trader in noise_traders:
            trader.stop()
        noise_traders = []
        return {"status": "disabled", "message": "Noise traders stopped"}
    
    return {"status": "no_change", "message": f"Noise traders already {'enabled' if enabled else 'disabled'}"}


@app.get("/trading")
async def trading_ui():
    """Serve the trading UI"""
    return FileResponse("api/static/trading.html")

async def trading_event_callback(event_type, data):
    """Callback for trading events"""
    if event_type == 'order_submitted':
        await connection_manager.broadcast_market_data({
            "type": "order_submitted",
            "order": {
                "order_id": data.order_id,
                "symbol": data.symbol,
                "user_id": data.user_id,
                "side": data.side.value,
                "price": str(data.price),
                "quantity": str(data.quantity),
                "timestamp": data.timestamp.isoformat()
            }
        })
    elif event_type == 'trade_executed':
        await connection_manager.broadcast_market_data({
            "type": "trade_executed",
            "trade": {
                "trade_id": data.trade_id,
                "symbol": data.symbol,
                "price": str(data.price),
                "quantity": data.quantity,
                "buyer": data.buyer_user_id,
                "seller": data.seller_user_id,
                "timestamp": data.timestamp.isoformat()
            }
        })

app.mount("/static", StaticFiles(directory="api/static"), name="static")
