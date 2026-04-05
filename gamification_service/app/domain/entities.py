from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class UserPoints:
    user_id: str = ""
    total_points: int = 0
    total_posts: int = 0
    total_comments: int = 0
    total_reactions_received: int = 0
    communities_joined: int = 0
    followers_count: int = 0
    level: int = 1
    level_name: str = "Beginner"
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Badge:
    id: str = field(default_factory=new_id)
    user_id: str = ""
    badge_type: str = ""
    awarded_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PointTransaction:
    id: str = field(default_factory=new_id)
    user_id: str = ""
    action: str = ""
    points: int = 0
    event_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
