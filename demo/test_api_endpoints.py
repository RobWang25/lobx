"""
Quick test to verify the API endpoints work correctly.
"""
import sys
from pathlib import Path

# Add parent directory to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import requests
import time


def test_api_endpoints():
    """Test all API endpoints"""
    base_url = "http://localhost:8000"
    
    print("Testing API Endpoints")
    print("=" * 60)
    
    # Test root endpoint
    try:
        response = requests.get(f"{base_url}/")
        print(f"✓ Root endpoint: {response.status_code}")
        data = response.json()
        print(f"  Version: {data.get('version')}")
        print(f"  Trading UI: {data.get('trading_ui')}")
    except Exception as e:
        print(f"✗ Root endpoint failed: {e}")
    
    # Test stats endpoint
    try:
        response = requests.get(f"{base_url}/stats")
        print(f"✓ Stats endpoint: {response.status_code}")
        data = response.json()
        print(f"  Total Orders: {data.get('total_orders')}")
        print(f"  Total Trades: {data.get('total_trades')}")
    except Exception as e:
        print(f"✗ Stats endpoint failed: {e}")
    
    # Test detailed stats endpoint
    try:
        response = requests.get(f"{base_url}/stats/detailed")
        print(f"✓ Detailed Stats endpoint: {response.status_code}")
        data = response.json()
        print(f"  Active Symbols: {data.get('active_symbols')}")
        if 'operation_latencies' in data:
            print(f"  Has Operation Latencies: Yes")
    except Exception as e:
        print(f"✗ Detailed stats endpoint failed: {e}")
    
    # Test profiling endpoint
    try:
        response = requests.get(f"{base_url}/stats/profiling?top_n=5")
        print(f"✓ Profiling endpoint: {response.status_code}")
    except Exception as e:
        print(f"✗ Profiling endpoint failed: {e}")
    
    # Test order book endpoint
    try:
        response = requests.get(f"{base_url}/book/AAPL")
        print(f"✓ Order Book endpoint: {response.status_code}")
        data = response.json()
        print(f"  Symbol: {data.get('symbol')}")
        print(f"  Bid Levels: {len(data.get('bids', []))}")
        print(f"  Ask Levels: {len(data.get('asks', []))}")
    except Exception as e:
        print(f"✗ Order book endpoint failed: {e}")
    
    # Submit a test order
    try:
        response = requests.post(
            f"{base_url}/orders",
            json={
                "symbol": "AAPL",
                "user_id": "test_user",
                "side": "BUY",
                "price": "150.00",
                "quantity": "100"
            }
        )
        print(f"✓ Submit Order endpoint: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"  Order ID: {data.get('order_id')}")
    except Exception as e:
        print(f"✗ Submit order failed: {e}")
    
    print("\n" + "=" * 60)
    print("API endpoint tests completed!")
    print("\nTo access the Trading UI, open:")
    print(f"  {base_url}/trading")
    print("\nTo access the API docs, open:")
    print(f"  {base_url}/docs")


if __name__ == "__main__":
    print("\nMake sure the server is running:")
    print("  uvicorn api.main:app --reload --host 0.0.0.0 --port 8000")
    print("\nWaiting 3 seconds...\n")
    time.sleep(3)
    
    test_api_endpoints()
