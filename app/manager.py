from fastapi import WebSocket
from typing import List, Dict


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, doc_id: str):
        await websocket.accept()

        if doc_id not in self.active_connections:
            self.active_connections[doc_id] = []

        self.active_connections[doc_id].append(websocket)

    async def disconnect(self, websocket: WebSocket, doc_id: str):
        if doc_id in self.active_connections:
            self.active_connections[doc_id].remove(websocket)

            if not self.active_connections[doc_id]:
                del self.active_connections[doc_id]

    async def broadcast(self, message: bytes, doc_id: str, sender: WebSocket):
        if doc_id in self.active_connections:
            for connection in self.active_connections[doc_id]:
                if connection != sender:
                    await connection.send_text(message)
