import uuid

from fastapi import APIRouter, Response

from hookline.auth.dependencies import CurrentUser
from hookline.clock import Now
from hookline.config import AppSettings
from hookline.database import DbSession
from hookline.endpoints import service
from hookline.endpoints.schemas import (
    EndpointCreate,
    EndpointRead,
    EndpointUpdate,
    EndpointWithSecret,
)
from hookline.endpoints.url_safety import HostResolver
from hookline.pagination import Page, PageQuery

router = APIRouter(prefix="/api/v1/endpoints", tags=["endpoints"])


def with_secret(endpoint_secret: service.EndpointSecret) -> EndpointWithSecret:
    endpoint = EndpointRead.model_validate(endpoint_secret.endpoint)
    return EndpointWithSecret(**endpoint.model_dump(), secret=endpoint_secret.secret)


@router.post("", status_code=201)
def create_endpoint(
    body: EndpointCreate,
    db: DbSession,
    user: CurrentUser,
    settings: AppSettings,
    resolver: HostResolver,
) -> EndpointWithSecret:
    return with_secret(service.create_endpoint(db, user, body, settings, resolver))


@router.get("")
def list_endpoints(
    db: DbSession, user: CurrentUser, page: PageQuery, is_active: bool | None = None
) -> Page[EndpointRead]:
    endpoints, total = service.list_endpoints(db, user, is_active, page)
    return Page[EndpointRead](
        items=[EndpointRead.model_validate(endpoint) for endpoint in endpoints],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{endpoint_id}")
def read_endpoint(endpoint_id: uuid.UUID, db: DbSession, user: CurrentUser) -> EndpointRead:
    return EndpointRead.model_validate(service.get_endpoint(db, user, endpoint_id))


@router.patch("/{endpoint_id}")
def update_endpoint(
    endpoint_id: uuid.UUID,
    body: EndpointUpdate,
    db: DbSession,
    user: CurrentUser,
    settings: AppSettings,
    resolver: HostResolver,
    now: Now,
) -> EndpointRead:
    endpoint = service.update_endpoint(db, user, endpoint_id, body, settings, resolver, now)
    return EndpointRead.model_validate(endpoint)


@router.delete("/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Response:
    service.delete_endpoint(db, user, endpoint_id)
    return Response(status_code=204)


@router.post("/{endpoint_id}/rotate-secret")
def rotate_secret(
    endpoint_id: uuid.UUID, db: DbSession, user: CurrentUser, now: Now
) -> EndpointWithSecret:
    return with_secret(service.rotate_secret(db, user, endpoint_id, now))
