from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, func
from .database import Base


class CommunityModel(Base):
    __tablename__ = "communities"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    description = Column(Text, default="")
    avatar_url = Column(String, default="")
    visibility = Column(String, default="public")
    owner_id = Column(String, nullable=False, index=True)
    member_count = Column(Integer, default=0)
    is_archived = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class MembershipModel(Base):
    __tablename__ = "memberships"
    id = Column(String, primary_key=True)
    community_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    role = Column(String, default="member")
    joined_at = Column(DateTime, server_default=func.now())


class CommunityPostModel(Base):
    __tablename__ = "community_posts"
    id = Column(String, primary_key=True)
    community_id = Column(String, index=True, nullable=False)
    author_id = Column(String, index=True, nullable=False)
    title = Column(String, default="")
    body = Column(Text, nullable=False)
    is_pinned = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class OutboxModel(Base):
    __tablename__ = "outbox"
    id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    topic = Column(String, nullable=False)
    partition_key = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    published_at = Column(DateTime, nullable=True)
