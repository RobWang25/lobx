# Server Configuration Guide

## Market Maker & Noise Trader Settings

You can control whether the market maker and noise traders run at server startup.

### Configuration

Edit the top of `api/main.py`:

```python
# Configuration - Set these to False to disable
ENABLE_MARKET_MAKER = True
ENABLE_NOISE_TRADERS = True
NUM_NOISE_TRADERS = 3
```

### Use Cases

#### 1. Manual Trading Only (No Automation)
Perfect for testing the UI with manual orders only:

```python
ENABLE_MARKET_MAKER = False
ENABLE_NOISE_TRADERS = False
NUM_NOISE_TRADERS = 0
```

**Result:** Clean order book, no automatic trades. You control everything.

#### 2. Market Maker Only (Liquidity Provider)
Provides liquidity but no random noise:

```python
ENABLE_MARKET_MAKER = True
ENABLE_NOISE_TRADERS = False
NUM_NOISE_TRADERS = 0
```

**Result:** Order book has consistent bid/ask spread, no random trades.

#### 3. Noise Traders Only (Random Activity)
Random market activity without consistent liquidity:

```python
ENABLE_MARKET_MAKER = False
ENABLE_NOISE_TRADERS = True
NUM_NOISE_TRADERS = 3
```

**Result:** Random orders appear, but no market making.

#### 4. Full Simulation (Default)
Realistic market with liquidity and random activity:

```python
ENABLE_MARKET_MAKER = True
ENABLE_NOISE_TRADERS = True
NUM_NOISE_TRADERS = 3
```

**Result:** Active market with spread and random trades.

#### 5. Light Simulation
Reduce noise for slower trading:

```python
ENABLE_MARKET_MAKER = True
ENABLE_NOISE_TRADERS = True
NUM_NOISE_TRADERS = 1  # Fewer noise traders
```

**Result:** Less chaotic market activity.

#### 6. Heavy Simulation
Maximum market activity:

```python
ENABLE_MARKET_MAKER = True
ENABLE_NOISE_TRADERS = True
NUM_NOISE_TRADERS = 10  # More noise traders
```

**Result:** Very active market with lots of trades.

### Startup Messages

When you start the server, you'll see:

**With defaults (both enabled):**
```
✓ Market Maker enabled
✓ 3 Noise Traders enabled
```

**With both disabled:**
```
✗ Market Maker disabled
✗ Noise Traders disabled
```

### Check Current Configuration

#### Via API Root
```bash
curl http://localhost:8000/
```

Returns:
```json
{
  "name": "Trading Exchange API",
  "version": "1.0.0",
  "market_maker_enabled": true,
  "noise_traders_enabled": true,
  "num_noise_traders": 3
}
```

#### Via Config Endpoint
```bash
curl http://localhost:8000/config
```

Returns detailed configuration:
```json
{
  "market_maker": {
    "enabled": true,
    "symbols": ["AAPL", "GOOGL", "MSFT"],
    "base_spread": "0.10",
    "quantity_range": [10, 100]
  },
  "noise_traders": {
    "enabled": true,
    "count": 3,
    "symbols": ["AAPL", "GOOGL", "MSFT"],
    "order_rate": 2.0
  }
}
```

### Modifying Settings

1. **Stop the server** (Ctrl+C)
2. **Edit** `api/main.py`
3. **Change the flags** at the top of the file
4. **Restart the server**
5. **Verify** the startup messages

### Example: Setting Up for Demo

For a clean demo where you manually place all orders:

```python
# api/main.py (top of file)

ENABLE_MARKET_MAKER = False   # No automatic liquidity
ENABLE_NOISE_TRADERS = False  # No random orders
NUM_NOISE_TRADERS = 0
```

Then restart:
```powershell
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

You'll see:
```
✗ Market Maker disabled
✗ Noise Traders disabled
```

Now the order book starts empty, and only your manual orders appear!

### Tips

- **For testing**: Disable both for full control
- **For demos**: Enable market maker only for clean liquidity
- **For realistic simulation**: Enable both (default)
- **For performance testing**: Adjust NUM_NOISE_TRADERS for load

### Performance Impact

- **Market Maker**: Low overhead (1 background task)
- **Noise Traders**: ~2 orders/sec per trader
  - 3 traders = ~6 orders/sec
  - 10 traders = ~20 orders/sec

Disabling them reduces server load and makes manual testing easier.
