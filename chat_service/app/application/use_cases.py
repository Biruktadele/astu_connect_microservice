from typing import Optional
from ..domain.entities import Conversation, Message
from ..domain.repositories import ConversationRepository, MessageRepository, EventPublisher


class StartDMUseCase:
    def __init__(self, conv_repo: ConversationRepository):
        self.conv_repo = conv_repo

    def execute(self, user_a: str, user_b: str) -> Conversation:
        if user_a == user_b:
            raise ValueError("Cannot DM yourself")
        existing = self.conv_repo.find_dm(user_a, user_b)
        if existing:
            return existing
        conv = Conversation(type="dm", participant_ids=sorted([user_a, user_b]))
        return self.conv_repo.create(conv)


class CreateGroupUseCase:
    def __init__(self, conv_repo: ConversationRepository):
        self.conv_repo = conv_repo

    def execute(self, creator_id: str, name: str, participant_ids: list[str]) -> Conversation:
        all_ids = list(set([creator_id] + participant_ids))
        conv = Conversation(type="group", name=name, participant_ids=all_ids)
        return self.conv_repo.create(conv)


class SendMessageUseCase:
    def __init__(self, msg_repo: MessageRepository, conv_repo: ConversationRepository, event_pub: EventPublisher):
        self.msg_repo = msg_repo
        self.conv_repo = conv_repo
        self.event_pub = event_pub

    def execute(self, conv_id: str, sender_id: str, body: str, media_url: Optional[str], client_msg_id: str) -> Message:
        conv = self.conv_repo.find_by_id(conv_id)
        if not conv:
            raise ValueError("Conversation not found")
        if sender_id not in conv.participant_ids:
            raise ValueError("Not a participant")

        if client_msg_id and self.msg_repo.exists_by_client_id(client_msg_id):
            raise ValueError("Duplicate message")

        msg = Message(
            conversation_id=conv_id, sender_id=sender_id,
            body=body, media_url=media_url, client_msg_id=client_msg_id,
        )
        saved = self.msg_repo.save(msg)

        self.event_pub.publish(
            event_type="chat.message.sent",
            topic="chat.events",
            partition_key=conv_id,
            payload={
                "message_id": saved.id,
                "conversation_id": conv_id,
                "sender_id": sender_id,
                "body_preview": body[:100],
                "created_at": saved.created_at.isoformat(),
                "recipient_ids": [uid for uid in conv.participant_ids if uid != sender_id],
            },
        )
        return saved


class GetHistoryUseCase:
    def __init__(self, msg_repo: MessageRepository, conv_repo: ConversationRepository):
        self.msg_repo = msg_repo
        self.conv_repo = conv_repo

    def execute(self, conv_id: str, user_id: str, before: Optional[str] = None, limit: int = 50) -> list[Message]:
        conv = self.conv_repo.find_by_id(conv_id)
        if not conv or user_id not in conv.participant_ids:
            raise ValueError("Not a participant or conversation not found")
        return self.msg_repo.find_by_conversation(conv_id, before, limit)
