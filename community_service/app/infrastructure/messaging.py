import asyncio, json, logging
from datetime import datetime
from aiokafka import AIOKafkaProducer
from ..core.config import settings
from .database import SessionLocal
from .models import OutboxModel

logger = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(self):
        self.producer = None
        self._running = False

    async def start(self):
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None)
        await self.producer.start()
        self._running = True

    async def stop(self):
        self._running = False
        if self.producer: await self.producer.stop()

    async def run_forever(self):
        await self.start()
        while self._running:
            try: await self._poll()
            except Exception: logger.exception("Outbox relay error")
            await asyncio.sleep(0.1)

    async def _poll(self):
        db = SessionLocal()
        try:
            entries = db.query(OutboxModel).filter(
                OutboxModel.published_at.is_(None)
            ).order_by(OutboxModel.created_at).limit(100).all()
            for e in entries:
                await self.producer.send(e.topic, value={
                    "event_id": e.id, "event_type": e.event_type,
                    "producer": "community-service",
                    "payload": json.loads(e.payload)
                }, key=e.partition_key)
                e.published_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()


outbox_relay = OutboxRelay()
