import redis.asyncio as redis
import asyncio

from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    """
    Manages local WebSocket connections per document room
    and coordinates Redis Pub/Sub listeners.
    """

    def __init__(self, redis_client: redis.Redis):
        # Maps doc_id -> set of active local WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # Tracks active Redis listener tasks per doc_id so we only run one per document per server
        self.listener_tasks: Dict[str, asyncio.Task] = {}
        self.redis_client = redis_client

    async def connect(self, doc_id: str, websocket: WebSocket):
        await websocket.accept()
        if doc_id not in self.active_connections:
            self.active_connections[doc_id] = set()
            # Start a Redis subscription listener for this document room
            self.listener_tasks[doc_id] = asyncio.create_task(
                self.redis_listener(doc_id)
            )
        self.active_connections[doc_id].add(websocket)

    def disconnect(self, doc_id: str, websocket: WebSocket):
        if doc_id in self.active_connections:
            self.active_connections[doc_id].discard(websocket)
            # If no local clients are left for this document, cancel the Redis listener
            if not self.active_connections[doc_id]:
                del self.active_connections[doc_id]
                task = self.listener_tasks.pop(doc_id, None)
                if task:
                    task.cancel()

    async def broadcast_local(self, doc_id: str, message: str):
        """Send a message to all WebSockets connected to this server for doc_id."""
        if doc_id in self.active_connections:
            dead_sockets = set()
            for ws in self.active_connections[doc_id]:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead_sockets.add(ws)

            for ws in dead_sockets:
                self.disconnect(doc_id, ws)

    async def redis_listener(self, doc_id: str):
        """
        Subscribes to a Redis channel for a specific document.
        Whenever a message arrives from any server, broadcast it to local WebSockets.
        """
        pubsub = self.redis_client.pubsub()
        channel_name = f"doc:{doc_id}"
        await pubsub.subscribe(channel_name)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    await self.broadcast_local(doc_id, data)
        except asyncio.CancelledError:
            await pubsub.unsubscribe(channel_name)
            await pubsub.close()
