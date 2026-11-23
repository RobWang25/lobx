# Quick Start Guide - New Features

## Getting Started in 60 Seconds

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

## Key Features

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

### 3. Async Engine (not working)
`TradingEngine(use_async=True)` currently raises a `TypeError` on the first order, and `AsyncMatchingEngine` can't create trades. Use the default synchronous engine. FastAPI already handles connections asynchronously around it.

## Trading UI Quick Guide

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

## API Endpoints

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

### Engine Options
```python
TradingEngine(
    enable_logging=True,      # Event logging
    event_callback=None,      # Async event callback
    use_async=False,          # Leave off: async matching doesn't work
    enable_profiling=False,   # Performance profiling
    backend=None,             # "python", "cpp", or automatic selection
    self_trade_prevention=True,
    latency_window=100_000,   # Recent submit latency samples to keep
)
```

Use Python 3.14 for development. The extension also supports Python 3.10 and newer. Build it with `python -m pip install -e .`. The engine selects C++ automatically when the extension is available, and warns before falling back to Python when it is missing.

##s Mobile Access

1. Find your IP: `ipconfig` (Windows)
2. Connect phone to same WiFi
3. Open: http://YOUR_IP:8000/trading

## Testing

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

## Performance

See `PERFORMANCE_RESULTS.md` for current numbers and how to reproduce them.

## Documentation

- `WEEK8_UPDATES.md` - Complete feature guide
- `IMPLEMENTATION_SUMMARY.md` - What was built
- `week7_checkpoint.md` - Updated status
- `websockets_guide.md` - WebSocket usage
- `PERFORMANCE_RESULTS.md` - Performance tests

## Quick Troubleshooting

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

## What's New

### Performance
- cProfile integration
- Operation-level latency tracking
- Hot path identification

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

**Ready to trade!** 

Start server → Open /trading → Place orders → Watch P&L grow!
