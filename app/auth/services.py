import bcrypt
import jwt

from datetime import datetime, timedelta, timezone

from auth.models import User
from auth.schemas import Token
from core.settings import get_settings


class UserService:
    def __init__(self, session):
        self.session = session
        self.settings = get_settings()

    def _hash_password(self, password: str) -> str:
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        return hashed

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )

    def _generate_access_token(
        self, data: dict, expires_delta: int | None = None
    ) -> str:
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=15)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(
            to_encode, self.settings.SECRET_KEY, algorithm=self.settings.ALGORITHM
        )
        return encoded_jwt

    def get_user_by_username(self, username: str) -> User | None:
        return self.session.query(User).filter(User.username == username).first()

    def create_user(self, username: str, password: str, name: str) -> User:
        if self.get_user_by_username(username):
            raise ValueError("Username already exists")

        hashed_password = self._hash_password(password)
        user = User(
            username=username, password=hashed_password.decode("utf-8"), name=name
        )

        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def authenticate_user(self, username: str, password: str) -> Token:
        user = self.get_user_by_username(username)
        if not user or not self._verify_password(password, user.password):
            raise ValueError("Invalid username or password")

        token = self._generate_access_token(data={"sub": user.username})
        return Token(access_token=token, token_type="bearer")
