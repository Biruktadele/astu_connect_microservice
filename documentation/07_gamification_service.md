# Gamification Service — API Documentation

**Base path:** `/api/v1/gamification`

> All endpoints require `Authorization: Bearer <token>` unless noted.

The Gamification Service tracks user points, levels, badges, and leaderboards to encourage platform engagement.

---

## Points & Levels

Users earn points automatically for actions (posting, commenting, getting reactions, following others, joining communities). There is no manual point granting via these endpoints.

| Level | Points Required | Level Name |
|---|---|---|
| 1 | 0 | Newcomer |
| 2 | 100 | Explorer |
| 3 | 500 | Contributor |
| 4 | 1500 | Influencer |
| 5 | 5000 | Champion |

---

## Endpoints

### GET /api/v1/gamification/me
Get your own full gamification profile (points, badges, level, stats).

**cURL:**
```bash
curl {{BASE_URL}}/api/v1/gamification/me \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "user_id": "user-uuid",
  "total_points": 740,
  "level": 3,
  "level_name": "Contributor",
  "total_posts": 12,
  "total_comments": 34,
  "total_reactions_received": 87,
  "communities_joined": 3,
  "followers_count": 22,
  "badges": [
    {
      "badge_type": "first_post",
      "label": "First Post",
      "description": "Published your first post on ASTU Connect",
      "awarded_at": "2026-04-01T12:00:00"
    },
    {
      "badge_type": "popular",
      "label": "Popular",
      "description": "Received 50+ reactions on a single post",
      "awarded_at": "2026-04-03T09:30:00"
    }
  ]
}
```

---

### GET /api/v1/gamification/users/{target_user_id}
Get the gamification profile of any user by their ID.

**cURL:**
```bash
curl {{BASE_URL}}/api/v1/gamification/users/user-uuid \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:** Same schema as `GET /me`.

---

### GET /api/v1/gamification/leaderboard
Get the top users by points for the selected time period.

**Query params:**
- `period` — `"weekly"` or `"alltime"` (default: `"weekly"`)
- `limit` — Number of entries (1–100, default: `10`)

**cURL:**
```bash
# Weekly leaderboard top 10
curl "{{BASE_URL}}/api/v1/gamification/leaderboard?period=weekly&limit=10" \
  -H "Authorization: Bearer <token>"

# All-time top 20
curl "{{BASE_URL}}/api/v1/gamification/leaderboard?period=alltime&limit=20" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "user_id": "user-uuid-1",
    "points": 2400,
    "rank": 1
  },
  {
    "user_id": "user-uuid-2",
    "points": 1850,
    "rank": 2
  },
  {
    "user_id": "user-uuid-3",
    "points": 1200,
    "rank": 3
  }
]
```

---

### GET /api/v1/gamification/badges
List all badge types available on the platform (no authentication required).

**cURL:**
```bash
curl {{BASE_URL}}/api/v1/gamification/badges
```

**Response 200 OK:**
```json
[
  {
    "badge_type": "first_post",
    "label": "First Post",
    "description": "Published your first post on ASTU Connect"
  },
  {
    "badge_type": "popular",
    "label": "Popular",
    "description": "Received 50+ reactions on a single post"
  },
  {
    "badge_type": "community_builder",
    "label": "Community Builder",
    "description": "Created a community with 10+ members"
  }
]
```

---

### GET /api/v1/gamification/me/transactions
Get your personal point transaction history (what earned you points).

**Query params:** `limit=50`, `offset=0`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/gamification/me/transactions?limit=20" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
[
  {
    "id": "txn-uuid",
    "action": "post_created",
    "points": 10,
    "created_at": "2026-04-05T10:00:00"
  },
  {
    "id": "txn-uuid-2",
    "action": "reaction_received",
    "points": 2,
    "created_at": "2026-04-05T10:05:00"
  },
  {
    "id": "txn-uuid-3",
    "action": "new_follower",
    "points": 5,
    "created_at": "2026-04-05T10:10:00"
  }
]
```
