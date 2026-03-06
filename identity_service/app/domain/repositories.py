"""Repository interfaces (ports) — no infrastructure dependencies."""

from abc import ABC, abstractmethod
from typing import Optional
from .entities import User, Follow, Block, RefreshToken


class UserRepository(ABC):
    @abstractmethod
    def save(self, user: User) -> User: ...

    @abstractmethod
    def find_by_id(self, user_id: str) -> Optional[User]: ...

    @abstractmethod
    def find_by_email(self, email: str) -> Optional[User]: ...

    @abstractmethod
    def find_by_username(self, username: str) -> Optional[User]: ...

    @abstractmethod
    def update(self, user: User) -> User: ...


class FollowRepository(ABC):
    @abstractmethod
    def save(self, follow: Follow) -> Follow: ...

    @abstractmethod
    def delete(self, follower_id: str, followee_id: str) -> bool: ...

    @abstractmethod
    def exists(self, follower_id: str, followee_id: str) -> bool: ...

    @abstractmethod
    def get_followers(self, user_id: str, limit: int = 50, offset: int = 0) -> list[User]: ...

    @abstractmethod
    def get_following(self, user_id: str, limit: int = 50, offset: int = 0) -> list[User]: ...

    @abstractmethod
    def get_follower_ids(self, user_id: str) -> list[str]: ...

    @abstractmethod
    def count_followers(self, user_id: str) -> int: ...

    @abstractmethod
    def count_following(self, user_id: str) -> int: ...


class BlockRepository(ABC):
    @abstractmethod
    def save(self, block: Block) -> Block: ...

    @abstractmethod
    def delete(self, blocker_id: str, blocked_id: str) -> bool: ...

    @abstractmethod
    def is_blocked(self, blocker_id: str, blocked_id: str) -> bool: ...

    @abstractmethod
    def get_blocked_ids(self, blocker_id: str) -> list[str]: ...


class RefreshTokenRepository(ABC):
    @abstractmethod
    def save(self, token: RefreshToken) -> RefreshToken: ...

    @abstractmethod
    def find_by_token_hash(self, token_hash: str) -> Optional[RefreshToken]: ...

    @abstractmethod
    def revoke_all_for_user(self, user_id: str) -> None: ...

    @abstractmethod
    def revoke(self, token_id: str) -> None: ...


class EventPublisher(ABC):
    @abstractmethod
    def publish(self, event_type: str, topic: str, partition_key: str, payload: dict) -> None: ...
