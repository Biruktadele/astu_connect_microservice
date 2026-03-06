"""Outbox relay — polls outbox table and publishes to Kafka."""

import asyncio
import json
import logging
from datetime import datetime

from aiokafka import AIOKafkaProducer
from sqlalchemy.orm import Session

from ..core.config import settings
from .database import SessionLocal
from .models import OutboxModel

logger = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(self):
        self.producer: AIOKafkaProducer | None = None
        self._running = False

    async def start(self):
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await self.producer.start()
        self._running = True
        logger.info("Outbox relay started")

    async def stop(self):
        self._running = False
        if self.producer:
            await self.producer.stop()

    async def run_forever(self):
        await self.start()
        while self._running:
            try:
                await self._poll_and_publish()
            except Exception:
                logger.exception("Outbox relay error")
            await asyncio.sleep(0.1)

    async def _poll_and_publish(self):
        db: Session = SessionLocal()
        try:
            entries = (
                db.query(OutboxModel)
                .filter(OutboxModel.published_at.is_(None))
                .order_by(OutboxModel.created_at)
                .limit(100)
                .all()
            )
            for entry in entries:
                payload = json.loads(entry.payload)
                envelope = {
                    "event_id": entry.id,
                    "event_type": entry.event_type,
                    "occurred_at": entry.created_at.isoformat(),
                    "producer": "identity-service",
                    "payload": payload,
                }
                await self.producer.send(
                    entry.topic, value=envelope, key=entry.partition_key,
                )
                entry.published_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()


outbox_relay = OutboxRelay()
