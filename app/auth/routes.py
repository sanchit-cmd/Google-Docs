import jwt

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.services import AuthService
from auth.schemas import UserCreate, UserLogin, Token
from core.database import get_session
from core.settings import get_settings

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# --- Dependencies ---
def get_user_service(session=Depends(get_session)):
    return AuthService(session)


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    user_service: Annotated[AuthService, Depends(get_user_service)],
):
    auth_token = token or request.cookies.get("access_token")
    is_html_request = "text/html" in request.headers.get("accept", "")

    if not auth_token:
        if is_html_request:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/auth/login"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        settings = get_settings()
        payload = jwt.decode(
            auth_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str | None = payload.get("sub")

        if username is None:
            if is_html_request:
                raise HTTPException(
                    status_code=status.HTTP_303_SEE_OTHER,
                    headers={"Location": "/auth/login"},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

    except jwt.PyJWTError:
        if is_html_request:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/auth/login"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = user_service.get_user_by_username(username)
    if user is None:
        if is_html_request:
            raise HTTPException(
                status_code=status.HTTP_303_SEE_OTHER,
                headers={"Location": "/auth/login"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_optional_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    user_service: Annotated[AuthService, Depends(get_user_service)] = None,
):
    auth_token = token or request.cookies.get("access_token")
    if not auth_token:
        return None

    try:
        settings = get_settings()
        payload = jwt.decode(
            auth_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str | None = payload.get("sub")
        if username and user_service:
            return user_service.get_user_by_username(username)
    except Exception:
        return None

    return None


# --- Routes ---
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    response: Response,
    user_service: Annotated[AuthService, Depends(get_user_service)],
):
    """
    Registers a new user, sets access_token cookie, and returns JWT token.
    """
    try:
        user = user_service.create_user(**payload.model_dump())
        token = user_service.authenticate_user(user.username, payload.password)

        response.set_cookie(
            key="access_token",
            value=token.access_token,
            httponly=True,
            samesite="lax",
            max_age=86400,
        )
        return {
            "access_token": token.access_token,
            "token_type": "bearer",
            "redirect_url": "/editor",
            "user": {
                "id": user.id,
                "name": user.name,
                "username": user.username,
            },
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/login")
async def login_user(
    payload: UserLogin,
    response: Response,
    user_service: Annotated[AuthService, Depends(get_user_service)],
):
    """
    Authenticates a user, sets access_token cookie, and returns JWT token.
    """
    try:
        token = user_service.authenticate_user(payload.username, payload.password)
        user = user_service.get_user_by_username(payload.username)

        response.set_cookie(
            key="access_token",
            value=token.access_token,
            httponly=True,
            samesite="lax",
            max_age=86400,
        )
        return {
            "access_token": token.access_token,
            "token_type": "bearer",
            "redirect_url": "/editor",
            "user": {
                "id": user.id if user else None,
                "name": user.name if user else payload.username,
                "username": payload.username,
            },
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/logout")
async def logout_user():
    """
    Logs out the user by clearing the access_token cookie and redirecting to login.
    """
    redirect = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    redirect.delete_cookie("access_token")
    return redirect


@router.get("/verify", status_code=status.HTTP_200_OK)
async def verify_token(current_user=Depends(get_current_user)):
    """
    Protected route to verify the token.
    """
    return {
        "message": "Token is valid!",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "username": current_user.username,
        },
    }


# --- HTML Response Routes ---
@router.get("/login", response_class=HTMLResponse)
async def get_login_page(
    request: Request,
    current_user=Depends(get_optional_current_user),
):
    """
    Serves the login & register page. If already authenticated, redirects to /editor.
    """
    if current_user:
        return RedirectResponse(url="/editor", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "auth/login.html")

