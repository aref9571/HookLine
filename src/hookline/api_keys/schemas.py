import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

KEY_SHOWN_ONCE_MESSAGE = "Store this key now. It will not be shown again."

ApiKeyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ApiKeyCreate(BaseModel):
    name: ApiKeyName


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    key: str
    message: str = KEY_SHOWN_ONCE_MESSAGE
