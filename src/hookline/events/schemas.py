import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

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


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    api_key_id: uuid.UUID | None
    event_type: str
    idempotency_key: str | None
    created_at: datetime


class DeliverySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint_id: uuid.UUID
    status: str
    attempt_count: int


class EventDetail(EventRead):
    payload: dict[str, Any]
    deliveries: list[DeliverySummary]
