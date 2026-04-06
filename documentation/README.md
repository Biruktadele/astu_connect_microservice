# ASTU Connect — API Documentation

**Base URL:** Configured via the `APP_BASE_URL` environment variable in `.env`.

> All example cURL commands use `{{BASE_URL}}` as a placeholder. Replace it with your actual host, e.g.:
> - **Production:** `http://16.171.11.166`
> - **Local dev:** `http://localhost:8000`
>
> Example: `curl {{BASE_URL}}/api/v1/auth/login`

All requests to protected endpoints require a Bearer JWT token obtained from `{{BASE_URL}}/api/v1/auth/login`.


---

## Authentication

Add this header to every protected request:

```
Authorization: Bearer <your_access_token>
```

---

## Service Documentation

| File | Service | Base Path |
|---|---|---|
| [01_identity_service.md](./01_identity_service.md) | Identity Service | `/api/v1/auth`, `/api/v1/users`, `/api/v1/admin` |
| [02_feed_service.md](./02_feed_service.md) | Feed Service | `/api/v1/feed` |
| [03_chat_service.md](./03_chat_service.md) | Chat Service | `/api/v1/chat`, `ws://` |
| [04_community_service.md](./04_community_service.md) | Community Service | `/api/v1/communities` |
| [05_media_service.md](./05_media_service.md) | Media Service | `/api/v1/media` |
| [06_search_service.md](./06_search_service.md) | Search Service | `/api/v1/search` |
| [07_gamification_service.md](./07_gamification_service.md) | Gamification Service | `/api/v1/gamification` |
| [08_notification_service.md](./08_notification_service.md) | Notification Service | `/api/v1/notifications` |
| [09_admin_endpoints.md](./09_admin_endpoints.md)| Admin-Only Endpoints | `/api/v1/admin`, `/api/v1/feed/admin`, `/api/v1/communities/admin` |

---

## Rate Limiting

- Standard endpoints: **120 requests / minute** per IP
- Auth endpoints (`/login`, `/register`, `/refresh`): **20 requests / minute** per IP

When exceeded, the server returns HTTP `429 Too Many Requests` with header `Retry-After: 60`.

---

## Common Response Codes

| Code | Meaning |
|---|---|
| 200 | OK |
| 201 | Created |
| 204 | No Content (success, no body) |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (not enough permissions) |
| 404 | Not Found |
| 429 | Rate Limit Exceeded |
| 503 | Service Unavailable |
