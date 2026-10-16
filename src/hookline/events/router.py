from typing import Annotated

from fastapi import APIRouter, Header, Response

from hookline.auth.dependencies import CurrentApiKey
from hookline.clock import Now
from hookline.config import AppSettings
from hookline.database import DbSession
from hookline.events import service
from hookline.events.schemas import IDEMPOTENCY_KEY_PATTERN, EventCreate, EventCreated

router = APIRouter(prefix="/api/v1/events", tags=["events"])

IdempotencyKeyHeader = Annotated[
    str | None, Header(alias="Idempotency-Key", pattern=IDEMPOTENCY_KEY_PATTERN)
]


@router.post("", status_code=201)
def submit_event(
    body: EventCreate,
    response: Response,
    db: DbSession,
    api_key: CurrentApiKey,
    settings: AppSettings,
    now: Now,
    idempotency_key: IdempotencyKeyHeader = None,
) -> EventCreated:
    submitted = service.submit_event(db, api_key, body, idempotency_key, settings, now)
    if submitted.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return EventCreated(
        id=submitted.id, created_at=submitted.created_at, delivery_count=submitted.delivery_count
    )
