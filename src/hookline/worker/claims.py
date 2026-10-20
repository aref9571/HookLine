import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, ScalarSelect, and_, func, or_, select, update
from sqlalchemy.orm import Session

from hookline.deliveries.models import Delivery, DeliveryAttempt, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.events.models import Event

logger = logging.getLogger(__name__)

ENDPOINT_DISABLED_ERROR = "endpoint disabled"


@dataclass
class ClaimedDelivery:
    delivery_id: uuid.UUID
    attempt_number: int
    attempt_count: int
    locked_until: datetime
    url: str = field(repr=False)
    secret: str = field(repr=False)
    event_id: uuid.UUID
    event_type: str
    event_created_at: datetime
    payload: dict[str, Any] = field(repr=False)


def next_attempt_number() -> ScalarSelect[int]:
    highest_attempt = func.coalesce(func.max(DeliveryAttempt.attempt_number), 0)
    return (
        select(highest_attempt + 1)
        .where(DeliveryAttempt.delivery_id == Delivery.id)
        .scalar_subquery()
    )


def is_due(now: datetime) -> ColumnElement[bool]:
    waiting = and_(
        Delivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.FAILED]),
        Delivery.next_attempt_at <= now,
    )
    lease_expired = and_(
        Delivery.status == DeliveryStatus.IN_PROGRESS,
        Delivery.locked_until < now,
    )
    return or_(waiting, lease_expired)


def mark_endpoint_disabled(session: Session, delivery_ids: list[uuid.UUID], now: datetime) -> None:
    session.execute(
        update(Delivery)
        .where(Delivery.id.in_(delivery_ids))
        .values(
            status=DeliveryStatus.DEAD,
            locked_until=None,
            last_error=ENDPOINT_DISABLED_ERROR,
            updated_at=now,
        )
    )
    for delivery_id in delivery_ids:
        logger.warning("Delivery %s is dead because its endpoint is disabled", delivery_id)


def start_lease(
    session: Session, delivery_ids: list[uuid.UUID], locked_until: datetime, now: datetime
) -> None:
    session.execute(
        update(Delivery)
        .where(Delivery.id.in_(delivery_ids))
        .values(status=DeliveryStatus.IN_PROGRESS, locked_until=locked_until, updated_at=now)
    )


def claim_due_deliveries(
    session: Session, now: datetime, batch_size: int, lease_seconds: int
) -> list[ClaimedDelivery]:
    rows = session.execute(
        select(
            Delivery.id.label("delivery_id"),
            next_attempt_number().label("attempt_number"),
            Delivery.attempt_count,
            Endpoint.is_active,
            Endpoint.url,
            Endpoint.secret,
            Event.id.label("event_id"),
            Event.event_type,
            Event.created_at.label("event_created_at"),
            Event.payload,
        )
        .join(Endpoint, Endpoint.id == Delivery.endpoint_id)
        .join(Event, Event.id == Delivery.event_id)
        .where(is_due(now))
        .order_by(Delivery.next_attempt_at, Delivery.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True, of=Delivery)
    ).all()

    locked_until = now + timedelta(seconds=lease_seconds)
    claimed = []
    disabled_ids = []
    for row in rows:
        if not row.is_active:
            disabled_ids.append(row.delivery_id)
            continue
        claimed.append(
            ClaimedDelivery(
                delivery_id=row.delivery_id,
                attempt_number=row.attempt_number,
                attempt_count=row.attempt_count,
                locked_until=locked_until,
                url=row.url,
                secret=row.secret,
                event_id=row.event_id,
                event_type=row.event_type,
                event_created_at=row.event_created_at,
                payload=row.payload,
            )
        )

    if disabled_ids:
        mark_endpoint_disabled(session, disabled_ids, now)
    if claimed:
        start_lease(session, [item.delivery_id for item in claimed], locked_until, now)
    session.commit()
    return claimed
