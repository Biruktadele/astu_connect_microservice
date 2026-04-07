from abc import ABC, abstractmethod
from typing import Optional
from .entities import Post, Comment, Reaction, AuthorSnapshot


class PostRepository(ABC):
    @abstractmethod
    def save(self, post: Post) -> Post: ...

    @abstractmethod
    def find_by_id(self, post_id: str) -> Optional[Post]: ...

    @abstractmethod
    def soft_delete(self, post_id: str) -> bool: ...

    @abstractmethod
    def find_by_author(self, author_id: str, limit: int, offset: int) -> list[Post]: ...

    @abstractmethod
    def find_by_ids(self, post_ids: list[str]) -> list[Post]: ...

    @abstractmethod
    def increment_comment_count(self, post_id: str) -> None: ...

    @abstractmethod
    def update_reaction_counts(self, post_id: str, counts: dict) -> None: ...


class CommentRepository(ABC):
    @abstractmethod
    def save(self, comment: Comment) -> Comment: ...

    @abstractmethod
    def find_by_post(self, post_id: str, limit: int, offset: int) -> list[Comment]: ...

    @abstractmethod
    def delete(self, comment_id: str) -> bool: ...


class ReactionRepository(ABC):
    @abstractmethod
    def upsert(self, reaction: Reaction) -> Reaction: ...

    @abstractmethod
    def delete(self, post_id: str, user_id: str) -> bool: ...

    @abstractmethod
    def get_counts(self, post_id: str) -> dict: ...

    @abstractmethod
    def get_user_reaction(self, post_id: str, user_id: str) -> Optional[str]: ...


class TimelineRepository(ABC):
    @abstractmethod
    def push(self, user_id: str, post_id: str, score: float) -> None: ...

    @abstractmethod
    def get_timeline(self, user_id: str, offset: int, limit: int) -> list[str]: ...

    @abstractmethod
    def remove(self, user_id: str, post_id: str) -> None: ...

    @abstractmethod
    def trim(self, user_id: str, max_size: int) -> None: ...

    @abstractmethod
    def push_recent(self, post_id: str, score: float) -> None: ...

    @abstractmethod
    def get_recent(self, offset: int, limit: int) -> list[str]: ...

    @abstractmethod
    def push_recommended(self, post_id: str, score: float) -> None: ...

    @abstractmethod
    def get_recommended(self, offset: int, limit: int) -> list[str]: ...

    @abstractmethod
    def update_score_recommended(self, post_id: str, score: float) -> None: ...


class AuthorSnapshotRepository(ABC):
    @abstractmethod
    def upsert(self, snapshot: AuthorSnapshot) -> None: ...

    @abstractmethod
    def get(self, user_id: str) -> Optional[AuthorSnapshot]: ...

    @abstractmethod
    def get_batch(self, user_ids: list[str]) -> dict[str, AuthorSnapshot]: ...


class EventPublisher(ABC):
    @abstractmethod
    def publish(self, event_type: str, topic: str, partition_key: str, payload: dict) -> None: ...
class SavedPostRepository(ABC):
    @abstractmethod
    def save(self, user_id: str, post_id: str) -> None: ...

    @abstractmethod
    def delete(self, user_id: str, post_id: str) -> None: ...

    @abstractmethod
    def is_saved(self, user_id: str, post_id: str) -> bool: ...

    @abstractmethod
    def find_by_user(self, user_id: str, limit: int, offset: int) -> list[str]: ...
