from fastapi import WebSocket
from typing import Dict, List, Set
import json


class ConnectionManager:
    """Manages WebSocket connections for market data and user notifications"""
    
    def __init__(self):
        self.market_connections: Set[WebSocket] = set()
        self.user_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect_market(self, websocket: WebSocket):
        """Connect to global market data feed"""
        await websocket.accept()
        self.market_connections.add(websocket)
    
    def disconnect_market(self, websocket: WebSocket):
        """Disconnect from market data feed"""
        self.market_connections.discard(websocket)
    
    async def connect_user(self, user_id: str, websocket: WebSocket):
        """Connect to user-specific notifications"""
        await websocket.accept()
        if user_id not in self.user_connections:
            self.user_connections[user_id] = set()
        self.user_connections[user_id].add(websocket)
    
    def disconnect_user(self, user_id: str, websocket: WebSocket):
        """Disconnect from user notifications"""
        if user_id in self.user_connections:
            self.user_connections[user_id].discard(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]
    
    async def broadcast_market_data(self, data: dict):
        """Broadcast data to all market feed subscribers"""
        disconnected = set()
        for connection in self.market_connections:
            try:
                await connection.send_json(data)
            except:
                disconnected.add(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            self.market_connections.discard(connection)
    
    async def send_to_user(self, user_id: str, data: dict):
        """Send data to specific user"""
        if user_id in self.user_connections:
            disconnected = set()
            for connection in self.user_connections[user_id]:
                try:
                    await connection.send_json(data)
                except:
                    disconnected.add(connection)
            
            # Clean up disconnected clients
            for connection in disconnected:
                self.user_connections[user_id].discard(connection)