import jwt
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from auth.services import UserService
from auth.schemas import UserCreate
from core.database import get_session
from core.settings import get_settings

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# --- Dependencies ---
def get_user_service(session=Depends(get_session)):
    return UserService(session)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    Dependency to validate the JWT token and return the current user.
    Inject this into any route to protect it.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        settings = get_settings()
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str | None = payload.get("sub")

        if username is None:
            raise credentials_exception

    except jwt.PyJWTError:
        # Catches expired signatures, invalid tokens, etc.
        raise credentials_exception

    user = user_service.get_user_by_username(username)
    if user is None:
        raise credentials_exception

    return user


# --- Routes ---
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate, user_service: Annotated[UserService, Depends(get_user_service)]
):
    try:
        user = user_service.create_user(**payload.model_dump())
        token = user_service.authenticate_user(user.username, payload.password)
        return token
    except ValueError as e:
        # Catches the "Username already exists" error from the service
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/login")
async def login_user(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        token = user_service.authenticate_user(form_data.username, form_data.password)
        return token
    except ValueError as e:
        # Catches the "Invalid username or password" error from the service
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/verify", status_code=status.HTTP_200_OK)
async def verify_token(current_user=Depends(get_current_user)):
    """
    Protected route to verify the token. It will only execute if
    `get_current_user` successfully decodes the token and finds the user.
    """
    return {
        "message": "Token is valid!",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "username": current_user.username,
        },
    }
