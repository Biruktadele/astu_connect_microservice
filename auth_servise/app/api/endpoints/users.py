from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ...db.session import get_db
from ...services import user_service
from ...schemas.user import UserCreate, UserActive
from ...db.models.user import User
from ...api import deps

router = APIRouter()

@router.post("/register", response_model=UserActive)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    user = user_service.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    return user_service.create_user(db, user_in=user_in)

@router.get("/me", response_model=UserActive)
def read_user_me(current_user: User = Depends(deps.get_current_user)):
    return current_user
