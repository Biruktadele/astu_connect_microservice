# Astu Connect Microservice API Documentation

## Overview

Astu Connect is a microservices-based social platform built with FastAPI. The system consists of multiple services communicating through an API Gateway that handles routing, authentication, and rate limiting.

**Base URL**: `http://localhost:80/api/v1`

**Architecture**:
- **API Gateway** (Port 8000): Routes requests to backend services
- **Identity Service** (Port 8001): Authentication and user management
- **Feed Service** (Port 8002): Posts, comments, reactions, timeline
- **Chat Service** (Port 8003): Direct messages and group chats
- **Community Service** (Port 8004): Community management
- **Notification Service** (Port 8005): User notifications
- **Media Service** (Port 8006): File uploads and media management
- **Search Service** (Port 8007): Content search functionality
- **Gamification Service** (Port 8008): Points and achievements

## Authentication

The API uses JWT Bearer tokens for authentication. Include the token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

### Public Endpoints (No Authentication Required)
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/resend-verification`
- `POST /api/v1/auth/verify-email`
- `POST /api/v1/auth/forgot-password`
- `POST /api/v1/auth/reset-password`

## Rate Limiting

- **Auth endpoints**: 10 requests per minute per IP
- **Other endpoints**: 100 requests per minute per authenticated user

---

## 1. Authentication Service

### 1.1 User Registration

**Endpoint**: `POST /api/v1/auth/register`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john_doe",
    "email": "john@example.com",
    "password": "SecurePass123!"
  }'
```

**Success Response (201)**:
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "is_active": true
}
```

**Error Responses**:
- `400`: User with this email already exists
```json
{
  "detail": "The user with this email already exists in the system."
}
```

### 1.2 User Login

**Endpoint**: `POST /api/v1/auth/login`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe&password=SecurePass123!"
```

**Success Response (200)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Error Responses**:
- `401`: Invalid credentials
```jsonPOST /api/v1/auth/register
{
  "detail": "Incorrect username or password",
  "headers": {
    "WWW-Authenticate": "Bearer"
  }
}
```

### 1.3 Get Current User Profile

**Endpoint**: `GET /api/v1/users/me`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/users/me" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "is_active": true
}
```

**Error Responses**:
- `401`: Authentication required
```json
{
  "detail": "Authentication required"
}
```

### 1.4 Deactivate User Account

**Endpoint**: `DELETE /api/v1/users/me`

**Request**:
```bash
curl -X DELETE "http://localhost:80/api/v1/users/me" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "is_active": false
}
```

---

## 2. Feed Service

### 2.1 Get User Timeline

**Endpoint**: `GET /api/v1/feed/timeline`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/feed/timeline?limit=10&offset=0" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "posts": [
    {
      "id": "post_123",
      "author_id": "user_456",
      "author_name": "Jane Doe",
      "author_avatar": "https://example.com/avatar.jpg",
      "community_id": null,
      "body": "Hello world! This is my first post.",
      "media_refs": [],
      "reaction_counts": {
        "like": 5,
        "love": 2POST /api/v1/auth/register
      },
      "my_reaction": "like",
      "comment_count": 3,
      "moderation_status": "approved",
      "created_at": "2024-01-15T10:30:00Z",
      "is_saved": false
    }
  ],
  "next_cursor": "10"
}
```

**Error Responses**:
- `401`: Authentication required
- `429`: Rate limit exceeded

### 2.2 Create Post

**Endpoint**: `POST /api/v1/feed/posts`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/feed/posts" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "body": "This is a new post with #hashtags",
    "media_refs": ["media_789"],
    "community_id": "community_123"
  }'
```

**Success Response (201)**:
```json
{
  "id": "post_456",
  "author_id": "user_789",
  "author_name": "John Doe",
  "author_avatar": "",
  "community_id": "community_123",
  "body": "This is a new post with #hashtags",
  "media_refs": ["media_789"],
  "reaction_counts": {},
  "my_reaction": null,
  "comment_count": 0,
  "moderation_status": "approved",
  "created_at": "2024-01-15T11:00:00Z",
  "is_saved": false
}
```

**Error Responses**:
- `400`: Invalid request data
- `401`: Authentication required
- `403`: Community access denied

### 2.3 Add Comment to Post

**Endpoint**: `POST /api/v1/feed/posts/{post_id}/comments`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/feed/posts/post_123/comments" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "body": "Great post! Thanks for sharing."
  }'
```

