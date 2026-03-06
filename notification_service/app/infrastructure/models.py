from sqlalchemy import Column, String, Boolean, DateTime, Text, JSON, func
from .database import Base


class NotificationModel(Base):
    __tablename__ = "notifications"
    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    data = Column(JSON, default={})
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class NotificationPrefModel(Base):
    __tablename__ = "notification_preferences"
    user_id = Column(String, primary_key=True)
    channel = Column(String, default="in_app")
    enabled = Column(Boolean, default=True)
    notify_follows = Column(Boolean, default=True)
    notify_comments = Column(Boolean, default=True)
    notify_reactions = Column(Boolean, default=True)
    notify_chat = Column(Boolean, default=True)
    notify_community = Column(Boolean, default=True)
