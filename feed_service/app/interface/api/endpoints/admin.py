"""Feed admin endpoints — moderation and post management."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.models import PostModel
from ....core.config import settings
from ..deps import oauth2_scheme

router = APIRouter(prefix="/feed/admin", tags=["feed-admin"])


def require_admin(token: str = Depends(oauth2_scheme)):
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from jose import jwt as jose_jwt, JWTError
    try:
        payload = jose_jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        roles = payload.get("roles", [])
        if "admin" not in roles:
            raise HTTPException(status_code=403, detail="Admin access required")
        return payload.get("sub", "")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


class AdminPostResponse(BaseModel):
    id: str
    author_id: str
    community_id: Optional[str] = None
    body: str
    media_refs: list[str] = []
    reaction_counts: dict = {}
    comment_count: int = 0
    moderation_status: str = "approved"
    is_deleted: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAdminPosts(BaseModel):
    posts: list[AdminPostResponse]
    total: int
    limit: int
    offset: int


class FeedStats(BaseModel):
    total_posts: int
    flagged_count: int
    rejected_count: int
    approved_count: int
    deleted_count: int


@router.get("/posts", response_model=PaginatedAdminPosts)
def list_posts(
    moderation_status: Optional[str] = Query(None, description="Filter: approved, flagged, rejected"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin_id: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(PostModel)
    if moderation_status:
        query = query.filter(PostModel.moderation_status == moderation_status)
    total = query.count()
    rows = query.order_by(PostModel.created_at.desc()).limit(limit).offset(offset).all()
    posts = [AdminPostResponse(
        id=r.id, author_id=r.author_id, community_id=r.community_id,
        body=r.body, media_refs=r.media_refs or [], reaction_counts=r.reaction_counts or {},
        comment_count=r.comment_count, moderation_status=r.moderation_status or "approved",
        is_deleted=r.is_deleted, created_at=r.created_at,
    ) for r in rows]
    return PaginatedAdminPosts(posts=posts, total=total, limit=limit, offset=offset)


@router.put("/posts/{post_id}/approve")
def approve_post(post_id: str, admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Post not found")
    m.moderation_status = "approved"
    db.commit()
    return {"status": "approved", "post_id": post_id}


@router.put("/posts/{post_id}/reject")
def reject_post(post_id: str, admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Post not found")
    m.moderation_status = "rejected"
    db.commit()
    return {"status": "rejected", "post_id": post_id}


@router.delete("/posts/{post_id}")
def delete_post(post_id: str, admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Post not found")
    m.is_deleted = True
    db.commit()
    return {"status": "deleted", "post_id": post_id}


@router.get("/stats", response_model=FeedStats)
def feed_stats(admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    total = db.query(func.count(PostModel.id)).scalar()
    flagged = db.query(func.count(PostModel.id)).filter(PostModel.moderation_status == "flagged").scalar()
    rejected = db.query(func.count(PostModel.id)).filter(PostModel.moderation_status == "rejected").scalar()
    approved = db.query(func.count(PostModel.id)).filter(PostModel.moderation_status == "approved").scalar()
    deleted = db.query(func.count(PostModel.id)).filter(PostModel.is_deleted == True).scalar()
    return FeedStats(
        total_posts=total, flagged_count=flagged, rejected_count=rejected,
        approved_count=approved, deleted_count=deleted,
    )
