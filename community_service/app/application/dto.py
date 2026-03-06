from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CreateCommunityDTO(BaseModel):
    name: str
    slug: str
    description: str = ""
    avatar_url: str = ""
    visibility: str = "public"


class UpdateCommunityDTO(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    visibility: Optional[str] = None


class CommunityResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    avatar_url: str
    visibility: str
    owner_id: str
    member_count: int
    is_member: bool = False
    my_role: Optional[str] = None
    created_at: datetime


class MembershipResponse(BaseModel):
    user_id: str
    role: str
    joined_at: datetime


class CreateCommunityPostDTO(BaseModel):
    title: str = ""
    body: str


class CommunityPostResponse(BaseModel):
    id: str
    community_id: str
    author_id: str
    title: str
    body: str
    is_pinned: bool
    created_at: datetime


class SetRoleDTO(BaseModel):
    role: str
