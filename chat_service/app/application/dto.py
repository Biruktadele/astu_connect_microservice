from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class StartDMDTO(BaseModel):
    other_user_id: str


class CreateGroupDTO(BaseModel):
    name: str
    participant_ids: list[str]


class SendMessageDTO(BaseModel):
    body: str
    media_url: Optional[str] = None
    client_msg_id: str = ""


class ConversationResponse(BaseModel):
    id: str
    type: str
    name: Optional[str]
    participant_ids: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    body: str
    media_url: Optional[str]
    client_msg_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WSIncoming(BaseModel):
    action: str  # send_message | typing | mark_read
    conversation_id: str = ""
    body: str = ""
    media_url: Optional[str] = None
    client_msg_id: str = ""


class WSOutgoing(BaseModel):
    event: str  # new_message | typing | error
    data: dict = {}