**Success Response (201)**:
```json
{
  "id": "comment_789",
  "post_id": "post_123",
  "author_id": "user_456",
  "author_name": "John Doe",
  "author_avatar": "",
  "body": "Great post! Thanks for sharing.",
  "created_at": "2024-01-15T11:15:00Z"
}
```

**Error Responses**:
- `400`: Invalid comment data
- `404`: Post not found
- `403`: Cannot comment on post

### 2.4 React to Post

**Endpoint**: `POST /api/v1/feed/posts/{post_id}/reactions`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/feed/posts/post_123/reactions" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "love"
  }'
```

**Success Response (200)**:
```json
{
  "success": true,
  "reaction_type": "love"
}
```

**Error Responses**:
- `400`: Invalid reaction type (must be: like, love, laugh, sad, angry)
- `404`: Post not found

### 2.5 Save/Unsave Post

**Endpoint**: `POST /api/v1/feed/posts/{post_id}/save`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/feed/posts/post_123/save" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "success": true,
  "is_saved": true
}
```

**Error Responses**:
- `404`: Post not found

### 2.6 Get Saved Posts

**Endpoint**: `GET /api/v1/feed/saved`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/feed/saved?limit=10&offset=0" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "posts": [
    {
      "id": "post_123",
      "author_id": "user_456",
      "author_name": "Jane Doe",
      "body": "Saved post content...",
      "created_at": "2024-01-15T10:30:00Z",
      "is_saved": true
    }
  ],
  "next_cursor": "10"
}
```

---

## 3. Chat Service

### 3.1 Start Direct Message Conversation

**Endpoint**: `POST /api/v1/chat/conversations/dm`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/chat/conversations/dm" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "other_user_id": "user_456"
  }'
```

**Success Response (201)**:
```json
{
  "id": "conv_123",
  "type": "dm",
  "name": null,
  "participant_ids": ["user_789", "user_456"],
  "created_at": "2024-01-15T12:00:00Z"
}
```

**Error Responses**:
- `400`: Cannot start conversation with yourself
- `404`: Other user not found

### 3.2 Create Group Chat

**Endpoint**: `POST /api/v1/chat/conversations/group`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/chat/conversations/group" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Study Group",
    "participant_ids": ["user_456", "user_789", "user_012"]
  }'
```

**Success Response (201)**:
```json
{
  "id": "conv_456",
  "type": "group",
  "name": "Study Group",
  "participant_ids": ["user_789", "user_456", "user_789", "user_012"],
  "created_at": "2024-01-15T12:30:00Z"
}
```

**Error Responses**:
- `400`: Invalid participant list

### 3.3 List User Conversations

**Endpoint**: `GET /api/v1/chat/conversations`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/chat/conversations" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
[
  {
    "id": "conv_123",
    "type": "dm",
    "name": null,
    "participant_ids": ["user_789", "user_456"],
    "created_at": "2024-01-15T12:00:00Z"
  },
  {
    "id": "conv_456",
    "type": "group",
    "name": "Study Group",
    "participant_ids": ["user_789", "user_456", "user_012"],
    "created_at": "2024-01-15T12:30:00Z"
  }
]
```

### 3.4 Send Message

**Endpoint**: `POST /api/v1/chat/conversations/{conversation_id}/messages`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/chat/conversations/conv_123/messages" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "body": "Hey! How are you doing?",
    "media_url": null,
    "client_msg_id": "msg_client_123"
  }'
```

**Success Response (201)**:
```json
{
  "id": "msg_789",
  "conversation_id": "conv_123",
  "sender_id": "user_789",
  "body": "Hey! How are you doing?",
  "media_url": null,
  "client_msg_id": "msg_client_123",
  "created_at": "2024-01-15T13:00:00Z"
}
```

**Error Responses**:
- `404`: Conversation not found
- `403`: Not a participant in conversation

### 3.5 Get Conversation History

**Endpoint**: `GET /api/v1/chat/conversations/{conversation_id}/messages`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/chat/conversations/conv_123/messages?limit=50&before=msg_123" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "messages": [
    {
      "id": "msg_456",
      "conversation_id": "conv_123",
      "sender_id": "user_456",
      "body": "I'm doing great, thanks!",
      "media_url": null,
      "client_msg_id": "",
      "created_at": "2024-01-15T13:05:00Z"
    }
  ],
  "next_cursor": "msg_456"
}
```

**Error Responses**:
- `404`: Conversation not found
- `403`: Not a participant in conversation

---

