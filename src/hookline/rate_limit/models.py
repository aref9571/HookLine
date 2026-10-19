import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from hookline.database import Base


class RateLimitWindow(Base):
    __tablename__ = "rate_limit_windows"
    __table_args__ = (CheckConstraint("request_count >= 0", name="request_count_not_negative"),)

    api_key_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("api_keys.id", ondelete="CASCADE"), primary_key=True
    )
    window_start: Mapped[datetime] = mapped_column(primary_key=True)
    request_count: Mapped[int]
