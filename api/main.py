from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global trading_engine, market_maker, noise_traders, start_time, background_tasks
    
    # Startup
    start_time = datetime.now()
    trading_engine = TradingEngine(event_callback=trading_event_callback)
    
    # Initialize symbols - TradingEngine creates books on-demand
    # No need to explicitly add symbols
    
    # Start market maker
    market_maker = MarketMaker(
        trading_engine=trading_engine,
        symbols=["AAPL", "GOOGL", "MSFT"],
        base_spread=Decimal("0.10"),
        quantity_range=(10, 100)
    )
    market_maker_task = asyncio.create_task(market_maker.run())
    background_tasks.append(market_maker_task)
    
    # Start noise traders
    for i in range(3):
        noise_trader = NoiseTrader(
            trading_engine=trading_engine,
            symbols=["AAPL", "GOOGL", "MSFT"],
            user_id=f"noise_trader_{i}",
            order_rate=2.0  # 2 orders per second
        )
        noise_trader_task = asyncio.create_task(noise_trader.run())
        background_tasks.append(noise_trader_task)
        noise_traders.append(noise_trader)
    
    # Start event broadcaster
    broadcaster_task = asyncio.create_task(broadcast_events())
    background_tasks.append(broadcaster_task)
    
    yield
    
    # Shutdown
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)


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
        side = Side.BUY if order_req.side.upper() == "BUY" else Side.SELL
        
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
        
        # Aggregate by price level
        bid_levels = {}
        for price, orders in book.bids.items():
            total_qty = sum(o.quantity for o in orders)
            bid_levels[price] = BookLevel(
                price=price,
                quantity=Decimal(total_qty),
                order_count=len(orders)
            )
        
        ask_levels = {}
        for price, orders in book.asks.items():
            total_qty = sum(o.quantity for o in orders)
            ask_levels[price] = BookLevel(
                price=price,
                quantity=Decimal(total_qty),
                order_count=len(orders)
            )
        
        # Sort and limit depth
        sorted_bids = sorted(bid_levels.values(), key=lambda x: x.price, reverse=True)[:depth]
        sorted_asks = sorted(ask_levels.values(), key=lambda x: x.price)[:depth]
        
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
        "docs": "/docs"
    }

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