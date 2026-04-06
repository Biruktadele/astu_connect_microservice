"""Reverse-proxy gateway that routes requests to backend services."""

import logging
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse
import httpx
from jose import jwt, JWTError

from ....core.config import settings
from ....core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)
router = APIRouter()

ROUTE_MAP = {
    "/api/v1/auth": settings.IDENTITY_SERVICE_URL,
    "/api/v1/users": settings.IDENTITY_SERVICE_URL,
    "/api/v1/admin": settings.IDENTITY_SERVICE_URL,
    "/api/v1/feed": settings.FEED_SERVICE_URL,
    "/api/v1/chat": settings.CHAT_SERVICE_URL,
    "/api/v1/communities": settings.COMMUNITY_SERVICE_URL,
    "/api/v1/notifications": settings.NOTIFICATION_SERVICE_URL,
    "/api/v1/media": settings.MEDIA_SERVICE_URL,
    "/api/v1/search": settings.SEARCH_SERVICE_URL,
    "/api/v1/gamification": settings.GAMIFICATION_SERVICE_URL,
}

PUBLIC_PREFIXES = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/resend-verification",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
}

ADMIN_PREFIXES = {"/api/v1/admin", "/api/v1/feed/admin", "/api/v1/communities/admin"}

_http_client = None


def get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


def _resolve_backend(path: str) -> str:
    for prefix, url in sorted(ROUTE_MAP.items(), key=lambda x: -len(x[0])):
        if path.startswith(prefix):
            return url
    return ""


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _validate_token(auth_header: str) -> tuple[str, list[str]]:
    """Returns (user_id, roles). Empty user_id on failure."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return "", []
    token = auth_header[7:]
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub", ""), payload.get("roles", [])
    except JWTError:
        return "", []


@router.api_route(
    "/api/v1/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy(request: Request, path: str):
    full_path = f"/api/v1/{path}"
    client_ip = _get_client_ip(request)

    is_auth_endpoint = any(full_path.startswith(p) for p in PUBLIC_PREFIXES)
    rate_limit = settings.RATE_LIMIT_AUTH_PER_MINUTE if is_auth_endpoint else settings.RATE_LIMIT_PER_MINUTE
    rate_key = f"{client_ip}:{full_path.split('/')[3] if len(full_path.split('/')) > 3 else 'default'}"

    if not await rate_limiter.is_allowed_async(rate_key, rate_limit):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"},
        )

    if not is_auth_endpoint:
        auth_header = request.headers.get("authorization", "")
        user_id, roles = _validate_token(auth_header)
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        is_admin_route = any(full_path.startswith(p) for p in ADMIN_PREFIXES)
        if is_admin_route and "admin" not in roles:
            raise HTTPException(status_code=403, detail="Admin access required")

    backend_url = _resolve_backend(full_path)
    if not backend_url:
        raise HTTPException(status_code=404, detail="Service not found")

    target_url = f"{backend_url}{full_path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["x-forwarded-for"] = client_ip
    headers["x-request-id"] = request.headers.get("x-request-id", "")

    body = await request.body()
    client = get_client()

    try:
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Service unavailable")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Service timeout")

    response_headers = dict(resp.headers)
    response_headers.pop("content-encoding", None)
    response_headers.pop("content-length", None)
    response_headers.pop("transfer-encoding", None)
    response_headers["x-ratelimit-remaining"] = str(await rate_limiter.remaining_async(rate_key, rate_limit))

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=response_headers,
        media_type=resp.headers.get("content-type"),
    )
