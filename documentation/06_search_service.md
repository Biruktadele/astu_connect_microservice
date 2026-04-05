# Search Service — API Documentation

**Base path:** `/api/v1/search`

> All endpoints require `Authorization: Bearer <token>`

The Search Service uses Elasticsearch with fuzzy full-text search across users, posts, and communities.

---

## Endpoints

### GET /api/v1/search
Search across all content types (users, posts, and communities) at once.

**Query params:**
- `q` *(required)* — Search keyword (min 1 character)
- `type` *(optional)* — Filter by type: `user`, `post`, or `community`. Omit to search all.
- `limit=20` — Number of results to return
- `offset=0` — Number to skip (for pagination)

**cURL:**
```bash
# Search everything
curl "http://16.171.11.166/api/v1/search?q=robotics&limit=10" \
  -H "Authorization: Bearer <token>"

# Search only users
curl "http://16.171.11.166/api/v1/search?q=biruk&type=user&limit=10" \
  -H "Authorization: Bearer <token>"

# Search only posts
curl "http://16.171.11.166/api/v1/search?q=hackathon&type=post&limit=20" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "results": [
    {
      "id": "user-uuid",
      "type": "user",
      "score": 4.25,
      "data": {
        "username": "biruk_tadele",
        "display_name": "Biruk Tadele",
        "department": "Computer Science",
        "avatar_url": "https://..."
      }
    },
    {
      "id": "post-uuid",
      "type": "post",
      "score": 2.1,
      "data": {
        "body": "Check out our robotics hackathon!",
        "author_id": "user-uuid"
      }
    },
    {
      "id": "community-uuid",
      "type": "community",
      "score": 3.8,
      "data": {
        "name": "ASTU Robotics Club",
        "description": "Robotics enthusiasts"
      }
    }
  ],
  "total": 3
}
```

---

### GET /api/v1/search/users
Shortcut to search only users.

**Query params:** `q` *(required)*, `limit=20`

**cURL:**
```bash
curl "http://16.171.11.166/api/v1/search/users?q=samrawit&limit=10" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "results": [
    {
      "id": "user-uuid",
      "type": "user",
      "score": 5.3,
      "data": {
        "username": "samrawit_g",
        "display_name": "Samrawit G.",
        "department": "Electrical Engineering",
        "avatar_url": "https://..."
      }
    }
  ],
  "total": 1
}
```

---

### GET /api/v1/search/posts
Shortcut to search only posts.

**Query params:** `q` *(required)*, `limit=20`

**cURL:**
```bash
curl "http://16.171.11.166/api/v1/search/posts?q=exam+tips&limit=10" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "results": [
    {
      "id": "post-uuid",
      "type": "post",
      "score": 3.7,
      "data": {
        "body": "Here are some exam tips for CS students...",
        "author_id": "user-uuid"
      }
    }
  ],
  "total": 1
}
```

---

### GET /api/v1/search/communities
Shortcut to search only communities.

**Query params:** `q` *(required)*, `limit=20`

**cURL:**
```bash
curl "http://16.171.11.166/api/v1/search/communities?q=coding+club&limit=10" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "results": [
    {
      "id": "community-uuid",
      "type": "community",
      "score": 4.9,
      "data": {
        "name": "ASTU Coding Club",
        "description": "Where coders meet",
        "member_count": 120
      }
    }
  ],
  "total": 1
}
```

> **Note:** Search uses fuzzy matching so typos are tolerated. Field weights: `username × 3`, `display_name × 2`, `community name × 3`, `body × 1`.
