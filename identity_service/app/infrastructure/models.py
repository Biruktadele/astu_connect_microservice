"""SQLAlchemy ORM models — infrastructure layer, not domain."""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, JSON, func
from .database import Base


class UserModel(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    display_name = Column(String, nullable=False, default="")
    department = Column(String, default="")
    year_of_study = Column(Integer, default=0)
    bio = Column(Text, default="")
    avatar_url = Column(String, default="")
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    status = Column(String, default="active")
    email_verified = Column(Boolean, default=False)
    is_astu_student = Column(Boolean, default=False)
    roles = Column(JSON, default=["student"])
    created_at = Column(DateTime, server_default=func.now())


class FollowModel(Base):
    __tablename__ = "follows"

    id = Column(String, primary_key=True)
    follower_id = Column(String, index=True, nullable=False)
    followee_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class BlockModel(Base):
    __tablename__ = "blocks"

    id = Column(String, primary_key=True)
    blocker_id = Column(String, index=True, nullable=False)
    blocked_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    token_hash = Column(String, unique=True, nullable=False)
    device_info = Column(String, default="")
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(DateTime, nullable=True)


class EmailVerificationTokenModel(Base):
    __tablename__ = "email_verification_tokens"

    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class PasswordResetOtpModel(Base):
    __tablename__ = "password_reset_otps"

    id = Column(String, primary_key=True)
    email = Column(String, index=True, nullable=False)
    otp = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class OutboxModel(Base):
    __tablename__ = "outbox"

    id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    topic = Column(String, nullable=False)
    partition_key = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    published_at = Column(DateTime, nullable=True)
