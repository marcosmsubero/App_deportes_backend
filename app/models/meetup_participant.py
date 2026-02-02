from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MeetupParticipant(Base):
    __tablename__ = "meetup_participants"
    __table_args__ = (UniqueConstraint("meetup_id", "user_id", name="uq_meetup_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    meetup_id: Mapped[int] = mapped_column(ForeignKey("meetups.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
