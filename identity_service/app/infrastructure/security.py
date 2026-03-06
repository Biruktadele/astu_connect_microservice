import bcrypt
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional

from ..core.config import settings


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(
        plain.encode("utf-8")[:72],
        hashed.encode("utf-8"),
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8")[:72],
        bcrypt.gensalt(),
    ).decode("utf-8")


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "iss": "astu-connect-identity"},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
