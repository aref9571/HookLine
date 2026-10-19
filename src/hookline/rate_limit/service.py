import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from hookline.rate_limit.models import RateLimitWindow

WINDOW_LENGTH = timedelta(minutes=1)
WINDOW_RETENTION = timedelta(hours=1)


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


def window_start_for(now: datetime) -> datetime:
    return now.replace(second=0, microsecond=0)


def seconds_left_in_window(now: datetime, window_start: datetime) -> int:
    seconds_left = (window_start + WINDOW_LENGTH - now).total_seconds()
    return max(math.ceil(seconds_left), 1)


def check_and_count(
    session: Session, api_key_id: uuid.UUID, now: datetime, limit: int
) -> RateLimitResult:
    window_start = window_start_for(now)
    statement = (
        insert(RateLimitWindow)
        .values(api_key_id=api_key_id, window_start=window_start, request_count=1)
        .on_conflict_do_update(
            index_elements=[RateLimitWindow.api_key_id, RateLimitWindow.window_start],
            set_={"request_count": RateLimitWindow.request_count + 1},
        )
        .returning(RateLimitWindow.request_count)
    )
    request_count = session.execute(statement).scalar_one()
    session.commit()
    return RateLimitResult(
        allowed=request_count <= limit,
        limit=limit,
        remaining=max(limit - request_count, 0),
        retry_after_seconds=seconds_left_in_window(now, window_start),
    )


def rate_limit_headers(result: RateLimitResult) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
    }


def delete_old_windows(session: Session, now: datetime) -> None:
    session.execute(
        delete(RateLimitWindow).where(RateLimitWindow.window_start < now - WINDOW_RETENTION)
    )
    session.commit()