## 4. Community Service

### 4.1 List Communities

**Endpoint**: `GET /api/v1/communities`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/communities?q=technology&limit=20&offset=0" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
[
  {
    "id": "comm_123",
    "name": "Tech Enthusiasts",
    "description": "A community for technology lovers",
    "creator_id": "user_456",
    "member_count": 150,
    "is_private": false,
    "created_at": "2024-01-01T00:00:00Z",
    "is_member": true,
    "my_role": "member"
  }
]
```

### 4.2 Create Community

**Endpoint**: `POST /api/v1/communities`

**Required Fields**:
- `name`: Community name (string)
- `slug`: URL-friendly slug (string, must be unique)
- `description`: Community description (string, optional, default: "")
- `avatar_url`: Avatar image URL (string, optional, default: "")
- `visibility`: Visibility level (string, optional, default: "public", values: "public", "private")

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/communities" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Computer Science Students",
    "slug": "cs-students",
    "description": "A community for CS students to share knowledge",
    "avatar_url": "",
    "visibility": "public"
  }'
```

**Success Response (201)**:
```json
{
  "id": "comm_456",
  "name": "Computer Science Students",
  "slug": "cs-students",
  "description": "A community for CS students to share knowledge",
  "avatar_url": "",
  "visibility": "public",
  "owner_id": "user_789",
  "member_count": 1,
  "created_at": "2024-01-15T14:00:00Z",
  "is_member": true,
  "my_role": "owner"
}
```

**Error Responses**:
- `400`: Invalid community data or slug already taken
```json
{
  "detail": "Slug already taken"
}
```

### 4.3 Join Community

**Endpoint**: `POST /api/v1/communities/{community_id}/join`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/communities/comm_123/join" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "success": true,
  "role": "member"
}
```

**Error Responses**:
- `404`: Community not found
- `403`: Cannot join private community
- `409`: Already a member

### 4.4 Leave Community

**Endpoint**: `POST /api/v1/communities/{community_id}/leave`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/communities/comm_123/leave" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "success": true
}
```

**Error Responses**:
- `404`: Community not found
- `400`: Not a member of community

### 4.5 Set Member Role

**Endpoint**: `PUT /api/v1/communities/{community_id}/members/{user_id}/role`

**Request**:
```bash
curl -X PUT "http://localhost:80/api/v1/communities/comm_123/members/user_456/role" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "moderator"
  }'
```

**Success Response (200)**:
```json
{
  "success": true,
  "role": "moderator"
}
```

**Error Responses**:
- `403`: Only admins can change roles
- `404`: Community or user not found
- `400`: Invalid role (must be: admin, moderator, member)

---

## 5. Notification Service

### 5.1 List Notifications

**Endpoint**: `GET /api/v1/notifications`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/notifications?limit=20&offset=0&unreadOnly=false" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
[
  {
    "id": "notif_123",
    "type": "new_follower",
    "title": "New Follower",
    "body": "Jane Doe started following you",
    "data": {
      "follower_id": "user_456",
      "follower_name": "Jane Doe"
    },
    "is_read": false,
    "created_at": "2024-01-15T15:00:00Z"
  },
  {
    "id": "notif_456",
    "type": "post_like",
    "title": "Post Liked",
    "body": "John Smith liked your post",
    "data": {
      "post_id": "post_789",
      "liker_name": "John Smith"
    },
    "is_read": true,
    "created_at": "2024-01-15T14:30:00Z"
  }
]
```

### 5.2 Get Unread Count

**Endpoint**: `GET /api/v1/notifications/unread-count`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/notifications/unread-count" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "count": 5
}
```

### 5.3 Mark Notification as Read

**Endpoint**: `POST /api/v1/notifications/{notification_id}/read`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/notifications/notif_123/read" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "success": true
}
```

**Error Responses**:
- `404`: Notification not found
- `403`: Notification does not belong to user

### 5.4 Mark All Notifications as Read

**Endpoint**: `POST /api/v1/notifications/read-all`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/notifications/read-all" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "success": true,
  "marked_count": 10
}
```

### 5.5 Update Notification Preferences

**Endpoint**: `PUT /api/v1/notifications/preferences`

**Request**:
```bash
curl -X PUT "http://localhost:80/api/v1/notifications/preferences" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "notify_follows": true,
    "notify_comments": true,
    "notify_reactions": false,
    "notify_chat": true,
    "notify_community": true
  }'
```

