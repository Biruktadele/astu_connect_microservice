"""Concrete repository implementations using SQLAlchemy."""

from typing import Optional
from sqlalchemy.orm import Session
import json, uuid
from datetime import datetime

from ..domain.entities import User, Follow, Block, RefreshToken
from ..domain.repositories import (
    UserRepository, FollowRepository, BlockRepository,
    RefreshTokenRepository, EventPublisher,
)
from .models import (
    UserModel, FollowModel, BlockModel, RefreshTokenModel, OutboxModel,
    EmailVerificationTokenModel, PasswordResetOtpModel,
)


def _user_to_entity(m: UserModel) -> User:
    return User(
        id=m.id, email=m.email, username=m.username, display_name=m.display_name,
        department=m.department, year_of_study=m.year_of_study, bio=m.bio,
        avatar_url=m.avatar_url, hashed_password=m.hashed_password,
        is_active=m.is_active, status=m.status,
        email_verified=m.email_verified,
        is_astu_student=m.is_astu_student,
        created_at=m.created_at,
    )


class PgUserRepository(UserRepository):
    def __init__(self, db: Session):
        self.db = db

    def save(self, user: User) -> User:
        m = UserModel(**user.__dict__)
        self.db.add(m)
        self.db.flush()
        return _user_to_entity(m)

    def find_by_id(self, user_id: str) -> Optional[User]:
        m = self.db.query(UserModel).filter(UserModel.id == user_id).first()
        return _user_to_entity(m) if m else None

    def find_by_email(self, email: str) -> Optional[User]:
        m = self.db.query(UserModel).filter(UserModel.email == email).first()
        return _user_to_entity(m) if m else None

    def find_by_username(self, username: str) -> Optional[User]:
        m = self.db.query(UserModel).filter(UserModel.username == username).first()
        return _user_to_entity(m) if m else None

    def update(self, user: User) -> User:
        m = self.db.query(UserModel).filter(UserModel.id == user.id).first()
        if m:
            for k, v in user.__dict__.items():
                if k != "created_at":
                    setattr(m, k, v)
            self.db.flush()
            return _user_to_entity(m)
        raise ValueError("User not found")


class PgFollowRepository(FollowRepository):
    def __init__(self, db: Session):
        self.db = db

    def save(self, follow: Follow) -> Follow:
        m = FollowModel(**follow.__dict__)
        self.db.add(m)
        self.db.flush()
        return follow

    def delete(self, follower_id: str, followee_id: str) -> bool:
        row = self.db.query(FollowModel).filter(
            FollowModel.follower_id == follower_id,
            FollowModel.followee_id == followee_id,
        ).first()
        if row:
            self.db.delete(row)
            self.db.flush()
            return True
        return False

    def exists(self, follower_id: str, followee_id: str) -> bool:
        return self.db.query(FollowModel).filter(
            FollowModel.follower_id == follower_id,
            FollowModel.followee_id == followee_id,
        ).first() is not None

    def get_followers(self, user_id: str, limit: int = 50, offset: int = 0) -> list[User]:
        rows = self.db.query(UserModel).join(
            FollowModel, FollowModel.follower_id == UserModel.id
        ).filter(FollowModel.followee_id == user_id).limit(limit).offset(offset).all()
        return [_user_to_entity(r) for r in rows]

    def get_following(self, user_id: str, limit: int = 50, offset: int = 0) -> list[User]:
        rows = self.db.query(UserModel).join(
            FollowModel, FollowModel.followee_id == UserModel.id
        ).filter(FollowModel.follower_id == user_id).limit(limit).offset(offset).all()
        return [_user_to_entity(r) for r in rows]

    def get_follower_ids(self, user_id: str) -> list[str]:
        rows = self.db.query(FollowModel.follower_id).filter(
            FollowModel.followee_id == user_id
        ).all()
        return [r[0] for r in rows]

    def count_followers(self, user_id: str) -> int:
        return self.db.query(FollowModel).filter(FollowModel.followee_id == user_id).count()

    def count_following(self, user_id: str) -> int:
        return self.db.query(FollowModel).filter(FollowModel.follower_id == user_id).count()


