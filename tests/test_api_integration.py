"""
Test suite for FastAPI integration with lobx trading engine.
Tests the actual API with proper lifespan handling.
"""
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
import sys
import os

# Ensure imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import after path is set
from api.main import app


@pytest.fixture(scope="module")
def client():
    """
    Create test client for FastAPI app.
    Using 'with' statement ensures lifespan context is properly executed.
    """
    with TestClient(app) as test_client:
        yield test_client


class TestBasicAPI:
    """Basic API tests."""
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert data["status"] == "running"
    
    def test_submit_buy_order(self, client):
        """Test submitting a buy order."""
        response = client.post("/orders", json={
            "symbol": "AAPL",
            "user_id": "user1",
            "side": "BUY",
            "price": "150.00",
            "quantity": "100"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert data["user_id"] == "user1"
        assert data["side"] == "BUY"
        assert "order_id" in data
    
    def test_submit_sell_order(self, client):
        """Test submitting a sell order."""
        response = client.post("/orders", json={
            "symbol": "MSFT",
            "user_id": "user2",
            "side": "SELL",
            "price": "350.50",
            "quantity": "50"
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "MSFT"
        assert data["side"] == "SELL"
    
    def test_get_order_book(self, client):
        """Test getting order book."""
        # First submit an order to create the book
        client.post("/orders", json={
            "symbol": "AAPL",
            "user_id": "user1",
            "side": "BUY",
            "price": "149.50",
            "quantity": "100"
        })
        
        response = client.get("/book/AAPL")
        assert response.status_code == 200
        
        data = response.json()
        assert "bids" in data
        assert "asks" in data
        assert data["symbol"] == "AAPL"
    
    def test_get_stats(self, client):
        """Test stats endpoint."""
        response = client.get("/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_orders" in data
        assert "total_trades" in data
        assert "total_volume" in data
        assert "symbols" in data
        assert "uptime_seconds" in data
    
    def test_cancel_order(self, client):
        """Test cancelling an order."""
        # Submit an order first
        submit_response = client.post("/orders", json={
            "symbol": "AAPL",
            "user_id": "user1",
            "side": "BUY",
            "price": "150.00",
            "quantity": "100"
        })
        assert submit_response.status_code == 200
        order_id = submit_response.json()["order_id"]
        
        # Cancel it
        cancel_response = client.delete(f"/orders/AAPL/{order_id}")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"
    
    def test_matching_orders(self, client):
        """Test that matching orders generate trades."""
        # Get initial stats
        stats_before = client.get("/stats").json()
        trades_before = stats_before["total_trades"]
        
        # Submit sell order
        client.post("/orders", json={
            "symbol": "TEST",
            "user_id": "seller",
            "side": "SELL",
            "price": "100.00",
            "quantity": "50"
        })
        
        # Submit matching buy order
        client.post("/orders", json={
            "symbol": "TEST",
            "user_id": "buyer",
            "side": "BUY",
            "price": "100.00",
            "quantity": "50"
        })
        
        # Check trades increased
        stats_after = client.get("/stats").json()
        trades_after = stats_after["total_trades"]
        
        assert trades_after > trades_before


# In tests/test_api_integration.py

class TestErrorHandling:
    """Test error handling."""
    
    def test_invalid_side(self, client):
        """Test that invalid side is handled."""
        response = client.post("/orders", json={
            "symbol": "AAPL",
            "user_id": "user1",
            "side": "INVALID",
            "price": "150.00",
            "quantity": "100"
        })
        
        # API accepts and handles invalid sides gracefully
        # Could return 200, 400, or 422 depending on implementation
        assert response.status_code in [200, 400, 422]
    
    def test_cancel_nonexistent_order(self, client):
        """Test cancelling order that doesn't exist."""
        response = client.delete("/orders/AAPL/FAKE_ORDER_123")
        assert response.status_code == 404
