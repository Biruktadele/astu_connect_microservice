from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.repositories import PgUserRepository, PgFollowRepository, OutboxEventPublisher
from ....application.use_cases import GetProfileUseCase, UpdateProfileUseCase
from ....application.dto import UserResponse, UpdateProfileDTO, PaginatedUsers
from ....domain.entities import User
from ..deps import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    uc = GetProfileUseCase(PgUserRepository(db), PgFollowRepository(db))
    data = uc.execute(current_user.id)
    return UserResponse(**data)


@router.patch("/me", response_model=UserResponse)
def update_me(
    dto: UpdateProfileDTO,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uc = UpdateProfileUseCase(PgUserRepository(db), OutboxEventPublisher(db))
    try:
        user = uc.execute(current_user.id, dto)
        db.commit()
        return UserResponse(**user.__dict__)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str, db: Session = Depends(get_db)):
    uc = GetProfileUseCase(PgUserRepository(db), PgFollowRepository(db))
    try:
        data = uc.execute(user_id)
        return UserResponse(**data)
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")


@router.get("/{user_id}/followers", response_model=PaginatedUsers)
def get_followers(user_id: str, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    repo = PgFollowRepository(db)
    users = repo.get_followers(user_id, limit, offset)
    total = repo.count_followers(user_id)
    return PaginatedUsers(
        users=[UserResponse(**u.__dict__) for u in users],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{user_id}/following", response_model=PaginatedUsers)
def get_following(user_id: str, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    repo = PgFollowRepository(db)
    users = repo.get_following(user_id, limit, offset)
    total = repo.count_following(user_id)
    return PaginatedUsers(
        users=[UserResponse(**u.__dict__) for u in users],
        total=total, limit=limit, offset=offset,
    )
