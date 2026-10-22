from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Friendship(Base):
    """A friend request (status 'pending') or an accepted friendship ('accepted')."""
    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friendship"),
    )

    id           : Mapped[int]      = mapped_column(Integer, primary_key=True)
    requester_id : Mapped[int]      = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    addressee_id : Mapped[int]      = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status       : Mapped[str]      = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    created_at   : Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
