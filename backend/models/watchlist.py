from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class WatchlistItem(Base):
    """A movie/show the user saved to watch later (or again). Existence of a
    row is the source of truth, like ShowRewatch — removed, not archived."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "media_id", name="uq_watchlist_user_media"),
    )

    id      : Mapped[int]             = mapped_column(Integer, primary_key=True)
    user_id : Mapped[int]             = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    media_id: Mapped[int]             = mapped_column(ForeignKey("media.id", ondelete="CASCADE"), nullable=False, index=True)
    note    : Mapped[Optional[str]]   = mapped_column(Text)
    added_at: Mapped[datetime]        = mapped_column(DateTime, server_default=func.now(), nullable=False)

    media: Mapped["Media"] = relationship()
