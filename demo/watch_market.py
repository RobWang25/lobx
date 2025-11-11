"""Watch real-time market data."""
import asyncio
import websockets
import json

async def watch_market():
    uri = "ws://localhost:8000/ws/market"
    print(f"🔌 Connecting to {uri}...")
    
    async with websockets.connect(uri) as websocket:
        print("✅ Connected! Watching market data...\n")
        
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            
            msg_type = data.get("type")
            
            if msg_type == "stats_update":
                stats = data.get("stats", {})
                print(f"Stats: {stats['total_trades']} trades")
            
            elif msg_type == "order_submitted":
                order = data["order"]
                print(f"Order: {order['side']} {order['quantity']} "
                      f"{order['symbol']} @ ${order['price']}")
            
            elif msg_type == "order_cancelled":
                print(f"Cancelled: {data['order_id']}")

if __name__ == "__main__":
    try:
        asyncio.run(watch_market())
    except KeyboardInterrupt:
        print("\n Goodbye!")