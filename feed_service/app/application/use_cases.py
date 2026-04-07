import logging
import math
from typing import Optional

import redis

from ..core.config import settings
from ..domain.entities import Post, Comment, Reaction
from ..domain.repositories import (
    PostRepository, CommentRepository, ReactionRepository,
    TimelineRepository, AuthorSnapshotRepository, EventPublisher,
    SavedPostRepository,
)

logger = logging.getLogger(__name__)

_moderation_redis = None


def _get_moderation_redis():
    global _moderation_redis
    if _moderation_redis is None:
        _moderation_redis = redis.Redis.from_url(settings.FEED_REDIS_URL, decode_responses=True)
    return _moderation_redis


class CreatePostUseCase:
    def __init__(self, post_repo: PostRepository, event_pub: EventPublisher):
        self.post_repo = post_repo
        self.event_pub = event_pub

    def execute(self, author_id: str, body: str, media_refs: list[str], community_id: Optional[str] = None) -> Post:
        post = Post(author_id=author_id, body=body, media_refs=media_refs, community_id=community_id)

        if media_refs:
            try:
                r = _get_moderation_redis()
                for url in media_refs:
                    if r.exists(f"moderation:flagged:{url}"):
                        post.moderation_status = "flagged"
                        logger.warning("Post auto-flagged: media %s was flagged by moderation", url)
                        break
            except Exception:
                logger.exception("Failed to check moderation flags in Redis")

        saved = self.post_repo.save(post)
        self.event_pub.publish(
            event_type="post.created",
            topic="post.events",
            partition_key=saved.id,
            payload={
                "post_id": saved.id,
                "author_id": saved.author_id,
                "community_id": saved.community_id,
                "body_preview": saved.body[:280],
                "has_media": len(saved.media_refs) > 0,
                "created_at": saved.created_at.isoformat(),
            },
        )
        return saved


class DeletePostUseCase:
    def __init__(self, post_repo: PostRepository, event_pub: EventPublisher):
        self.post_repo = post_repo
        self.event_pub = event_pub

    def execute(self, post_id: str, requester_id: str) -> None:
        post = self.post_repo.find_by_id(post_id)
        if not post:
            raise ValueError("Post not found")
        if post.author_id != requester_id:
            raise ValueError("Not authorized to delete this post")
        self.post_repo.soft_delete(post_id)
        self.event_pub.publish(
            event_type="post.deleted",
            topic="post.events",
            partition_key=post_id,
            payload={"post_id": post_id, "author_id": post.author_id},
        )


class CreateCommentUseCase:
    def __init__(self, comment_repo: CommentRepository, post_repo: PostRepository, event_pub: EventPublisher):
        self.comment_repo = comment_repo
        self.post_repo = post_repo
        self.event_pub = event_pub

    def execute(self, post_id: str, author_id: str, body: str) -> Comment:
        post = self.post_repo.find_by_id(post_id)
        if not post:
            raise ValueError("Post not found")
        comment = Comment(post_id=post_id, author_id=author_id, body=body)
        saved = self.comment_repo.save(comment)
        self.post_repo.increment_comment_count(post_id)
        self.event_pub.publish(
            event_type="comment.created",
            topic="comment.events",
            partition_key=post_id,
            payload={
                "comment_id": saved.id,
                "post_id": post_id,
                "post_author_id": post.author_id,
                "commenter_id": author_id,
                "body_preview": body[:280],
                "created_at": saved.created_at.isoformat(),
            },
        )
        return saved


class ReactToPostUseCase:
    def __init__(self, reaction_repo: ReactionRepository, post_repo: PostRepository, event_pub: EventPublisher):
        self.reaction_repo = reaction_repo
        self.post_repo = post_repo
        self.event_pub = event_pub

    def execute(self, post_id: str, user_id: str, reaction_type: str) -> dict:
        post = self.post_repo.find_by_id(post_id)
        if not post:
            raise ValueError("Post not found")
        reaction = Reaction(post_id=post_id, user_id=user_id, reaction_type=reaction_type)
        self.reaction_repo.upsert(reaction)
        counts = self.reaction_repo.get_counts(post_id)
        self.post_repo.update_reaction_counts(post_id, counts)
        self.event_pub.publish(
            event_type="reaction.set",
            topic="reaction.events",
            partition_key=post_id,
            payload={
                "post_id": post_id,
                "post_author_id": post.author_id,
                "reactor_id": user_id,
                "reaction_type": reaction_type,
            },
        )
        return counts


