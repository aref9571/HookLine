import uuid

from fastapi import APIRouter, Response

from hookline.api_keys import service
from hookline.api_keys.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from hookline.auth.dependencies import CurrentUser
from hookline.clock import Now
from hookline.database import DbSession
from hookline.pagination import Page, PageQuery

router = APIRouter(prefix="/api/v1/api-keys", tags=["api keys"])


@router.post("", status_code=201)
def create_api_key(body: ApiKeyCreate, db: DbSession, user: CurrentUser) -> ApiKeyCreated:
    created = service.create_api_key(db, user, body.name)
    api_key = ApiKeyRead.model_validate(created.api_key)
    return ApiKeyCreated(**api_key.model_dump(), key=created.plaintext)


@router.get("")
def list_api_keys(db: DbSession, user: CurrentUser, page: PageQuery) -> Page[ApiKeyRead]:
    api_keys, total = service.list_api_keys(db, user, page)
    return Page[ApiKeyRead](
        items=[ApiKeyRead.model_validate(api_key) for api_key in api_keys],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.delete("/{api_key_id}", status_code=204)
def revoke_api_key(api_key_id: uuid.UUID, db: DbSession, user: CurrentUser, now: Now) -> Response:
    service.revoke_api_key(db, user, api_key_id, now)
    return Response(status_code=204)
