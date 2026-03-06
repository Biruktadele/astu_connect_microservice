"""Outbox relay + Kafka consumers for feed fan-out and user event sync."""

import asyncio
import json
import logging
from datetime import datetime

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from sqlalchemy.orm import Session

from ..core.config import settings
from .database import SessionLocal
from .models import OutboxModel, AuthorSnapshotModel
from .repositories import RedisTimelineRepository

logger = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(self):
        self.producer: AIOKafkaProducer | None = None
        self._running = False

    async def start(self):
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
        )
        await self.producer.start()
        self._running = True

    async def stop(self):
        self._running = False
        if self.producer:
            await self.producer.stop()

    async def run_forever(self):
        await self.start()
        while self._running:
            try:
                await self._poll()
            except Exception:
                logger.exception("Outbox relay error")
            await asyncio.sleep(0.1)

    async def _poll(self):
        db = SessionLocal()
        try:
            entries = db.query(OutboxModel).filter(
                OutboxModel.published_at.is_(None)
            ).order_by(OutboxModel.created_at).limit(100).all()
            for e in entries:
                envelope = {
                    "event_id": e.id, "event_type": e.event_type,
                    "occurred_at": e.created_at.isoformat(),
                    "producer": "feed-service", "payload": json.loads(e.payload),
                }
                await self.producer.send(e.topic, value=envelope, key=e.partition_key)
                e.published_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()


class FanoutWorker:
    """Consumes post.created events and pushes post IDs into follower timelines."""

    def __init__(self):
        self._running = False
        self.timeline_repo = RedisTimelineRepository()

    async def run_forever(self):
        self._running = True
        consumer = AIOKafkaConsumer(
            "post.events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="feed-fanout-worker",
            value_deserializer=lambda v: json.loads(v),
            auto_offset_reset="latest",
        )
        await consumer.start()
        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    await self._handle(msg.value)
                except Exception:
                    logger.exception("Fanout error for message %s", msg.offset)
        finally:
            await consumer.stop()

    async def _handle(self, event: dict):
        payload = event.get("payload", {})
        event_type = event.get("event_type", "")
        if event_type == "post.created":
            await self._fanout_post(payload)
        elif event_type == "post.deleted":
            pass  # tombstone filtering at read time

    async def _fanout_post(self, payload: dict):
        import httpx
        author_id = payload["author_id"]
        post_id = payload["post_id"]
        created_at = payload.get("created_at", "")

        try:
            score = datetime.fromisoformat(created_at).timestamp()
        except (ValueError, TypeError):
            score = datetime.utcnow().timestamp()

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{settings.IDENTITY_SERVICE_URL}/api/v1/users/{author_id}/followers?limit=5000")
                if resp.status_code == 200:
                    data = resp.json()
                    follower_count = data.get("total", 0)
                    if follower_count >= settings.CELEBRITY_THRESHOLD:
                        return
                    for u in data.get("users", []):
                        self.timeline_repo.push(u["id"], post_id, score)
                        self.timeline_repo.trim(u["id"], settings.TIMELINE_MAX_SIZE)
        except Exception:
            logger.exception("Failed to fan out post %s", post_id)


class UserEventConsumer:
    """Consumes user.events to keep author_snapshots in sync."""

    def __init__(self):
        self._running = False

    async def run_forever(self):
        self._running = True
        consumer = AIOKafkaConsumer(
            "user.events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="feed-user-events",
            value_deserializer=lambda v: json.loads(v),
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    self._handle(msg.value)
                except Exception:
                    logger.exception("User event error")
        finally:
            await consumer.stop()

    def _handle(self, event: dict):
        payload = event.get("payload", {})
        event_type = event.get("event_type", "")
        if event_type in ("user.created", "user.updated"):
            db = SessionLocal()
            try:
                existing = db.query(AuthorSnapshotModel).filter(
                    AuthorSnapshotModel.user_id == payload.get("user_id")
                ).first()
                if existing:
                    existing.display_name = payload.get("display_name", existing.display_name)
                    existing.avatar_url = payload.get("avatar_url", existing.avatar_url)
                else:
                    db.add(AuthorSnapshotModel(
                        user_id=payload["user_id"],
                        display_name=payload.get("display_name", ""),
                        avatar_url=payload.get("avatar_url", ""),
                    ))
                db.commit()
            finally:
                db.close()


outbox_relay = OutboxRelay()
fanout_worker = FanoutWorker()
user_event_consumer = UserEventConsumer()
