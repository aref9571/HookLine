import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from hookline.config import Settings
from hookline.endpoints.models import Endpoint
from hookline.endpoints.schemas import EndpointCreate, EndpointUpdate
from hookline.endpoints.url_safety import Resolver, validate_target_url
from hookline.errors import NotFoundError
from hookline.pagination import PageParams
from hookline.users.models import User, UserRole

logger = logging.getLogger(__name__)

SECRET_PREFIX = "whsec_"


@dataclass
class EndpointSecret:
    endpoint: Endpoint
    secret: str = field(repr=False)


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def create_endpoint(
    session: Session, user: User, data: EndpointCreate, settings: Settings, resolver: Resolver
) -> EndpointSecret:
    validate_target_url(data.url, settings, resolver)
    secret = new_secret()
    endpoint = Endpoint(
        user_id=user.id,
        url=data.url,
        description=data.description,
        event_types=data.event_types,
        secret=secret,
    )
    session.add(endpoint)
    session.commit()
    logger.info("Endpoint %s created for user %s", endpoint.id, user.id)
    return EndpointSecret(endpoint=endpoint, secret=secret)


def visible_endpoints(user: User) -> Select[Endpoint]:
    query = select(Endpoint)
    if user.role != UserRole.ADMIN:
        query = query.where(Endpoint.user_id == user.id)
    return query


def list_endpoints(
    session: Session, user: User, is_active: bool | None, page: PageParams
) -> tuple[list[Endpoint], int]:
    query = visible_endpoints(user)
    if is_active is not None:
        query = query.where(Endpoint.is_active == is_active)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    endpoints = session.scalars(
        query.order_by(Endpoint.created_at.desc(), Endpoint.id)
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(endpoints), total


def get_endpoint(session: Session, user: User, endpoint_id: uuid.UUID) -> Endpoint:
    endpoint = session.scalar(visible_endpoints(user).where(Endpoint.id == endpoint_id))
    if endpoint is None:
        raise NotFoundError("Endpoint not found.")
    return endpoint


def update_endpoint(
    session: Session,
    user: User,
    endpoint_id: uuid.UUID,
    changes: EndpointUpdate,
    settings: Settings,
    resolver: Resolver,
    now: datetime,
) -> Endpoint:
    endpoint = get_endpoint(session, user, endpoint_id)
    if changes.url is not None:
        validate_target_url(changes.url, settings, resolver)
        endpoint.url = changes.url
    if "description" in changes.model_fields_set:
        endpoint.description = changes.description
    if changes.event_types is not None:
        endpoint.event_types = changes.event_types
    if changes.is_active is not None:
        endpoint.is_active = changes.is_active
    endpoint.updated_at = now
    session.commit()
    logger.info("Endpoint %s updated by user %s", endpoint.id, user.id)
    return endpoint


def delete_endpoint(session: Session, user: User, endpoint_id: uuid.UUID) -> None:
    endpoint = get_endpoint(session, user, endpoint_id)
    session.delete(endpoint)
    session.commit()
    logger.info("Endpoint %s deleted by user %s", endpoint_id, user.id)


def rotate_secret(
    session: Session, user: User, endpoint_id: uuid.UUID, now: datetime
) -> EndpointSecret:
    endpoint = get_endpoint(session, user, endpoint_id)
    secret = new_secret()
    endpoint.secret = secret
    endpoint.updated_at = now
    session.commit()
    logger.info("Endpoint %s secret rotated by user %s", endpoint.id, user.id)
    return EndpointSecret(endpoint=endpoint, secret=secret)
