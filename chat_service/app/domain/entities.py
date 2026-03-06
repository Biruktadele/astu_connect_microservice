from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Conversation:
    id: str = field(default_factory=new_id)
    type: str = "dm"  # dm | group
    name: Optional[str] = None
    participant_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Message:
    id: str = field(default_factory=new_id)
    conversation_id: str = ""
    sender_id: str = ""
    body: str = ""
    media_url: Optional[str] = None
    client_msg_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ReadReceipt:
    conversation_id: str = ""
    user_id: str = ""
    last_read_at: datetime = field(default_factory=datetime.utcnow)
