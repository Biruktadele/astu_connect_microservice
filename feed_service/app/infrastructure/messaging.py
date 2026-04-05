"""Outbox relay + Kafka consumers for feed fan-out, engagement scoring,
community feed sync, and user event handling."""

import asyncio
import json
import logging
import uuid
from datetime import datetime

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from sqlalchemy.orm import Session

from ..core.config import settings
from .database import SessionLocal
from .models import OutboxModel, AuthorSnapshotModel, PostModel
from .repositories import RedisTimelineRepository, PgPostRepository

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

        self.timeline_repo.push(author_id, post_id, score)
        self.timeline_repo.trim(author_id, settings.TIMELINE_MAX_SIZE)

        self.timeline_repo.push_recent(post_id, score)

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
    """Consumes user.events to keep author_snapshots in sync and backfill
    a new follower's timeline with recent posts from the followee."""

    def __init__(self):
        self._running = False
        self.timeline_repo = RedisTimelineRepository()

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
            self._sync_snapshot(payload)
        elif event_type == "user.followed":
            self._backfill_follow(payload)

    def _sync_snapshot(self, payload: dict):
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

    def _backfill_follow(self, payload: dict):
        """When user A follows user B, load B's recent posts into A's timeline."""
        follower_id = payload.get("follower_id")
        followee_id = payload.get("followee_id")
        if not follower_id or not followee_id:
            return
        db = SessionLocal()
        try:
            repo = PgPostRepository(db)
            recent_posts = repo.find_by_author(
                followee_id, limit=settings.FOLLOW_BACKFILL_COUNT, offset=0,
            )
            for p in recent_posts:
                score = p.created_at.timestamp()
                self.timeline_repo.push(follower_id, p.id, score)
            self.timeline_repo.trim(follower_id, settings.TIMELINE_MAX_SIZE)
        finally:
            db.close()


class EngagementWorker:
    """Consumes reaction.events and comment.events to populate the
    recommended timeline with high-engagement posts."""

    def __init__(self):
        self._running = False
        self.timeline_repo = RedisTimelineRepository()

    async def run_forever(self):
        self._running = True
        consumer = AIOKafkaConsumer(
            "reaction.events", "comment.events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="feed-engagement-worker",
            value_deserializer=lambda v: json.loads(v),
            auto_offset_reset="latest",
        )
        await consumer.start()
        logger.info("EngagementWorker started")
        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    self._handle(msg.value)
                except Exception:
                    logger.exception("EngagementWorker error")
        finally:
            await consumer.stop()

    def _handle(self, event: dict):
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})
        if event_type not in ("reaction.set", "comment.created"):
            return
        post_id = payload.get("post_id")
        if not post_id:
            return

        db = SessionLocal()
        try:
            row = db.query(PostModel).filter(PostModel.id == post_id).first()
            if not row or row.is_deleted:
                return
            counts = row.reaction_counts or {}
            total_reactions = sum(counts.values())
            total_comments = row.comment_count or 0
            score = total_reactions * 2 + total_comments * 3
            if score >= settings.RECOMMENDED_MIN_SCORE:
                self.timeline_repo.update_score_recommended(post_id, float(score))
        finally:
            db.close()


class CommunityFeedWorker:
    """Consumes community.events and mirrors community posts into the
    feed service's DB and the recent timeline."""

    def __init__(self):
        self._running = False
        self.timeline_repo = RedisTimelineRepository()

    async def run_forever(self):
        self._running = True
        consumer = AIOKafkaConsumer(
            "community.events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="feed-community-worker",
            value_deserializer=lambda v: json.loads(v),
            auto_offset_reset="latest",
        )
        await consumer.start()
        logger.info("CommunityFeedWorker started")
        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    self._handle(msg.value)
                except Exception:
                    logger.exception("CommunityFeedWorker error")
        finally:
            await consumer.stop()

    def _handle(self, event: dict):
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})
        if event_type != "community.post.created":
            return

        post_id = payload.get("post_id")
        community_id = payload.get("community_id")
        author_id = payload.get("author_id")
        body_preview = payload.get("body_preview", "")
        created_at_str = payload.get("created_at", "")

        if not post_id or not community_id:
            return

        try:
            created_at = datetime.fromisoformat(created_at_str)
        except (ValueError, TypeError):
            created_at = datetime.utcnow()
        score = created_at.timestamp()

        db = SessionLocal()
        try:
            existing = db.query(PostModel).filter(PostModel.id == post_id).first()
            if not existing:
                db.add(PostModel(
                    id=post_id,
                    author_id=author_id or "",
                    community_id=community_id,
                    body=body_preview,
                    media_refs=[],
                    reaction_counts={"like": 0, "love": 0, "laugh": 0, "sad": 0, "angry": 0},
                    comment_count=0,
                    is_deleted=False,
                    created_at=created_at,
                ))
                db.commit()
            self.timeline_repo.push_recent(post_id, score)
        finally:
            db.close()


outbox_relay = OutboxRelay()
fanout_worker = FanoutWorker()
user_event_consumer = UserEventConsumer()
engagement_worker = EngagementWorker()
community_feed_worker = CommunityFeedWorker()