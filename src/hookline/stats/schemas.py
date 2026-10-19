import uuid

from pydantic import BaseModel


class StatusCounts(BaseModel):
    pending: int
    in_progress: int
    succeeded: int
    failed: int
    dead: int


class RecentActivity(BaseModel):
    events_received: int
    deliveries_succeeded: int
    deliveries_dead: int
    success_rate: float | None


class EndpointStats(BaseModel):
    id: uuid.UUID
    url: str
    succeeded: int
    dead: int


class Stats(BaseModel):
    deliveries_by_status: StatusCounts
    last_24_hours: RecentActivity
    average_attempts_to_success: float | None
    endpoints: list[EndpointStats]
