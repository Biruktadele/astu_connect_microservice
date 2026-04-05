# Chat Service — API Documentation

**Base path:** `/api/v1/chat`, WebSocket: `ws://16.171.11.166/ws/chat`

> All HTTP endpoints require `Authorization: Bearer <token>`

---

## Conversations (HTTP)

### POST /api/v1/chat/conversations/dm
Start or retrieve a one-on-one Direct Message conversation with another user.

**Request body:**
```json
{
  "other_user_id": "target-user-uuid"
}
```

**cURL:**
```bash
curl -X POST http://16.171.11.166/api/v1/chat/conversations/dm \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"other_user_id": "target-user-uuid"}'
```

**Response 201 Created:**
```json
{
  "id": "conversation-uuid",
  "type": "dm",
  "participant_ids": ["user-uuid-1", "user-uuid-2"],
  "name": null,
  "created_at": "2026-04-05T10:00:00"
}
```

**Response 400 Bad Request:**
```json
{"detail": "Cannot DM yourself"}
```

---

### POST /api/v1/chat/conversations/group
Create a new group conversation.

**Request body:**
```json
{
  "name": "CS Study Group",
  "participant_ids": ["user-uuid-2", "user-uuid-3", "user-uuid-4"]
}
```

**cURL:**
```bash
curl -X POST http://16.171.11.166/api/v1/chat/conversations/group \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "CS Study Group", "participant_ids": ["user-uuid-2", "user-uuid-3"]}'
```

**Response 201 Created:**
```json
{
  "id": "conversation-uuid",
  "type": "group",
  "participant_ids": ["your-user-uuid", "user-uuid-2", "user-uuid-3"],
  "name": "CS Study Group",
  "created_at": "2026-04-05T10:00:00"
}
```

---

### GET /api/v1/chat/conversations
List all conversations for the current user.

**cURL:**
```bash
curl http://16.171.11.166/api/v1/chat/conversations \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "id": "conversation-uuid",
    "type": "dm",
    "participant_ids": ["user-uuid-1", "user-uuid-2"],
    "name": null,
    "created_at": "2026-04-05T10:00:00"
  }
]
```

---

### POST /api/v1/chat/conversations/{conv_id}/messages
Send a message to a conversation (REST fallback — prefer WebSocket for real-time).

**Request body:**
```json
{
  "body": "Hey! How are you?",
  "media_url": null,
  "client_msg_id": "unique-client-side-id"
}
```

**cURL:**
```bash
curl -X POST http://16.171.11.166/api/v1/chat/conversations/conversation-uuid/messages \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"body": "Hey! How are you?", "client_msg_id": "msg-001"}'
```

**Response 201 Created:**
```json
{
  "id": "message-uuid",
  "conversation_id": "conversation-uuid",
  "sender_id": "user-uuid",
  "body": "Hey! How are you?",
  "media_url": null,
  "client_msg_id": "msg-001",
  "created_at": "2026-04-05T10:00:00"
}
```

---

### GET /api/v1/chat/conversations/{conv_id}/messages
Get message history for a conversation (paginated, newest first).

**Query params:** `limit=50`, `before=<message_id>` (optional, for pagination)

**cURL:**
```bash
curl "http://16.171.11.166/api/v1/chat/conversations/conversation-uuid/messages?limit=20" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "id": "message-uuid",
    "conversation_id": "conversation-uuid",
    "sender_id": "user-uuid",
    "body": "Hey! How are you?",
    "media_url": null,
    "client_msg_id": "msg-001",
    "created_at": "2026-04-05T10:00:00"
  }
]
```

---

## WebSocket — Real-Time Chat

The WebSocket allows real-time bidirectional messaging.

**Connection URL:**
```
ws://16.171.11.166/ws/chat?token=<your_access_token>
```

---

### Action: send_message
Send a message through the WebSocket connection.

**Send (client → server):**
```json
{
  "action": "send_message",
  "conversation_id": "conversation-uuid",
  "body": "Hello in real time!",
  "client_msg_id": "msg-xyz-001",
  "media_url": null
}
```

**Receive back (server → client, acknowledgement):**
```json
{
  "event": "message_ack",
  "data": {
    "message_id": "server-message-uuid",
    "client_msg_id": "msg-xyz-001"
  }
}
```

**Other participants receive (server → other clients):**
```json
{
  "event": "new_message",
  "data": {
    "message_id": "server-message-uuid",
    "conversation_id": "conversation-uuid",
    "sender_id": "your-uuid",
    "body": "Hello in real time!",
    "created_at": "2026-04-05T10:00:00"
  }
}
```

---

### Action: typing
Notify others that you are currently typing.

**Send (client → server):**
```json
{
  "action": "typing",
  "conversation_id": "conversation-uuid"
}
```

**Other participants receive:**
```json
{
  "event": "typing",
  "data": {
    "conversation_id": "conversation-uuid",
    "user_id": "your-uuid"
  }
}
```

---

### Error Response
If any action fails, the server will emit:
```json
{
  "event": "error",
  "data": {"message": "Unknown action: bad_action"}
}
```

**Disconnect code `4001`:** Token is missing or invalid.
