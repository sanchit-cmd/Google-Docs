from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


from pathlib import Path
from auth.routes import get_current_user

BASE_DIR = Path(__file__).resolve().parent.parent.parent
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/api/metadata")
async def get_documents_metadata(
    ids: str = "", current_user=Depends(get_current_user)
):
    """
    Returns document metadata (title) for a comma-separated list of doc_ids.
    Checks Redis hot cache first, then falls back to MongoDB.
    """
    doc_ids = [i.strip() for i in ids.split(",") if i.strip()]
    if not doc_ids:
        return {}

    result = {}
    import main
    from services.mongo import get_document

    for doc_id in doc_ids:
        title = None
        if main.redis_client:
            try:
                title = await main.redis_client.get(f"doc:{doc_id}:title")
            except Exception:
                pass

        if not title:
            try:
                doc = await get_document(doc_id)
                if doc:
                    title = doc.get("title")
            except Exception:
                pass

        if title:
            result[doc_id] = {"title": title}

    return result


@router.get("/{doc_id}", response_class=HTMLResponse)
async def get_editor(
    request: Request, doc_id: str, current_user=Depends(get_current_user)
):
    return templates.TemplateResponse(
        request, "editor/editor.html", {"doc_id": doc_id, "user": current_user}
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def get_editor_home(request: Request, current_user=Depends(get_current_user)):
    return templates.TemplateResponse(
        request, "editor/room.html", {"user": current_user}
    )
