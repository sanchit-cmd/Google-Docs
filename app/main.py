import json
from pprint import pprint
import uuid
import redis.asyncio as redis

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from network.manager import ConnectionManager
from core.settings import get_settings

from auth.routes import router as auth_router

# Setup Variables
redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = await redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    yield

    await redis_client.close()


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
manager = ConnectionManager(redis_client=redis_client)

app.include_router(auth_router, prefix="/auth", tags=["auth"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
async def get_document(request: Request, doc_id: str):
    return templates.TemplateResponse(request, "index.html", {"doc_id": doc_id})


@app.websocket("/ws/{doc_id}")
async def editor_websocket(websocket: WebSocket, doc_id: str):
    await manager.connect(doc_id, websocket)
    client_id = str(uuid.uuid4())[:8]

    try:
        while True:
            data = await websocket.receive_text()
            pprint(data)

            payload = json.loads(data)
            payload["sender_id"] = client_id

            channel_name = f"doc:{doc_id}"
            await redis_client.publish(channel_name, json.dumps(payload))

    except WebSocketDisconnect:
        manager.disconnect(doc_id, websocket)
