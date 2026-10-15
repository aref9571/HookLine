import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from hookline.auth.schemas import Email, Password


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
