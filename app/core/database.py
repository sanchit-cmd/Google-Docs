from sqlmodel import SQLModel, create_engine, Session
from core.settings import get_settings


def get_session():
    engine = create_engine(get_settings().DATABASE_URL, echo=True)
    SQLModel.metadata.create_all(engine)
    return Session(engine)
