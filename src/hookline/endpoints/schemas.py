import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SECRET_SHOWN_ONCE_MESSAGE = "Store this secret now. It will not be shown again."
ALL_EVENT_TYPES = "*"

EventType = Annotated[str, StringConstraints(pattern=r"^(\*|[a-z0-9][a-z0-9_.-]{0,99})$")]
EventTypeList = Annotated[list[EventType], Field(min_length=1, max_length=50)]
Description = Annotated[str, StringConstraints(max_length=255)]


def check_event_types(event_types: list[str]) -> list[str]:
    if len(set(event_types)) != len(event_types):
        raise ValueError("event types must be unique")
    if ALL_EVENT_TYPES in event_types and len(event_types) > 1:
        raise ValueError("the wildcard * must be the only event type")
    return event_types


class EndpointCreate(BaseModel):
    url: str
    description: Description | None = None
    event_types: EventTypeList

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, event_types: list[str]) -> list[str]:
        return check_event_types(event_types)


class EndpointUpdate(BaseModel):
    url: str | None = None
    description: Description | None = None
    event_types: EventTypeList | None = None
    is_active: bool | None = None

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, event_types: list[str] | None) -> list[str] | None:
        if event_types is None:
            return None
        return check_event_types(event_types)


class EndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    url: str
    description: str | None
    event_types: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class EndpointWithSecret(EndpointRead):
    secret: str
    message: str = SECRET_SHOWN_ONCE_MESSAGE
