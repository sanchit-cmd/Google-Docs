from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from core.settings import get_settings

mongo_client: AsyncIOMotorClient | None = None
mongo_db: AsyncIOMotorDatabase | None = None


def init_mongo() -> AsyncIOMotorDatabase:
    global mongo_client, mongo_db
    settings = get_settings()
    mongo_client = AsyncIOMotorClient(settings.MONGO_URI)
    mongo_db = mongo_client[settings.MONGO_DB]
    return mongo_db


def close_mongo():
    global mongo_client, mongo_db
    if mongo_client:
        mongo_client.close()
        mongo_client = None
        mongo_db = None


def get_mongo_db() -> AsyncIOMotorDatabase:
    global mongo_db
    if mongo_db is None:
        init_mongo()
    return mongo_db


async def get_document(doc_id: str) -> dict | None:
    db = get_mongo_db()
    doc = await db.documents.find_one({"_id": doc_id})
    return doc


async def save_document(
    doc_id: str,
    title: str | None = None,
    content: dict | list | str | None = None,
    updated_by: str | None = None,
) -> dict:
    db = get_mongo_db()
    now = datetime.now(timezone.utc)

    update_fields = {"updated_at": now}
    if title is not None:
        update_fields["title"] = title
    if content is not None:
        update_fields["content"] = content
    if updated_by is not None:
        update_fields["last_modified_by"] = updated_by

    setOnInsert_fields = {
        "_id": doc_id,
        "created_at": now,
    }

    result = await db.documents.find_one_and_update(
        {"_id": doc_id},
        {
            "$set": update_fields,
            "$setOnInsert": setOnInsert_fields,
            "$inc": {"version": 1},
        },
        upsert=True,
        return_document=True,
    )
    return result
