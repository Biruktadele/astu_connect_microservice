import asyncio
import json
import logging
import uuid
from datetime import datetime

from aiokafka import AIOKafkaConsumer
from ..core.config import settings
from .database import SessionLocal
from .models import NotificationModel, NotificationPrefModel

logger = logging.getLogger(__name__)

EVENT_MAP = {
    "user.followed": {
        "user_key": "followee_id",
        "pref_field": "notify_follows",
        "title": "New follower",
        "body_fn": lambda p: "Someone started following you",
        "type": "follow",
    },
    "comment.created": {
        "user_key": "post_author_id",
        "pref_field": "notify_comments",
        "title": "New comment",
        "body_fn": lambda p: p.get("body_preview", "New comment on your post")[:100],
        "type": "comment",
    },
    "reaction.set": {
        "user_key": "post_author_id",
        "pref_field": "notify_reactions",
        "title": "New reaction",
        "body_fn": lambda p: "Someone reacted to your post",
        "type": "reaction",
    },
    "chat.message.sent": {
        "user_key": "recipient_ids",
        "pref_field": "notify_chat",
        "title": "New message",
        "body_fn": lambda p: p.get("body_preview", "You have a new message"),
        "type": "chat",
        "multi": True,
    },
}


class NotificationConsumer:
    def __init__(self):
        self._running = False

    async def run_forever(self):
        self._running = True
        consumer = AIOKafkaConsumer(
            "user.events", "comment.events", "reaction.events",
            "chat.events", "community.events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="notification-service",
            value_deserializer=lambda v: json.loads(v),
            auto_offset_reset="latest",
        )
        await consumer.start()
        logger.info("Notification consumer started")
        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    self._handle(msg.value)
                except Exception:
                    logger.exception("Notification event error")
        finally:
            await consumer.stop()

    def _handle(self, event):
        et = event.get("event_type", "")
        payload = event.get("payload", {})
        m = EVENT_MAP.get(et)
        if not m:
            return

        is_multi = m.get("multi", False)
        if is_multi:
            uids = payload.get(m["user_key"], [])
        else:
            uid = payload.get(m.get("user_key", ""))
            uids = [uid] if uid else []

        db = SessionLocal()
        try:
            for uid in uids:
                pref = db.query(NotificationPrefModel).filter(
                    NotificationPrefModel.user_id == uid
                ).first()
                if pref and not getattr(pref, m["pref_field"], True):
                    continue
                db.add(NotificationModel(
                    id=str(uuid.uuid4()), user_id=uid, type=m["type"],
                    title=m["title"], body=m["body_fn"](payload), data=payload,
                ))
            db.commit()
        finally:
            db.close()

    def stop(self):
        self._running = False


notification_consumer = NotificationConsumer()
