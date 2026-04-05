# Admin-Only Endpoints — API Documentation

**Base paths:** `/api/v1/admin`, `/api/v1/feed/admin`, `/api/v1/communities/admin`

> ⚠️ All endpoints in this section require an **admin JWT token**.
> After login, the token must contain `"roles": ["admin"]` in its payload.
> The first admin is set via `INITIAL_ADMIN_EMAIL` in `.env`.

---

## Identity Admin — User Management

### GET /api/v1/admin/users
List all platform users with optional filters.

**Query params:**
- `q` — Search by email or username
- `status` — Filter by status: `"active"` or `"banned"`
- `role` — Filter by role: `"student"`, `"moderator"`, `"admin"`
- `limit=50`, `offset=0`

**cURL:**
```bash
curl "http://16.171.11.166/api/v1/admin/users?q=biruk&status=active&limit=20" \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{
  "users": [
    {
      "id": "user-uuid",
      "email": "biruk@astu.edu.et",
      "username": "biruk_tadele",
      "display_name": "Biruk Tadele",
      "department": "Computer Science",
      "year_of_study": 3,
      "bio": "",
      "avatar_url": "",
      "is_active": true,
      "status": "active",
      "email_verified": true,
      "is_astu_student": true,
      "roles": ["student"],
      "created_at": "2026-04-01T08:00:00"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

### GET /api/v1/admin/users/{user_id}
Get full details of a specific user.

**cURL:**
```bash
curl http://16.171.11.166/api/v1/admin/users/user-uuid \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:** Single `AdminUserResponse` (same schema as above).

**Response 404 Not Found:**
```json
{"detail": "User not found"}
```

---

### PUT /api/v1/admin/users/{user_id}/ban
Ban a user from the platform (revokes all their sessions immediately).

**Request body (optional):**
```json
{"reason": "Violated community guidelines"}
```

**cURL:**
```bash
curl -X PUT http://16.171.11.166/api/v1/admin/users/user-uuid/ban \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Violated community guidelines"}'
```

**Response 200 OK:**
```json
{"status": "banned", "user_id": "user-uuid"}
```

**Response 400 Bad Request:**
```json
{"detail": "Cannot ban yourself"}
```

---

### PUT /api/v1/admin/users/{user_id}/unban
Restore a banned user's access to the platform.

**cURL:**
```bash
curl -X PUT http://16.171.11.166/api/v1/admin/users/user-uuid/unban \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{"status": "active", "user_id": "user-uuid"}
```

---

### PUT /api/v1/admin/users/{user_id}/roles
Set the platform roles of a user (completely replaces existing roles).

**Request body:**
```json
{"roles": ["student", "moderator"]}
```

> Valid roles: `"student"`, `"moderator"`, `"admin"`

**cURL:**
```bash
# Promote to moderator
curl -X PUT http://16.171.11.166/api/v1/admin/users/user-uuid/roles \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"roles": ["student", "moderator"]}'

# Promote to admin
curl -X PUT http://16.171.11.166/api/v1/admin/users/user-uuid/roles \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"roles": ["admin"]}'
```

**Response 200 OK:**
```json
{"user_id": "user-uuid", "roles": ["student", "moderator"]}
```

---

### GET /api/v1/admin/stats
Get platform-wide user statistics.

**cURL:**
```bash
curl http://16.171.11.166/api/v1/admin/stats \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{
  "total_users": 847,
  "active_users": 831,
  "banned_users": 16,
  "new_today": 12,
  "new_this_week": 84
}
```

---

## Feed Admin — Post Moderation

### GET /api/v1/feed/admin/posts
List all posts with optional moderation status filter.

**Query params:**
- `moderation_status` — Filter by: `"approved"`, `"flagged"`, `"rejected"`
- `limit=50`, `offset=0`

**cURL:**
```bash
# See all NSFW-flagged posts
curl "http://16.171.11.166/api/v1/feed/admin/posts?moderation_status=flagged&limit=20" \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{
  "posts": [
    {
      "id": "post-uuid",
      "author_id": "user-uuid",
      "community_id": null,
      "body": "...",
      "media_refs": ["https://res.cloudinary.com/..."],
      "reaction_counts": {},
      "comment_count": 0,
      "moderation_status": "flagged",
      "is_deleted": false,
      "created_at": "2026-04-05T10:00:00"
    }
  ],
  "total": 3,
  "limit": 20,
  "offset": 0
}
```

---

### PUT /api/v1/feed/admin/posts/{post_id}/approve
Approve a flagged post (marks it as safe to display).

**cURL:**
```bash
curl -X PUT http://16.171.11.166/api/v1/feed/admin/posts/post-uuid/approve \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{"status": "approved", "post_id": "post-uuid"}
```

---

### PUT /api/v1/feed/admin/posts/{post_id}/reject
Reject a post and hide it from the feed.

**cURL:**
```bash
curl -X PUT http://16.171.11.166/api/v1/feed/admin/posts/post-uuid/reject \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{"status": "rejected", "post_id": "post-uuid"}
```

---

### DELETE /api/v1/feed/admin/posts/{post_id}
Permanently soft-delete a post from the feed.

**cURL:**
```bash
curl -X DELETE http://16.171.11.166/api/v1/feed/admin/posts/post-uuid \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{"status": "deleted", "post_id": "post-uuid"}
```

---

### GET /api/v1/feed/admin/stats
Get moderation statistics for posts.

**cURL:**
```bash
curl http://16.171.11.166/api/v1/feed/admin/stats \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{
  "total_posts": 1240,
  "flagged_count": 8,
  "rejected_count": 3,
  "approved_count": 1229,
  "deleted_count": 12
}
```

---

## Community Admin — Community Management

### GET /api/v1/communities/admin/list
List all communities on the platform.

**Query params:** `q=` (search by name), `limit=50`, `offset=0`

**cURL:**
```bash
curl "http://16.171.11.166/api/v1/communities/admin/list?limit=20" \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{
  "communities": [
    {
      "id": "community-uuid",
      "name": "ASTU Robotics Club",
      "slug": "astu-robotics",
      "description": "Robotics enthusiasts",
      "avatar_url": "",
      "visibility": "public",
      "owner_id": "user-uuid",
      "member_count": 87,
      "is_archived": false,
      "created_at": "2026-01-01T00:00:00"
    }
  ],
  "total": 47,
  "limit": 20,
  "offset": 0
}
```

---

### DELETE /api/v1/communities/admin/{community_id}
Archive (soft-delete) a community.

**cURL:**
```bash
curl -X DELETE http://16.171.11.166/api/v1/communities/admin/community-uuid \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{"status": "archived", "community_id": "community-uuid"}
```

---

### GET /api/v1/communities/admin/stats
Get platform-wide community statistics.

**cURL:**
```bash
curl http://16.171.11.166/api/v1/communities/admin/stats \
  -H "Authorization: Bearer <admin_token>"
```

**Response 200 OK:**
```json
{
  "total_communities": 47,
  "total_members": 1893,
  "archived_count": 2
}
```
