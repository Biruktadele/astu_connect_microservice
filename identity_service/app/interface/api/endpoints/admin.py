"""Platform admin endpoints — protected by require_admin dependency."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.models import UserModel
from ....infrastructure.repositories import PgUserRepository, PgRefreshTokenRepository, _user_to_entity
from ....infrastructure.security import decode_access_token
from ....core.config import settings
from ....application.dto import UserResponse
from ..deps import oauth2_scheme

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Auth dependency ──────────────────────────────────────────────────

def require_admin(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from jose import jwt as jose_jwt, JWTError
    try:
        payload = jose_jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        roles = payload.get("roles", [])
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        if "admin" not in roles:
            raise HTTPException(status_code=403, detail="Admin access required")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── DTOs ─────────────────────────────────────────────────────────────

class AdminUserResponse(BaseModel):
    id: str
    email: str
    username: str
    display_name: str
    department: str
    year_of_study: int
    bio: str
    avatar_url: str
    is_active: bool
    status: str
    email_verified: bool
    is_astu_student: bool
    roles: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAdminUsers(BaseModel):
    users: list[AdminUserResponse]
    total: int
    limit: int
    offset: int


class SetRolesDTO(BaseModel):
    roles: list[str]


class BanReasonDTO(BaseModel):
    reason: str = ""


class PlatformStats(BaseModel):
    total_users: int
    active_users: int
    banned_users: int
    new_today: int
    new_this_week: int


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/users", response_model=PaginatedAdminUsers)
def list_users(
    q: str = Query("", description="Search by email or username"),
    status: Optional[str] = Query(None, description="Filter by status (active, banned)"),
    role: Optional[str] = Query(None, description="Filter by role"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin_id: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(UserModel)
    if q:
        pattern = f"%{q}%"
        query = query.filter(or_(UserModel.email.ilike(pattern), UserModel.username.ilike(pattern)))
    if status:
        query = query.filter(UserModel.status == status)
    if role:
        query = query.filter(UserModel.roles.op("@>")(f'["{role}"]'))

    total = query.count()
    rows = query.order_by(UserModel.created_at.desc()).limit(limit).offset(offset).all()
    users = []
    for m in rows:
        users.append(AdminUserResponse(
            id=m.id, email=m.email, username=m.username, display_name=m.display_name,
            department=m.department, year_of_study=m.year_of_study, bio=m.bio,
            avatar_url=m.avatar_url, is_active=m.is_active, status=m.status,
            email_verified=m.email_verified, is_astu_student=m.is_astu_student,
            roles=m.roles or ["student"], created_at=m.created_at,
        ))
    return PaginatedAdminUsers(users=users, total=total, limit=limit, offset=offset)


@router.get("/users/{user_id}", response_model=AdminUserResponse)
def get_user(user_id: str, admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="User not found")
    return AdminUserResponse(
        id=m.id, email=m.email, username=m.username, display_name=m.display_name,
        department=m.department, year_of_study=m.year_of_study, bio=m.bio,
        avatar_url=m.avatar_url, is_active=m.is_active, status=m.status,
        email_verified=m.email_verified, is_astu_student=m.is_astu_student,
        roles=m.roles or ["student"], created_at=m.created_at,
    )


@router.put("/users/{user_id}/ban")
def ban_user(
    user_id: str,
    body: BanReasonDTO = BanReasonDTO(),
    admin_id: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    m = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot ban yourself")
    m.is_active = False
    m.status = "banned"
    PgRefreshTokenRepository(db).revoke_all_for_user(user_id)
    db.commit()
    return {"status": "banned", "user_id": user_id}


@router.put("/users/{user_id}/unban")
def unban_user(user_id: str, admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    m = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="User not found")
    m.is_active = True
    m.status = "active"
    db.commit()
    return {"status": "active", "user_id": user_id}


@router.put("/users/{user_id}/roles")
def set_roles(
    user_id: str,
    dto: SetRolesDTO,
    admin_id: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    m = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="User not found")
    valid_roles = {"student", "moderator", "admin"}
    for r in dto.roles:
        if r not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role: {r}. Valid: {valid_roles}")
    m.roles = dto.roles
    db.commit()
    return {"user_id": user_id, "roles": dto.roles}


@router.get("/stats", response_model=PlatformStats)
def platform_stats(admin_id: str = Depends(require_admin), db: Session = Depends(get_db)):
    total = db.query(func.count(UserModel.id)).scalar()
    active = db.query(func.count(UserModel.id)).filter(UserModel.status == "active").scalar()
    banned = db.query(func.count(UserModel.id)).filter(UserModel.status == "banned").scalar()
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    new_today = db.query(func.count(UserModel.id)).filter(UserModel.created_at >= today_start).scalar()
    new_week = db.query(func.count(UserModel.id)).filter(UserModel.created_at >= week_start).scalar()
    return PlatformStats(
        total_users=total, active_users=active, banned_users=banned,
        new_today=new_today, new_this_week=new_week,
    )
