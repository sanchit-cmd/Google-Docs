from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


from pathlib import Path
from auth.routes import get_current_user

BASE_DIR = Path(__file__).resolve().parent.parent.parent
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