class PgBlockRepository(BlockRepository):
    def __init__(self, db: Session):
        self.db = db

    def save(self, block: Block) -> Block:
        m = BlockModel(**block.__dict__)
        self.db.add(m)
        self.db.flush()
        return block

    def delete(self, blocker_id: str, blocked_id: str) -> bool:
        row = self.db.query(BlockModel).filter(
            BlockModel.blocker_id == blocker_id,
            BlockModel.blocked_id == blocked_id,
        ).first()
        if row:
            self.db.delete(row)
            self.db.flush()
            return True
        return False

    def is_blocked(self, blocker_id: str, blocked_id: str) -> bool:
        return self.db.query(BlockModel).filter(
            BlockModel.blocker_id == blocker_id,
            BlockModel.blocked_id == blocked_id,
        ).first() is not None

    def get_blocked_ids(self, blocker_id: str) -> list[str]:
        rows = self.db.query(BlockModel.blocked_id).filter(
            BlockModel.blocker_id == blocker_id
        ).all()
        return [r[0] for r in rows]


class PgRefreshTokenRepository(RefreshTokenRepository):
    def __init__(self, db: Session):
        self.db = db

    def save(self, token: RefreshToken) -> RefreshToken:
        m = RefreshTokenModel(**token.__dict__)
        self.db.add(m)
        self.db.flush()
        return token

    def find_by_token_hash(self, token_hash: str) -> Optional[RefreshToken]:
        m = self.db.query(RefreshTokenModel).filter(
            RefreshTokenModel.token_hash == token_hash
        ).first()
        if not m:
            return None
        return RefreshToken(
            id=m.id, user_id=m.user_id, token_hash=m.token_hash,
            is_revoked=m.is_revoked, created_at=m.created_at, expires_at=m.expires_at,
        )

    def revoke_all_for_user(self, user_id: str) -> None:
        self.db.query(RefreshTokenModel).filter(
            RefreshTokenModel.user_id == user_id
        ).update({"is_revoked": True})
        self.db.flush()

    def revoke(self, token_id: str) -> None:
        self.db.query(RefreshTokenModel).filter(
            RefreshTokenModel.id == token_id
        ).update({"is_revoked": True})
        self.db.flush()


class PgEmailVerificationTokenRepository:
    """Create and consume email verification tokens (infra-only, no domain entity)."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, user_id: str, token: str, expires_at: datetime) -> None:
        m = EmailVerificationTokenModel(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token=token,
            expires_at=expires_at,
        )
        self.db.add(m)
        self.db.flush()

    def find_valid_by_token(self, token: str) -> Optional[str]:
        """Return user_id if token is valid (not used, not expired), else None."""
        m = self.db.query(EmailVerificationTokenModel).filter(
            EmailVerificationTokenModel.token == token,
            EmailVerificationTokenModel.used_at.is_(None),
            EmailVerificationTokenModel.expires_at > datetime.utcnow(),
        ).first()
        return m.user_id if m else None

    def mark_used(self, token: str) -> None:
        self.db.query(EmailVerificationTokenModel).filter(
            EmailVerificationTokenModel.token == token,
        ).update({"used_at": datetime.utcnow()})
        self.db.flush()


class PgPasswordResetOtpRepository:
    """Create and consume password reset OTPs (infra-only)."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, email: str, otp: str, expires_at: datetime) -> None:
        m = PasswordResetOtpModel(
            id=str(uuid.uuid4()),
            email=email,
            otp=otp,
            expires_at=expires_at,
        )
        self.db.add(m)
        self.db.flush()

    def find_valid(self, email: str, otp: str) -> bool:
        """Return True if a valid (not used, not expired) OTP exists for this email+otp."""
        m = self.db.query(PasswordResetOtpModel).filter(
            PasswordResetOtpModel.email == email,
            PasswordResetOtpModel.otp == otp,
            PasswordResetOtpModel.used_at.is_(None),
            PasswordResetOtpModel.expires_at > datetime.utcnow(),
        ).first()
        return m is not None

    def mark_used(self, email: str, otp: str) -> None:
        self.db.query(PasswordResetOtpModel).filter(
            PasswordResetOtpModel.email == email,
            PasswordResetOtpModel.otp == otp,
        ).update({"used_at": datetime.utcnow()})
        self.db.flush()


class OutboxEventPublisher(EventPublisher):
    """Writes events to the outbox table in the same DB transaction."""

    def __init__(self, db: Session):
        self.db = db

    def publish(self, event_type: str, topic: str, partition_key: str, payload: dict) -> None:
        entry = OutboxModel(
            id=str(uuid.uuid4()),
            event_type=event_type,
            topic=topic,
            partition_key=partition_key,
            payload=json.dumps(payload),
            created_at=datetime.utcnow(),
        )
        self.db.add(entry)
        self.db.flush()
