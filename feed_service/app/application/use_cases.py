from typing import Optional
from ..domain.entities import Post, Comment, Reaction
from ..domain.repositories import (
    PostRepository, CommentRepository, ReactionRepository,
    TimelineRepository, AuthorSnapshotRepository, EventPublisher,
)


class CreatePostUseCase:
    def __init__(self, post_repo: PostRepository, event_pub: EventPublisher):
        self.post_repo = post_repo
        self.event_pub = event_pub

    def execute(self, author_id: str, body: str, media_refs: list[str], community_id: Optional[str] = None) -> Post:
        post = Post(author_id=author_id, body=body, media_refs=media_refs, community_id=community_id)
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
    def __init__(
        self, timeline_repo: TimelineRepository, post_repo: PostRepository,
        author_repo: AuthorSnapshotRepository, reaction_repo: ReactionRepository,
    ):
        self.timeline_repo = timeline_repo
        self.post_repo = post_repo
        self.author_repo = author_repo
        self.reaction_repo = reaction_repo

    def execute(self, user_id: str, offset: int = 0, limit: int = 30, requester_id: str = "") -> list[dict]:
        post_ids = self.timeline_repo.get_timeline(user_id, offset, limit)
        if not post_ids:
            return []
        posts = self.post_repo.find_by_ids(post_ids)
        posts = [p for p in posts if not p.is_deleted]

        author_ids = list({p.author_id for p in posts})
        snapshots = self.author_repo.get_batch(author_ids)

        result = []
        for p in posts:
            snap = snapshots.get(p.author_id)
            my_reaction = self.reaction_repo.get_user_reaction(p.id, requester_id) if requester_id else None
            result.append({
                **p.__dict__,
                "author_name": snap.display_name if snap else "",
                "author_avatar": snap.avatar_url if snap else "",
                "my_reaction": my_reaction,
            })
        return result
