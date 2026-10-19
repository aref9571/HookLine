import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Response
from pydantic import AwareDatetime

from hookline.auth.dependencies import CurrentApiKey, CurrentUser
from hookline.clock import Now
from hookline.config import AppSettings
from hookline.database import DbSession
from hookline.errors import RateLimitExceededError
from hookline.events import service
from hookline.events.schemas import (
    IDEMPOTENCY_KEY_PATTERN,
    DeliverySummary,
    EventCreate,
    EventCreated,
    EventDetail,
    EventRead,
)
from hookline.pagination import Page, PageQuery
from hookline.rate_limit.service import check_and_count, rate_limit_headers

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
    rate_limit = check_and_count(db, api_key.id, now, settings.rate_limit_per_minute)
    headers = rate_limit_headers(rate_limit)
    if not rate_limit.allowed:
        raise RateLimitExceededError(rate_limit.retry_after_seconds, headers)
    response.headers.update(headers)
    submitted = service.submit_event(db, api_key, body, idempotency_key, settings, now)
    if submitted.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return EventCreated(
        id=submitted.id, created_at=submitted.created_at, delivery_count=submitted.delivery_count
    )


@router.get("")
def list_events(
    db: DbSession,
    user: CurrentUser,
    page: PageQuery,
    event_type: str | None = None,
    created_after: AwareDatetime | None = None,
    created_before: AwareDatetime | None = None,
) -> Page[EventRead]:
    events, total = service.list_events(db, user, event_type, created_after, created_before, page)
    return Page[EventRead](
        items=[EventRead.model_validate(event) for event in events],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{event_id}")
def read_event(event_id: uuid.UUID, db: DbSession, user: CurrentUser) -> EventDetail:
    event, deliveries = service.get_event(db, user, event_id)
    return EventDetail(
        **EventRead.model_validate(event).model_dump(),
        payload=event.payload,
        deliveries=[DeliverySummary.model_validate(delivery) for delivery in deliveries],
    )
