import json
import uuid
from pathlib import Path
import redis.asyncio as redis

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from network.manager import ConnectionManager
from core.settings import get_settings

from auth.routes import router as auth_router, get_optional_current_user
from editor.routes import router as editor_router

from services.mongo import init_mongo, close_mongo
from services.stream_worker import DocumentPersistenceManager

# Setup Variables
redis_client = None
persistence_manager = DocumentPersistenceManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = await redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    manager.redis_client = redis_client
    persistence_manager.set_redis_client(redis_client)

    # Initialize MongoDB connection & start Redis Streams background worker
    init_mongo()
    await persistence_manager.start_worker()

    yield

    # Shutdown background worker, close MongoDB & Redis
    await persistence_manager.stop_worker()
    close_mongo()
    await redis_client.close()


app = FastAPI(lifespan=lifespan)
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
manager = ConnectionManager(redis_client=redis_client)


# --- Routers ---
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(editor_router, prefix="/editor", tags=["editor"])


# --- HTML Routes ---
@app.get("/", response_class=HTMLResponse)
async def get_home(request: Request, current_user=Depends(get_optional_current_user)):
    return templates.TemplateResponse(request, "home.html", {"user": current_user})


# --- Routes ---
@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.websocket("/ws/{doc_id}")
async def editor_websocket(websocket: WebSocket, doc_id: str):
    await manager.connect(doc_id, websocket)

    # 1. Hydrate and send saved document state (Title & Content) upon connection
    try:
        doc_state = await persistence_manager.get_or_hydrate_document(doc_id)
        await websocket.send_text(
            json.dumps(
                {
                    "type": "init",
                    "doc_id": doc_id,
                    "title": doc_state.get("title", "Untitled Document"),
                    "content": doc_state.get("content", {"ops": []}),
                    "sender_id": "server",
                }
            )
        )
    except Exception as e:
        pass

    try:
        while True:
            data = await websocket.receive_text()
            channel_name = f"doc:{doc_id}"

            # 2. Process incoming changes for in-memory buffer and debounce queue
            try:
                payload = json.loads(data)
                msg_type = payload.get("type")

                if msg_type == "title" and "title" in payload:
                    await persistence_manager.update_in_memory_title(
                        doc_id, payload["title"]
                    )
                elif msg_type == "delta" or "delta" in payload or "full_content" in payload:
                    content_to_save = payload.get("full_content") or payload.get("delta")
                    if content_to_save:
                        await persistence_manager.update_in_memory_content(
                            doc_id, content_to_save
                        )
            except Exception:
                pass

            # 3. Broadcast real-time delta to all connected clients
            if redis_client:
                await redis_client.publish(channel_name, data)
            else:
                await manager.broadcast_local(doc_id, data)

    except WebSocketDisconnect:
        manager.disconnect(doc_id, websocket)
