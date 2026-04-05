import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer

from ..core.config import settings, compute_level
from .database import SessionLocal
from .repositories import (
    PgUserPointsRepository, PgBadgeRepository,
    PgPointTransactionRepository, RedisLeaderboardRepository,
)
from ..domain.entities import PointTransaction

logger = logging.getLogger(__name__)

ACTION_MAP = {
    "post.created":              ("post",               "total_posts",              settings.POINTS_POST),
    "comment.created":           ("comment",            "total_comments",           settings.POINTS_COMMENT),
    "reaction.set":              ("reaction_received",  "total_reactions_received",  settings.POINTS_REACTION_RECEIVED),
    "user.followed":             None,
    "community.member.joined":   ("community_join",     "communities_joined",       settings.POINTS_JOIN_COMMUNITY),
}

BADGE_RULES: list[tuple[str, str, int]] = [
    ("first_post",           "total_posts",              1),
    ("prolific_poster",      "total_posts",              50),
    ("commentator",          "total_comments",           20),
    ("top_commenter",        "total_comments",           100),
    ("popular",              "followers_count",          100),
    ("influencer",           "followers_count",          500),
    ("community_joiner",     "communities_joined",       5),
]

POINT_BADGES = [
    ("point_milestone_100",  100),
    ("point_milestone_1000", 1000),
]


class GamificationConsumer:
    def __init__(self):
        self._running = False
        self.leaderboard = RedisLeaderboardRepository()

    async def run_forever(self):
        self._running = True
        consumer = AIOKafkaConsumer(
            "post.events", "comment.events", "reaction.events",
            "user.events", "community.events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="gamification-service",
            value_deserializer=lambda v: json.loads(v),
            auto_offset_reset="earliest",
        )
        await consumer.start()
        logger.info("GamificationConsumer started")
        try:
            async for msg in consumer:
                if not self._running:
                    break
                try:
                    self._handle(msg.value)
                except Exception:
                    logger.exception("Gamification event error")
        finally:
            await consumer.stop()

    def stop(self):
        self._running = False

    def _handle(self, event: dict):
        event_type = event.get("event_type", "")
        event_id = event.get("event_id", "")
        payload = event.get("payload", {})

        if event_type == "user.followed":
            self._handle_follow(event_id, payload)
            return

        mapping = ACTION_MAP.get(event_type)
        if mapping is None:
            return
        action_name, counter_field, points = mapping

        user_id = self._extract_user_id(event_type, payload)
        if not user_id:
            return

        self._award_points(user_id, action_name, counter_field, points, event_id)

    def _handle_follow(self, event_id: str, payload: dict):
        follower_id = payload.get("follower_id")
        followee_id = payload.get("followee_id")

        if follower_id:
            self._award_points(
                follower_id, "follow", None,
                settings.POINTS_FOLLOW, f"{event_id}:follower",
            )
        if followee_id:
            self._award_points(
                followee_id, "get_followed", "followers_count",
                settings.POINTS_GET_FOLLOWED, f"{event_id}:followee",
            )

    def _extract_user_id(self, event_type: str, payload: dict) -> str:
        if event_type == "post.created":
            return payload.get("author_id", "")
        if event_type == "comment.created":
            return payload.get("commenter_id", "")
        if event_type == "reaction.set":
            return payload.get("post_author_id", "")
        if event_type == "community.member.joined":
            return payload.get("user_id", "")
        return ""

    def _award_points(
        self, user_id: str, action: str,
        counter_field: str | None, points: int, event_id: str,
    ):
        db = SessionLocal()
        try:
            txn_repo = PgPointTransactionRepository(db)
            if txn_repo.exists_by_event_id(event_id):
                return

            pts_repo = PgUserPointsRepository(db)
            badge_repo = PgBadgeRepository(db)

            up = pts_repo.get_or_create(user_id)
            up.total_points += points

            if counter_field and hasattr(up, counter_field):
                setattr(up, counter_field, getattr(up, counter_field) + 1)

            level_num, level_name = compute_level(up.total_points)
            up.level = level_num
            up.level_name = level_name

            pts_repo.save(up)

            txn_repo.create(PointTransaction(
                user_id=user_id, action=action,
                points=points, event_id=event_id,
            ))

            self._check_badges(badge_repo, up)

            db.commit()

            self.leaderboard.increment(user_id, points)

        except Exception:
            db.rollback()
            logger.exception("Failed to award points for user %s", user_id)
        finally:
            db.close()

    def _check_badges(self, badge_repo: PgBadgeRepository, up):
        for badge_type, field, threshold in BADGE_RULES:
            if getattr(up, field, 0) >= threshold:
                badge_repo.award(up.user_id, badge_type)

        for badge_type, threshold in POINT_BADGES:
            if up.total_points >= threshold:
                badge_repo.award(up.user_id, badge_type)


gamification_consumer = GamificationConsumer()
