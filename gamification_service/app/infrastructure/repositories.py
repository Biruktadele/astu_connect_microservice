from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
import redis
import uuid

from ..core.config import settings
from ..domain.entities import UserPoints, Badge, PointTransaction
from .models import UserPointsModel, BadgeModel, PointTransactionModel


class PgUserPointsRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, user_id: str) -> UserPoints:
        m = self.db.query(UserPointsModel).filter(UserPointsModel.user_id == user_id).first()
        if m:
            return self._to_entity(m)
        m = UserPointsModel(user_id=user_id)
        self.db.add(m)
        self.db.flush()
        return self._to_entity(m)

    def save(self, up: UserPoints) -> None:
        m = self.db.query(UserPointsModel).filter(UserPointsModel.user_id == up.user_id).first()
        if not m:
            m = UserPointsModel(user_id=up.user_id)
            self.db.add(m)
        m.total_points = up.total_points
        m.total_posts = up.total_posts
        m.total_comments = up.total_comments
        m.total_reactions_received = up.total_reactions_received
        m.communities_joined = up.communities_joined
        m.followers_count = up.followers_count
        m.level = up.level
        m.level_name = up.level_name
        m.updated_at = datetime.utcnow()
        self.db.flush()

    def get_top(self, limit: int = 10) -> list[UserPoints]:
        rows = (
            self.db.query(UserPointsModel)
            .order_by(UserPointsModel.total_points.desc())
            .limit(limit)
            .all()
        )
        return [self._to_entity(r) for r in rows]

    @staticmethod
    def _to_entity(m: UserPointsModel) -> UserPoints:
        return UserPoints(
            user_id=m.user_id,
            total_points=m.total_points or 0,
            total_posts=m.total_posts or 0,
            total_comments=m.total_comments or 0,
            total_reactions_received=m.total_reactions_received or 0,
            communities_joined=m.communities_joined or 0,
            followers_count=m.followers_count or 0,
            level=m.level or 1,
            level_name=m.level_name or "Beginner",
            updated_at=m.updated_at or datetime.utcnow(),
        )


class PgBadgeRepository:
    def __init__(self, db: Session):
        self.db = db

    def award(self, user_id: str, badge_type: str) -> Optional[Badge]:
        if self.has_badge(user_id, badge_type):
            return None
        m = BadgeModel(id=str(uuid.uuid4()), user_id=user_id, badge_type=badge_type)
        self.db.add(m)
        self.db.flush()
        return Badge(id=m.id, user_id=user_id, badge_type=badge_type, awarded_at=m.awarded_at or datetime.utcnow())

    def get_user_badges(self, user_id: str) -> list[Badge]:
        rows = self.db.query(BadgeModel).filter(BadgeModel.user_id == user_id).order_by(BadgeModel.awarded_at).all()
        return [Badge(id=r.id, user_id=r.user_id, badge_type=r.badge_type, awarded_at=r.awarded_at) for r in rows]

    def has_badge(self, user_id: str, badge_type: str) -> bool:
        return (
            self.db.query(BadgeModel)
            .filter(BadgeModel.user_id == user_id, BadgeModel.badge_type == badge_type)
            .first()
        ) is not None


class PgPointTransactionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, txn: PointTransaction) -> None:
        m = PointTransactionModel(
            id=txn.id, user_id=txn.user_id, action=txn.action,
            points=txn.points, event_id=txn.event_id,
        )
        self.db.add(m)
        self.db.flush()

    def exists_by_event_id(self, event_id: str) -> bool:
        return (
            self.db.query(PointTransactionModel)
            .filter(PointTransactionModel.event_id == event_id)
            .first()
        ) is not None

    def get_user_transactions(self, user_id: str, limit: int = 50, offset: int = 0) -> list[PointTransaction]:
        rows = (
            self.db.query(PointTransactionModel)
            .filter(PointTransactionModel.user_id == user_id)
            .order_by(PointTransactionModel.created_at.desc())
            .limit(limit).offset(offset).all()
        )
        return [
            PointTransaction(
                id=r.id, user_id=r.user_id, action=r.action,
                points=r.points, event_id=r.event_id, created_at=r.created_at,
            )
            for r in rows
        ]


class RedisLeaderboardRepository:
    WEEKLY_KEY = "leaderboard:weekly"
    ALLTIME_KEY = "leaderboard:alltime"

    def __init__(self):
        self.r = redis.Redis.from_url(settings.FEED_REDIS_URL, decode_responses=True)

    def increment(self, user_id: str, points: int) -> None:
        self.r.zincrby(self.WEEKLY_KEY, points, user_id)
        self.r.zincrby(self.ALLTIME_KEY, points, user_id)

    def get_top(self, period: str = "weekly", limit: int = 10) -> list[dict]:
        key = self.WEEKLY_KEY if period == "weekly" else self.ALLTIME_KEY
        results = self.r.zrevrange(key, 0, limit - 1, withscores=True)
        return [{"user_id": uid, "points": int(score), "rank": i + 1} for i, (uid, score) in enumerate(results)]

    def get_rank(self, user_id: str, period: str = "weekly") -> Optional[dict]:
        key = self.WEEKLY_KEY if period == "weekly" else self.ALLTIME_KEY
        rank = self.r.zrevrank(key, user_id)
        if rank is None:
            return None
        score = self.r.zscore(key, user_id)
        return {"user_id": user_id, "points": int(score or 0), "rank": rank + 1}

    def reset_weekly(self) -> None:
        self.r.delete(self.WEEKLY_KEY)
