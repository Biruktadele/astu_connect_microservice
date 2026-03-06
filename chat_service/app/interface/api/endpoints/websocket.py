"""WebSocket endpoint for real-time chat."""

import json
import logging
import os
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ....infrastructure.repositories import (
    CassandraConversationRepository, CassandraMessageRepository,
    RedisPresenceRepository, InMemoryEventPublisher,
)
from ....application.use_cases import SendMessageUseCase
from ....infrastructure.messaging import publish_event
from ..deps import get_ws_user_id

router = APIRouter()
logger = logging.getLogger(__name__)

POD_ID = os.getenv("HOSTNAME", "chat-pod-1")

active_connections: dict[str, WebSocket] = {}


@router.websocket("/ws/chat")
async def chat_ws(ws: WebSocket, token: str = ""):
    user_id = get_ws_user_id(token)
    if not user_id:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    active_connections[user_id] = ws
    presence = RedisPresenceRepository()
    presence.set_online(user_id, POD_ID)
    logger.info("User %s connected to WS", user_id)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                action = data.get("action", "")

                if action == "send_message":
                    await _handle_send(ws, user_id, data)
                elif action == "typing":
                    await _handle_typing(user_id, data)
                elif action == "mark_read":
                    pass
                else:
                    await ws.send_json({"event": "error", "data": {"message": f"Unknown action: {action}"}})
            except json.JSONDecodeError:
                await ws.send_json({"event": "error", "data": {"message": "Invalid JSON"}})
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.pop(user_id, None)
        presence.set_offline(user_id)
        logger.info("User %s disconnected from WS", user_id)


async def _handle_send(ws: WebSocket, user_id: str, data: dict):
    conv_id = data.get("conversation_id", "")
    body = data.get("body", "")
    client_msg_id = data.get("client_msg_id", "")
    media_url = data.get("media_url")

    event_pub = InMemoryEventPublisher()
    uc = SendMessageUseCase(CassandraMessageRepository(), CassandraConversationRepository(), event_pub)
    try:
        msg = uc.execute(conv_id, user_id, body, media_url, client_msg_id)

        await ws.send_json({
            "event": "message_ack",
            "data": {"message_id": msg.id, "client_msg_id": client_msg_id},
        })

        conv = CassandraConversationRepository().find_by_id(conv_id)
        if conv:
            outgoing = {
                "event": "new_message",
                "data": {
                    "message_id": msg.id, "conversation_id": conv_id,
                    "sender_id": user_id, "body": body,
                    "created_at": msg.created_at.isoformat(),
                },
            }
            for pid in conv.participant_ids:
                if pid != user_id and pid in active_connections:
                    try:
                        await active_connections[pid].send_json(outgoing)
                    except Exception:
                        pass

        for evt in event_pub.events:
            await publish_event(evt["event_type"], evt["topic"], evt["partition_key"], evt["payload"])

    except ValueError as e:
        await ws.send_json({"event": "error", "data": {"message": str(e)}})


async def _handle_typing(user_id: str, data: dict):
    conv_id = data.get("conversation_id", "")
    conv = CassandraConversationRepository().find_by_id(conv_id)
    if conv:
        outgoing = {"event": "typing", "data": {"conversation_id": conv_id, "user_id": user_id}}
        for pid in conv.participant_ids:
            if pid != user_id and pid in active_connections:
                try:
                    await active_connections[pid].send_json(outgoing)
                except Exception:
                    pass
