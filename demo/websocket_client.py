"""WebSocket client to watch live market data."""
import asyncio
import websockets
import json

async def watch_market():
    """Connect to market data feed and display updates."""
    uri = "ws://localhost:8000/ws/market"
    
    print("🔌 Connecting to market data feed...")
    
    async with websockets.connect(uri) as websocket:
        print("✅ Connected! Watching market data...\n")
        
        try:
            while True:
                message = await websocket.recv()
                data = json.loads(message)
                
                # Pretty print the update
                if data.get("type") == "stats_update":
                    print(f"Stats Update: {data['stats']}")
                elif data.get("type") == "order_submitted":
                    order = data["order"]
                    print(f"New Order: {order['side']} {order['quantity']} {order['symbol']} @ ${order['price']}")
                elif data.get("type") == "order_cancelled":
                    print(f"Order Cancelled: {data['order_id']}")
                else:
                    print(f"{data}")
                    
        except websockets.exceptions.ConnectionClosed:
            print("\nConnection closed")
        except KeyboardInterrupt:
            print("\nDisconnecting...")

if __name__ == "__main__":
    asyncio.run(watch_market())