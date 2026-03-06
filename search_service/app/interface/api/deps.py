from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from ...core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user_id(token: str = Depends(oauth2_scheme)) -> str:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        uid = payload.get("sub")
        if not uid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return uid
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
