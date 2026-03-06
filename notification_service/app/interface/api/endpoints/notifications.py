from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ....infrastructure.database import get_db
from ....infrastructure.models import NotificationModel, NotificationPrefModel
from ..deps import get_current_user_id

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: str
    data: dict
    is_read: bool
    created_at: datetime


class PreferenceDTO(BaseModel):
    enabled: Optional[bool] = None
    notify_follows: Optional[bool] = None
    notify_comments: Optional[bool] = None
    notify_reactions: Optional[bool] = None
    notify_chat: Optional[bool] = None
    notify_community: Optional[bool] = None


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    limit: int = 50, offset: int = 0, unread_only: bool = False,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    q = db.query(NotificationModel).filter(NotificationModel.user_id == user_id)
    if unread_only:
        q = q.filter(NotificationModel.is_read == False)
    rows = q.order_by(NotificationModel.created_at.desc()).limit(limit).offset(offset).all()
    return [NotificationResponse(id=r.id, type=r.type, title=r.title, body=r.body,
                                  data=r.data or {}, is_read=r.is_read, created_at=r.created_at) for r in rows]


@router.get("/unread-count")
def unread_count(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    count = db.query(NotificationModel).filter(
        NotificationModel.user_id == user_id, NotificationModel.is_read == False
    ).count()
    return {"unread_count": count}


@router.post("/{notif_id}/read")
def mark_read(notif_id: str, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    n = db.query(NotificationModel).filter(
        NotificationModel.id == notif_id, NotificationModel.user_id == user_id
    ).first()
    if not n:
        raise HTTPException(status_code=404)
    n.is_read = True
    db.commit()
    return {"status": "read"}


@router.post("/read-all")
def mark_all_read(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    db.query(NotificationModel).filter(
        NotificationModel.user_id == user_id, NotificationModel.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"status": "all_read"}


@router.get("/preferences")
def get_preferences(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    pref = db.query(NotificationPrefModel).filter(NotificationPrefModel.user_id == user_id).first()
    if not pref:
        return {"enabled": True, "notify_follows": True, "notify_comments": True,
                "notify_reactions": True, "notify_chat": True, "notify_community": True}
    return {
        "enabled": pref.enabled, "notify_follows": pref.notify_follows,
        "notify_comments": pref.notify_comments, "notify_reactions": pref.notify_reactions,
        "notify_chat": pref.notify_chat, "notify_community": pref.notify_community,
    }


@router.put("/preferences")
def update_preferences(dto: PreferenceDTO, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    pref = db.query(NotificationPrefModel).filter(NotificationPrefModel.user_id == user_id).first()
    if not pref:
        pref = NotificationPrefModel(user_id=user_id)
        db.add(pref)
    for k, v in dto.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(pref, k, v)
    db.commit()
    return {"status": "updated"}
