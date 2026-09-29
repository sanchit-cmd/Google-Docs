import asyncio
import json
import logging
from datetime import datetime, timezone
import redis.asyncio as redis
from services.mongo import get_document, save_document

logger = logging.getLogger("stream_worker")

STREAM_KEY = "doc_save_stream"
GROUP_NAME = "mongo_writers"
CONSUMER_NAME = "worker_main"


class DocumentPersistenceManager:
    """
    Coordinates in-memory document caching in Redis, debounced flush scheduling,
    Redis Streams task creation, and background stream consumption to persist to MongoDB.
    """

    def __init__(self, redis_client: redis.Redis | None = None):
        self.redis_client = redis_client
        self.debounce_tasks: dict[str, asyncio.Task] = {}
        self.worker_task: asyncio.Task | None = None
        self.running = False

    def set_redis_client(self, redis_client: redis.Redis):
        self.redis_client = redis_client

    async def get_or_hydrate_document(self, doc_id: str) -> dict:
        """
        Retrieves document title and content from Redis cache if available;
        otherwise loads from MongoDB and hydrates Redis cache.
        """
        title_key = f"doc:{doc_id}:title"
        content_key = f"doc:{doc_id}:content"

        cached_title = None
        cached_content = None

        if self.redis_client:
            try:
                cached_title = await self.redis_client.get(title_key)
                cached_content_raw = await self.redis_client.get(content_key)
                if cached_content_raw:
                    try:
                        cached_content = json.loads(cached_content_raw)
                    except Exception:
                        cached_content = cached_content_raw
            except Exception as e:
                logger.warning(f"Error reading Redis cache for {doc_id}: {e}")

        # If present in Redis hot memory, return immediately
        if cached_title is not None and cached_content is not None:
            return {
                "doc_id": doc_id,
                "title": cached_title,
                "content": cached_content,
            }

        # Cold path: load from MongoDB
        doc = await get_document(doc_id)
        if doc:
            title = doc.get("title", "Untitled Document")
            content = doc.get("content", {"ops": []})

            # Hydrate Redis
            if self.redis_client:
                try:
                    await self.redis_client.set(title_key, title)
                    await self.redis_client.set(content_key, json.dumps(content))
                except Exception as e:
                    logger.warning(f"Error hydrating Redis for {doc_id}: {e}")

            return {
                "doc_id": doc_id,
                "title": title,
                "content": content,
            }

        # Brand new document
        default_title = cached_title or "Untitled Document"
        default_content = cached_content or {"ops": []}
        return {
            "doc_id": doc_id,
            "title": default_title,
            "content": default_content,
        }

    async def update_in_memory_content(self, doc_id: str, delta: dict):
        """
        Updates the in-memory document content in Redis and schedules a debounced save.
        """
        content_key = f"doc:{doc_id}:content"
        if self.redis_client:
            try:
                # Store latest delta / content state
                await self.redis_client.set(content_key, json.dumps(delta))
            except Exception as e:
                logger.warning(f"Error saving content to Redis for {doc_id}: {e}")

        self.schedule_debounced_save(doc_id)

    async def update_in_memory_title(self, doc_id: str, title: str):
        """
        Updates document title in Redis and schedules a debounced save.
        """
        title_key = f"doc:{doc_id}:title"
        if self.redis_client:
            try:
                await self.redis_client.set(title_key, title)
            except Exception as e:
                logger.warning(f"Error saving title to Redis for {doc_id}: {e}")

        self.schedule_debounced_save(doc_id)

    def schedule_debounced_save(self, doc_id: str, delay_seconds: float = 3.0):
        """
        Schedules a background task to enqueue a save job to Redis Stream
        after a quiet window of inactivity. Resets if new edits arrive.
        """
        if doc_id in self.debounce_tasks:
            self.debounce_tasks[doc_id].cancel()

        self.debounce_tasks[doc_id] = asyncio.create_task(
            self._debounced_flush_to_stream(doc_id, delay_seconds)
        )

    async def _debounced_flush_to_stream(self, doc_id: str, delay_seconds: float):
        try:
            await asyncio.sleep(delay_seconds)
            # Enqueue save job to Redis Stream
            if self.redis_client:
                await self.redis_client.xadd(
                    STREAM_KEY,
                    {
                        "doc_id": doc_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error publishing save task to stream for {doc_id}: {e}")
        finally:
            self.debounce_tasks.pop(doc_id, None)

    async def start_worker(self):
        """
        Initializes consumer group and starts the Redis Streams background consumer loop.
        """
        if not self.redis_client:
            return

        self.running = True

        # Ensure stream and consumer group exist
        try:
            await self.redis_client.xgroup_create(
                STREAM_KEY, GROUP_NAME, id="0", mkstream=True
            )
        except Exception as e:
            # Group already exists
            pass

        self.worker_task = asyncio.create_task(self._stream_consumer_loop())

    async def stop_worker(self):
        """
        Gracefully stops background worker and cancels remaining debounce timers.
        """
        self.running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass

        for task in self.debounce_tasks.values():
            task.cancel()
        self.debounce_tasks.clear()

    async def _stream_consumer_loop(self):
        """
        Reads save jobs from Redis Stream and flushes state to MongoDB.
        """
        while self.running:
            try:
                if not self.redis_client:
                    await asyncio.sleep(1)
                    continue

                # Read batch from stream
                response = await self.redis_client.xreadgroup(
                    GROUP_NAME,
                    CONSUMER_NAME,
                    {STREAM_KEY: ">"},
                    count=10,
                    block=2000,
                )

                if not response:
                    continue

                for stream_name, messages in response:
                    for msg_id, data in messages:
                        doc_id = data.get("doc_id")
                        if doc_id:
                            await self._persist_document_to_mongo(doc_id)

                        # Acknowledge task completion
                        await self.redis_client.xack(STREAM_KEY, GROUP_NAME, msg_id)

                # Trim stream to prevent unbounded memory growth
                await self.redis_client.xtrim(STREAM_KEY, maxlen=1000, approximate=True)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Redis Stream consumer worker: {e}")
                await asyncio.sleep(1)

    async def _persist_document_to_mongo(self, doc_id: str):
        """
        Reads the latest snapshot from Redis and upserts to MongoDB.
        """
        if not self.redis_client:
            return

        try:
            title_key = f"doc:{doc_id}:title"
            content_key = f"doc:{doc_id}:content"

            title = await self.redis_client.get(title_key) or "Untitled Document"
            raw_content = await self.redis_client.get(content_key)

            content = None
            if raw_content:
                try:
                    content = json.loads(raw_content)
                except Exception:
                    content = raw_content

            await save_document(doc_id=doc_id, title=title, content=content)
            logger.info(f"Successfully persisted document {doc_id} to MongoDB")
        except Exception as e:
            logger.error(f"Failed to persist document {doc_id} to MongoDB: {e}")
