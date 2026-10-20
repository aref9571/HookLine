import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from hookline.deliveries.models import Delivery, DeliveryAttempt, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.errors import ConflictError, NotFoundError
from hookline.events.models import Event
from hookline.events.service import check_created_range
from hookline.pagination import PageParams
from hookline.users.models import User, UserRole

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = [DeliveryStatus.DEAD, DeliveryStatus.FAILED]


@dataclass
class DeliveryFilters:
    status: DeliveryStatus | None = None
    endpoint_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


@dataclass
class DeliveryDetails:
    delivery: Delivery
    endpoint_url: str
    event_type: str
    attempts: list[DeliveryAttempt]


def visible_deliveries(user: User) -> Select[Delivery]:
    query = select(Delivery).join(Endpoint, Endpoint.id == Delivery.endpoint_id)
    if user.role != UserRole.ADMIN:
        query = query.where(Endpoint.user_id == user.id)
    return query


def apply_filters(query: Select[Delivery], filters: DeliveryFilters) -> Select[Delivery]:
    if filters.status is not None:
        query = query.where(Delivery.status == filters.status)
    if filters.endpoint_id is not None:
        query = query.where(Delivery.endpoint_id == filters.endpoint_id)
    if filters.event_id is not None:
        query = query.where(Delivery.event_id == filters.event_id)
    if filters.created_after is not None:
        query = query.where(Delivery.created_at >= filters.created_after)
    if filters.created_before is not None:
        query = query.where(Delivery.created_at < filters.created_before)
    return query


def list_deliveries(
    session: Session, user: User, filters: DeliveryFilters, page: PageParams
) -> tuple[list[Delivery], int]:
    check_created_range(filters.created_after, filters.created_before)
    query = apply_filters(visible_deliveries(user), filters)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    deliveries = session.scalars(
        query.order_by(Delivery.created_at.desc(), Delivery.id)
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(deliveries), total


def get_delivery_details(session: Session, user: User, delivery_id: uuid.UUID) -> DeliveryDetails:
    row = session.execute(
        visible_deliveries(user)
        .add_columns(Endpoint.url, Event.event_type)
        .join(Event, Event.id == Delivery.event_id)
        .where(Delivery.id == delivery_id)
    ).one_or_none()
    if row is None:
        raise NotFoundError("Delivery not found.")
    delivery, endpoint_url, event_type = row
    return DeliveryDetails(
        delivery=delivery,
        endpoint_url=endpoint_url,
        event_type=event_type,
        attempts=list(delivery.attempts),
    )


def retry_delivery(session: Session, user: User, delivery_id: uuid.UUID, now: datetime) -> Delivery:
    row = session.execute(
        visible_deliveries(user).add_columns(Endpoint.is_active).where(Delivery.id == delivery_id)
    ).one_or_none()
    if row is None:
        raise NotFoundError("Delivery not found.")
    delivery, endpoint_is_active = row
    if not endpoint_is_active:
        raise ConflictError("The endpoint is disabled.")

    requeued_id = session.scalar(
        update(Delivery)
        .where(Delivery.id == delivery.id, Delivery.status.in_(RETRYABLE_STATUSES))
        .values(
            status=DeliveryStatus.PENDING,
            next_attempt_at=now,
            locked_until=None,
            attempt_count=0,
            updated_at=now,
        )
        .returning(Delivery.id)
    )
    if requeued_id is None:
        session.rollback()
        raise ConflictError("Only failed or dead deliveries can be retried.")
    session.commit()
    session.refresh(delivery)
    logger.info("Delivery %s requeued by user %s", delivery.id, user.id)
    return delivery
