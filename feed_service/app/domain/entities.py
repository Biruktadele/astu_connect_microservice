from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Post:
    id: str = field(default_factory=new_id)
    author_id: str = ""
    community_id: Optional[str] = None
    body: str = ""
    media_refs: list[str] = field(default_factory=list)
    reaction_counts: dict = field(default_factory=lambda: {"like": 0, "love": 0, "laugh": 0, "sad": 0, "angry": 0})
    comment_count: int = 0
    is_deleted: bool = False
    moderation_status: str = "approved"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Comment:
    id: str = field(default_factory=new_id)
    post_id: str = ""
    author_id: str = ""
    body: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Reaction:
    post_id: str = ""
    user_id: str = ""
    reaction_type: str = "like"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AuthorSnapshot:
    user_id: str = ""
    display_name: str = ""
    avatar_url: str = ""
    updated_at: datetime = field(default_factory=datetime.utcnow)
@dataclass
class SavedPost:
    user_id: str = ""
    post_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
