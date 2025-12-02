# Quick Start Guide - New Features

## 🚀 Getting Started in 60 Seconds

### Start the Server
```powershell
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Access the Trading UI
Open in browser: **http://localhost:8000/trading**

### Test Profiling
```powershell
$env:PYTHONPATH = "c:\Users\bobwa\Downloads\Masters\python-market-project"
python demo/test_profiling.py
```

## 📊 Key Features

### 1. Web Trading UI
- **URL**: http://localhost:8000/trading
- **Features**: Live order book, charts, P&L tracking
- **Mobile**: Works on phone/tablet (same WiFi network)

### 2. Performance Profiling
```python
engine = TradingEngine(enable_profiling=True)
stats = engine.get_statistics()
print(stats['profiler_metrics'])
```

### 3. Async Engine
```python
engine = TradingEngine(use_async=True)
```

## 🎯 Trading UI Quick Guide

### Place an Order
1. Enter User ID (default: trader_1)
2. Choose Limit or Market
3. Enter Price (if limit) and Quantity
4. Click Buy or Sell

### View Order Book
- Left side: Bids (green)
- Right side: Asks (red)
- Click on price to auto-fill order form

### Track P&L
- Right panel shows position and P&L
- Updates in real-time
- Color-coded: green = profit, red = loss

### Switch Symbols
- Click tabs at top: AAPL, GOOGL, MSFT
- Each symbol has separate position

## 📈 API Endpoints

### New Endpoints
- `GET /trading` - Trading UI
- `GET /stats/detailed` - Full statistics + profiling
- `GET /stats/profiling` - Detailed profiling report

### Existing Endpoints
- `GET /docs` - Swagger API docs
- `GET /book/{symbol}` - Order book
- `POST /orders` - Submit order
- `DELETE /orders/{symbol}/{order_id}` - Cancel order
- `GET /stats` - Basic statistics
- `WS /ws/market` - Market data WebSocket
- `WS /ws/account/{user_id}` - User account WebSocket

## 🔧 Configuration

### Disable Market Maker or Noise Traders

Edit `api/main.py` and set these flags at the top:

```python
# Configuration - Set these to False to disable
ENABLE_MARKET_MAKER = True   # Set to False to disable market maker
ENABLE_NOISE_TRADERS = True  # Set to False to disable noise traders
NUM_NOISE_TRADERS = 3        # Number of noise traders (if enabled)
```

Then restart the server. You'll see confirmation messages:
```
✓ Market Maker enabled
✓ 3 Noise Traders enabled
```

Or if disabled:
```
✗ Market Maker disabled
✗ Noise Traders disabled
```

Check current configuration:
```
GET http://localhost:8000/config
```

### Engine Options
```python
TradingEngine(
    enable_logging=True,      # Event logging
    event_callback=None,      # Async event callback
    use_async=False,          # Async matching
    enable_profiling=False    # Performance profiling
)
```

### Async Engine Options
```python
AsyncMatchingEngine(
    enable_self_trade_prevention=True,
    thread_safe=False,        # Thread-safe mode
    batch_size=100           # Batch processing size
)
```

## 📱 Mobile Access

1. Find your IP: `ipconfig` (Windows)
2. Connect phone to same WiFi
3. Open: http://YOUR_IP:8000/trading

## 🧪 Testing

### Test Profiling
```powershell
python demo/test_profiling.py
```

### Test API
```powershell
python demo/test_api_endpoints.py
```

### Run Existing Tests
```powershell
python -m pytest tests/ -v
```

## 📊 Performance

### Without Profiling
- 152,000 orders/sec
- P50: 0.002 ms
- P99: 0.007 ms

### With Profiling
- 80,000 orders/sec (5% overhead)
- Detailed metrics available

### Async Batch Mode
- 100,000+ orders/sec
- Better resource utilization

## 🎨 UI Features

✅ Real-time order book with depth visualization
✅ Live price charts (Chart.js)
✅ Position tracking and P&L
✅ Trade history
✅ Order management (submit/cancel)
✅ Multi-symbol support
✅ Mobile responsive
✅ WebSocket real-time updates
✅ One-click trading
✅ Market and limit orders

## 📚 Documentation

- `WEEK8_UPDATES.md` - Complete feature guide
- `IMPLEMENTATION_SUMMARY.md` - What was built
- `week7_checkpoint.md` - Updated status
- `websockets_guide.md` - WebSocket usage
- `PERFORMANCE_RESULTS.md` - Performance tests

## 🆘 Quick Troubleshooting

**UI not loading?**
- Check server is running
- Try http://localhost:8000/trading

**WebSocket disconnected?**
- Refresh page
- Check connection indicator (green dot)

**Orders not appearing?**
- Check user ID matches
- Verify symbol is selected
- Check order book depth

**Profiling not working?**
- Enable with `enable_profiling=True`
- Check `/stats/detailed` endpoint

## ✨ What's New

### Performance
- cProfile integration
- Operation-level latency tracking
- Hot path identification
- Async matching engine
- Batch processing
- Thread-safe mode

### UI
- Professional trading terminal
- Real-time order book
- Live price charts
- P&L tracking
- Multi-symbol tabs
- Mobile responsive

### API
- `/stats/detailed` - Enhanced stats
- `/stats/profiling` - Profiling data
- `/trading` - Trading UI

---

**Ready to trade!** 🚀

Start server → Open /trading → Place orders → Watch P&L grow!
