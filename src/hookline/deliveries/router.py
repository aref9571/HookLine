import uuid

from fastapi import APIRouter
from pydantic import AwareDatetime

from hookline.auth.dependencies import CurrentUser
from hookline.database import DbSession
from hookline.deliveries import service
from hookline.deliveries.models import DeliveryStatus
from hookline.deliveries.schemas import AttemptRead, DeliveryDetail, DeliveryRead
from hookline.pagination import Page, PageQuery

router = APIRouter(prefix="/api/v1/deliveries", tags=["deliveries"])


@router.get("")
def list_deliveries(
    db: DbSession,
    user: CurrentUser,
    page: PageQuery,
    status: DeliveryStatus | None = None,
    endpoint_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    created_after: AwareDatetime | None = None,
    created_before: AwareDatetime | None = None,
) -> Page[DeliveryRead]:
    filters = service.DeliveryFilters(
        status=status,
        endpoint_id=endpoint_id,
        event_id=event_id,
        created_after=created_after,
        created_before=created_before,
    )
    deliveries, total = service.list_deliveries(db, user, filters, page)
    return Page[DeliveryRead](
        items=[DeliveryRead.model_validate(delivery) for delivery in deliveries],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{delivery_id}")
def read_delivery(delivery_id: uuid.UUID, db: DbSession, user: CurrentUser) -> DeliveryDetail:
    details = service.get_delivery_details(db, user, delivery_id)
    return DeliveryDetail(
        **DeliveryRead.model_validate(details.delivery).model_dump(),
        endpoint_url=details.endpoint_url,
        event_type=details.event_type,
        attempts=[AttemptRead.model_validate(attempt) for attempt in details.attempts],
    )
