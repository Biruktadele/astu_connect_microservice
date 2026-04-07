from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CreatePostDTO(BaseModel):
    body: str
    media_refs: list[str] = []
    community_id: Optional[str] = None


class PostResponse(BaseModel):
    id: str
    author_id: str
    author_name: str = ""
    author_avatar: str = ""
    community_id: Optional[str] = None
    body: str
    media_refs: list[str] = []
    reaction_counts: dict = {}
    my_reaction: Optional[str] = None
    comment_count: int = 0
    moderation_status: str = "approved"
    created_at: datetime
    is_saved: bool = False

    model_config = {"from_attributes": True}


class CreateCommentDTO(BaseModel):
    body: str


class CommentResponse(BaseModel):
    id: str
    post_id: str
    author_id: str
    author_name: str = ""
    author_avatar: str = ""
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SetReactionDTO(BaseModel):
    type: str  # like | love | laugh | sad | angry


class TimelineResponse(BaseModel):
    posts: list[PostResponse]
    next_cursor: Optional[str] = None
