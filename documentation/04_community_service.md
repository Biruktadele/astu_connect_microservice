# Community Service — API Documentation

**Base path:** `/api/v1/communities`

> All endpoints require `Authorization: Bearer <token>`

---

## Communities

### GET /api/v1/communities
List all communities (optionally search by name).

**Query params:** `q=` (search), `limit=20`, `offset=0`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/communities?q=robotics&limit=10" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "id": "community-uuid",
    "name": "ASTU Robotics Club",
    "slug": "astu-robotics",
    "description": "Robotics enthusiasts at ASTU",
    "avatar_url": "https://res.cloudinary.com/.../logo.jpg",
    "visibility": "public",
    "owner_id": "user-uuid",
    "member_count": 87,
    "is_archived": false,
    "is_member": false,
    "my_role": null,
    "created_at": "2026-01-01T00:00:00"
  }
]
```

---

### POST /api/v1/communities
Create a new community.

**Request body:**
```json
{
  "name": "ASTU Robotics Club",
  "slug": "astu-robotics",
  "description": "For all robotics enthusiasts at ASTU",
  "visibility": "public",
  "avatar_url": "https://res.cloudinary.com/.../logo.jpg"
}
```

> `visibility` can be `"public"` or `"private"`.

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/communities \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "ASTU Robotics Club", "slug": "astu-robotics", "description": "For all robotics enthusiasts at ASTU", "visibility": "public"}'
```

**Response 201 Created:**
```json
{
  "id": "community-uuid",
  "name": "ASTU Robotics Club",
  "slug": "astu-robotics",
  "description": "For all robotics enthusiasts at ASTU",
  "avatar_url": "",
  "visibility": "public",
  "owner_id": "your-user-uuid",
  "member_count": 1,
  "is_archived": false,
  "is_member": true,
  "my_role": "owner",
  "created_at": "2026-04-05T10:00:00"
}
```

---

### GET /api/v1/communities/{community_id}
Get a single community by ID.

**cURL:**
```bash
curl {{BASE_URL}}/api/v1/communities/community-uuid \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:** Same schema as community object above.

**Response 404 Not Found:**
```json
{"detail": "Community not found"}
```

---

### PATCH /api/v1/communities/{community_id}
Update a community (only owners or admins of the community can do this).

**Request body (all optional):**
```json
{
  "name": "Updated Club Name",
  "description": "Updated description",
  "avatar_url": "https://...",
  "visibility": "private"
}
```

**cURL:**
```bash
curl -X PATCH {{BASE_URL}}/api/v1/communities/community-uuid \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated description"}'
```

**Response 200 OK:** Updated community object.

**Response 403 Forbidden:**
```json
{"detail": "Not authorized"}
```

---

### POST /api/v1/communities/{community_id}/join
Join a community.

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/communities/community-uuid/join \
  -H "Authorization: Bearer <token>"
```

**Response 201 Created:**
```json
{"status": "joined"}
```

---

### POST /api/v1/communities/{community_id}/leave
Leave a community.

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/communities/community-uuid/leave \
  -H "Authorization: Bearer <token>"
```

**Response 204 No Content**

---

## Community Members

### GET /api/v1/communities/{community_id}/members
List all members of a community.

**Query params:** `limit=50`, `offset=0`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/communities/community-uuid/members?limit=20" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "user_id": "user-uuid",
    "role": "member",
    "joined_at": "2026-04-01T08:00:00"
  }
]
```

---

### PUT /api/v1/communities/{community_id}/members/{target_id}/role
Change a member's role (only owners and admins can do this).

**Request body:**
```json
{
  "role": "admin"
}
```

> Valid roles: `"member"`, `"admin"`, `"owner"`

**cURL:**
```bash
curl -X PUT {{BASE_URL}}/api/v1/communities/community-uuid/members/user-uuid/role \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin"}'
```

**Response 200 OK:**
```json
{"status": "role_updated"}
```

---

## Community Posts

### GET /api/v1/communities/{community_id}/posts
List posts within a community.

**Query params:** `limit=30`, `offset=0`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/communities/community-uuid/posts?limit=10" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "id": "post-uuid",
    "community_id": "community-uuid",
    "author_id": "user-uuid",
    "title": "Welcome to our community!",
    "body": "Happy to have everyone here.",
    "is_pinned": false,
    "moderation_status": "approved",
    "created_at": "2026-04-05T10:00:00"
  }
]
```

---

### POST /api/v1/communities/{community_id}/posts
Create a post inside a community (you must be a member).

**Request body:**
```json
{
  "title": "Event Announcement",
  "body": "We are hosting a hackathon next week!"
}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/communities/community-uuid/posts \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "Event Announcement", "body": "Hackathon next week!"}'
```

**Response 201 Created:** Community post object.

---

### DELETE /api/v1/communities/{community_id}/posts/{post_id}
Delete a community post (owner/admin can delete any post; members can only delete their own).

**cURL:**
```bash
curl -X DELETE {{BASE_URL}}/api/v1/communities/community-uuid/posts/post-uuid \
  -H "Authorization: Bearer <token>"
```

**Response 204 No Content**

---

### PATCH /api/v1/communities/{community_id}/posts/{post_id}/pin
Pin or unpin a community post (admins/owners only).

**Query params:** `pinned=true` or `pinned=false`

**cURL:**
```bash
# Pin a post
curl -X PATCH "{{BASE_URL}}/api/v1/communities/community-uuid/posts/post-uuid/pin?pinned=true" \
  -H "Authorization: Bearer <token>"

# Unpin a post
curl -X PATCH "{{BASE_URL}}/api/v1/communities/community-uuid/posts/post-uuid/pin?pinned=false" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{"status": "pinned"}
```