**Success Response (200)**:
```json
{
  "enabled": true,
  "notify_follows": true,
  "notify_comments": true,
  "notify_reactions": false,
  "notify_chat": true,
  "notify_community": true
}
```

---

## 6. Media Service

### 6.1 Upload File

**Endpoint**: `POST /api/v1/media/upload`

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/media/upload" \
  -H "Authorization: Bearer <your_jwt_token>" \
  -F "file=@/path/to/your/image.jpg" \
  -F "type=image"
```

**Success Response (201)**:
```json
{
  "id": "media_123",
  "url": "https://cdn.example.com/media/image_123.jpg",
  "type": "image",
  "size": 1024000,
  "mime_type": "image/jpeg",
  "uploaded_by": "user_789",
  "created_at": "2024-01-15T16:00:00Z"
}
```

**Error Responses**:
- `400`: Invalid file type or size
- `413`: File too large
- `415`: Unsupported media type

### 6.2 Get Media Info

**Endpoint**: `GET /api/v1/media/{media_id}`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/media/media_123" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "id": "media_123",
  "url": "https://cdn.example.com/media/image_123.jpg",
  "type": "image",
  "size": 1024000,
  "mime_type": "image/jpeg",
  "uploaded_by": "user_789",
  "created_at": "2024-01-15T16:00:00Z"
}
```

**Error Responses**:
- `404`: Media not found

### 6.3 Delete Media

**Endpoint**: `DELETE /api/v1/media/{media_id}`

**Request**:
```bash
curl -X DELETE "http://localhost:80/api/v1/media/media_123" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "success": true
}
```

**Error Responses**:
- `404`: Media not found
- `403`: Not authorized to delete this media

---

## 7. Search Service

### 7.1 Search Content

**Endpoint**: `GET /api/v1/search`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/search?q=technology&type=all&limit=20&offset=0" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "results": [
    {
      "id": "post_123",
      "type": "post",
      "title": null,
      "content": "Latest technology trends in 2024...",
      "author_id": "user_456",
      "author_name": "Tech Expert",
      "created_at": "2024-01-15T10:00:00Z",
      "score": 0.95
    },
    {
      "id": "comm_456",
      "type": "community",
      "title": "Technology Discussion",
      "content": "A community for tech enthusiasts...",
      "member_count": 500,
      "created_at": "2024-01-01T00:00:00Z",
      "score": 0.87
    }
  ],
  "total": 150,
  "next_cursor": "20"
}
```

**Query Parameters**:
- `q` (required): Search query string
- `type` (optional): Filter by type (all, posts, users, communities)
- `limit` (optional): Number of results (default: 20, max: 100)
- `offset` (optional): Pagination offset

**Error Responses**:
- `400`: Invalid search query
- `401`: Authentication required

---

## 8. Gamification Service

### 8.1 Get User Profile

**Endpoint**: `GET /api/v1/gamification/profile`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/gamification/profile" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "user_id": "user_789",
  "total_points": 1250,
  "level": 5,
  "badges": [
    {
      "id": "badge_123",
      "name": "First Post",
      "description": "Created your first post",
      "icon_url": "https://cdn.example.com/badges/first_post.png",
      "earned_at": "2024-01-10T10:00:00Z"
    },
    {
      "id": "badge_456",
      "name": "Social Butterfly",
      "description": "Made 100 connections",
      "icon_url": "https://cdn.example.com/badges/social.png",
      "earned_at": "2024-01-12T15:30:00Z"
    }
  ],
  "achievements": [
    {
      "id": "achieve_123",
      "name": "Post Master",
      "description": "Created 50 posts",
      "progress": 50,
      "target": 50,
      "completed": true,
      "completed_at": "2024-01-14T09:00:00Z"
    }
  ],
  "leaderboard_rank": 25
}
```

### 8.2 Get Leaderboard

**Endpoint**: `GET /api/v1/gamification/leaderboard`

**Request**:
```bash
curl -X GET "http://localhost:80/api/v1/gamification/leaderboard?type=points&limit=50&offset=0" \
  -H "Authorization: Bearer <your_jwt_token>"
```

**Success Response (200)**:
```json
{
  "entries": [
    {
      "rank": 1,
      "user_id": "user_123",
      "username": "TopUser",
      "avatar_url": "https://cdn.example.com/avatars/user_123.jpg",
      "score": 5000,
      "level": 10
    },
    {
      "rank": 2,
      "user_id": "user_456",
      "username": "ActiveUser",
      "avatar_url": "https://cdn.example.com/avatars/user_456.jpg",
      "score": 4500,
      "level": 9
    }
  ],
  "total_users": 1000,
  "my_rank": 25
}
```

