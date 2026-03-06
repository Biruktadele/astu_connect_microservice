from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Notification:
    id: str = field(default_factory=new_id)
    user_id: str = ""
    type: str = ""
    title: str = ""
    body: str = ""
    data: dict = field(default_factory=dict)
    is_read: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NotificationPreference:
    user_id: str = ""
    channel: str = "in_app"
    enabled: bool = True
    notify_follows: bool = True
    notify_comments: bool = True
    notify_reactions: bool = True
    notify_chat: bool = True
    notify_community: bool = True
