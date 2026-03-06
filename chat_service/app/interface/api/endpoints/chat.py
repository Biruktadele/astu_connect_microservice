from fastapi import APIRouter, Depends, HTTPException

from ....infrastructure.repositories import (
    CassandraConversationRepository, CassandraMessageRepository, InMemoryEventPublisher,
)
from ....application.use_cases import StartDMUseCase, CreateGroupUseCase, SendMessageUseCase, GetHistoryUseCase
from ....application.dto import (
    StartDMDTO, CreateGroupDTO, SendMessageDTO,
    ConversationResponse, MessageResponse,
)
from ....infrastructure.messaging import publish_event
from ..deps import get_current_user_id

router = APIRouter(tags=["chat"])


@router.post("/chat/conversations/dm", response_model=ConversationResponse, status_code=201)
def start_dm(dto: StartDMDTO, user_id: str = Depends(get_current_user_id)):
    uc = StartDMUseCase(CassandraConversationRepository())
    try:
        conv = uc.execute(user_id, dto.other_user_id)
        return ConversationResponse(**conv.__dict__)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/chat/conversations/group", response_model=ConversationResponse, status_code=201)
def create_group(dto: CreateGroupDTO, user_id: str = Depends(get_current_user_id)):
    uc = CreateGroupUseCase(CassandraConversationRepository())
    conv = uc.execute(user_id, dto.name, dto.participant_ids)
    return ConversationResponse(**conv.__dict__)


@router.get("/chat/conversations", response_model=list[ConversationResponse])
def list_conversations(user_id: str = Depends(get_current_user_id)):
    repo = CassandraConversationRepository()
    convs = repo.get_user_conversations(user_id)
    return [ConversationResponse(**c.__dict__) for c in convs]


@router.post("/chat/conversations/{conv_id}/messages", response_model=MessageResponse, status_code=201)
async def send_message(conv_id: str, dto: SendMessageDTO, user_id: str = Depends(get_current_user_id)):
    event_pub = InMemoryEventPublisher()
    uc = SendMessageUseCase(CassandraMessageRepository(), CassandraConversationRepository(), event_pub)
    try:
        msg = uc.execute(conv_id, user_id, dto.body, dto.media_url, dto.client_msg_id)
        for evt in event_pub.events:
            await publish_event(evt["event_type"], evt["topic"], evt["partition_key"], evt["payload"])
        return MessageResponse(**msg.__dict__)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/chat/conversations/{conv_id}/messages", response_model=list[MessageResponse])
def get_history(conv_id: str, before: str = None, limit: int = 50, user_id: str = Depends(get_current_user_id)):
    uc = GetHistoryUseCase(CassandraMessageRepository(), CassandraConversationRepository())
    try:
        msgs = uc.execute(conv_id, user_id, before, limit)
        return [MessageResponse(**m.__dict__) for m in msgs]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
