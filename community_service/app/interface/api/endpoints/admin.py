"""Community admin endpoints — platform-level community management."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.models import CommunityModel, MembershipModel
from ....core.config import settings
from ..deps import oauth2_scheme

router = APIRouter(prefix="/communities/admin", tags=["community-admin"])


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


class AdminCommunityResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    avatar_url: str
    visibility: str
    owner_id: str
    member_count: int
    is_archived: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAdminCommunities(BaseModel):
    communities: list[AdminCommunityResponse]
    total: int
    limit: int
    offset: int


class CommunityStats(BaseModel):
    total_communities: int
    total_members: int
    archived_count: int


@router.get("/list", response_model=PaginatedAdminCommunities)
def list_communities(
    q: str = Query("", description="Search by name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin_id: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(CommunityModel)
    if q:
        query = query.filter(CommunityModel.name.ilike(f"%{q}%"))
    total = query.count()
    rows = query.order_by(CommunityModel.created_at.desc()).limit(limit).offset(offset).all()
    communities = [AdminCommunityResponse(
        id=r.id, name=r.name, slug=r.slug, description=r.description,
        avatar_url=r.avatar_url, visibility=r.visibility, owner_id=r.owner_id,
        member_count=r.member_count, is_archived=r.is_archived, created_at=r.created_at,
    ) for r in rows]
    return PaginatedAdminCommunities(communities=communities, total=total, limit=limit, offset=offset)


@router.delete("/{community_id}")
def delete_community(community_id: str, admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.query(CommunityModel).filter(CommunityModel.id == community_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Community not found")
    m.is_archived = True
    db.commit()
    return {"status": "archived", "community_id": community_id}


@router.get("/stats", response_model=CommunityStats)
def community_stats(admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    total = db.query(func.count(CommunityModel.id)).scalar()
    total_members = db.query(func.count(MembershipModel.id)).scalar()
    archived = db.query(func.count(CommunityModel.id)).filter(CommunityModel.is_archived == True).scalar()
    return CommunityStats(total_communities=total, total_members=total_members, archived_count=archived)
