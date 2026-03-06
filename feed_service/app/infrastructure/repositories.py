from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func
import json, uuid, redis
from datetime import datetime

from ..domain.entities import Post, Comment, Reaction, AuthorSnapshot
from ..domain.repositories import (
    PostRepository, CommentRepository, ReactionRepository,
    TimelineRepository, AuthorSnapshotRepository, EventPublisher,
)
from .models import PostModel, CommentModel, ReactionModel, AuthorSnapshotModel, OutboxModel
from ..core.config import settings


def _post_to_entity(m: PostModel) -> Post:
    return Post(
        id=m.id, author_id=m.author_id, community_id=m.community_id,
        body=m.body, media_refs=m.media_refs or [], reaction_counts=m.reaction_counts or {},
        comment_count=m.comment_count, is_deleted=m.is_deleted, created_at=m.created_at,
    )


class PgPostRepository(PostRepository):
    def __init__(self, db: Session):
        self.db = db

    def save(self, post: Post) -> Post:
        m = PostModel(
            id=post.id, author_id=post.author_id, community_id=post.community_id,
            body=post.body, media_refs=post.media_refs, reaction_counts=post.reaction_counts,
            comment_count=0, is_deleted=False, created_at=post.created_at,
        )
        self.db.add(m)
        self.db.flush()
        return _post_to_entity(m)

    def find_by_id(self, post_id: str) -> Optional[Post]:
        m = self.db.query(PostModel).filter(PostModel.id == post_id, PostModel.is_deleted == False).first()
        return _post_to_entity(m) if m else None

    def soft_delete(self, post_id: str) -> bool:
        m = self.db.query(PostModel).filter(PostModel.id == post_id).first()
        if m:
            m.is_deleted = True
            self.db.flush()
            return True
        return False

    def find_by_author(self, author_id: str, limit: int = 30, offset: int = 0) -> list[Post]:
        rows = self.db.query(PostModel).filter(
            PostModel.author_id == author_id, PostModel.is_deleted == False
        ).order_by(PostModel.created_at.desc()).limit(limit).offset(offset).all()
        return [_post_to_entity(r) for r in rows]

    def find_by_ids(self, post_ids: list[str]) -> list[Post]:
        rows = self.db.query(PostModel).filter(PostModel.id.in_(post_ids)).all()
        by_id = {r.id: _post_to_entity(r) for r in rows}
        return [by_id[pid] for pid in post_ids if pid in by_id]

    def increment_comment_count(self, post_id: str) -> None:
        self.db.query(PostModel).filter(PostModel.id == post_id).update(
            {PostModel.comment_count: PostModel.comment_count + 1}
        )
        self.db.flush()

    def update_reaction_counts(self, post_id: str, counts: dict) -> None:
        self.db.query(PostModel).filter(PostModel.id == post_id).update(
            {PostModel.reaction_counts: counts}
        )
        self.db.flush()


class PgCommentRepository(CommentRepository):
    def __init__(self, db: Session):
        self.db = db

    def save(self, comment: Comment) -> Comment:
        m = CommentModel(id=comment.id, post_id=comment.post_id, author_id=comment.author_id, body=comment.body)
        self.db.add(m)
        self.db.flush()
        return comment

    def find_by_post(self, post_id: str, limit: int = 50, offset: int = 0) -> list[Comment]:
        rows = self.db.query(CommentModel).filter(
            CommentModel.post_id == post_id
        ).order_by(CommentModel.created_at.desc()).limit(limit).offset(offset).all()
        return [Comment(id=r.id, post_id=r.post_id, author_id=r.author_id, body=r.body, created_at=r.created_at) for r in rows]

    def delete(self, comment_id: str) -> bool:
        r = self.db.query(CommentModel).filter(CommentModel.id == comment_id).first()
        if r:
            self.db.delete(r)
            self.db.flush()
            return True
        return False


