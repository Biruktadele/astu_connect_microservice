from typing import Optional
import json
import redis
from datetime import datetime

from ..domain.entities import Conversation, Message
from ..domain.repositories import ConversationRepository, MessageRepository, PresenceRepository, EventPublisher
from .cassandra_db import get_cassandra_session
from ..core.config import settings


class CassandraConversationRepository(ConversationRepository):
    def __init__(self):
        self.session = get_cassandra_session()

    def create(self, conv: Conversation) -> Conversation:
        self.session.execute(
            "INSERT INTO conversations (id, type, name, participant_ids, created_at) VALUES (%s,%s,%s,%s,%s)",
            (conv.id, conv.type, conv.name, conv.participant_ids, conv.created_at),
        )
        for uid in conv.participant_ids:
            self.session.execute(
                "INSERT INTO user_conversations (user_id, conversation_id, joined_at) VALUES (%s,%s,%s)",
                (uid, conv.id, conv.created_at),
            )
        return conv

    def find_by_id(self, conv_id: str) -> Optional[Conversation]:
        row = self.session.execute("SELECT * FROM conversations WHERE id=%s", (conv_id,)).one()
        if not row:
            return None
        return Conversation(
            id=row.id, type=row.type, name=row.name,
            participant_ids=list(row.participant_ids or []),
            created_at=row.created_at,
        )

    def find_dm(self, user_a: str, user_b: str) -> Optional[Conversation]:
        convs_a = self.get_user_conversations(user_a)
        for c in convs_a:
            if c.type == "dm" and set(c.participant_ids) == {user_a, user_b}:
                return c
        return None

    def get_user_conversations(self, user_id: str) -> list[Conversation]:
        rows = self.session.execute(
            "SELECT conversation_id FROM user_conversations WHERE user_id=%s", (user_id,)
        )
        result = []
        for row in rows:
            conv = self.find_by_id(row.conversation_id)
            if conv:
                result.append(conv)
        return result

    def add_participant(self, conv_id: str, user_id: str) -> None:
        conv = self.find_by_id(conv_id)
        if conv and user_id not in conv.participant_ids:
            new_list = conv.participant_ids + [user_id]
            self.session.execute(
                "UPDATE conversations SET participant_ids=%s WHERE id=%s", (new_list, conv_id),
            )
            self.session.execute(
                "INSERT INTO user_conversations (user_id, conversation_id, joined_at) VALUES (%s,%s,%s)",
                (user_id, conv_id, datetime.utcnow()),
            )


class CassandraMessageRepository(MessageRepository):
    def __init__(self):
        self.session = get_cassandra_session()

    def save(self, message: Message) -> Message:
        self.session.execute(
            "INSERT INTO messages (conversation_id, created_at, id, sender_id, body, media_url, client_msg_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (message.conversation_id, message.created_at, message.id, message.sender_id,
             message.body, message.media_url, message.client_msg_id),
        )
        if message.client_msg_id:
            self.session.execute(
                "INSERT INTO message_dedup (client_msg_id, message_id) VALUES (%s,%s)",
                (message.client_msg_id, message.id),
            )
        return message

    def find_by_conversation(self, conv_id: str, before: Optional[str] = None, limit: int = 50) -> list[Message]:
        if before:
            rows = self.session.execute(
                "SELECT * FROM messages WHERE conversation_id=%s AND created_at < %s LIMIT %s",
                (conv_id, before, limit),
            )
        else:
            rows = self.session.execute(
                "SELECT * FROM messages WHERE conversation_id=%s LIMIT %s",
                (conv_id, limit),
            )
        return [
            Message(id=r.id, conversation_id=r.conversation_id, sender_id=r.sender_id,
                    body=r.body, media_url=r.media_url, client_msg_id=r.client_msg_id or "",
                    created_at=r.created_at)
            for r in rows
        ]

    def exists_by_client_id(self, client_msg_id: str) -> bool:
        row = self.session.execute(
            "SELECT message_id FROM message_dedup WHERE client_msg_id=%s", (client_msg_id,)
        ).one()
        return row is not None


class RedisPresenceRepository(PresenceRepository):
    def __init__(self):
        self.r = redis.Redis.from_url(settings.CHAT_REDIS_URL, decode_responses=True)

    def set_online(self, user_id: str, pod_id: str) -> None:
        self.r.hset("presence", user_id, pod_id)
        self.r.sadd("online_users", user_id)

    def set_offline(self, user_id: str) -> None:
        self.r.hdel("presence", user_id)
        self.r.srem("online_users", user_id)

    def is_online(self, user_id: str) -> bool:
        return self.r.sismember("online_users", user_id)

    def get_pod(self, user_id: str) -> Optional[str]:
        return self.r.hget("presence", user_id)


class InMemoryEventPublisher(EventPublisher):
    """Collects events to be published by the outbox relay / directly via Kafka."""

    def __init__(self):
        self.events: list[dict] = []

    def publish(self, event_type: str, topic: str, partition_key: str, payload: dict) -> None:
        self.events.append({
            "event_type": event_type, "topic": topic,
            "partition_key": partition_key, "payload": payload,
        })
