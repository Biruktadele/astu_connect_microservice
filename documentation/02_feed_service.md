# Feed Service — API Documentation

**Base path:** `/api/v1/feed`

> All endpoints require `Authorization: Bearer <token>`

---

## Timeline

### GET /api/v1/feed/timeline
Get the personalized timeline for the logged-in user (posts from people they follow).

**Query params:** `limit=30`, `offset=0`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/feed/timeline?limit=30&offset=0" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "posts": [
    {
      "id": "post-uuid",
      "author_id": "user-uuid",
      "author_name": "Biruk Tadele",
      "author_avatar": "https://res.cloudinary.com/.../avatar.jpg",
      "body": "Hello ASTU Connect!",
      "media_refs": ["https://res.cloudinary.com/.../image.jpg"],
      "community_id": null,
      "reaction_counts": {"like": 5, "love": 2},
      "comment_count": 3,
      "moderation_status": "approved",
      "my_reaction": null,
      "created_at": "2026-04-05T10:00:00"
    }
  ],
  "next_cursor": "30"
}
```

---

## Posts

### POST /api/v1/feed/posts
Create a new post.

**Request body:**
```json
{
  "body": "Hello ASTU Connect! This is my first post.",
  "media_refs": ["https://res.cloudinary.com/.../image.jpg"],
  "community_id": null
}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/feed/posts \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"body": "Hello ASTU Connect! This is my first post.", "media_refs": []}'
```

**Response 201 Created:**
```json
{
  "id": "post-uuid",
  "author_id": "user-uuid",
  "author_name": "",
  "author_avatar": "",
  "body": "Hello ASTU Connect! This is my first post.",
  "media_refs": [],
  "community_id": null,
  "reaction_counts": {},
  "comment_count": 0,
  "moderation_status": "approved",
  "my_reaction": null,
  "created_at": "2026-04-05T10:00:00"
}
```

---

### GET /api/v1/feed/posts/{post_id}
Get a single post by ID.

**cURL:**
```bash
curl {{BASE_URL}}/api/v1/feed/posts/post-uuid \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:** Same schema as post object above.

**Response 404 Not Found:**
```json
{"detail": "Post not found"}
```

---

### DELETE /api/v1/feed/posts/{post_id}
Delete a post (only the author can delete their own post).

**cURL:**
```bash
curl -X DELETE {{BASE_URL}}/api/v1/feed/posts/post-uuid \
  -H "Authorization: Bearer <token>"
```

**Response 204 No Content**

**Response 400 Bad Request:**
```json
{"detail": "Not authorized to delete this post"}
```

---

### GET /api/v1/feed/users/{author_id}/posts
Get all posts by a specific user.

**Query params:** `limit=30`, `offset=0`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/feed/users/user-uuid/posts?limit=20" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:** List of post objects.

---

## Comments

### GET /api/v1/feed/posts/{post_id}/comments
Get all comments for a post.

**Query params:** `limit=50`, `offset=0`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/feed/posts/post-uuid/comments?limit=20" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "id": "comment-uuid",
    "post_id": "post-uuid",
    "author_id": "user-uuid",
    "author_name": "John Doe",
    "body": "Great post!",
    "created_at": "2026-04-05T10:05:00"
  }
]
```

---

### POST /api/v1/feed/posts/{post_id}/comments
Add a comment to a post.

**Request body:**
```json
{
  "body": "Great post!"
}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/feed/posts/post-uuid/comments \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"body": "Great post!"}'
```

**Response 201 Created:**
```json
{
  "id": "comment-uuid",
  "post_id": "post-uuid",
  "author_id": "user-uuid",
  "author_name": "",
  "body": "Great post!",
  "created_at": "2026-04-05T10:05:00"
}
```

---

## Reactions

### PUT /api/v1/feed/posts/{post_id}/reactions
Add or change your reaction to a post.

**Request body:**
```json
{
  "type": "like"
}
```

> Valid types: `like`, `love`, `haha`, `wow`, `sad`, `angry`

**cURL:**
```bash
curl -X PUT {{BASE_URL}}/api/v1/feed/posts/post-uuid/reactions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"type": "love"}'
```

**Response 200 OK:**
```json
{
  "post_id": "post-uuid",
  "reaction_counts": {"like": 3, "love": 7}
}
```

---

### DELETE /api/v1/feed/posts/{post_id}/reactions
Remove your reaction from a post.

**cURL:**
```bash
curl -X DELETE {{BASE_URL}}/api/v1/feed/posts/post-uuid/reactions \
  -H "Authorization: Bearer <token>"
```

**Response 204 No Content**
