# WebSocket Setup Guide - Trading Exchange API

Complete guide to setting up and using WebSocket connections for real-time market data.

---

## Quick Start (TL;DR)

```bash
# 1. Start server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 2. Test connection
python -c "
import asyncio, websockets
async def test():
    async with websockets.connect('ws://localhost:8000/ws/market') as ws:
        await ws.send('ping')
        print(await ws.recv())
asyncio.run(test())
"
```

If this works, you're all set! If not, read below.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Verify Setup](#verify-setup)
3. [Testing](#testing)
4. [Client Examples](#client-examples)
5. [Troubleshooting](#troubleshooting)

---

## Verify Setup

### Step 1: Start Server

```bash
cd "/Users/robertwang/Downloads/School/Intermediate Python/python-market-project"
source .venv/bin/activate
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Step 2: Check Routes

Visit `http://localhost:8000/docs` and look for WebSocket endpoints.

### Step 3: Simple Test

Create `test_ws.py`:

```python
import asyncio
import websockets

async def test():
    try:
        async with websockets.connect('ws://localhost:8000/ws/market') as ws:
            print("Connected!")
            await ws.send("ping")
            response = await ws.recv()
            print(f"Received: {response}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test())
```

Run it:
```bash
python test_ws.py
```

**Expected:** `Connected!` and `Received: {"type":"pong"}`

---

## Testing

### Browser Test

Open `websocket_test.html`in browser and click "Connect".

---

## Client Examples

### Python Client - Watch Market Data

```bash
python watch_market.py
```

### Python Client - Watch User Account

```bash
python watch_account.py trader1
```

---

## Troubleshooting

### Error: "HTTP 404"

**Problem:** WebSocket route doesn't exist

**Fix:**

1. Check `api/main.py` has the `@app.websocket("/ws/market")` decorator
2. Restart the server
3. Verify at `http://localhost:8000/docs`

### Error: "Connection refused"

**Problem:** Server not running or wrong port

**Fix:**

```bash
# Check if server is running
curl http://localhost:8000/

# Check what's on port 8000
lsof -i :8000

# Start server if not running
uvicorn api.main:app --reload
```

### Error: Connection closes immediately

### No messages received

**Problem:** Background broadcaster not running

**Fix:** Check `api/main.py` lifespan function has:

```python
broadcaster_task = asyncio.create_task(broadcast_events())
background_tasks.append(broadcaster_task)
```

---

## WebSocket Endpoints

### Market Feed

**URL:** `ws://localhost:8000/ws/market`

**Purpose:** All market activity (orders, trades, stats)

**Messages:**
- `stats_update` - Periodic statistics
- `order_submitted` - New orders
- `order_cancelled` - Cancelled orders

### Account Feed

**URL:** `ws://localhost:8000/ws/account/{user_id}`

**Purpose:** User-specific updates

**Messages:**
- User's order fills
- User's order updates

---

## Message Format

### Stats Update
```json
{
  "type": "stats_update",
  "timestamp": "2025-11-10T15:30:45.123456",
  "stats": {
    "total_trades": 1250,
    "total_volume": "125000.00"
  }
}
```

### Order Submitted
```json
{
  "type": "order_submitted",
  "order": {
    "order_id": "ORD-ABC123",
    "symbol": "AAPL",
    "user_id": "trader1",
    "side": "BUY",
    "price": "150.00",
    "quantity": "100",
    "timestamp": "2025-11-10T15:30:45.123456"
  }
}
```

### Order Cancelled
```json
{
  "type": "order_cancelled",
  "order_id": "ORD-ABC123",
  "timestamp": "2025-11-10T15:30:46.123456"
}
```

---

## Complete Demo Workflow

### Terminal 1: Start Server
```bash
uvicorn api.main:app --reload
```
For allowing other connections run:
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2: Watch Market
```bash
python watch_market.py
```

### Terminal 3: Submit Orders
```bash
# Submit order via REST API
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","user_id":"demo","side":"BUY","price":"150.00","quantity":"100"}'
```

### Terminal 2: See the Order!
You should see the order appear in real-time in Terminal 2.

## Mobile Walkthrough

### Step 1: Get Your Computer's IP Address

On Mac:
```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
```
On Windows:
```bash
ipconfig
```

On Linux:
```bash
hostname -I
```

### Step 2: Make Sure Your Server is Running
Make sure your venv is activated when you run this:
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Step 3
Ensure that your phone and computer are on the same WiFi network and open:
```
   http://{YOUR IP ADDRESS}:8080/mobile_websocket.html
```