class PgReactionRepository(ReactionRepository):
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, reaction: Reaction) -> Reaction:
        existing = self.db.query(ReactionModel).filter(
            ReactionModel.post_id == reaction.post_id, ReactionModel.user_id == reaction.user_id
        ).first()
        if existing:
            existing.reaction_type = reaction.reaction_type
        else:
            self.db.add(ReactionModel(
                post_id=reaction.post_id, user_id=reaction.user_id, reaction_type=reaction.reaction_type,
            ))
        self.db.flush()
        return reaction

    def delete(self, post_id: str, user_id: str) -> bool:
        r = self.db.query(ReactionModel).filter(
            ReactionModel.post_id == post_id, ReactionModel.user_id == user_id
        ).first()
        if r:
            self.db.delete(r)
            self.db.flush()
            return True
        return False

    def get_counts(self, post_id: str) -> dict:
        rows = self.db.query(ReactionModel.reaction_type, sa_func.count()).filter(
            ReactionModel.post_id == post_id
        ).group_by(ReactionModel.reaction_type).all()
        counts = {"like": 0, "love": 0, "laugh": 0, "sad": 0, "angry": 0}
        for rtype, cnt in rows:
            counts[rtype] = cnt
        return counts

    def get_user_reaction(self, post_id: str, user_id: str) -> Optional[str]:
        r = self.db.query(ReactionModel.reaction_type).filter(
            ReactionModel.post_id == post_id, ReactionModel.user_id == user_id
        ).first()
        return r[0] if r else None


class RedisTimelineRepository(TimelineRepository):
    def __init__(self):
        self.r = redis.Redis.from_url(settings.FEED_REDIS_URL, decode_responses=True)

    def push(self, user_id: str, post_id: str, score: float) -> None:
        self.r.zadd(f"timeline:{user_id}", {post_id: score})

    def get_timeline(self, user_id: str, offset: int = 0, limit: int = 30) -> list[str]:
        return self.r.zrevrange(f"timeline:{user_id}", offset, offset + limit - 1)

    def remove(self, user_id: str, post_id: str) -> None:
        self.r.zrem(f"timeline:{user_id}", post_id)

    def trim(self, user_id: str, max_size: int) -> None:
        self.r.zremrangebyrank(f"timeline:{user_id}", 0, -(max_size + 1))


class PgAuthorSnapshotRepository(AuthorSnapshotRepository):
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, snapshot: AuthorSnapshot) -> None:
        existing = self.db.query(AuthorSnapshotModel).filter(AuthorSnapshotModel.user_id == snapshot.user_id).first()
        if existing:
            existing.display_name = snapshot.display_name
            existing.avatar_url = snapshot.avatar_url
            existing.updated_at = datetime.utcnow()
        else:
            self.db.add(AuthorSnapshotModel(
                user_id=snapshot.user_id, display_name=snapshot.display_name, avatar_url=snapshot.avatar_url,
            ))
        self.db.flush()

    def get(self, user_id: str) -> Optional[AuthorSnapshot]:
        m = self.db.query(AuthorSnapshotModel).filter(AuthorSnapshotModel.user_id == user_id).first()
        return AuthorSnapshot(user_id=m.user_id, display_name=m.display_name, avatar_url=m.avatar_url) if m else None

    def get_batch(self, user_ids: list[str]) -> dict[str, AuthorSnapshot]:
        rows = self.db.query(AuthorSnapshotModel).filter(AuthorSnapshotModel.user_id.in_(user_ids)).all()
        return {r.user_id: AuthorSnapshot(user_id=r.user_id, display_name=r.display_name, avatar_url=r.avatar_url) for r in rows}


class OutboxEventPublisher(EventPublisher):
    def __init__(self, db: Session):
        self.db = db

    def publish(self, event_type: str, topic: str, partition_key: str, payload: dict) -> None:
        entry = OutboxModel(
            id=str(uuid.uuid4()), event_type=event_type, topic=topic,
            partition_key=partition_key, payload=json.dumps(payload),
        )
        self.db.add(entry)
        self.db.flush()
