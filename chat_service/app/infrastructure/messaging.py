"""Kafka producer for chat events."""

import asyncio
import json
import logging
from aiokafka import AIOKafkaProducer
from ..core.config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
        )
        await _producer.start()
    return _producer


async def publish_event(event_type: str, topic: str, partition_key: str, payload: dict):
    producer = await get_producer()
    envelope = {
        "event_type": event_type,
        "producer": "chat-service",
        "payload": payload,
    }
    await producer.send(topic, value=envelope, key=partition_key)


async def shutdown_producer():
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
