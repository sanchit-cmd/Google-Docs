from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = f"redis://{REDIS_HOST}:{REDIS_PORT}"

    POSTGRES_USER: str = "user"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "editor"
    DATABASE_URL: str = (
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

    MONGO_HOST: str = "localhost"
    MONGO_PORT: int = 27017
    MONGO_USER: str = "admin"
    MONGO_PASSWORD: str = "SuperSecurePassword123"
    MONGO_DB: str = "editor_db"
    MONGO_URI: str = (
        f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/?authSource=admin"
    )

    SECRET_KEY: str = (
        "super-secret-jwt-token-key-with-at-least-32-bytes-length-here"
    )
    ALGORITHM: str = "HS256"


@lru_cache
def get_settings() -> Settings:
    return Settings()
