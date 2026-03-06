from abc import ABC, abstractmethod
from typing import Optional
from .entities import Conversation, Message, ReadReceipt


class ConversationRepository(ABC):
    @abstractmethod
    def create(self, conversation: Conversation) -> Conversation: ...

    @abstractmethod
    def find_by_id(self, conv_id: str) -> Optional[Conversation]: ...

    @abstractmethod
    def find_dm(self, user_a: str, user_b: str) -> Optional[Conversation]: ...

    @abstractmethod
    def get_user_conversations(self, user_id: str) -> list[Conversation]: ...

    @abstractmethod
    def add_participant(self, conv_id: str, user_id: str) -> None: ...


class MessageRepository(ABC):
    @abstractmethod
    def save(self, message: Message) -> Message: ...

    @abstractmethod
    def find_by_conversation(self, conv_id: str, before: Optional[str] = None, limit: int = 50) -> list[Message]: ...

    @abstractmethod
    def exists_by_client_id(self, client_msg_id: str) -> bool: ...


class PresenceRepository(ABC):
    @abstractmethod
    def set_online(self, user_id: str, pod_id: str) -> None: ...

    @abstractmethod
    def set_offline(self, user_id: str) -> None: ...

    @abstractmethod
    def is_online(self, user_id: str) -> bool: ...

    @abstractmethod
    def get_pod(self, user_id: str) -> Optional[str]: ...


class EventPublisher(ABC):
    @abstractmethod
    def publish(self, event_type: str, topic: str, partition_key: str, payload: dict) -> None: ...