**Query Parameters**:
- `type` (optional): Leaderboard type (points, level, posts)
- `limit` (optional): Number of entries (default: 50, max: 100)
- `offset` (optional): Pagination offset

### 8.3 Award Points

**Endpoint**: `POST /api/v1/gamification/points` (Admin only)

**Request**:
```bash
curl -X POST "http://localhost:80/api/v1/gamification/points" \
  -H "Authorization: Bearer <admin_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_789",
    "points": 100,
    "reason": "Quality contribution",
    "type": "bonus"
  }'
```

**Success Response (201)**:
```json
{
  "success": true,
  "points_awarded": 100,
  "new_total": 1350,
  "level_up": false
}
```

**Error Responses**:
- `403`: Admin access required
- `404`: User not found

---

## Common Error Responses

### Authentication Errors

**401 Unauthorized**:
```json
{
  "detail": "Authentication required"
}
```

**403 Forbidden**:
```json
{
  "detail": "Admin access required"
}
```

### Rate Limiting

**429 Too Many Requests**:
```json
{
  "detail": "Rate limit exceeded",
  "headers": {
    "Retry-After": "60"
  }
}
```

### Validation Errors

**422 Unprocessable Entity**:
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Server Errors

**500 Internal Server Error**:
```json
{
  "detail": "Internal server error"
}
```

**503 Service Unavailable**:
```json
{
  "detail": "Service unavailable"
}
```

**504 Gateway Timeout**:
```json
{
  "detail": "Service timeout"
}
```

---

## WebSocket Endpoints

### Chat WebSocket

**Endpoint**: `ws://localhost:80/api/v1/chat/ws`

**Connection**:
```bash
wscat -c "ws://localhost:80/api/v1/chat/ws?token=<your_jwt_token>"
```

**Message Format**:
```json
{
  "action": "send_message",
  "conversation_id": "conv_123",
  "body": "Hello via WebSocket!",
  "media_url": null,
  "client_msg_id": "ws_msg_123"
}
```

**Response Format**:
```json
{
  "type": "message",
  "data": {
    "id": "msg_789",
    "conversation_id": "conv_123",
    "sender_id": "user_456",
    "body": "Hello via WebSocket!",
    "created_at": "2024-01-15T17:00:00Z"
  }
}
```

**WebSocket Actions**:
- `send_message`: Send a chat message
- `typing`: Send typing indicator
- `mark_read`: Mark messages as read

---

## Health Check Endpoints

All services provide health check endpoints:

**Liveness**: `GET /health/live`
```json
{
  "status": "ok"
}
```

**Readiness**: `GET /health/ready`
```json
{
  "status": "ok"
}
```

---

## Testing with curl

### Setup Environment Variables

```bash
export API_BASE="http://localhost:80/api/v1"
export JWT_TOKEN="<your_jwt_token>"
export ADMIN_TOKEN="<admin_jwt_token>"
```

### Quick Test Script

```bash
#!/bin/bash

# Test authentication
echo "Testing login..."
LOGIN_RESPONSE=$(curl -s -X POST "${API_BASE}/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test_user&password=test_pass")

echo "Login response: ${LOGIN_RESPONSE}"

# Extract token (requires jq)
TOKEN=$(echo ${LOGIN_RESPONSE} | jq -r '.access_token')

# Test getting user profile
echo "Testing user profile..."
curl -s -X GET "${API_BASE}/users/me" \
  -H "Authorization: Bearer ${TOKEN}"

# Test creating a post
echo "Testing post creation..."
curl -s -X POST "${API_BASE}/feed/posts" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"body": "Test post from curl"}'

echo "Tests completed!"
```

---

## Notes

1. **Authentication**: All endpoints (except public auth endpoints) require a valid JWT token
2. **Rate Limiting**: Be mindful of rate limits when testing
3. **Pagination**: Most list endpoints support `limit` and `offset` parameters
4. **Error Handling**: Always check HTTP status codes and response bodies
5. **Media Uploads**: Use multipart/form-data for file uploads
6. **WebSocket**: Real-time chat functionality available via WebSocket
7. **Admin Endpoints**: Some endpoints require admin privileges
8. **CORS**: The API Gateway handles CORS headers for cross-origin requests

For more detailed information about specific services or advanced features, refer to the individual service documentation or contact the development team.
