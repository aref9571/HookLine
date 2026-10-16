import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints

from hookline.endpoints.schemas import EVENT_TYPE_PATTERN

IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_.:-]{1,100}$"

EventType = Annotated[str, StringConstraints(pattern="^" + EVENT_TYPE_PATTERN + "$")]


class EventCreate(BaseModel):
    event_type: EventType
    payload: dict[str, Any]


class EventCreated(BaseModel):
    id: uuid.UUID
    created_at: datetime
    delivery_count: int
