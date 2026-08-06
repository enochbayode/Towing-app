# app/services/websocket_manager.py
from fastapi import WebSocket
from typing import Dict, List
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Maps a trip_id to a list of active WebSocket connections
        self.active_connections: Dict[UUID, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, trip_id: UUID):
        await websocket.accept()
        if trip_id not in self.active_connections:
            self.active_connections[trip_id] = []
        self.active_connections[trip_id].append(websocket)
        logger.info(f"Client connected to trip {trip_id}. Total connections: {len(self.active_connections[trip_id])}")

    def disconnect(self, websocket: WebSocket, trip_id: UUID):
        if trip_id in self.active_connections:
            self.active_connections[trip_id].remove(websocket)
            if not self.active_connections[trip_id]:
                del self.active_connections[trip_id]
            logger.info(f"Client disconnected from trip {trip_id}.")

    async def broadcast_location(self, trip_id: UUID, location_data: dict):
        """Sends GPS coordinates to everyone watching this specific trip."""
        if trip_id in self.active_connections:
            for connection in self.active_connections[trip_id]:
                try:
                    await connection.send_json(location_data)
                except Exception as e:
                    logger.error(f"Failed to send message to a client: {e}")

# Create a single global instance to be used across the app
manager = ConnectionManager()