import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from hookline.auth.schemas import Email, Password
from hookline.users.models import UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime


class AdminCreate(BaseModel):
    email: Email
    password: Password


class UserCreate(BaseModel):
    email: Email
    password: Password
    role: UserRole


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
