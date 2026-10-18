import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    endpoint_id: uuid.UUID
    status: str
    attempt_count: int
    next_attempt_at: datetime
    locked_until: datetime | None
    last_status_code: int | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class AttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_number: int
    status_code: int | None
    error: str | None
    duration_ms: int
    response_excerpt: str | None
    attempted_at: datetime


class DeliveryDetail(DeliveryRead):
    endpoint_url: str
    event_type: str
    attempts: list[AttemptRead]
