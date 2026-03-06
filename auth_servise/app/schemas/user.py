from pydantic import BaseModel, EmailStr
from typing import Optional

class UserBase(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None

class UserCreate(UserBase):
    username: str
    email: EmailStr
    password: str

class UserActive(UserBase):
    id: int
    is_active: bool

    class Config:
        from_attributes = True
