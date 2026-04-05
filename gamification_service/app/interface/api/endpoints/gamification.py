from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.repositories import (
    PgUserPointsRepository, PgBadgeRepository,
    PgPointTransactionRepository, RedisLeaderboardRepository,
)
from ....core.config import BADGE_DEFINITIONS
from ..deps import get_current_user_id

router = APIRouter(prefix="/gamification", tags=["gamification"])


class BadgeResponse(BaseModel):
    badge_type: str
    label: str
    description: str
    awarded_at: datetime | None = None


class UserGamificationResponse(BaseModel):
    user_id: str
    total_points: int
    level: int
    level_name: str
    total_posts: int
    total_comments: int
    total_reactions_received: int
    communities_joined: int
    followers_count: int
    badges: list[BadgeResponse]


class LeaderboardEntry(BaseModel):
    user_id: str
    points: int
    rank: int


class TransactionResponse(BaseModel):
    id: str
    action: str
    points: int
    created_at: datetime


class BadgeDefinitionResponse(BaseModel):
    badge_type: str
    label: str
    description: str


def _build_user_response(db: Session, user_id: str) -> UserGamificationResponse:
    pts_repo = PgUserPointsRepository(db)
    badge_repo = PgBadgeRepository(db)
    up = pts_repo.get_or_create(user_id)
    badges = badge_repo.get_user_badges(user_id)
    badge_list = []
    for b in badges:
        defn = BADGE_DEFINITIONS.get(b.badge_type, {})
        badge_list.append(BadgeResponse(
            badge_type=b.badge_type,
            label=defn.get("label", b.badge_type),
            description=defn.get("description", ""),
            awarded_at=b.awarded_at,
        ))
    return UserGamificationResponse(
        user_id=up.user_id,
        total_points=up.total_points,
        level=up.level,
        level_name=up.level_name,
        total_posts=up.total_posts,
        total_comments=up.total_comments,
        total_reactions_received=up.total_reactions_received,
        communities_joined=up.communities_joined,
        followers_count=up.followers_count,
        badges=badge_list,
    )


@router.get("/me", response_model=UserGamificationResponse)
def get_my_gamification(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return _build_user_response(db, user_id)


@router.get("/users/{target_user_id}", response_model=UserGamificationResponse)
def get_user_gamification(
    target_user_id: str,
    db: Session = Depends(get_db),
):
    return _build_user_response(db, target_user_id)


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def get_leaderboard(
    period: str = Query("weekly", pattern="^(weekly|alltime)$"),
    limit: int = Query(10, ge=1, le=100),
):
    repo = RedisLeaderboardRepository()
    return [LeaderboardEntry(**entry) for entry in repo.get_top(period, limit)]


@router.get("/badges", response_model=list[BadgeDefinitionResponse])
def list_all_badges():
    return [
        BadgeDefinitionResponse(badge_type=k, label=v["label"], description=v["description"])
        for k, v in BADGE_DEFINITIONS.items()
    ]


@router.get("/me/transactions", response_model=list[TransactionResponse])
def get_my_transactions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = PgPointTransactionRepository(db)
    txns = repo.get_user_transactions(user_id, limit, offset)
    return [
        TransactionResponse(id=t.id, action=t.action, points=t.points, created_at=t.created_at)
        for t in txns
    ]
