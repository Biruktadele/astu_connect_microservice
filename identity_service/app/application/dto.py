from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class RegisterDTO(BaseModel):
    email: EmailStr
    username: str
    password: str
    display_name: str
    department: str = ""
    year_of_study: int = 0


class LoginDTO(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshDTO(BaseModel):
    refresh_token: str


class ForgotPasswordDTO(BaseModel):
    email: EmailStr


class ResetPasswordDTO(BaseModel):
    email: EmailStr
    otp: str
    new_password: str


class ResendVerificationDTO(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    display_name: str
    department: str
    year_of_study: int
    bio: str
    avatar_url: str
    is_active: bool
    email_verified: bool = False
    is_astu_student: bool = False
    roles: list[str] = ["student"]
    created_at: datetime
    follower_count: int = 0
    following_count: int = 0

    model_config = {"from_attributes": True}


class UpdateProfileDTO(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    department: Optional[str] = None
    year_of_study: Optional[int] = None


class FollowResponse(BaseModel):
    follower_id: str
    followee_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedUsers(BaseModel):
    users: list[UserResponse]
    total: int
    limit: int
    offset: int
