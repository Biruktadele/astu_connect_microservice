"""Use cases — orchestrate domain objects and ports. No framework imports."""

from datetime import datetime, timedelta
from typing import Callable, Optional
import hashlib, secrets

from ..domain.entities import User, Follow, Block, RefreshToken
from ..domain.repositories import (
    UserRepository, FollowRepository, BlockRepository,
    RefreshTokenRepository, EventPublisher,
)
from .dto import RegisterDTO, LoginDTO, UpdateProfileDTO


def _is_astu_email(email: str) -> bool:
    return email.endswith("@astu.edu.et") or email.endswith(".edu.et") or email.endswith("@gmail.com")


class RegisterUserUseCase:
    def __init__(
        self,
        user_repo: UserRepository,
        event_pub: EventPublisher,
        send_verification_fn: Optional[Callable[[str, str], None]] = None,
    ):
        self.user_repo = user_repo
        self.event_pub = event_pub
        self.send_verification_fn = send_verification_fn

    def execute(self, dto: RegisterDTO, hash_password_fn) -> User:
        if not _is_astu_email(dto.email):
            raise ValueError("Email must be an ASTU student email or @gmail.com for testing")
        if self.user_repo.find_by_email(dto.email):
            raise ValueError("Email already registered")
        if self.user_repo.find_by_username(dto.username):
            raise ValueError("Username already taken")

        user = User(
            email=dto.email,
            username=dto.username,
            display_name=dto.display_name,
            department=dto.department,
            year_of_study=dto.year_of_study,
            hashed_password=hash_password_fn(dto.password),
            email_verified=False,
            is_astu_student=True,
        )
        saved = self.user_repo.save(user)
        if self.send_verification_fn:
            self.send_verification_fn(saved.id, saved.email)
        self.event_pub.publish(
            event_type="user.created",
            topic="user.events",
            partition_key=saved.id,
            payload={
                "user_id": saved.id,
                "username": saved.username,
                "display_name": saved.display_name,
                "email": saved.email,
                "department": saved.department,
                "avatar_url": saved.avatar_url,
                "created_at": saved.created_at.isoformat(),
            },
        )
        return saved


class LoginUserUseCase:
    def __init__(self, user_repo: UserRepository, token_repo: RefreshTokenRepository):
        self.user_repo = user_repo
        self.token_repo = token_repo

    def execute(
        self,
        dto: LoginDTO,
        verify_password_fn,
        create_access_fn,
        refresh_expire_days: int,
        require_email_verification: bool = True,
    ) -> dict:
        user = self.user_repo.find_by_email(dto.email)
        if not user or not verify_password_fn(dto.password, user.hashed_password):
            raise ValueError("Invalid credentials")
        if not user.is_active:
            raise ValueError("Account is deactivated")
        if require_email_verification and not user.email_verified:
            raise ValueError("Verify your email to sign in")

        access_token = create_access_fn(user.id, user.roles)
        raw_refresh = secrets.token_urlsafe(64)
        token_hash = hashlib.sha256(raw_refresh.encode()).hexdigest()

        rt = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(days=refresh_expire_days),
        )
        self.token_repo.save(rt)

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
        }


class RefreshTokenUseCase:
    def __init__(self, token_repo: RefreshTokenRepository, user_repo: UserRepository):
        self.token_repo = token_repo
        self.user_repo = user_repo

    def execute(self, raw_refresh: str, create_access_fn, refresh_expire_days: int) -> dict:
        token_hash = hashlib.sha256(raw_refresh.encode()).hexdigest()
        rt = self.token_repo.find_by_token_hash(token_hash)
        if not rt or rt.is_revoked:
            raise ValueError("Invalid refresh token")
        if rt.expires_at and rt.expires_at < datetime.utcnow():
            raise ValueError("Refresh token expired")

        self.token_repo.revoke(rt.id)

        user = self.user_repo.find_by_id(rt.user_id)
        if not user or not user.is_active:
            raise ValueError("User not found or inactive")

        access_token = create_access_fn(user.id, user.roles)
        new_raw = secrets.token_urlsafe(64)
        new_hash = hashlib.sha256(new_raw.encode()).hexdigest()
        new_rt = RefreshToken(
            user_id=user.id,
            token_hash=new_hash,
            expires_at=datetime.utcnow() + timedelta(days=refresh_expire_days),
        )
        self.token_repo.save(new_rt)
        return {"access_token": access_token, "refresh_token": new_raw, "token_type": "bearer"}


class VerifyEmailUseCase:
    """Consume verification token from link; set user.email_verified=True."""

    def __init__(self, user_repo: UserRepository, verification_token_repo):
        self.user_repo = user_repo
        self.verification_token_repo = verification_token_repo

    def execute(self, token: str) -> None:
        user_id = self.verification_token_repo.find_valid_by_token(token)
        if not user_id:
            raise ValueError("Invalid or expired verification link")
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        user.email_verified = True
        self.user_repo.update(user)
        self.verification_token_repo.mark_used(token)


class ForgotPasswordUseCase:
    """Generate OTP, store it, send to user email. Always return success to avoid enumeration."""

    def __init__(self, user_repo: UserRepository, create_otp_and_send_fn: Callable[[str], None]):
        self.user_repo = user_repo
        self.create_otp_and_send_fn = create_otp_and_send_fn

    def execute(self, email: str) -> None:
        user = self.user_repo.find_by_email(email)
        if not user:
            return
        self.create_otp_and_send_fn(email)


