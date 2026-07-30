from tempfile import template

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from manager import ConnectionManager

app = FastAPI()
manager = ConnectionManager()
templates = Jinja2Templates(directory="templates")


@app.get("/doc/{doc_id}", response_class=HTMLResponse)
async def get_document(request: Request, doc_id: str):
    return templates.TemplateResponse(request, "index.html", {"doc_id": doc_id})


@app.websocket("/ws/{doc_id}")
async def websocket_endpoint(websocket: WebSocket, doc_id: str):
    await manager.connect(websocket, doc_id)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(data, doc_id, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket, doc_id)
        print(f"User Disconnected from the document {doc_id}")
