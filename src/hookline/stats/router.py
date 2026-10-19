import uuid

from fastapi import APIRouter

from hookline.auth.dependencies import CurrentUser
from hookline.clock import Now
from hookline.database import DbSession
from hookline.stats import service
from hookline.stats.schemas import Stats

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("")
def read_stats(
    db: DbSession, user: CurrentUser, now: Now, endpoint_id: uuid.UUID | None = None
) -> Stats:
    return service.get_stats(db, user, endpoint_id, now)
