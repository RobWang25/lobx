"""Watch user-specific updates."""
import asyncio
import websockets
import json

async def watch_account(user_id):
    uri = f"ws://localhost:8000/ws/account/{user_id}"
    print(f"🔌 Connecting to account feed for {user_id}...")
    
    async with websockets.connect(uri) as websocket:
        print(f"✅ Connected! Watching {user_id}'s activity...\n")
        
        while True:
            message = await websocket.recv()
            data = json.loads(message)
            print(f"Update for {user_id}: {data}")

if __name__ == "__main__":
    import sys
    user_id = sys.argv[1] if len(sys.argv) > 1 else "trader1"
    
    try:
        asyncio.run(watch_account(user_id))
    except KeyboardInterrupt:
        print("\n Goodbye!")