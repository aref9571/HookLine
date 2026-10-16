import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from hookline.api_keys.models import ApiKey
from hookline.config import Settings
from hookline.deliveries.models import Delivery, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.endpoints.schemas import ALL_EVENT_TYPES
from hookline.errors import ConflictError, ContentTooLargeError
from hookline.events.models import Event
from hookline.events.schemas import EventCreate

logger = logging.getLogger(__name__)


@dataclass
class SubmittedEvent:
    id: uuid.UUID
    created_at: datetime
    delivery_count: int
    replayed: bool


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def compute_request_hash(data: EventCreate) -> str:
    return hashlib.sha256(canonical_json(data.model_dump()).encode()).hexdigest()


def check_payload_size(payload: dict[str, Any], settings: Settings) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > settings.max_payload_bytes:
        raise ContentTooLargeError(
            "The payload must be at most " + str(settings.max_payload_bytes) + " bytes."
        )


def create_deliveries(
    session: Session, event_id: uuid.UUID, user_id: uuid.UUID, event_type: str, now: datetime
) -> int:
    matching_endpoints = select(
        literal(event_id),
        Endpoint.id,
        literal(DeliveryStatus.PENDING.value),
        literal(now, DateTime(timezone=True)),
    ).where(
        Endpoint.user_id == user_id,
        Endpoint.is_active.is_(True),
        Endpoint.event_types.overlap([event_type, ALL_EVENT_TYPES]),
    )
    statement = (
        insert(Delivery)
        .from_select(["event_id", "endpoint_id", "status", "next_attempt_at"], matching_endpoints)
        .returning(Delivery.id)
    )
    return len(session.execute(statement).all())


def count_deliveries(session: Session, event_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).where(Delivery.event_id == event_id)) or 0


def replay_event(
    session: Session, user_id: uuid.UUID, idempotency_key: str | None, request_hash: str
) -> SubmittedEvent:
    event = session.scalars(
        select(Event).where(Event.user_id == user_id, Event.idempotency_key == idempotency_key)
    ).one()
    if event.request_hash != request_hash:
        raise ConflictError("The idempotency key was already used with a different request.")
    logger.info("Event %s replayed for idempotency key", event.id)
    return SubmittedEvent(
        id=event.id,
        created_at=event.created_at,
        delivery_count=count_deliveries(session, event.id),
        replayed=True,
    )


def submit_event(
    session: Session,
    api_key: ApiKey,
    data: EventCreate,
    idempotency_key: str | None,
    settings: Settings,
    now: datetime,
) -> SubmittedEvent:
    check_payload_size(data.payload, settings)
    request_hash = compute_request_hash(data)
    event_id = session.scalar(
        insert(Event)
        .values(
            user_id=api_key.user_id,
            api_key_id=api_key.id,
            event_type=data.event_type,
            payload=data.payload,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            created_at=now,
        )
        .on_conflict_do_nothing(constraint="events_idempotency_uk")
        .returning(Event.id)
    )
    if event_id is None:
        return replay_event(session, api_key.user_id, idempotency_key, request_hash)

    delivery_count = create_deliveries(session, event_id, api_key.user_id, data.event_type, now)
    session.commit()
    logger.info("Event %s accepted with %s deliveries", event_id, delivery_count)
    return SubmittedEvent(
        id=event_id, created_at=now, delivery_count=delivery_count, replayed=False
    )
