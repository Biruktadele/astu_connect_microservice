"""Pure domain entities — no framework dependencies."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class User:
    id: str = field(default_factory=new_id)
    email: str = ""
    username: str = ""
    display_name: str = ""
    department: str = ""
    year_of_study: int = 0
    bio: str = ""
    avatar_url: str = ""
    hashed_password: str = ""
    is_active: bool = True
    status: str = "active"  # active | deactivating | deleted
    email_verified: bool = False
    is_astu_student: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)

    def deactivate(self) -> None:
        self.status = "deactivating"
        self.is_active = False

    def validate_astu_email(self) -> bool:
        return self.email.endswith("@astu.edu.et") or self.email.endswith(".edu.et")


@dataclass
class Follow:
    id: str = field(default_factory=new_id)
    follower_id: str = ""
    followee_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Block:
    id: str = field(default_factory=new_id)
    blocker_id: str = ""
    blocked_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RefreshToken:
    id: str = field(default_factory=new_id)
    user_id: str = ""
    token_hash: str = ""
    device_info: str = ""
    is_revoked: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
