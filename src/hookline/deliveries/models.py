import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hookline.database import Base


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        CheckConstraint("duration_ms >= 0", name="duration_ms_not_negative"),
        UniqueConstraint("delivery_id", "attempt_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    attempt_number: Mapped[int]
    status_code: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(String(500))
    duration_ms: Mapped[int]
    response_excerpt: Mapped[str | None] = mapped_column(String(1000))
    attempted_at: Mapped[datetime]


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'succeeded', 'failed', 'dead')", name="status"
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_not_negative"),
        UniqueConstraint("event_id", "endpoint_id"),
        Index(
            "ix_deliveries_due",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending', 'failed')"),
        ),
        Index("ix_deliveries_endpoint_id_created_at", "endpoint_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    endpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))
    attempt_count: Mapped[int] = mapped_column(server_default=text("0"))
    next_attempt_at: Mapped[datetime]
    locked_until: Mapped[datetime | None]
    last_status_code: Mapped[int | None]
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    attempts: Mapped[list[DeliveryAttempt]] = relationship(
        order_by=DeliveryAttempt.attempt_number, passive_deletes=True
    )
