import uuid
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from hookline.deliveries.models import Delivery, DeliveryStatus
from hookline.endpoints.models import Endpoint
from hookline.events.models import Event
from hookline.stats.schemas import EndpointStats, RecentActivity, Stats, StatusCounts
from hookline.users.models import User, UserRole

RECENT_PERIOD = timedelta(hours=24)
MAX_ENDPOINTS = 50


def endpoint_conditions(user: User, endpoint_id: uuid.UUID | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if user.role != UserRole.ADMIN:
        conditions.append(Endpoint.user_id == user.id)
    if endpoint_id is not None:
        conditions.append(Endpoint.id == endpoint_id)
    return conditions


def count_by_status(session: Session, conditions: list[ColumnElement[bool]]) -> StatusCounts:
    rows = session.execute(
        select(Delivery.status, func.count())
        .join(Endpoint, Endpoint.id == Delivery.endpoint_id)
        .where(*conditions)
        .group_by(Delivery.status)
    ).all()
    counts = {status: count for status, count in rows}
    return StatusCounts(**{status.value: counts.get(status.value, 0) for status in DeliveryStatus})


def count_recent_events(
    session: Session, user: User, endpoint_id: uuid.UUID | None, since: datetime
) -> int:
    query = select(func.count()).select_from(Event).where(Event.created_at >= since)
    if user.role != UserRole.ADMIN:
        query = query.where(Event.user_id == user.id)
    if endpoint_id is not None:
        query = query.where(
            Event.id.in_(select(Delivery.event_id).where(Delivery.endpoint_id == endpoint_id))
        )
    return session.scalar(query) or 0


def success_rate(succeeded: int, dead: int) -> float | None:
    finished = succeeded + dead
    if finished == 0:
        return None
    return round(succeeded / finished, 4)


def recent_activity(
    session: Session,
    user: User,
    endpoint_id: uuid.UUID | None,
    conditions: list[ColumnElement[bool]],
    since: datetime,
) -> RecentActivity:
    succeeded, dead = session.execute(
        select(
            func.count().filter(Delivery.status == DeliveryStatus.SUCCEEDED),
            func.count().filter(Delivery.status == DeliveryStatus.DEAD),
        )
        .select_from(Delivery)
        .join(Endpoint, Endpoint.id == Delivery.endpoint_id)
        .where(Delivery.updated_at >= since, *conditions)
    ).one()
    return RecentActivity(
        events_received=count_recent_events(session, user, endpoint_id, since),
        deliveries_succeeded=succeeded,
        deliveries_dead=dead,
        success_rate=success_rate(succeeded, dead),
    )


def average_attempts_to_success(
    session: Session, conditions: list[ColumnElement[bool]], since: datetime
) -> float | None:
    average = session.scalar(
        select(func.avg(Delivery.attempt_count))
        .join(Endpoint, Endpoint.id == Delivery.endpoint_id)
        .where(
            Delivery.status == DeliveryStatus.SUCCEEDED,
            Delivery.updated_at >= since,
            *conditions,
        )
    )
    if average is None:
        return None
    return round(float(average), 2)


def list_endpoint_stats(
    session: Session, conditions: list[ColumnElement[bool]], since: datetime
) -> list[EndpointStats]:
    succeeded = func.count(Delivery.id).filter(Delivery.status == DeliveryStatus.SUCCEEDED)
    dead = func.count(Delivery.id).filter(Delivery.status == DeliveryStatus.DEAD)
    rows = session.execute(
        select(Endpoint.id, Endpoint.url, succeeded, dead)
        .outerjoin(
            Delivery, and_(Delivery.endpoint_id == Endpoint.id, Delivery.updated_at >= since)
        )
        .where(*conditions)
        .group_by(Endpoint.id)
        .order_by(dead.desc(), Endpoint.id)
        .limit(MAX_ENDPOINTS)
    ).all()
    return [
        EndpointStats(id=id, url=url, succeeded=succeeded_count, dead=dead_count)
        for id, url, succeeded_count, dead_count in rows
    ]


def get_stats(session: Session, user: User, endpoint_id: uuid.UUID | None, now: datetime) -> Stats:
    since = now - RECENT_PERIOD
    conditions = endpoint_conditions(user, endpoint_id)
    return Stats(
        deliveries_by_status=count_by_status(session, conditions),
        last_24_hours=recent_activity(session, user, endpoint_id, conditions, since),
        average_attempts_to_success=average_attempts_to_success(session, conditions, since),
        endpoints=list_endpoint_stats(session, conditions, since),
    )
