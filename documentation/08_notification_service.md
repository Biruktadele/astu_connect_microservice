# Notification Service — API Documentation

**Base path:** `/api/v1/notifications`

> All endpoints require `Authorization: Bearer <token>`

Notifications are created automatically by the system when events occur (a user follows you, someone comments on your post, you receive a reaction, etc.). You cannot create notifications manually via the API.

---

## Endpoints

### GET /api/v1/notifications
List all notifications for the current user.

**Query params:**
- `limit=50` — Max notifications to return
- `offset=0` — Pagination
- `unread_only=false` — Set to `true` to return only unread notifications

**cURL:**
```bash
# All notifications
curl "http://16.171.11.166/api/v1/notifications?limit=20" \
  -H "Authorization: Bearer <token>"

# Only unread notifications
curl "http://16.171.11.166/api/v1/notifications?unread_only=true" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "id": "notif-uuid",
    "type": "follow",
    "title": "New Follower",
    "body": "biruk_tadele started following you",
    "data": {
      "follower_id": "user-uuid",
      "follower_username": "biruk_tadele"
    },
    "is_read": false,
    "created_at": "2026-04-05T10:00:00"
  },
  {
    "id": "notif-uuid-2",
    "type": "comment",
    "title": "New Comment",
    "body": "someone commented on your post",
    "data": {
      "post_id": "post-uuid",
      "commenter_id": "user-uuid-2"
    },
    "is_read": true,
    "created_at": "2026-04-05T09:00:00"
  }
]
```

---

### GET /api/v1/notifications/unread-count
Get the count of unread notifications (for showing a badge in the UI).

**cURL:**
```bash
curl http://16.171.11.166/api/v1/notifications/unread-count \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "unread_count": 7
}
```

---

### POST /api/v1/notifications/{notif_id}/read
Mark a single notification as read.

**cURL:**
```bash
curl -X POST http://16.171.11.166/api/v1/notifications/notif-uuid/read \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{"status": "read"}
```

**Response 404 Not Found:**
```json
{"detail": "Not Found"}
```

---

### POST /api/v1/notifications/read-all
Mark ALL unread notifications as read at once.

**cURL:**
```bash
curl -X POST http://16.171.11.166/api/v1/notifications/read-all \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{"status": "all_read"}
```

---

## Notification Preferences

### GET /api/v1/notifications/preferences
Get the current user's notification preference settings.

**cURL:**
```bash
curl http://16.171.11.166/api/v1/notifications/preferences \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "enabled": true,
  "notify_follows": true,
  "notify_comments": true,
  "notify_reactions": true,
  "notify_chat": true,
  "notify_community": true
}
```

---

### PUT /api/v1/notifications/preferences
Update notification preferences (partial update — only include fields to change).

**Request body (all optional):**
```json
{
  "notify_reactions": false,
  "notify_community": false
}
```

**cURL:**
```bash
# Disable reaction notifications only
curl -X PUT http://16.171.11.166/api/v1/notifications/preferences \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"notify_reactions": false}'

# Disable all notifications
curl -X PUT http://16.171.11.166/api/v1/notifications/preferences \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

**Response 200 OK:**
```json
{"status": "updated"}
```

---

## Notification Types Reference

| Type | When It's Sent |
|---|---|
| `follow` | Someone followed you |
| `comment` | Someone commented on your post |
| `reaction` | Someone reacted to your post |
| `chat` | You received a new chat message |
| `community` | Activity in a community you belong to |
