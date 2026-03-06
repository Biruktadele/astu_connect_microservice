import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.repositories import (
    PgUserRepository, PgRefreshTokenRepository, OutboxEventPublisher,
    PgEmailVerificationTokenRepository, PgPasswordResetOtpRepository,
)
from ....infrastructure.security import hash_password, verify_password, create_access_token
from ....infrastructure.email_sender import send_verification_email, send_otp_email
from ....application.use_cases import (
    RegisterUserUseCase, LoginUserUseCase, RefreshTokenUseCase,
    VerifyEmailUseCase, ForgotPasswordUseCase, ResetPasswordUseCase,
)
from ....application.dto import (
    RegisterDTO, LoginDTO, RefreshDTO, TokenResponse, UserResponse,
    ForgotPasswordDTO, ResetPasswordDTO,
)
from ....core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _create_and_send_verification(db: Session):
    """Return a callable(user_id, email) that creates a token and sends the email. Never raises."""
    def _send(user_id: str, email: str) -> None:
        try:
            token = secrets.token_urlsafe(48)
            expires_at = datetime.utcnow() + timedelta(hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS)
            repo = PgEmailVerificationTokenRepository(db)
            repo.create(user_id=user_id, token=token, expires_at=expires_at)
            link = f"{settings.APP_BASE_URL}{settings.API_V1_STR}/auth/verify-email?token={token}"
            send_verification_email(email, link)
        except Exception as e:
            logger.exception("Verification email failed for %s: %s", email, e)
    return _send


def _create_otp_and_send(db: Session):
    """Return a callable(email) that creates an OTP and sends it."""
    def _send(email: str) -> None:
        otp = "".join([str(secrets.randbelow(10)) for _ in range(settings.OTP_LENGTH)])
        expires_at = datetime.utcnow() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)
        repo = PgPasswordResetOtpRepository(db)
        repo.create(email=email, otp=otp, expires_at=expires_at)
        send_otp_email(email, otp)
    return _send


@router.post("/register", response_model=UserResponse, status_code=201)
def register(dto: RegisterDTO, db: Session = Depends(get_db)):
    uc = RegisterUserUseCase(
        PgUserRepository(db),
        OutboxEventPublisher(db),
        send_verification_fn=_create_and_send_verification(db),
    )
    try:
        user = uc.execute(dto, hash_password)
        db.commit()
        return UserResponse(**user.__dict__)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/verify-email")
def verify_email(token: str = Query(...), db: Session = Depends(get_db)):
    uc = VerifyEmailUseCase(
        PgUserRepository(db),
        PgEmailVerificationTokenRepository(db),
    )
    try:
        uc.execute(token)
        db.commit()
        return {"message": "Email verified successfully"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=TokenResponse)
def login(dto: LoginDTO, db: Session = Depends(get_db)):
    uc = LoginUserUseCase(PgUserRepository(db), PgRefreshTokenRepository(db))
    try:
        result = uc.execute(
            dto, verify_password, create_access_token,
            settings.REFRESH_TOKEN_EXPIRE_DAYS,
            require_email_verification=settings.REQUIRE_EMAIL_VERIFICATION,
        )
        db.commit()
        return TokenResponse(**result)
    except ValueError as e:
        detail = str(e)
        code = 403 if "Verify your email" in detail else 401
        raise HTTPException(status_code=code, detail=detail)


@router.post("/refresh", response_model=TokenResponse)
def refresh(dto: RefreshDTO, db: Session = Depends(get_db)):
    uc = RefreshTokenUseCase(PgRefreshTokenRepository(db), PgUserRepository(db))
    try:
        result = uc.execute(dto.refresh_token, create_access_token, settings.REFRESH_TOKEN_EXPIRE_DAYS)
        db.commit()
        return TokenResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/forgot-password")
def forgot_password(dto: ForgotPasswordDTO, db: Session = Depends(get_db)):
    uc = ForgotPasswordUseCase(
        PgUserRepository(db),
        create_otp_and_send_fn=_create_otp_and_send(db),
    )
    uc.execute(dto.email)
    db.commit()
    return {"message": "If an account with that email exists, a reset code has been sent"}


@router.post("/reset-password")
def reset_password(dto: ResetPasswordDTO, db: Session = Depends(get_db)):
    uc = ResetPasswordUseCase(
        PgUserRepository(db),
        PgPasswordResetOtpRepository(db),
        hash_password,
    )
    try:
        uc.execute(dto.email, dto.otp, dto.new_password)
        db.commit()
        return {"message": "Password reset successfully"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
