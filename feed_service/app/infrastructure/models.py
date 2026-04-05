from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, JSON, func
from .database import Base


class PostModel(Base):
    __tablename__ = "posts"
    id = Column(String, primary_key=True)
    author_id = Column(String, index=True, nullable=False)
    community_id = Column(String, nullable=True, index=True)
    body = Column(Text, nullable=False)
    media_refs = Column(JSON, default=[])
    reaction_counts = Column(JSON, default={"like": 0, "love": 0, "laugh": 0, "sad": 0, "angry": 0})
    comment_count = Column(Integer, default=0)
    is_deleted = Column(Boolean, default=False)
    moderation_status = Column(String, default="approved", index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class CommentModel(Base):
    __tablename__ = "comments"
    id = Column(String, primary_key=True)
    post_id = Column(String, index=True, nullable=False)
    author_id = Column(String, index=True, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class ReactionModel(Base):
    __tablename__ = "reactions"
    post_id = Column(String, primary_key=True)
    user_id = Column(String, primary_key=True)
    reaction_type = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class AuthorSnapshotModel(Base):
    __tablename__ = "author_snapshots"
    user_id = Column(String, primary_key=True)
    display_name = Column(String, default="")
    avatar_url = Column(String, default="")
    updated_at = Column(DateTime, server_default=func.now())


class OutboxModel(Base):
    __tablename__ = "outbox"
    id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    topic = Column(String, nullable=False)
    partition_key = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    published_at = Column(DateTime, nullable=True)
