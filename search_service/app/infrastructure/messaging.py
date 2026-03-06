import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
from ..core.config import settings
from .elasticsearch_client import get_es_client

logger = logging.getLogger(__name__)


class SearchIndexConsumer:
    def __init__(self):
        self._running = False

    async def run_forever(self):
        self._running = True
        consumer = AIOKafkaConsumer(
            "user.events", "post.events", "community.events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="search-indexer",
            value_deserializer=lambda v: json.loads(v),
            auto_offset_reset="earliest",
        )
        await consumer.start()
        logger.info("Search indexer consumer started")
        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    self._handle(msg.value)
                except Exception:
                    logger.exception("Search indexing error")
        finally:
            await consumer.stop()

    def _handle(self, event: dict):
        et = event.get("event_type", "")
        payload = event.get("payload", {})
        es = get_es_client()

        if et == "user.created":
            es.index(index="users", id=payload.get("user_id"), document={
                "user_id": payload.get("user_id"),
                "username": payload.get("username", ""),
                "display_name": payload.get("display_name", ""),
                "department": payload.get("department", ""),
                "email": payload.get("email", ""),
                "avatar_url": payload.get("avatar_url", ""),
                "created_at": payload.get("created_at"),
            })

        elif et == "user.updated":
            uid = payload.get("user_id")
            doc = {}
            if "display_name" in payload:
                doc["display_name"] = payload["display_name"]
            if "avatar_url" in payload:
                doc["avatar_url"] = payload["avatar_url"]
            if "department" in payload:
                doc["department"] = payload["department"]
            if doc:
                es.update(index="users", id=uid, doc=doc)

        elif et == "post.created":
            es.index(index="posts", id=payload.get("post_id"), document={
                "post_id": payload.get("post_id"),
                "author_id": payload.get("author_id"),
                "community_id": payload.get("community_id"),
                "body": payload.get("body_preview", ""),
                "has_media": payload.get("has_media", False),
                "created_at": payload.get("created_at"),
            })

        elif et == "post.deleted":
            try:
                es.delete(index="posts", id=payload.get("post_id"))
            except Exception:
                pass

        elif et == "community.created":
            es.index(index="communities", id=payload.get("community_id"), document={
                "community_id": payload.get("community_id"),
                "name": payload.get("name", ""),
                "description": payload.get("description", ""),
                "owner_id": payload.get("owner_id", ""),
                "visibility": payload.get("visibility", "public"),
            })

    def stop(self):
        self._running = False


search_consumer = SearchIndexConsumer()
