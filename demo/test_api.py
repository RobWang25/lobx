"""Demo script to test the trading API."""
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def print_response(name, response):
    """Pretty print API response."""
    print(f"\n{'='*60}")
    print(f"{name}")
    print(f"{'='*60}")
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

# 1. Check API is running
print("Testing Trading Exchange API")
response = requests.get(f"{BASE_URL}/")
print_response("API Info", response)

# 2. Get initial stats
response = requests.get(f"{BASE_URL}/stats")
print_response("Initial Stats", response)

# 3. Submit buy order
buy_order = {
    "symbol": "AAPL",
    "user_id": "alice",
    "side": "BUY",
    "price": "150.00",
    "quantity": "100"
}
response = requests.post(f"{BASE_URL}/orders", json=buy_order)
print_response("Buy Order Submitted", response)
buy_order_id = response.json()["order_id"]

# 4. Submit sell order
sell_order = {
    "symbol": "AAPL",
    "user_id": "bob",
    "side": "SELL",
    "price": "149.50",
    "quantity": "50"
}
response = requests.post(f"{BASE_URL}/orders", json=sell_order)
print_response("Sell Order Submitted", response)

# 5. Check order book
response = requests.get(f"{BASE_URL}/book/AAPL")
print_response("Order Book for AAPL", response)

# 6. Submit matching order to create a trade
match_order = {
    "symbol": "AAPL",
    "user_id": "charlie",
    "side": "SELL",
    "price": "150.00",
    "quantity": "100"
}
response = requests.post(f"{BASE_URL}/orders", json=match_order)
print_response("Matching Order (Creates Trade)", response)

# 7. Get final stats
time.sleep(0.5)
response = requests.get(f"{BASE_URL}/stats")
print_response("Final Stats", response)

# 8. Cancel an order
response = requests.delete(f"{BASE_URL}/orders/AAPL/{buy_order_id}")
print_response("Cancel Order", response)

print("\nDemo complete!")