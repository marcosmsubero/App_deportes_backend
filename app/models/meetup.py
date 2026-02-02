from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Meetup(Base):
    __tablename__ = "meetups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    meeting_point: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # nivel/running (opcionales)
    level_tag: Mapped[str | None] = mapped_column(String(30), nullable=True)      # suave/medio/rapido...
    pace_min: Mapped[int | None] = mapped_column(Integer, nullable=True)          # seg/km
    pace_max: Mapped[int | None] = mapped_column(Integer, nullable=True)          # seg/km

    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open/full/cancelled/done
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

