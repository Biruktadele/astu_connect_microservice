from sqlalchemy import Column, String, Integer, DateTime, UniqueConstraint, func
from .database import Base


class UserPointsModel(Base):
    __tablename__ = "user_points"
    user_id = Column(String, primary_key=True)
    total_points = Column(Integer, default=0)
    total_posts = Column(Integer, default=0)
    total_comments = Column(Integer, default=0)
    total_reactions_received = Column(Integer, default=0)
    communities_joined = Column(Integer, default=0)
    followers_count = Column(Integer, default=0)
    level = Column(Integer, default=1)
    level_name = Column(String, default="Beginner")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class BadgeModel(Base):
    __tablename__ = "badges"
    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    badge_type = Column(String, nullable=False)
    awarded_at = Column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("user_id", "badge_type", name="uq_user_badge"),
    )


class PointTransactionModel(Base):
    __tablename__ = "point_transactions"
    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    action = Column(String, nullable=False)
    points = Column(Integer, nullable=False)
    event_id = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
