from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ....infrastructure.database import get_db
from ....infrastructure.repositories import (
    PgFollowRepository, PgUserRepository, PgBlockRepository, OutboxEventPublisher,
)
from ....application.use_cases import (
    FollowUserUseCase, UnfollowUserUseCase, BlockUserUseCase, UnblockUserUseCase,
)
from ....domain.entities import User
from ..deps import get_current_user

router = APIRouter(prefix="/users", tags=["follows"])


@router.post("/{user_id}/follow", status_code=201)
def follow_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uc = FollowUserUseCase(
        PgFollowRepository(db), PgUserRepository(db),
        PgBlockRepository(db), OutboxEventPublisher(db),
    )
    try:
        uc.execute(current_user.id, user_id)
        db.commit()
        return {"status": "followed"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{user_id}/follow", status_code=204)
def unfollow_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uc = UnfollowUserUseCase(PgFollowRepository(db), OutboxEventPublisher(db))
    try:
        uc.execute(current_user.id, user_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{user_id}/block", status_code=201)
def block_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uc = BlockUserUseCase(PgBlockRepository(db), PgFollowRepository(db), OutboxEventPublisher(db))
    try:
        uc.execute(current_user.id, user_id)
        db.commit()
        return {"status": "blocked"}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{user_id}/block", status_code=204)
def unblock_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uc = UnblockUserUseCase(PgBlockRepository(db), OutboxEventPublisher(db))
    try:
        uc.execute(current_user.id, user_id)
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