class FetchTimelineUseCase:
    """Builds a mixed feed from personal, recommended, and recent streams.

    When the personal timeline is empty (cold start) the gap is filled
    with more recommended and recent posts so the feed is never blank.
    """

    def __init__(
        self, timeline_repo: TimelineRepository, post_repo: PostRepository,
        author_repo: AuthorSnapshotRepository, reaction_repo: ReactionRepository,
        saved_repo: SavedPostRepository,
    ):
        self.timeline_repo = timeline_repo
        self.post_repo = post_repo
        self.author_repo = author_repo
        self.reaction_repo = reaction_repo
        self.saved_repo = saved_repo

    def execute(self, user_id: str, offset: int = 0, limit: int = 30, requester_id: str = "") -> list[dict]:
        personal_target = max(1, math.ceil(limit * settings.FEED_MIX_PERSONAL / 100))
        recommended_target = max(1, math.ceil(limit * settings.FEED_MIX_RECOMMENDED / 100))
        recent_target = max(1, math.ceil(limit * settings.FEED_MIX_RECENT / 100))

        personal_ids = self.timeline_repo.get_timeline(user_id, offset, personal_target)
        recommended_ids = self.timeline_repo.get_recommended(0, recommended_target + limit)
        recent_ids = self.timeline_repo.get_recent(0, recent_target + limit)

        if len(personal_ids) < personal_target:
            gap = personal_target - len(personal_ids)
            recommended_target += gap // 2 + gap % 2
            recent_target += gap // 2

        seen: set[str] = set()
        merged: list[str] = []

        for pid in personal_ids:
            if pid not in seen:
                seen.add(pid)
                merged.append(pid)

        added_rec = 0
        for pid in recommended_ids:
            if added_rec >= recommended_target:
                break
            if pid not in seen:
                seen.add(pid)
                merged.append(pid)
                added_rec += 1

        added_recent = 0
        for pid in recent_ids:
            if added_recent >= recent_target:
                break
            if pid not in seen:
                seen.add(pid)
                merged.append(pid)
                added_recent += 1

        if not merged:
            return []

        posts = self.post_repo.find_by_ids(merged)
        posts = [p for p in posts if not p.is_deleted and p.moderation_status != "rejected"]
        posts.sort(key=lambda p: p.created_at, reverse=True)

        author_ids = list({p.author_id for p in posts})
        snapshots = self.author_repo.get_batch(author_ids)

        result = []
        for p in posts:
            snap = snapshots.get(p.author_id)
            my_reaction = self.reaction_repo.get_user_reaction(p.id, requester_id) if requester_id else None
            is_saved = self.saved_repo.is_saved(requester_id, p.id) if requester_id else False
            result.append({
                **p.__dict__,
                "author_name": snap.display_name if snap else "",
                "author_avatar": snap.avatar_url if snap else "",
                "my_reaction": my_reaction,
                "is_saved": is_saved,
            })
        return result
class ToggleSavePostUseCase:
    def __init__(self, saved_repo: SavedPostRepository, post_repo: PostRepository):
        self.saved_repo = saved_repo
        self.post_repo = post_repo

    def execute(self, user_id: str, post_id: str) -> bool:
        post = self.post_repo.find_by_id(post_id)
        if not post:
            raise ValueError("Post not found")
        
        if self.saved_repo.is_saved(user_id, post_id):
            self.saved_repo.delete(user_id, post_id)
            return False
        else:
            self.saved_repo.save(user_id, post_id)
            return True


class FetchSavedPostsUseCase:
    def __init__(self, saved_repo: SavedPostRepository, post_repo: PostRepository, author_repo: AuthorSnapshotRepository):
        self.saved_repo = saved_repo
        self.post_repo = post_repo
        self.author_repo = author_repo

    def execute(self, user_id: str, offset: int = 0, limit: int = 30) -> list[dict]:
        post_ids = self.saved_repo.find_by_user(user_id, limit, offset)
        if not post_ids:
            return []
        
        posts = self.post_repo.find_by_ids(post_ids)
        # Sort by the order in post_ids (saved order)
        order = {pid: i for i, pid in enumerate(post_ids)}
        posts.sort(key=lambda p: order.get(p.id, 999))

        author_ids = list({p.author_id for p in posts})
        snapshots = self.author_repo.get_batch(author_ids)

        return [
            {
                **p.__dict__,
                "author_name": snapshots[p.author_id].display_name if p.author_id in snapshots else "",
                "author_avatar": snapshots[p.author_id].avatar_url if p.author_id in snapshots else "",
                "is_saved": True
            }
            for p in posts
        ]
