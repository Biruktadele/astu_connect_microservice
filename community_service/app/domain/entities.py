from dataclasses import dataclass, field
from datetime import datetime
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Community:
    id: str = field(default_factory=new_id)
    name: str = ""
    slug: str = ""
    description: str = ""
    avatar_url: str = ""
    visibility: str = "public"
    owner_id: str = ""
    member_count: int = 0
    is_archived: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Membership:
    id: str = field(default_factory=new_id)
    community_id: str = ""
    user_id: str = ""
    role: str = "member"
    joined_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CommunityPost:
    id: str = field(default_factory=new_id)
    community_id: str = ""
    author_id: str = ""
    title: str = ""
    body: str = ""
    is_pinned: bool = False
    is_deleted: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