class ResetPasswordUseCase:
    """Validate OTP, update password, mark OTP used."""

    def __init__(self, user_repo: UserRepository, otp_repo, hash_password_fn):
        self.user_repo = user_repo
        self.otp_repo = otp_repo
        self.hash_password_fn = hash_password_fn

    def execute(self, email: str, otp: str, new_password: str) -> None:
        if not self.otp_repo.find_valid(email, otp):
            raise ValueError("Invalid or expired OTP")
        self.otp_repo.mark_used(email, otp)
        user = self.user_repo.find_by_email(email)
        if not user:
            raise ValueError("User not found")
        user.hashed_password = self.hash_password_fn(new_password)
        self.user_repo.update(user)


class GetProfileUseCase:
    def __init__(self, user_repo: UserRepository, follow_repo: FollowRepository):
        self.user_repo = user_repo
        self.follow_repo = follow_repo

    def execute(self, user_id: str) -> dict:
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        return {
            **user.__dict__,
            "follower_count": self.follow_repo.count_followers(user_id),
            "following_count": self.follow_repo.count_following(user_id),
        }


class UpdateProfileUseCase:
    def __init__(self, user_repo: UserRepository, event_pub: EventPublisher):
        self.user_repo = user_repo
        self.event_pub = event_pub

    def execute(self, user_id: str, dto: UpdateProfileDTO) -> User:
        user = self.user_repo.find_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        changed = []
        for field_name, value in dto.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(user, field_name, value)
                changed.append(field_name)

        updated = self.user_repo.update(user)
        if changed:
            self.event_pub.publish(
                event_type="user.updated",
                topic="user.events",
                partition_key=user_id,
                payload={
                    "user_id": user_id,
                    "changed_fields": changed,
                    "display_name": updated.display_name,
                    "avatar_url": updated.avatar_url,
                    "department": updated.department,
                },
            )
        return updated


class FollowUserUseCase:
    def __init__(
        self, follow_repo: FollowRepository, user_repo: UserRepository,
        block_repo: BlockRepository, event_pub: EventPublisher,
    ):
        self.follow_repo = follow_repo
        self.user_repo = user_repo
        self.block_repo = block_repo
        self.event_pub = event_pub

    def execute(self, follower_id: str, followee_id: str) -> Follow:
        if follower_id == followee_id:
            raise ValueError("Cannot follow yourself")
        if not self.user_repo.find_by_id(followee_id):
            raise ValueError("User not found")
        if self.block_repo.is_blocked(followee_id, follower_id):
            raise ValueError("You are blocked by this user")
        if self.follow_repo.exists(follower_id, followee_id):
            raise ValueError("Already following")

        follow = Follow(follower_id=follower_id, followee_id=followee_id)
        saved = self.follow_repo.save(follow)
        self.event_pub.publish(
            event_type="user.followed",
            topic="user.events",
            partition_key=follower_id,
            payload={
                "follower_id": follower_id,
                "followee_id": followee_id,
                "followed_at": saved.created_at.isoformat(),
            },
        )
        return saved


class UnfollowUserUseCase:
    def __init__(self, follow_repo: FollowRepository, event_pub: EventPublisher):
        self.follow_repo = follow_repo
        self.event_pub = event_pub

    def execute(self, follower_id: str, followee_id: str) -> None:
        if not self.follow_repo.delete(follower_id, followee_id):
            raise ValueError("Not following this user")
        self.event_pub.publish(
            event_type="user.unfollowed",
            topic="user.events",
            partition_key=follower_id,
            payload={"follower_id": follower_id, "followee_id": followee_id},
        )


class BlockUserUseCase:
    def __init__(
        self, block_repo: BlockRepository, follow_repo: FollowRepository,
        event_pub: EventPublisher,
    ):
        self.block_repo = block_repo
        self.follow_repo = follow_repo
        self.event_pub = event_pub

    def execute(self, blocker_id: str, blocked_id: str) -> Block:
        if blocker_id == blocked_id:
            raise ValueError("Cannot block yourself")
        self.follow_repo.delete(blocker_id, blocked_id)
        self.follow_repo.delete(blocked_id, blocker_id)

        block = Block(blocker_id=blocker_id, blocked_id=blocked_id)
        saved = self.block_repo.save(block)
        self.event_pub.publish(
            event_type="user.blocked",
            topic="user.events",
            partition_key=blocker_id,
            payload={
                "blocker_id": blocker_id,
                "blocked_id": blocked_id,
                "blocked_at": saved.created_at.isoformat(),
            },
        )
        return saved


class UnblockUserUseCase:
    def __init__(self, block_repo: BlockRepository, event_pub: EventPublisher):
        self.block_repo = block_repo
        self.event_pub = event_pub

    def execute(self, blocker_id: str, blocked_id: str) -> None:
        if not self.block_repo.delete(blocker_id, blocked_id):
            raise ValueError("User is not blocked")
        self.event_pub.publish(
            event_type="user.unblocked",
            topic="user.events",
            partition_key=blocker_id,
            payload={"blocker_id": blocker_id, "unblocked_id": blocked_id},
        )
